#!/usr/bin/env python3.12

"""Bulk curl download orchestration for both drivers in
``pybatch.subprocessBatchCommands``: :class:`CurlTransfer` for the internal-parallel
transfer (``CurlWithInternalParallel``, one curl with ``--parallel``, what ships) and
:class:`ParallelRunTransfer` for the legacy ``ParallelRun`` (many curl processes).

``pybatch`` must NOT be imported here -- it resolves this module lazily at call
time because ``pyinstl/__init__`` pulls ``pybatch`` in through
``instlInstanceBase``. The sibling ``download*`` modules are likewise reached
lazily, from inside the methods that emit events.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path
from threading import Event, Thread

import utils
from configVar import config_vars
from configVar import config_var_bool, config_var_int

log = logging.getLogger(__name__)

# curl's per-tick Speed is too jittery to drive a stable ETA, so Central gets an
# EMA-smoothed throughput (alpha weights the newest sample), once per interval
_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC = 1.0
_DOWNLOAD_PROGRESS_THROUGHPUT_EMA_ALPHA = 0.2


def _client_handles_backend_hold():
    """True when the driving client (Waves Central) declared it handles backend
    holds itself, so our offline evidence is informational. Default FALSE: an old
    Central's 3-streak online detector answers those events with a pause that
    nothing ever auto-resumes on Windows (navigator.onLine lies there),
    deadlocking the engine in wait_if_paused."""
    return config_var_bool("DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD", False)


def get_control_channel():
    """The stdin control channel singleton, or None if unavailable. Only used for
    curl downloads, so a pause/offline-hold can't affect unrelated parallel runs
    (e.g. copy). Imported lazily to avoid a utils->pyinstl import."""
    try:
        from pyinstl.downloadControlChannel import get_global_channel
        return get_global_channel()
    except Exception:
        return None


def is_network_error(exit_code):
    """True when ``exit_code`` is one of curl's transient network exits."""
    try:
        return int(exit_code) in utils.NETWORK_ERROR_CURL_EXIT_CODES
    except (TypeError, ValueError):
        return False


def can_run_fallback(fallback_config_file, exit_code, fallback_exit_codes):
    """True when a fallback config exists and ``exit_code`` opts into it."""
    return (
        fallback_config_file
        and int(exit_code) in {int(code) for code in fallback_exit_codes}
    )


def is_curl_command(commands):
    """True when a parallel-run batch is a curl batch. Only such a batch gets a
    control channel wired, so a pause can never stall e.g. a copy."""
    return bool(commands) and Path(commands[0][0]).name.lower().startswith("curl")


def read_parallel_run_config_file(resolved_config_file):
    """Parse a parallel-run config file into one argv list per non-comment line."""
    commands = list()
    with utils.utf8_open_for_read(resolved_config_file, "r") as rfd:
        for line in rfd:
            line = line.strip()
            if line and line[0] != "#":
                args = shlex.split(line)
                commands.append(args)
    return commands


# converts a number of bytes to human-readable string
# 0 => 0
# 1024 => 1K
#
def bytes_to_string(number):
    suffixes = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']
    magnitude = 0

    if number == 0:
        return "0"

    while number >= 1024 and magnitude < len(suffixes) - 1:
        number /= 1024
        magnitude += 1

    decimal_places = 2 if magnitude > 0 else 0
    formatted_number = "{:.{}f}".format(number, decimal_places)

    return f"{formatted_number}{suffixes[magnitude]}"


# inverse of bytes_to_string: curl's "Dled"/"Speed"-style size string to bytes
#   "0"     => 0
#   "1305k" => 1305 * 1024
#   "70.2M" => 70.2 * 1024**2
def string_to_bytes(size_str):
    try:
        s = str(size_str).strip()
        if not s:
            return 0
        suffixes = {'B': 0, 'K': 1, 'M': 2, 'G': 3, 'T': 4, 'P': 5, 'E': 6, 'Z': 7, 'Y': 8}
        last = s[-1].upper()
        if last in suffixes:
            magnitude = suffixes[last]
            number_part = s[:-1]
        else:
            magnitude = 0
            number_part = s
        number = float(number_part)
        return int(number * (1024 ** magnitude))
    except Exception:
        return 0  # never raise: keep progress accounting fail-safe


