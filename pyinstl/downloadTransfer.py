#!/usr/bin/env python3.12

"""Bulk curl download orchestration for the internal-parallel transfer.

``CurlWithInternalParallel`` (``pybatch.subprocessBatchCommands``) is the
pybatch *command* that appears in a generated batch script: it owns its
repr, its progress accounting, and nothing else. Everything the actual
download needs in order to survive a real network -- pause/resume through
the stdin control channel, connectivity probing, the offline hold with its
structured events, post-run output reconciliation, the ``.part``-size
progress poller with its stall watchdog, and the range-failure fallback --
lives here, in :class:`CurlTransfer`.

Why a collaborator and not more methods on the command? The orchestration
touches none of the pybatch command surface (``doing``, ``log_result``,
progress counters); it needs only the seven plain values curlHelper passes
in plus its own runtime bookkeeping. Keeping it out of the command file
lets it sit next to its siblings (``downloadState``, ``downloadEvents``,
``downloadRetry``, ``downloadFailures``, ``downloadControlChannel``,
``downloadObservability``) whose contracts it drives, and keeps every
pybatch command in that file at the house size of 1-7 methods.

Import direction: this module imports ``utils`` / ``configVar`` only, and
reaches the sibling ``download*`` modules lazily from inside the methods
that emit events. ``pybatch`` must NOT be imported here -- ``pybatch``
resolves this module lazily at call time precisely because
``pyinstl/__init__`` pulls ``pybatch`` in through ``instlInstanceBase``.

Every emission in here is best-effort: instrumentation must never break a
download.
"""

from __future__ import annotations

import logging
import os
import re
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

# cadence + smoothing for the in-loop `session_state`
# progress ticks emitted during the curl download. curl's per-tick Speed is too
# jittery to drive a stable ETA, so we feed Central an EMA-smoothed throughput
# (alpha weights the newest sample) at most once per interval. Best-effort:
# emitting must never break a download.
_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC = 1.0
_DOWNLOAD_PROGRESS_THROUGHPUT_EMA_ALPHA = 0.2


def _client_handles_backend_hold():
    """Capability handshake with the driving client (Waves Central).

    A NEW Central injects DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD: true into the
    generated yaml, declaring that it treats backend-derived offline evidence
    (the bulk-loop network-class retry_decision events and the offline-hold /
    stall session_state events) as INFORMATIONAL -- it will never respond
    with a stdin pause, because the engine is already holding and resumes
    itself.

    Default FALSE: an OLD Central's pre-existing 3-streak online detector
    would answer a burst of network-class retry_decisions with a pause that
    nothing ever auto-resumes on Windows (navigator.onLine lies there),
    deadlocking the engine in wait_if_paused. When false, the engine still
    performs ALL silent recovery (reconciliation, offline-hold/backoff, stall
    detection, redownload budgets) but emits only the legacy log lines -- an
    old Central sees exactly today's event stream.
    """
    return config_var_bool("DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD", False)


def get_control_channel():
    """The stdin control channel singleton, or None if unavailable.

    Only used for curl downloads, so a pause/offline-hold can't affect
    unrelated parallel runs (e.g. copy). Imported lazily to avoid a
    utils->pyinstl import at module load.

    Shared by both curl drivers: the internal-parallel transfer below and
    ``pybatch.subprocessBatchCommands.ParallelRun`` (external parallel),
    which had a byte-identical copy of this lookup.
    """
    try:
        from pyinstl.downloadControlChannel import get_global_channel
        return get_global_channel()
    except Exception:
        return None


def is_network_error(exit_code):
    """True when ``exit_code`` is one of curl's transient network exits.

    Shared by both curl drivers (internal-parallel transfer and
    ``ParallelRun``), which each carried an identical copy.
    """
    try:
        return int(exit_code) in utils.NETWORK_ERROR_CURL_EXIT_CODES
    except (TypeError, ValueError):
        return False


def can_run_fallback(fallback_config_file, exit_code, fallback_exit_codes):
    """True when a fallback config exists and ``exit_code`` opts into it.

    Shared by both curl drivers, which differed only in the attribute the
    fallback config path is stored under (``fallback_config_file`` for
    ``ParallelRun``, ``fallback_config_file_path`` for the internal-parallel
    transfer -- both names are part of a repr'd public signature, so the
    value is passed in rather than reached for).
    """
    return (
        fallback_config_file
        and int(exit_code) in {int(code) for code in fallback_exit_codes}
    )


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