class CurlTransfer:
    """Drives one curlHelper-generated ``--config`` file to completion: pause/resume,
    connectivity probing, the offline hold and its structured events, post-run output
    reconciliation, the ``.part``-size progress poller with its stall watchdog, and
    the range-failure fallback. One instance == one bulk transfer, however many curl
    passes that takes, so all the cross-pass bookkeeping lives on the instance.
    """

    # what the chunks run so far in this process actually put on disk; they are
    # separate pybatch commands, so a running total has nowhere else to live.
    # Never cleared: one instl invocation runs one download phase, so the class
    # outlives every chunk of it and nothing else. A second phase in the same
    # process would have to reset this first, or inherit the first phase's base.
    files_delivered_so_far = None  # None means nothing measured yet

    # the same, in bytes. Both channels report against the GLOBAL
    # __NUM_BYTES_TO_DOWNLOAD__, so without a running base each chunk restarted its
    # byte count at zero and the bar collapsed at every chunk boundary - including the
    # download_last / Info.xml chunk that ends every install.
    bytes_delivered_so_far = None

    def __init__(self, curl_path, config_file_path, total_files_to_download,
                 previously_downloaded_files, total_bytes_to_download,
                 fallback_config_file_path=None, fallback_exit_codes=(),
                 label="CurlInternalParallel"):
        self.curl_path = curl_path
        self.config_file_path = config_file_path
        self.total_files_to_download = total_files_to_download
        self.previously_downloaded_files = previously_downloaded_files
        self.total_bytes_to_download = total_bytes_to_download
        self.fallback_config_file_path = fallback_config_file_path
        self.fallback_exit_codes = fallback_exit_codes
        self.label = label

        # progress carried ACROSS re-runs: a re-launched curl restarts its
        # Xfers/Dled at 0 (see the FILES/BYTES accounting in _run_curl_once)
        self._files_high_water = 0
        self._bytes_baseline = 0
        self._bytes_high_water = 0
        # what the preceding chunks delivered, seeded from the class attribute in run()
        self.previously_downloaded_bytes = 0

        # the EMA persists ACROSS re-runs so the ETA stays stable through
        # pause/resume; the sample baseline is re-seeded per pass in _run_curl_once
        self._ema_throughput_bps = 0.0
        self._last_emit_monotonic = None
        self._last_emit_bytes = 0
        try:
            self._session_id = str(config_vars["__INVOCATION_RANDOM_ID__"]) \
                if config_vars.defined("__INVOCATION_RANDOM_ID__") else "unknown"
        except Exception:
            self._session_id = "unknown"

        # the initial pass and any reconciliation passes draw from ONE overall
        # hold budget, so a flapping network cannot hold an install forever
        self._hold_seconds_used = 0.0
        self._offline_probe_attempt = 0
        # set by the progress poller while an offline hold is reported; read by the
        # meter loop to freeze the files-done count it propagates (see _note_meter_files)
        self._offline_hold_active = False

        self._probe_host_port_cache = None
        self._part_output_paths_cache = None
        self._poll_files_high_water = 0

    def run(self):
        """Run the bulk download to completion and return curl's final code. On pause
        we SIGTERM curl (so the partial .part files flush), wait for resume, then
        re-run `curl --config`, which picks up from the partials via the
        `continue-at` entries curlHelper wrote."""
        config_file_path_fixed = os.fspath(self.config_file_path)
        if 'Win' in utils.get_current_os_names():
            # on windows curl fail to read long paths or paths with unicode chars
            # so convert the path to short path (DOS style 8.3 chars)
            import win32api
            config_file_path_fixed = win32api.GetShortPathName(config_file_path_fixed)

        # curlHelper seeds previously_downloaded_files with the preceding chunks'
        # PLANNED url count, overstating by the unfetched tail of any that died early
        if CurlTransfer.files_delivered_so_far is not None:
            self.previously_downloaded_files = CurlTransfer.files_delivered_so_far
        if CurlTransfer.bytes_delivered_so_far is not None:
            self.previously_downloaded_bytes = CurlTransfer.bytes_delivered_so_far

        channel = get_control_channel()
        pause_check = channel.is_paused if channel is not None else None

        try:
            curl_return_code = self._run_config_with_recovery(config_file_path_fixed, pause_check, channel)
        finally:
            self._publish_delivered()
        # every exit code, not just 0: a pause landing just before a resume terminates
        # curl mid-chunk and the re-run exits 23 with the chunk's tail unfetched
        try:
            return_code = self._reconcile_missing_outputs(
                pause_check, channel, curl_return_code=curl_return_code)
        finally:
            self._publish_delivered()

        print(f"Curl ended {return_code}")
        if can_run_fallback(self.fallback_config_file_path, return_code, self.fallback_exit_codes):
            self._run_fallback_after_curl_range_failure(return_code)
        return return_code

    def _run_config_with_recovery(self, config_file_path_fixed, pause_check, channel):
        """Run one curl config to completion, surviving pause and network drops. On a
        network-class curl exit we probe connectivity ourselves and hold while
        offline, instead of waiting for a pause from Central that never comes for
        elevated runs. Once retries are exhausted or the hold times out we return
        curl's code -- the checksum pass is the final gate and this never raises."""
        network_retry_budget = 12
        network_attempt = 0
        while True:
            return_code, paused = self._run_curl_once(config_file_path_fixed, pause_check)
            if paused:
                log.info(f"{self.label} paused; holding until resume")
                if channel is not None:
                    channel.wait_if_paused()
                network_attempt = 0
                continue  # continue-at resumes the partial files
            if return_code != 0 and is_network_error(return_code):
                if channel is not None:
                    channel.wait_if_paused()
                network_attempt += 1
                self._emit_network_retry_decision(
                    attempt=network_attempt,
                    reason="bulk_curl_network_error",
                    curl_exit_code=return_code,
                )
                if config_var_bool("DOWNLOAD_OFFLINE_HOLD_ENABLED", True) \
                        and not self._probe_connectivity()[0]:
                    # a hold does not consume the retry budget
                    if self._hold_until_online(channel):
                        continue
                    log.info(f"{self.label} network error (curl {return_code}); offline hold timeout expired, continuing")
                    return return_code
                if network_retry_budget > 0:
                    network_retry_budget -= 1
                    backoff = min(2 * network_attempt, 10)
                    log.info(f"{self.label} network error (curl {return_code}); retry in {backoff}s ({network_retry_budget} left)")
                    if channel is not None:
                        channel.sleep_or_wake(backoff)  # resume/try_now cuts this short
                    else:
                        time.sleep(backoff)
                    continue
                log.info(f"{self.label} network error (curl {return_code}); retries exhausted, continuing")
            elif return_code != 0:
                log.warning(f"{self.label} curl exited {return_code} "
                            f"({self._curl_exit_meaning(return_code)}); not a network code, "
                            f"so no retry here -- reconciliation will re-run the missing outputs")
            return return_code

    @staticmethod
    def _curl_exit_meaning(exit_code):
        """Failure-class name for a curl exit code, for log messages only."""
        try:
            from pyinstl.downloadFailures import classify_curl_exit_code
            return classify_curl_exit_code(exit_code).failure_class.value
        except Exception:
            return "unclassified"

    # -- offline-hold with structured events --------------------

    def _probe_host_and_port(self):
        """BASE_LINKS_URL's host when available, else the host of the first url
        entry in the curl config. Cached; (None, 443) when undeterminable."""
        cached = self._probe_host_port_cache
        if cached is not None:
            return cached
        host, port = None, 443
        try:
            base_links_url = str(config_vars.get("BASE_LINKS_URL", "")).strip()
        except Exception:
            base_links_url = ""
        candidates = [base_links_url] if base_links_url else []
        if not candidates:
            try:
                with open(os.fspath(self.config_file_path), "r", encoding="utf-8", errors="replace") as cfg:
                    for line in cfg:
                        s = line.strip()
                        if s.startswith("url"):
                            _, sep, rhs = s.partition("=")
                            if sep:
                                candidates.append(rhs.strip().strip('"'))
                                break
            except OSError:
                pass
        for candidate in candidates:
            try:
                split = urllib.parse.urlsplit(candidate)
                if split.hostname:
                    host = split.hostname
                    port = split.port or (80 if split.scheme == "http" else 443)
                    break
            except ValueError:
                continue
        self._probe_host_port_cache = (host, port)
        return self._probe_host_port_cache

    # proxy env vars curl honors, checked in this order; os.environ lookup is
    # case-insensitive on Windows, so both cases are listed for POSIX
    _PROXY_ENV_VARS = ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
                       "all_proxy", "ALL_PROXY")

    @classmethod
    def _proxy_probe_target(cls):
        """The proxy endpoint to probe instead of the download host; ``None`` when no
        proxy env var is set, ``("", 0)`` when one is set but unparsable (the caller
        must then fail open). On proxy-only networks outbound 443 is firewalled, so
        a DIRECT connect to the download host always fails and would turn every
        transient curl exit into a long false offline hold; a reachable proxy ==
        usable network for curl, which honors the same env vars."""
        proxy_url = ""
        for env_name in cls._PROXY_ENV_VARS:
            value = os.environ.get(env_name, "").strip()
            if value:
                proxy_url = value
                break
        if not proxy_url:
            return None
        try:
            if "://" not in proxy_url:
                proxy_url = "http://" + proxy_url
            split = urllib.parse.urlsplit(proxy_url)
            if split.hostname and split.port:
                return split.hostname, split.port
        except ValueError:
            pass
        # no explicit port: probing a guessed one risks a false offline
        return "", 0

    def _probe_connectivity(self):
        """Cheap connectivity probe: DNS resolve + TCP connect to the download host,
        or to the proxy when proxy env vars are set. Returns ``(online,
        failure_class)``, failure_class being a DownloadFailureClass value string
        (dns_resolution / tcp_connect -- both network-class for Central's online
        detector). Fails OPEN when no probe host can be determined."""
        proxy_target = self._proxy_probe_target()
        if proxy_target is not None:
            host, port = proxy_target
            if not host:
                return True, None  # inconclusive: fail open
        else:
            host, port = self._probe_host_and_port()
            if not host:
                return True, None
        timeout = max(1, config_var_int("DOWNLOAD_OFFLINE_PROBE_TIMEOUT_SECONDS", 5))
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True, None
        except socket.gaierror:
            return False, "dns_resolution"
        except OSError:
            return False, "tcp_connect"

    def _hold_until_online(self, channel):
        """Hold the download while the network is down, probing in a pause-aware
        loop (``sleep_or_wake``, so pause/resume/try_now still interrupt). False when
        the OVERALL hold timeout (DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS, cumulative
        across this transfer's holds) expired.

        Emits an offline ``session_state`` plus a network-class ``retry_decision`` per
        failed probe: curl is not being re-run while we hold, so without those
        Central's online detector would never reach its >=3 event streak. Time blocked
        in ``wait_if_paused`` does not count against the budget, or one paused outage
        would spend all of it and a later one would get no hold at all."""
        probe_interval = max(1, config_var_int("DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS", 5))
        hold_timeout = max(0, config_var_int("DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS", 1800))
        event_interval = max(probe_interval, config_var_int("DOWNLOAD_OFFLINE_HOLD_EVENT_INTERVAL_SECONDS", 30))
        already_used = self._hold_seconds_used
        hold_start = time.monotonic()
        paused_seconds = 0.0
        log.info(f"{self.label} offline detected; holding until connectivity returns "
                 f"(overall hold budget {hold_timeout}s, {int(already_used)}s already used)")
        self._emit_hold_session_state("paused", "offline_no_network", previous_state="downloading")
        last_state_emit = time.monotonic()
        while True:
            elapsed_total = already_used + (time.monotonic() - hold_start) - paused_seconds
            self._hold_seconds_used = elapsed_total
            if hold_timeout > 0 and elapsed_total >= hold_timeout:
                return False
            if channel is not None:
                pause_wait_start = time.monotonic()
                channel.wait_if_paused()
                paused_seconds += time.monotonic() - pause_wait_start  # paused time is not hold time
                channel.sleep_or_wake(probe_interval)  # try_now probes immediately
            else:
                time.sleep(probe_interval)
            online, probe_failure_class = self._probe_connectivity()
            if online:
                self._hold_seconds_used = already_used + (time.monotonic() - hold_start) - paused_seconds
                log.info(f"{self.label} connectivity returned after "
                         f"{int(time.monotonic() - hold_start)}s offline hold; resuming download")
                self._emit_hold_session_state("downloading", "resuming_after_offline", previous_state="paused")
                return True
            self._offline_probe_attempt += 1
            self._emit_network_retry_decision(
                attempt=self._offline_probe_attempt,
                reason="offline_hold_probe_failed",
                failure_class=probe_failure_class,
                delay_seconds=probe_interval,
            )
            if time.monotonic() - last_state_emit >= event_interval:
                self._emit_hold_session_state("paused", "offline_no_network", previous_state="downloading")
                last_state_emit = time.monotonic()

    def _emit_network_retry_decision(self, *, attempt, reason, curl_exit_code=None,
                                     failure_class=None, delay_seconds=0.0):
        """Emit a structured ``download.retry_decision`` DOWNLOAD_EVENT for a bulk
        network failure (curl exit or connectivity probe). Same schema as the
        per-file event, with fileId/repoPath left null. Gated by the
        DOWNLOAD_TELEMETRY_ENABLED kill switch and by
        :func:`_client_handles_backend_hold`."""
        if not _client_handles_backend_hold():
            return
        try:
            from pyinstl.downloadEvents import emit_retry_decision
            from pyinstl.downloadFailures import DownloadFailureClass, classify_curl_exit_code
            from pyinstl.downloadRetry import RetryAction, RetryDecision
            if curl_exit_code is not None:
                failure_enum = classify_curl_exit_code(curl_exit_code).failure_class
            else:
                failure_enum = DownloadFailureClass(failure_class)
            decision = RetryDecision(
                action=RetryAction.RESUME,  # the bulk loop always retries in place (continue-at)
                failure_class=failure_enum,
                attempt=int(attempt),
                delay_seconds=float(delay_seconds),
                reason=reason,
                curl_exit_code=int(curl_exit_code) if curl_exit_code is not None else None,
            )
            emit_retry_decision(decision, session_id=self._session_id)
        except Exception as ex:  # pragma: no cover - instrumentation must never break a download
            log.debug(f"could not emit bulk retry decision event: {ex}")

    def _emit_hold_session_state(self, state, reason, previous_state=None):
        """Emit a ``session_state`` transition for the offline hold / resume, with the
        current on-disk byte progress so Central's bar keeps its position while
        frozen. No throughput field: the hold gap must not be averaged into the ETA.
        Gated by :func:`_client_handles_backend_hold`."""
        if not _client_handles_backend_hold():
            return
        try:
            from pyinstl.downloadEvents import emit_session_state
            try:
                cumulative_bytes, files_est = self._sum_downloaded_part_bytes()
            except Exception:
                cumulative_bytes, files_est = 0, 0
            emit_session_state(
                session_id=self._session_id,
                state=state,
                previous_state=previous_state,
                reason=reason,
                bytes_received=int(cumulative_bytes),
                files_completed=int(files_est),
                phase_bytes_done=int(cumulative_bytes),
                phase_bytes_planned=int(self.total_bytes_to_download),
            )
        except Exception as ex:  # pragma: no cover
            log.debug(f"could not emit hold session_state event: {ex}")

    # -- post-run completeness reconciliation -------------------

    # directive keys curlHelper writes per download entry; everything else in
    # the config file is header material (see curlHelper write_download_entry)
    _CURL_ENTRY_KEYS = frozenset({"no-fail", "continue-at", "header", "url", "output", "next"})

    def _parse_curl_config_for_reconcile(self, config_path):
        """Parse a curlHelper-generated ``--config`` into ``(header_lines, entries,
        uses_isolated_sections)``, each entry a dict of ``pre_lines`` (no-fail /
        continue-at / header), ``url_line``, ``output_line`` and the unquoted
        ``output_path``. A read problem returns empty results, so reconciliation
        just no-ops."""
        header_lines = []
        entries = []
        uses_isolated_sections = False
        pre_lines = []
        url_line = None
        in_entries = False
        try:
            with open(os.fspath(config_path), "r", encoding="utf-8", errors="replace") as cfg:
                for raw in cfg:
                    line = raw.rstrip("\n")
                    stripped = line.strip()
                    if not stripped:
                        continue
                    key = stripped.partition("=")[0].strip().lower()
                    if key in self._CURL_ENTRY_KEYS:
                        in_entries = True
                        if key == "next":
                            # isolated transfer sections: 'next' + a repeated header
                            uses_isolated_sections = True
                            pre_lines = []
                            url_line = None
                        elif key == "output":
                            output_path = stripped.partition("=")[2].strip().strip('"')
                            entries.append({
                                "pre_lines": pre_lines,
                                "url_line": url_line,
                                "output_line": line,
                                "output_path": output_path,
                            })
                            pre_lines = []
                            url_line = None
                        elif key == "url":
                            url_line = line
                        else:  # no-fail / continue-at / header
                            pre_lines.append(line)
                    elif not in_entries:
                        header_lines.append(line)
                    # any other key here is a repeated isolated-section header
        except OSError as ex:
            log.warning(f"{self.label} could not parse curl config for reconciliation: {ex}")
            return [], [], False
        return header_lines, entries, uses_isolated_sections

    @staticmethod
    def _fresh_start_entry(entry):
        """Rewrite a reconcile entry as a FRESH-START transfer: reconciliation only
        re-runs entries whose output is MISSING, so the original resume lines must
        not be replayed. ``continue-at = N`` (N>0) with a nonexistent output makes
        curl fetch bytes N..end but write them at offset 0 -- a silently corrupt
        file missing its first N bytes (or the server answers 416 / curl exits 33);
        rewritten to ``continue-at = -``. An ``If-...`` header is stale without the
        partial file it validated, and a 304 would produce no body at all; dropped."""
        fresh_pre_lines = []
        for pre_line in entry["pre_lines"]:
            key, _, value = pre_line.strip().partition("=")
            key = key.strip().lower()
            if key == "continue-at":
                if value.strip() != "-":
                    pre_line = "continue-at = -"
            elif key == "header":
                header_name = value.strip().strip('"').partition(":")[0].strip().lower()
                if header_name.startswith("if-"):
                    continue
            fresh_pre_lines.append(pre_line)
        fresh_entry = dict(entry)
        fresh_entry["pre_lines"] = fresh_pre_lines
        return fresh_entry

    def _write_reconcile_config(self, retry_config_path, header_lines, entries, uses_isolated_sections):
        """Write a retry curl config with only ``entries``, under the original
        config's header."""
        header_text = "\n".join(header_lines)
        with utils.utf8_open_for_write(retry_config_path, "w") as wfd:
            wfd.write(header_text + "\n\n")
            for entry_i, entry in enumerate(entries):
                if uses_isolated_sections and entry_i > 0:
                    wfd.write("next\n")
                    wfd.write(header_text + "\n\n")
                for pre_line in entry["pre_lines"]:
                    wfd.write(pre_line + "\n")
                if entry["url_line"] is not None:
                    wfd.write(entry["url_line"] + "\n")
                wfd.write(entry["output_line"] + "\n\n")

    def _reconcile_missing_outputs(self, pause_check, channel, curl_return_code=0):
        """Verify every expected output exists after curl exits -- on any exit code --
        and re-download only the missing ones; returns the final return code. curl
        --parallel masks per-transfer failures: transfers whose internal retries were
        exhausted are simply dropped, yet the final exit code can still be 0. The
        config's ``output`` entries ARE the ``.part`` paths curl writes, so a missing
        output means the transfer never produced a byte.

        ``curl_return_code`` is the verdict kept when nothing needed fixing; a
        reconciliation that recovers every output clears it to 0."""
        return_code = curl_return_code
        if not config_var_bool("DOWNLOAD_RECONCILE_MISSING_OUTPUTS", True):
            return return_code
        max_rounds = max(0, config_var_int("DOWNLOAD_RECONCILE_MAX_ROUNDS", 3))
        if max_rounds == 0:
            return return_code
        header_lines, entries, uses_isolated_sections = \
            self._parse_curl_config_for_reconcile(self.config_file_path)
        if not entries:
            # otherwise an unreadable config looks exactly like nothing to reconcile
            log.warning(f"{self.label} no download entries parsed from "
                        f"'{self.config_file_path}'; completeness cannot be verified here, "
                        f"leaving it to the checksum phase")
            return return_code
        missing = []
        for round_i in range(1, max_rounds + 1):
            missing = [self._fresh_start_entry(entry) for entry in entries
                       if not os.path.exists(entry["output_path"])]
            if not missing:
                if round_i > 1:
                    log.info(f"{self.label} reconciliation recovered all missing outputs")
                    return 0  # the chunk IS complete now, whatever curl said earlier
                return return_code
            log.info(f"{self.label} curl exited {curl_return_code} and {len(missing)} of "
                     f"{len(entries)} expected outputs are missing; "
                     f"reconciliation round {round_i} of {max_rounds}")
            self._emit_hold_session_state("retrying", "reconcile_missing_outputs")
            retry_config_path = Path(f"{os.fspath(self.config_file_path)}.reconcile-{round_i:02}")
            self._write_reconcile_config(retry_config_path, header_lines, missing, uses_isolated_sections)
            retry_config_path_fixed = os.fspath(retry_config_path)
            if 'Win' in utils.get_current_os_names():
                import win32api
                retry_config_path_fixed = win32api.GetShortPathName(retry_config_path_fixed)
            return_code = self._run_config_with_recovery(retry_config_path_fixed, pause_check, channel)
        still_missing = [entry for entry in entries if not os.path.exists(entry["output_path"])]
        if still_missing:
            log.warning(f"{self.label} {len(still_missing)} outputs still missing after "
                        f"{max_rounds} reconciliation rounds; leaving recovery to the checksum phase")
        elif return_code == 0:
            log.info(f"{self.label} reconciliation recovered all missing outputs")
        return return_code

    def files_actually_downloaded(self):
        """How many of this chunk's ``output`` paths exist on disk. ``None`` when the
        config could not be read, so callers fall back rather than report a confident
        zero. In-flight ``.part`` files count as delivered, overstating by at most the
        parallel-max in flight when curl stops."""
        paths = self._download_part_output_paths()
        if not paths:
            return None
        return sum(1 for p in paths if os.path.exists(p))

    def _publish_delivered(self):
        """Record base + this chunk's completions as the running total, leaving the
        next chunk on its planned base when this one cannot measure itself. Never
        raises: progress accounting must not be able to fail a download."""
        try:
            delivered = self.files_actually_downloaded()
            if delivered is not None:
                CurlTransfer.files_delivered_so_far = self.previously_downloaded_files + delivered
            delivered_bytes = self._sum_this_chunk_part_bytes()
            if delivered_bytes is not None:
                CurlTransfer.bytes_delivered_so_far = self.previously_downloaded_bytes + delivered_bytes
        except Exception as ex:  # pragma: no cover - accounting must never break sync
            log.debug(f"could not publish delivered-file count: {ex}")

    def _maybe_emit_progress_tick(self, cumulative_bytes, downloaded_files):
        """Emit a throttled, EMA-smoothed ``session_state`` progress tick, giving
        Central cumulative received bytes and a stable throughput for its ETA. The
        EMA persists across re-runs; the first sample of each curl pass only
        re-establishes the baseline (the ``_last_emit_monotonic = None`` reset in
        ``_run_curl_once``) so a paused gap is not divided into a bogus low speed."""
        try:
            now = time.monotonic()
            last = self._last_emit_monotonic
            if last is None:
                # baseline only, but the carried-over EMA still rides along
                self._last_emit_monotonic = now
                self._last_emit_bytes = cumulative_bytes
            else:
                dt = now - last
                if dt < _DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC:
                    return  # throttle
                inst_bps = max(0.0, (cumulative_bytes - self._last_emit_bytes) / dt)
                if self._ema_throughput_bps <= 0.0:
                    self._ema_throughput_bps = inst_bps
                else:
                    a = _DOWNLOAD_PROGRESS_THROUGHPUT_EMA_ALPHA
                    self._ema_throughput_bps = a * inst_bps + (1.0 - a) * self._ema_throughput_bps
                self._last_emit_monotonic = now
                self._last_emit_bytes = cumulative_bytes

            try:
                from pyinstl.downloadEvents import emit_session_state
            except Exception:
                return  # structured channel unavailable; legacy text line still flows
            emit_session_state(
                session_id=self._session_id,
                state="downloading",
                bytes_received=int(cumulative_bytes),
                files_completed=int(downloaded_files),
                observed_throughput_bytes_per_second=int(self._ema_throughput_bps),
                # phase_bytes_* are what Central needs for a determinate bar
                phase_bytes_done=int(cumulative_bytes),
                phase_bytes_planned=int(self.total_bytes_to_download),
                reason="download_progress",
            )
        except Exception as ex:  # pragma: no cover
            log.debug(f"could not emit download progress tick: {ex}")

    def _download_part_output_paths(self):
        """The ``output = "..."`` entries of the curl ``--config`` file, parsed once
        and cached ([] on any failure). curlHelper writes every download as
        ``output = "<final>.instl-<id>.part"``, so these are exactly the files curl
        grows on disk; summing their sizes gives true cumulative received bytes,
        independent of curl's console meter, which has no in-flight rows on Windows."""
        cached = self._part_output_paths_cache
        if cached is not None:
            return cached
        paths = []
        try:
            with open(os.fspath(self.config_file_path), "r", encoding="utf-8", errors="replace") as cfg:
                for line in cfg:
                    s = line.strip()
                    if s.startswith("output"):
                        _, sep, rhs = s.partition("=")
                        if not sep:
                            continue
                        rhs = rhs.strip().strip('"')
                        if rhs:
                            paths.append(rhs)
        except OSError as ex:
            log.debug(f"download poller: could not read curl config for part paths: {ex}")
            paths = []
        self._part_output_paths_cache = paths
        return paths

    def _sum_this_chunk_part_bytes(self):
        """Sum the on-disk sizes of THIS chunk's ``.part`` outputs. ``None`` when the
        config could not be read, so callers keep the running base rather than publish
        a confident zero."""
        paths = self._download_part_output_paths()
        if not paths:
            return None
        total = 0
        for p in paths:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass  # not created yet / locked / vanished -- skip this sample
        return total

    def _sum_downloaded_part_bytes(self):
        """Cumulative received bytes across the whole download phase - the preceding
        chunks' published total plus this chunk's ``.part`` sizes - and a files estimate;
        returns ``(cumulative_bytes, files_estimate)``. instl renames the parts only
        after the whole batch, so a true per-file completion count is not observable
        here: files_estimate is a monotonic, byte-proportional approximation. Bytes
        drive the bar and ETA."""
        total = self.previously_downloaded_bytes + (self._sum_this_chunk_part_bytes() or 0)
        planned_bytes = self.total_bytes_to_download or 0
        if planned_bytes > 0:
            files_est = int(self.total_files_to_download * min(1.0, total / planned_bytes))
        else:
            files_est = 0
        prev_high = self._poll_files_high_water
        if files_est < prev_high:
            files_est = prev_high
        else:
            self._poll_files_high_water = files_est
        files_est = min(files_est, self.total_files_to_download)
        return total, files_est

    def _run_download_progress_poller(self, stop_event):
        """Daemon poller: ~once/second, emit a ``download_progress`` tick derived from
        on-disk ``.part`` sizes. Never raises, and is bounded by ``stop_event`` so it
        always joins promptly -- it must never wedge the sync process. The stall
        watchdog never kills curl either: enforcement is curl's own
        speed-limit/speed-time (see curlHelper), which makes a stalled transfer exit
        28 and feed the offline-hold/retry loop.

        A link that drops mid-transfer only STALLS curl's sockets: no exit code fires
        until speed-time, so that hold cannot start for minutes. This poller notices
        within a tick, and after DOWNLOAD_STALL_PROBE_SECONDS of zero growth runs the
        same connectivity probe; a failed probe raises the offline hold immediately
        while curl keeps running. The hold is released only on real byte growth -- a
        wedged curl gets speed-time-aborted and re-run before progress resumes."""
        stall_watchdog_seconds = max(0, config_var_int("DOWNLOAD_STALL_WATCHDOG_SECONDS", 180))
        stall_probe_seconds = max(0, config_var_int("DOWNLOAD_STALL_PROBE_SECONDS", 8))
        probe_interval = max(1, config_var_int("DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS", 5))
        event_interval = max(probe_interval, config_var_int("DOWNLOAD_OFFLINE_HOLD_EVENT_INTERVAL_SECONDS", 30))
        probe_enabled = stall_probe_seconds > 0 and config_var_bool("DOWNLOAD_OFFLINE_HOLD_ENABLED", True)
        last_growth_bytes = -1
        last_growth_monotonic = time.monotonic()
        last_stall_emit_monotonic = 0.0
        last_probe_monotonic = 0.0
        last_hold_emit_monotonic = 0.0
        self._offline_hold_active = False
        while not stop_event.is_set():
            try:
                cumulative_bytes, files_est = self._sum_downloaded_part_bytes()
                now = time.monotonic()
                if cumulative_bytes > last_growth_bytes:
                    if self._offline_hold_active:
                        # announce the resume BEFORE the first grown tick, so
                        # Central's detector resets its streak explicitly
                        log.info(f"{self.label} download progress resumed after "
                                 f"{int(now - last_growth_monotonic)}s offline stall")
                        self._emit_hold_session_state("downloading", "resuming_after_offline",
                                                      previous_state="paused")
                        self._offline_hold_active = False
                    last_growth_bytes = cumulative_bytes
                    last_growth_monotonic = now
                    self._maybe_emit_progress_tick(cumulative_bytes, files_est)
                else:
                    stalled_for = now - last_growth_monotonic
                    if not self._offline_hold_active:
                        # flat ticks only while NOT holding: a non-paused session
                        # state would clear Central's backend-hold flag every second
                        self._maybe_emit_progress_tick(cumulative_bytes, files_est)
                    if (probe_enabled and stalled_for >= stall_probe_seconds
                            and now - last_probe_monotonic >= probe_interval):
                        last_probe_monotonic = now
                        online, _probe_failure_class = self._probe_connectivity()
                        if not online and (not self._offline_hold_active
                                           or now - last_hold_emit_monotonic >= event_interval):
                            if not self._offline_hold_active:
                                log.info(f"{self.label} no byte progress for "
                                         f"{int(stalled_for)}s and connectivity probe failed; "
                                         f"reporting offline hold while curl transfer is stalled")
                            self._emit_hold_session_state("paused", "offline_no_network",
                                                          previous_state="downloading")
                            last_hold_emit_monotonic = now
                            self._offline_hold_active = True
                    if (stall_watchdog_seconds > 0 and not self._offline_hold_active
                            and stalled_for >= stall_watchdog_seconds
                            and now - last_stall_emit_monotonic >= stall_watchdog_seconds):
                        log.info(f"{self.label} no download progress for "
                                 f"{int(stalled_for)}s while curl is running; "
                                 f"transfer appears stalled")
                        self._emit_hold_session_state("downloading", "stalled_no_progress")
                        last_stall_emit_monotonic = now
            except Exception as ex:  # pragma: no cover - defensive; poller must never raise
                log.debug(f"download progress poller tick failed: {ex}")
            stop_event.wait(_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC)

    def _note_meter_files(self, candidate_files):
        """Fold one meter sample into the monotonic files high-water and return the
        count to report. While the offline hold is active the high-water is FROZEN:
        with the network down, curl burns through the queue with instant connection
        failures (~tens of files/second observed) and its Xfers column counts a
        failed transfer as a finished one, so an unfrozen count climbs through the
        outage while zero bytes move -- and this count is the sole driver of
        Central's progress-bar percentage. The burned files are recovered later by
        the verify/redownload pass; after the hold releases, the high-water catches
        up to curl's cumulative meter in one step."""
        if candidate_files > self._files_high_water and not self._offline_hold_active:
            self._files_high_water = candidate_files
        return min(self._files_high_water, self.total_files_to_download)

    def _run_curl_once(self, config_file_path_fixed, pause_check):
        """Run one `curl --config` pass, logging progress; returns (returncode,
        paused). Pause-detection latency is bounded by curl's progress cadence (~1s),
        same as utils.parallel_run.run_process."""
        # start_new_session so curl is its own process-group leader -- what
        # terminate_process's os.killpg targets on pause, or curl keeps downloading.
        # cwd is the config file's folder so relative paths in it resolve.
        working_dir = os.fspath(Path(config_file_path_fixed).parent)
        process = subprocess.Popen([os.fspath(self.curl_path), "--config", config_file_path_fixed],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                   universal_newlines=True,
                                   start_new_session=True,
                                   bufsize=1,
                                   cwd=working_dir)
        # Total/Current/Left are OPTIONAL: up to curl 8.19 an unknown time column
        # printed the placeholder "--:--:--", but 8.20+ leaves it literally blank.
        # Requiring them meant not one meter line matched under the system curl on
        # Windows (8.21), so Dled/Xfers/Speed were never parsed there and the legacy
        # progress line below was never emitted at all. Only Dled/Xfers/Live/Speed
        # are consumed, and those parse identically either way.
        reg = re.compile(r"""^\s*
           (?P<DL_percent>[\d.-]+)\s+
           (?P<UL_percent>[\d.-]+)\s+
           (?P<Dled>[\d.a-z]+)\s+
           (?P<Uled>[\d.a-z]+)\s+
           (?P<Xfers>[\d]+)\s+
           (?P<Live>[\d]+)\s+
           (?P<Queue>[\d]+)?\s*?
           (?P<Total>[\d:-]+)?\s+
           (?P<Current>[\d:-]+)?\s+
           (?P<Left>[\d:-]+)?\s+
           (?P<Speed>[\d.a-z]+)
           (?P<the_rest>.*)?$""",
           re.IGNORECASE | re.VERBOSE)

        bytes_to_download_str = bytes_to_string(self.total_bytes_to_download)

        last_run_dled_bytes = 0

        # re-seed the throughput sample baseline for THIS pass, so the
        # paused/offline wall-time gap is never counted as transfer time
        self._last_emit_monotonic = None

        # the download_progress ticks come from on-disk .part sizes via this poller,
        # not from curl's --parallel console meter. Hang-safe: daemon thread + stop
        # Event + bounded join in the finally below; the poller only reads sizes.
        _poll_stop = Event()
        _poll_thread = Thread(target=self._run_download_progress_poller,
                              args=(_poll_stop,),
                              name="download-progress-poller",
                              daemon=True)
        _poll_thread.start()

        paused = False
        try:
            while process.poll() is None:
                if pause_check is not None and pause_check():
                    from utils.parallel_run import terminate_process
                    terminate_process(process)
                    paused = True
                    log.info(f"{self.label} paused - terminated curl")
                    break
                stdout_line = process.stdout.readline().strip()
                stdout_lines = stdout_line.split('\r')
                for stdout_line in stdout_lines:
                    match = reg.match(stdout_line)
                    if match:
                        downloaded_files = self.previously_downloaded_files
                        try:
                            # Add the total Xfers, Reduce by the live count
                            downloaded_files += int(match.group('Xfers')) - int(match.group('Live'))
                        except:
                            pass  # in case 'Xfers' could not be converted to int

                        # FILES: monotonic only, no per-run baseline -- a re-run
                        # re-counts finished files in Xfers anyway
                        downloaded_files = self._note_meter_files(downloaded_files)

                        # BYTES: this run's Dled counts only new bytes (curl
                        # resumes via continue-at), so add the prior runs' baseline,
                        # and the preceding chunks' delivered total on top of that -
                        # this line reports against the whole download, not the chunk
                        current_dled_bytes = string_to_bytes(match.group('Dled'))
                        last_run_dled_bytes = current_dled_bytes
                        cumulative_bytes = (self.previously_downloaded_bytes
                                            + self._bytes_baseline + current_dled_bytes)
                        if cumulative_bytes > self._bytes_high_water:
                            self._bytes_high_water = cumulative_bytes
                        cumulative_bytes = min(self._bytes_high_water, self.total_bytes_to_download)
                        downloaded_bytes_str = bytes_to_string(cumulative_bytes)

                        # legacy line, also feeding Central's text-based liveDownload
                        # parser -- which is still the sole driver of Central's
                        # progress-bar percentage, so this must keep being emitted
                        message = f"Progress ... of ...; " \
                                  f"Downloaded {downloaded_files} of {self.total_files_to_download} files, " \
                                  f"Downloaded {downloaded_bytes_str} of {bytes_to_download_str}, " \
                                  f"Speed {match.group('Speed')}"
                        log.info(message)
        finally:
            # bounded join so a stuck size-read can never wedge the process
            _poll_stop.set()
            _poll_thread.join(timeout=2.0)

        try:
            process.stdout.close()
        except Exception:
            pass
        process.wait()
        # fold this run's final Dled into the baseline, so the next re-run (whose
        # Dled restarts at 0) is reported on top of what this run transferred
        self._bytes_baseline += last_run_dled_bytes
        return process.returncode, paused

    def _run_fallback_after_curl_range_failure(self, exit_code):
        """Re-run the whole transfer from zero using the fallback curl config."""
        config_file_path_fixed = os.fspath(self.fallback_config_file_path)
        if 'Win' in utils.get_current_os_names():
            import win32api
            config_file_path_fixed = win32api.GetShortPathName(config_file_path_fixed)
        log.info(
            f"CurlInternalParallel curl resume failed with exit code {exit_code}; "
            f"retrying from zero with fallback config '{self.fallback_config_file_path}'"
        )
        fallback_process = subprocess.run(
            [os.fspath(self.curl_path), "--config", config_file_path_fixed],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if fallback_process.stdout:
            log.info(fallback_process.stdout)
        if fallback_process.stderr:
            log.info(fallback_process.stderr)
        fallback_process.check_returncode()


class ParallelRunTransfer:
    """Drives one parallel-run batch through ``utils.run_processes_in_parallel``:
    pause/resume and a bounded backoff for network-class curl exits.

    This runner spawns many curl processes and only sees an aggregate exit code, so
    it has none of :class:`CurlTransfer`'s reconciliation / offline-hold / stall
    watchdog: the checksum phase remains its completeness gate.
    """

    def __init__(self, commands, shell, action_name, channel=None,
                 fallback_config_file=None, fallback_exit_codes=()):
        self.commands = commands
        self.shell = shell
        self.action_name = action_name
        self.channel = channel  # None for a non-curl batch, which is never paused
        self.fallback_config_file = fallback_config_file
        self.fallback_exit_codes = fallback_exit_codes

    def run(self):
        """Run the batch, honoring pause and surviving a brief offline.

        On pause the runner terminates curl and returns PAUSED_EXIT_CODE; we
        wait_if_paused() and re-run, which resumes from the .part files via
        continue-at. A network-class curl exit without a pause gets a bounded
        backoff instead, so a short blip recovers rather than failing the session.

        Returns the exit code the CALLER must answer with its range-failure
        fallback, or None when the batch is done: that fallback stays on the
        ParallelRun command, which owns the config path and the `doing` it reports
        through.
        """
        is_curl = is_curl_command(self.commands)
        channel = self.channel
        pause_check = channel.is_paused if channel is not None else None
        network_retry_budget = 12
        network_attempt = 0
        while True:
            try:
                utils.run_processes_in_parallel(self.commands, self.shell, pause_check=pause_check)
                return None  # run_processes_in_parallel always sys.exits; here for safety
            except SystemExit as sys_exit:
                code = sys_exit.code
                if code == 0:
                    return None
                if code == utils.PAUSED_EXIT_CODE:
                    log.info(f"{self.action_name} paused; holding until resume")
                    if channel is not None:
                        channel.wait_if_paused()
                    network_attempt = 0
                    continue
                if can_run_fallback(self.fallback_config_file, code, self.fallback_exit_codes):
                    return code
                if is_curl and is_network_error(code):
                    if channel is not None:
                        channel.wait_if_paused()
                    if network_retry_budget > 0:
                        network_retry_budget -= 1
                        network_attempt += 1
                        backoff = min(2 * network_attempt, 10)
                        log.info(f"{self.action_name} network error (curl {code}); retry in {backoff}s ({network_retry_budget} left)")
                        if channel is not None:
                            channel.sleep_or_wake(backoff)  # try_now/resume cuts this short
                        else:
                            time.sleep(backoff)
                        continue
                    raise Exception(utils.get_curl_err_msg(code))
                if is_curl:
                    raise Exception(utils.get_curl_err_msg(code))
                raise