# inverse of bytes_to_string: converts curl's "Dled"/"Speed"-style size
# string back to a number of bytes. Tolerant: returns 0 on any parse
# failure and never raises (progress accounting must never break curl).
#   "0"     => 0
#   "1305k" => 1305 * 1024
#   "70.2M" => 70.2 * 1024**2
#   "5.98G" => 5.98 * 1024**3
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
    """Drives one curlHelper-generated ``--config`` file to completion.

    Constructed per download config by the pybatch command, from the plain
    values that command was serialized with. ``label`` is the human-readable
    prefix the command uses for its own progress message; it is passed in so
    the log lines stay identical without this object reaching back into the
    command.

    All the cross-pass bookkeeping (byte/file high-water marks, the EMA
    throughput, the offline-hold budget, the parse caches) lives on the
    instance: one instance == one bulk transfer, however many curl passes
    that takes.
    """

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

        # Cumulative & monotonic progress state carried ACROSS re-runs (each
        # _run_curl_once is one curl pass; on pause/network-resume curl is
        # re-launched and its Xfers/Dled restart at 0). Without this, the
        # logged counts would reset on every resume and the UI would appear to
        # "start from the beginning". See _run_curl_once for the accounting.
        #
        # FILES: a re-run re-walks the WHOLE config -- already-finished files
        #   are still counted in Xfers (processed/skipped fast) so
        #   previously_downloaded_files + (Xfers - Live) trends back up to the
        #   true total on its own; we add NO per-run baseline (that would
        #   double-count). We only clamp it monotonic via this high-water mark.
        # BYTES: with curl resume (`continue-at = -`) a re-run's Dled counts
        #   only the NEW bytes this run. So cumulative = bytes_baseline (sum of
        #   each prior run's final Dled) + this run's current Dled. We fold the
        #   run's last Dled into the baseline when each run ends/pauses, and
        #   clamp monotonic via its own high-water mark.
        self._files_high_water = 0
        self._bytes_baseline = 0
        self._bytes_high_water = 0

        # EMA-smoothed throughput and the last-emit
        # sample baseline. The EMA value persists ACROSS re-runs so the ETA
        # stays stable through pause/resume; the per-run sample baseline is
        # re-seeded in _run_curl_once so the paused/offline gap is never divided
        # into a bogus "slow" speed. session_id is resolved once (not per tick).
        self._ema_throughput_bps = 0.0
        self._last_emit_monotonic = None
        self._last_emit_bytes = 0
        try:
            self._session_id = str(config_vars["__INVOCATION_RANDOM_ID__"]) \
                if config_vars.defined("__INVOCATION_RANDOM_ID__") else "unknown"
        except Exception:
            self._session_id = "unknown"

        # Offline-hold bookkeeping shared by the whole transfer (the initial
        # pass and any reconciliation passes draw from ONE overall hold budget
        # so a flapping network cannot hold an install forever).
        self._hold_seconds_used = 0.0
        self._offline_probe_attempt = 0

        # Lazily-filled parse caches (see the methods that own them).
        self._probe_host_port_cache = None
        self._part_output_paths_cache = None
        self._poll_files_high_water = 0

    def run(self):
        """Run the bulk download to completion and return curl's final code.

        Honors the Central pause/resume control channel during the curl
        download. This is the path that actually runs the bulk download (a
        single `curl --config` using curl's internal --parallel), so pause
        must be enforced HERE -- not only in ParallelRun. On pause we SIGTERM
        curl (so the partial .part files flush), wait for resume, then re-run
        `curl --config`, which resumes from the partial files via the
        `continue-at` entries curlHelper wrote. Without a channel (e.g.
        non-sync invocations) pause_check is None and behavior is unchanged.
        """
        config_file_path_fixed = os.fspath(self.config_file_path)
        if 'Win' in utils.get_current_os_names():
            # on windows curl fail to read long paths or paths with unicode chars
            # so convert the path to short path (DOS style 8.3 chars)
            import win32api
            config_file_path_fixed = win32api.GetShortPathName(config_file_path_fixed)

        channel = get_control_channel()
        pause_check = channel.is_paused if channel is not None else None

        return_code = self._run_config_with_recovery(config_file_path_fixed, pause_check, channel)
        if return_code == 0:
            # in --parallel mode curl's final exit code can be 0
            # while individual transfers failed permanently (their per-transfer
            # retries were exhausted while offline). Do not trust exit 0 --
            # reconcile expected outputs against the disk and re-download only
            # what is missing.
            return_code = self._reconcile_missing_outputs(pause_check, channel)

        print(f"Curl ended {return_code}")
        if can_run_fallback(self.fallback_config_file_path, return_code, self.fallback_exit_codes):
            self._run_fallback_after_curl_range_failure(return_code)
        return return_code

    def _run_config_with_recovery(self, config_file_path_fixed, pause_check, channel):
        """Run one curl config to completion, honoring pause/resume and
        surviving network drops. Returns curl's final return code.

        Re-run loop honoring pause/resume (mirrors
        ParallelRun._run_with_pause_and_offline_hold -- the bulk download
        actually runs here, not there). On pause we hold then re-run; on a
        network-class curl exit we:

        * emit a structured ``download.retry_decision`` event -- ONLY when
          the driving client declared DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD
          (a new Central treats it as informational offline evidence; an old
          Central's 3-streak detector would answer with a never-resumed
          pause, so without the capability only the legacy log line is
          written);
        * probe connectivity ourselves (``DOWNLOAD_OFFLINE_HOLD_ENABLED``):
          when the probe fails we HOLD -- probing in a pause-aware loop and
          emitting offline session_state events -- until the network returns
          or the overall hold timeout expires, WITHOUT burning the bounded
          retry budget. This makes the engine self-sufficient even when
          Central never sends a pause (e.g. elevated runs);
        * otherwise (reachable host, transfer-level failure) back off briefly
          and retry a bounded number of times so a short blip recovers.

        Terminal behavior is intentionally unchanged: once retries are
        exhausted / the hold times out (or for a non-network error) we return
        and let the downstream checksum pass redownload whatever is still
        missing -- this transfer never raised on curl failure.
        """
        network_retry_budget = 12
        network_attempt = 0
        while True:
            return_code, paused = self._run_curl_once(config_file_path_fixed, pause_check)
            if paused:
                log.info(f"{self.label} paused; holding until resume")
                if channel is not None:
                    channel.wait_if_paused()
                network_attempt = 0
                continue  # resume: re-run curl --config (continue-at resumes partial files)
            if return_code != 0 and is_network_error(return_code):
                # Offline grace: hold if Central paused us (offline), otherwise
                # probe/hold or back off briefly and retry.
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
                    # Genuinely offline: hold until connectivity returns.
                    # A hold does not consume the retry budget -- waiting out
                    # an outage is not a failed attempt.
                    if self._hold_until_online(channel):
                        continue  # back online: re-run (continue-at resumes .part files)
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
            return return_code

    # -- offline-hold with structured events --------------------

    def _probe_host_and_port(self):
        """The (host, port) to probe for connectivity: the validated download
        host from BASE_LINKS_URL when available, else the host of the first
        url entry in the curl config. Cached; (None, 443) when undeterminable
        (the probe then fails open -- assume online, keep legacy behavior)."""
        cached = getattr(self, "_probe_host_port_cache", None)
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

    # Proxy env vars curl honors (checked in this order; os.environ lookup is
    # case-insensitive on Windows, so both cases are listed for POSIX).
    _PROXY_ENV_VARS = ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
                       "all_proxy", "ALL_PROXY")

    @classmethod
    def _proxy_probe_target(cls):
        """When curl's transfers go through a proxy, a DIRECT TCP connect to
        the download host proves nothing -- on proxy-only networks outbound
        443 is firewalled and the direct probe always fails, which would turn
        every transient curl exit into a long false offline hold while the
        (proxied) network is perfectly healthy.

        Returns:
        * ``None`` -- no proxy env var set: probe the download host directly.
        * ``(host, port)`` -- probe THROUGH the proxy, i.e. TCP connect to
          the proxy endpoint itself (reachable proxy == usable network for
          curl, which uses the same env vars).
        * ``("", 0)`` -- a proxy is configured but its address cannot be
          determined: the probe is INCONCLUSIVE and must fail open (assume
          online -> legacy bounded backoff, never a false 30-min hold).
        """
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
        # Proxy set but host/port unparsable (e.g. no explicit port): probing
        # a guessed port risks a false offline -- treat as inconclusive.
        return "", 0

    def _probe_connectivity(self):
        """Cheap connectivity probe: DNS resolve + TCP connect to the download
        host -- or to the PROXY when proxy env vars are set (curl connects to
        the proxy, not the origin, so that is the reachability that matters;
        see :meth:`_proxy_probe_target`). Returns ``(online, failure_class)``
        where failure_class is a DownloadFailureClass value string when
        offline (dns_resolution / tcp_connect -- both network-class for
        Central's online detector). Fails OPEN: when no probe host can be
        determined, or a proxy is configured but not parsable, report online
        so behavior degrades to the legacy bounded-backoff path."""
        proxy_target = self._proxy_probe_target()
        if proxy_target is not None:
            host, port = proxy_target
            if not host:
                return True, None  # proxy configured but undeterminable: inconclusive, fail open
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
        """Hold the download while the network is down.

        Probes connectivity in a pause-aware loop (``sleep_or_wake`` so
        Central's pause/resume/try_now still interrupt), emitting:

        * a throttled ``session_state`` event with ``state=paused`` and an
          offline-flavored ``reason`` so Central freezes the progress UI and
          shows the offline label (downloadVisibleState.reasonLooksOffline);
        * a network-class ``retry_decision`` event per failed probe so
          Central's online detector reaches its >=3 streak even though curl
          is not being re-run while offline.

        Both emissions are gated on DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD
        (inside the emit helpers): a client that did not declare the
        capability gets the legacy log lines only, while the hold itself
        still recovers silently.

        Returns True when connectivity returned (a ``downloading`` /
        ``resuming_after_offline`` session_state is emitted), False when the
        OVERALL hold timeout (cumulative across holds in this transfer, config
        var DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS) expired.

        The hold budget measures ACTIVE hold time only: time spent blocked in
        ``channel.wait_if_paused()`` (an explicit user/Central pause) is
        subtracted -- otherwise one paused outage would silently spend the
        whole cumulative budget and a LATER outage in the same transfer would
        get zero hold protection (the same principle _RedownloadBudget
        applies to the redownload pass).
        """
        probe_interval = max(1, config_var_int("DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS", 5))
        hold_timeout = max(0, config_var_int("DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS", 1800))
        event_interval = max(probe_interval, config_var_int("DOWNLOAD_OFFLINE_HOLD_EVENT_INTERVAL_SECONDS", 30))
        already_used = getattr(self, "_hold_seconds_used", 0.0)
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
                channel.wait_if_paused()          # explicit Central pause still holds here
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
            self._offline_probe_attempt = getattr(self, "_offline_probe_attempt", 0) + 1
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
        """Emit a structured ``download.retry_decision`` DOWNLOAD_EVENT for a
        bulk-download network failure (curl exit or connectivity probe).

        The bulk curl loop previously only wrote a free-text log line on
        network errors, so Central's online detector (which counts a streak
        of network-class retry_decision events) never fired. Best-effort and
        additive: schema/fields are exactly the existing retry_decision event
        (fileId/repoPath stay null for the bulk transfer); the emitter is
        gated by the DOWNLOAD_TELEMETRY_ENABLED kill switch like every other
        structured event.

        Emitted ONLY when the driving client declared it handles backend
        holds (see :func:`_client_handles_backend_hold`): an old Central's
        streak detector would answer these events with a pause nothing
        auto-resumes on Windows. When the capability is absent the bulk loop
        keeps its legacy free-text log lines only.
        """
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
            emit_retry_decision(decision, session_id=getattr(self, "_session_id", "unknown"))
        except Exception as ex:  # pragma: no cover - instrumentation must never break a download
            log.debug(f"could not emit bulk retry decision event: {ex}")

    def _emit_hold_session_state(self, state, reason, previous_state=None):
        """Emit a ``session_state`` transition for the offline hold / resume.

        Carries the current on-disk byte progress so Central's bar keeps its
        position while frozen. No throughput field is sent -- the hold gap
        must not be averaged into the ETA (the EMA baseline is re-seeded per
        curl pass, see _run_curl_once). Additive to the existing schema.

        Like the bulk retry_decision events, these offline-hold / stall /
        reconcile session_states are emitted ONLY when the driving client
        declared DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD (see
        :func:`_client_handles_backend_hold`) -- an old Central must see
        exactly the legacy event stream while the engine recovers silently.
        """
        if not _client_handles_backend_hold():
            return
        try:
            from pyinstl.downloadEvents import emit_session_state
            try:
                cumulative_bytes, files_est = self._sum_downloaded_part_bytes()
            except Exception:
                cumulative_bytes, files_est = 0, 0
            emit_session_state(
                session_id=getattr(self, "_session_id", "unknown"),
                state=state,
                previous_state=previous_state,
                reason=reason,
                bytes_received=int(cumulative_bytes),
                files_completed=int(files_est),
                phase_bytes_done=int(cumulative_bytes),
                phase_bytes_planned=int(self.total_bytes_to_download),
            )
        except Exception as ex:  # pragma: no cover - instrumentation must never break a download
            log.debug(f"could not emit hold session_state event: {ex}")

    # -- post-run completeness reconciliation -------------------

    # Directive keys that curlHelper writes per download entry; everything
    # else in the config file is header material (see curlHelper
    # write_download_entry / *_parallel_header_text).
    _CURL_ENTRY_KEYS = frozenset({"no-fail", "continue-at", "header", "url", "output", "next"})

    def _parse_curl_config_for_reconcile(self, config_path):
        """Parse a curlHelper-generated ``--config`` file into its header and
        per-download entries so a retry config can be written for missing
        outputs, preserving each entry's original lines (url / output /
        continue-at / conditional headers).

        Returns ``(header_lines, entries, uses_isolated_sections)`` where each
        entry is a dict with ``pre_lines`` (no-fail / continue-at / header
        lines), ``url_line``, ``output_line`` and the unquoted ``output_path``.
        Best-effort: any read problem returns empty results so reconciliation
        degrades to a no-op instead of breaking the download.
        """
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
                            # isolated transfer sections: 'next' + repeated
                            # header; the repeats are skipped below because
                            # in_entries is already True.
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
                    # non-entry keys after the first entry are repeated header
                    # lines from isolated sections -- skip them.
        except OSError as ex:
            log.warning(f"{self.label} could not parse curl config for reconciliation: {ex}")
            return [], [], False
        return header_lines, entries, uses_isolated_sections

    @staticmethod
    def _fresh_start_entry(entry):
        """Rewrite a reconcile entry as a FRESH-START transfer.

        Reconciliation only ever re-runs entries whose output file is MISSING
        on disk, so the entry's original resume/conditional lines must not be
        replayed verbatim:

        * ``continue-at = N`` (N>0, written for resume entries): with a
          nonexistent output, curl fetches the ranged body (bytes N..end) but
          writes it at offset 0 -- a silently corrupt file missing its first
          N bytes that reconciliation would then count as recovered (or the
          server answers 416 / curl exits 33). Rewritten to ``continue-at =
          -`` so curl starts from whatever is on disk -- nothing, i.e. byte 0.
        * ``header = "If-..."`` conditional headers (If-None-Match /
          If-Modified-Since etc., written alongside resume entries): stale
          without the partial file they validated; a 304 would produce no
          body at all. Dropped.

        ``no-fail`` and any other non-conditional pre-lines are preserved.
        """
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
                    continue  # stale conditional header: drop for a fresh start
            fresh_pre_lines.append(pre_line)
        fresh_entry = dict(entry)
        fresh_entry["pre_lines"] = fresh_pre_lines
        return fresh_entry

    def _write_reconcile_config(self, retry_config_path, header_lines, entries, uses_isolated_sections):
        """Write a retry curl config containing only ``entries``, preserving
        their original lines, under the original config's header."""
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

    def _reconcile_missing_outputs(self, pause_check, channel):
        """verify every expected output exists after curl exit 0
        and re-download only the missing ones.

        curl --parallel masks per-transfer failures: transfers whose internal
        retries were exhausted (e.g. while offline) are simply dropped, yet
        the final exit code can still be 0. The config's ``output`` entries
        ARE the ``.part`` paths curl writes, so a missing output means the
        transfer never produced a byte. Bounded by
        DOWNLOAD_RECONCILE_MAX_ROUNDS; each round re-runs through the same
        pause/offline-hold recovery loop. After rounds are exhausted we log
        and continue -- the checksum phase remains the final gate.

        Returns the final curl return code (0 when nothing was missing or the
        reconciliation runs succeeded).
        """
        return_code = 0
        if not config_var_bool("DOWNLOAD_RECONCILE_MISSING_OUTPUTS", True):
            return return_code
        max_rounds = max(0, config_var_int("DOWNLOAD_RECONCILE_MAX_ROUNDS", 3))
        if max_rounds == 0:
            return return_code
        header_lines, entries, uses_isolated_sections = \
            self._parse_curl_config_for_reconcile(self.config_file_path)
        if not entries:
            return return_code
        missing = []
        for round_i in range(1, max_rounds + 1):
            # Entries here are by definition missing their output file, so
            # each is rewritten as a fresh-start transfer (no continue-at = N
            # replay, no stale conditional headers -- see _fresh_start_entry).
            missing = [self._fresh_start_entry(entry) for entry in entries
                       if not os.path.exists(entry["output_path"])]
            if not missing:
                if round_i > 1:
                    log.info(f"{self.label} reconciliation recovered all missing outputs")
                return return_code
            log.info(f"{self.label} curl exited 0 but {len(missing)} of {len(entries)} "
                     f"expected outputs are missing; reconciliation round {round_i} of {max_rounds}")
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
        return return_code

    def _maybe_emit_progress_tick(self, cumulative_bytes, downloaded_files):
        """Emit a throttled, EMA-smoothed ``session_state`` progress tick.

        curl's per-tick Speed is too jittery to drive
        a stable ETA, and the structured ``session_state`` events otherwise
        carry no in-flight bytes/throughput -- so Central could only compute an
        ETA from the end-of-session summary (i.e. never, during the download).
        This feeds Central cumulative received bytes plus a smoothed throughput
        roughly once per second, so its ETA is populated and stable from the
        first tick.

        The EMA persists across re-runs (smoothing survives pause/resume); the
        first sample of each curl pass only re-establishes the baseline (see the
        ``_last_emit_monotonic = None`` reset in ``_run_curl_once``) so a paused
        gap is never divided into a bogus low speed. Best-effort: any failure is
        swallowed -- instrumentation must never break a download.
        """
        try:
            now = time.monotonic()
            last = getattr(self, "_last_emit_monotonic", None)
            if last is None:
                # First sample of this curl pass: establish the baseline only.
                # The carried-over EMA (if any) still rides along on the tick.
                self._last_emit_monotonic = now
                self._last_emit_bytes = cumulative_bytes
            else:
                dt = now - last
                if dt < _DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC:
                    return  # throttle: at most one tick per interval
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
                session_id=getattr(self, "_session_id", "unknown"),
                state="downloading",
                bytes_received=int(cumulative_bytes),
                files_completed=int(downloaded_files),
                observed_throughput_bytes_per_second=int(self._ema_throughput_bps),
                # phase_bytes_* mirror the verify phase's tick so Central's
                # phaseDisplayPercent drives a determinate download bar (received
                # / planned), not just the meta line's byte/throughput counters.
                phase_bytes_done=int(cumulative_bytes),
                phase_bytes_planned=int(self.total_bytes_to_download),
                reason="download_progress",
            )
        except Exception as ex:  # pragma: no cover - instrumentation must never break sync
            log.debug(f"could not emit download progress tick: {ex}")

    def _download_part_output_paths(self):
        """Parse the curl ``--config`` file once for its ``output = "..."`` entries.

        curlHelper writes every download as ``output = "<final>.instl-<id>.part"``
        with a ``continue-at`` directive for resume, so these ``.part`` files are
        exactly what curl grows on disk. Summing their sizes gives true cumulative
        received bytes -- independent of curl's console meter, the fragile,
        platform-variable source that yields no in-flight rows on Windows. Parsed
        once and cached; best-effort (any failure -> empty list, so the poller
        simply emits nothing rather than breaking the download)."""
        cached = getattr(self, "_part_output_paths_cache", None)
        if cached is not None:
            return cached
        paths = []
        try:
            with open(os.fspath(self.config_file_path), "r", encoding="utf-8", errors="replace") as cfg:
                for line in cfg:
                    s = line.strip()
                    # form: output = "C:\...\file.ext.instl-<id>.part"
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

    def _sum_downloaded_part_bytes(self):
        """Sum on-disk sizes of the ``.part`` outputs (cumulative received bytes).

        Best-effort per file: a not-yet-created, locked, or vanished part is
        skipped, never raised. Returns ``(cumulative_bytes, files_estimate)``.
        curl writes all parts in place and instl renames only after the batch, so
        a true per-file completion count is not observable here -- files_estimate
        is a monotonic, byte-proportional approximation (bytes drive the bar/ETA;
        the file count is informational)."""
        total = 0
        for p in self._download_part_output_paths():
            try:
                total += os.path.getsize(p)
            except OSError:
                pass  # not created yet / locked / vanished -- skip this sample
        planned_bytes = self.total_bytes_to_download or 0
        if planned_bytes > 0:
            files_est = int(self.total_files_to_download * min(1.0, total / planned_bytes))
        else:
            files_est = 0
        prev_high = getattr(self, "_poll_files_high_water", 0)
        if files_est < prev_high:
            files_est = prev_high
        else:
            self._poll_files_high_water = files_est
        files_est = min(files_est, self.total_files_to_download)
        return total, files_est

    def _run_download_progress_poller(self, stop_event):
        """Daemon poller: ~once/second, emit a ``download_progress`` tick derived
        from on-disk ``.part`` sizes -- mirroring the verify phase's in-process
        Python cadence, the one progress mechanism that works cross-platform.

        Never raises (instrumentation must never break a download) and is bounded
        by ``stop_event`` so it always joins promptly -- this must never wedge the
        sync or elevated-copy process (see P7-010).

        Stall watchdog: when total on-disk
        bytes have not grown for DOWNLOAD_STALL_WATCHDOG_SECONDS while curl is
        still alive, log it and emit a stalled-flavored ``session_state`` as a
        backstop signal. The poller never kills curl -- enforcement is curl's
        own speed-limit/speed-time (see curlHelper), which makes a stalled
        transfer exit 28 and feed the offline-hold/retry loop. 0 disables.

        Fast offline detection (field finding 2026-07-30): when the link drops
        mid-transfer, curl's sockets merely STALL -- no exit code fires until
        speed-time, so the offline hold in _run_config_with_recovery could
        not start for minutes while the UI showed a climbing ETA. The poller
        is the component that notices the freeze within a tick, so after
        DOWNLOAD_STALL_PROBE_SECONDS of zero byte growth it runs the same
        connectivity probe the recovery loop uses: probe-offline raises the
        paused/offline_no_network hold events immediately (curl keeps
        running; if the outage outlives speed-time the recovery loop takes
        over seamlessly), and the hold is released with
        resuming_after_offline only when bytes actually grow again -- probe
        success alone keeps the UI paused, because a wedged curl will be
        speed-time-aborted and re-run before real progress resumes. 0
        disables the probe; emissions stay gated by the client capability
        handshake inside the emit helpers."""
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
        stall_offline_active = False
        while not stop_event.is_set():
            try:
                cumulative_bytes, files_est = self._sum_downloaded_part_bytes()
                now = time.monotonic()
                if cumulative_bytes > last_growth_bytes:
                    if stall_offline_active:
                        # Announce the resume BEFORE the first grown tick so
                        # Central's detector takes the explicit
                        # resuming_after_offline path (streak reset + online),
                        # not the weaker hold-ended-without-announcement one.
                        log.info(f"{self.label} download progress resumed after "
                                 f"{int(now - last_growth_monotonic)}s offline stall")
                        self._emit_hold_session_state("downloading", "resuming_after_offline",
                                                      previous_state="paused")
                        stall_offline_active = False
                    last_growth_bytes = cumulative_bytes
                    last_growth_monotonic = now
                    self._maybe_emit_progress_tick(cumulative_bytes, files_est)
                else:
                    stalled_for = now - last_growth_monotonic
                    if not stall_offline_active:
                        # Flat ticks are only emitted while NOT holding: a
                        # non-paused session state would clear Central's
                        # backend-hold flag every second and churn its logs
                        # (the frozen UI needs no updates for frozen bytes).
                        self._maybe_emit_progress_tick(cumulative_bytes, files_est)
                    if (probe_enabled and stalled_for >= stall_probe_seconds
                            and now - last_probe_monotonic >= probe_interval):
                        last_probe_monotonic = now
                        online, _probe_failure_class = self._probe_connectivity()
                        if not online and (not stall_offline_active
                                           or now - last_hold_emit_monotonic >= event_interval):
                            if not stall_offline_active:
                                log.info(f"{self.label} no byte progress for "
                                         f"{int(stalled_for)}s and connectivity probe failed; "
                                         f"reporting offline hold while curl transfer is stalled")
                            self._emit_hold_session_state("paused", "offline_no_network",
                                                          previous_state="downloading")
                            last_hold_emit_monotonic = now
                            stall_offline_active = True
                        # probe success while still stalled: keep the hold visible;
                        # resuming_after_offline is announced only on real byte growth
                    if (stall_watchdog_seconds > 0 and not stall_offline_active
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

    def _run_curl_once(self, config_file_path_fixed, pause_check):
        """Run one `curl --config` pass, logging progress.

        Returns (returncode, paused). If pause_check() becomes true while curl
        is running we terminate it (SIGTERM, so partial .part files flush for a
        later resume) and return paused=True. Pause-detection latency is bounded
        by curl's progress cadence (~1s), same as utils.parallel_run.run_process.
        """
        # start_new_session so curl becomes its own process-group leader, which
        # is what terminate_process's os.killpg targets on pause (mirrors
        # launch_process's preexec_fn=os.setsid in parallel_run). Without it the
        # killpg has no group to signal and curl would keep downloading.
        # cwd is the config file's folder so relative paths in the config
        # resolve next to it (CEN2-3679).
        working_dir = os.fspath(Path(config_file_path_fixed).parent)
        process = subprocess.Popen([os.fspath(self.curl_path), "--config", config_file_path_fixed],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                   universal_newlines=True,
                                   start_new_session=True,
                                   bufsize=1,
                                   cwd=working_dir)
        reg = re.compile(r"""^\s*
           (?P<DL_percent>[\d.-]+)\s+
           (?P<UL_percent>[\d.-]+)\s+
           (?P<Dled>[\d.a-z]+)\s+
           (?P<Uled>[\d.a-z]+)\s+
           (?P<Xfers>[\d]+)\s+
           (?P<Live>[\d]+)\s+
           (?P<Queue>[\d]+)?\s*?
           (?P<Total>[\d:-]+)\s+
           (?P<Current>[\d:-]+)\s+
           (?P<Left>[\d:-]+)\s+
           (?P<Speed>[\d.a-z]+)
           (?P<the_rest>.*)?$""",
           re.IGNORECASE | re.VERBOSE)

        bytes_to_download_str = bytes_to_string(self.total_bytes_to_download)

        # Last Dled (in bytes) parsed this run; folded into the cumulative
        # bytes baseline when the run ends/pauses (so the next run's Dled, which
        # restarts at 0 yet only fetches the remaining bytes, adds on top).
        last_run_dled_bytes = 0

        # re-seed the throughput sample baseline for THIS curl
        # pass. The EMA value itself carries over (smoothing survives resume),
        # but the first sample of each pass only re-establishes the baseline so
        # the paused/offline wall-time gap is never counted as transfer time.
        self._last_emit_monotonic = None

        # Windows parity with Mac: drive the
        # structured download_progress ticks from on-disk .part sizes via a
        # Python-cadence poller -- exactly like the verify phase -- instead of
        # scraping curl's --parallel console meter. That meter yields no usable
        # in-flight rows on Windows (so the download bar/ETA never move), while
        # verify, an in-process Python loop, ticks fine in the very same run.
        # Cross-platform, no sys.platform branch: Mac keeps working and gains a
        # deterministic cadence. Hang-safe (P7-010): daemon thread + stop Event
        # + bounded join in the finally below; the poller only reads file sizes.
        _poll_stop = Event()
        _poll_thread = Thread(target=self._run_download_progress_poller,
                              args=(_poll_stop,),
                              name="download-progress-poller",
                              daemon=True)
        _poll_thread.start()

        paused = False
        try:
            while process.poll() is None:
                # Check pause before blocking on the next progress line so a pause
                # stops the transfer within roughly one progress tick.
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

                        # FILES: monotonic only (no per-run baseline -- a re-run
                        # re-counts finished files in Xfers, so the value already
                        # trends back to the true total). Never report below the
                        # high-water mark, cap at the total.
                        if downloaded_files > self._files_high_water:
                            self._files_high_water = downloaded_files
                        downloaded_files = min(self._files_high_water, self.total_files_to_download)

                        # BYTES: cumulative across re-runs. This run's Dled only
                        # counts new bytes (curl resumes via continue-at), so add
                        # the baseline of bytes finished in prior runs. Clamp
                        # monotonic and cap at the total.
                        current_dled_bytes = string_to_bytes(match.group('Dled'))
                        last_run_dled_bytes = current_dled_bytes
                        cumulative_bytes = self._bytes_baseline + current_dled_bytes
                        if cumulative_bytes > self._bytes_high_water:
                            self._bytes_high_water = cumulative_bytes
                        cumulative_bytes = min(self._bytes_high_water, self.total_bytes_to_download)
                        downloaded_bytes_str = bytes_to_string(cumulative_bytes)

                        # Legacy human-readable line (also feeds Central's older
                        # text-based liveDownload parser where curl's meter is
                        # available, e.g. Mac). The structured download_progress
                        # tick is now emitted by the .part poller, not here, so
                        # the UI advances even when this meter line never appears.
                        message = f"Progress ... of ...; " \
                                  f"Downloaded {downloaded_files} of {self.total_files_to_download} files, " \
                                  f"Downloaded {downloaded_bytes_str} of {bytes_to_download_str}, " \
                                  f"Speed {match.group('Speed')}"
                        log.info(message)
        finally:
            # Stop the poller deterministically before returning. Bounded join so
            # a stuck size-read can never wedge the sync/elevated-copy process.
            _poll_stop.set()
            _poll_thread.join(timeout=2.0)

        try:
            process.stdout.close()
        except Exception:
            pass
        process.wait()
        # Fold this run's final Dled into the cumulative byte baseline so the
        # next re-run (whose Dled restarts at 0 but fetches only the remaining
        # bytes) is reported on top of what this run actually transferred.
        self._bytes_baseline += last_run_dled_bytes
        return process.returncode, paused

    def _run_fallback_after_curl_range_failure(self, exit_code):
        """Re-run the whole transfer from zero using the fallback curl config.

        NOT shared with ParallelRun's same-named method: that one reads a
        parallel-run command file (one shell command per line) and hands it to
        utils.run_processes_in_parallel, whereas this one hands curl a single
        `--config` file of its own. Different input format, different runner.
        """
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
