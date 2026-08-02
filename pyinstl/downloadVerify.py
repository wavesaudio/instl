#!/usr/bin/env python3.12

"""Post-download verification and recovery, driven by the batch commands in
``pybatch.info_mapBatchCommands``: resume-sidecar bookkeeping, retry decisions for
files that fail the checksum gate, the parallel hashing pass, the budget-bounded
redownload pass, and the download-phase ``session_state`` emitters.

``pybatch`` must NOT be imported here -- ``pyinstl/__init__`` pulls it in through
``instlInstanceBase``. The command instead passes itself, for the progress counter it
owns, plus ``report_progress``: its bound ``increment_and_output_progress``.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from configVar import config_vars
from configVar import config_var_str, config_var_bool, config_var_int, config_var_list

from pyinstl.downloadState import (
    DownloadFileState,
    checksum_matches,
    file_id_for_download_item,
    get_file_sha1,
    load_resume_sidecar_for_download_item,
    redact_url_for_state,
    remove_stale_temp_for_download_item,
    resolve_validated_hosts,
    resume_decision_for_download_item,
    save_resume_sidecar_for_download_item,
    temp_path_for_download_item,
)
from pyinstl.downloadFailures import (
    DownloadFailureClass,
    DownloadFailureInfo,
    classify_exception,
    is_retryable_failure_class,
)
from pyinstl.downloadRetry import (
    RetryAction,
    decide_retry,
    format_retry_decision_log_line,
    sleep_backoff,
)
from pyinstl.downloadControlChannel import get_global_channel
from pyinstl.downloadObservability import (
    DownloadOutcome,
    record_outcome as _observability_record_outcome,
    record_retry_decision as _observability_record_retry_decision,
)
from pyinstl.downloadEvents import (
    emit_retry_decision as _events_emit_retry_decision,
    emit_file_state as _events_emit_file_state,
    emit_capability as _events_emit_capability,
    emit_session_state as _events_emit_session_state,
    set_telemetry_enabled as _events_set_telemetry_enabled,
    active_flags_from_config as _events_active_flags_from_config,
)

log = logging.getLogger(__name__)


# -- resume sidecar bookkeeping -----------------------------------


def source_url_for_file_item(info_map_table, file_item):
    try:
        return info_map_table.get_sync_url_for_file_item(file_item)
    except Exception:
        return getattr(file_item, "url", None)


def source_metadata_from_record(record):
    if record is None:
        return {}
    return {
        key: value
        for key, value in {
            "etag": record.source.etag,
            "last_modified": record.source.last_modified,
            "content_length": record.source.content_length,
            "version_id": record.source.version_id,
            "signed_url_expires_at": record.source.signed_url_expires_at,
        }.items()
        if value is not None
    }


def _existing_source_metadata(info_map_table, file_item, bookkeeping_dir, source_url):
    try:
        record = load_resume_sidecar_for_download_item(file_item, bookkeeping_dir)
    except Exception:
        return {}
    if record and record.source.url_redacted == redact_url_for_state(source_url):
        return source_metadata_from_record(record)
    return {}


def resume_decision_for_file_item(info_map_table, file_item):
    bookkeeping_dir = config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
    return resume_decision_for_download_item(
        file_item,
        source_url_for_file_item(info_map_table, file_item),
        bookkeeping_dir,
        resume_enabled=config_var_bool("DOWNLOAD_RESUME_ENABLED", False),
        validated_hosts=resolve_validated_hosts(
            config_var_list("DOWNLOAD_RESUME_VALIDATED_HOSTS"),
            config_var_str("BASE_LINKS_URL"),
        ),
        validated_path_prefixes=config_var_list("DOWNLOAD_RESUME_VALIDATED_PATH_PREFIXES"),
        require_conditional=config_var_bool("DOWNLOAD_RESUME_REQUIRE_CONDITIONAL", True),
        signed_url_min_ttl_seconds=config_var_int("DOWNLOAD_RESUME_MIN_SIGNED_URL_TTL_SECONDS", 300),
    )


def _resume_bookkeeping_enabled():
    """Whether per-file resume sidecars should be written this run. Each is an fsync +
    atomic replace, so one per file in a large sync costs minutes, and they are only
    ever read back to drive a byte-range resume. Telemetry is a separate channel."""
    return config_var_bool("DOWNLOAD_RESUME_ENABLED", False)


def save_resume_sidecar(info_map_table, file_item, transfer_state, received_bytes=None, last_failure_class=None, source_metadata=None, retry_count=0):
    if not _resume_bookkeeping_enabled():
        return None
    bookkeeping_dir = config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
    if not bookkeeping_dir:
        return None
    source_url = source_url_for_file_item(info_map_table, file_item)
    if source_metadata is None:
        source_metadata = _existing_source_metadata(info_map_table, file_item, bookkeeping_dir, source_url)
    try:
        return save_resume_sidecar_for_download_item(
            file_item,
            source_url,
            bookkeeping_dir,
            session_id=config_var_str("__INVOCATION_RANDOM_ID__", "unknown"),
            repository_major_version=config_var_str("TARGET_MAJOR_VERSION") or config_var_str("SYNC_BASE_URL_MAIN_ITEM"),
            transfer_state=transfer_state,
            received_bytes=received_bytes,
            last_failure_class=last_failure_class,
            retry_count=retry_count,
            source_metadata=source_metadata,
        )
    except Exception as ex:
        log.warning(f"could not save download resume sidecar for {getattr(file_item, 'path', 'unknown')}: {ex}")
        return None


# -- failure classification and the retry decision ----------------


def build_failure_info(failure_class, *, http_status=None, curl_exit_code=None, retry_after_seconds=None, reason=""):
    """DownloadFailureInfo for a caller that already knows the class, so a decision made
    at a known checkpoint has the same shape as one made from an exception."""
    try:
        cls = DownloadFailureClass(failure_class) if isinstance(failure_class, str) else failure_class
    except ValueError:
        cls = DownloadFailureClass.UNKNOWN_DOWNLOAD_ERROR
    return DownloadFailureInfo(
        failure_class=cls,
        retryable=is_retryable_failure_class(cls),
        source="instl",
        reason=reason or cls.value,
        curl_exit_code=curl_exit_code,
        http_status=http_status,
        retry_after_seconds=retry_after_seconds,
    )


def emit_retry_decision(info_map_table, file_item, failure, *, received_bytes=None, resume_eligible=False, concurrency=None, previous_retry_count_override=None):
    """Compute a retry decision for file_item, persist it on the sidecar, log it, and
    return it so callers can drive the retry. None when DOWNLOAD_RETRY_POLICY_ENABLED
    is off. The redownload loop must pass previous_retry_count_override: the persisted
    count lives on the resume sidecar, not written when resume bookkeeping is disabled
    (the default), so reading it would always give 0 and never reach the terminal
    attempt."""
    if not config_var_bool("DOWNLOAD_RETRY_POLICY_ENABLED", True):
        return None
    bookkeeping_dir = config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
    previous_retry_count = 0
    if previous_retry_count_override is not None:
        previous_retry_count = previous_retry_count_override
    elif bookkeeping_dir:
        try:
            existing = load_resume_sidecar_for_download_item(file_item, bookkeeping_dir)
        except Exception:
            existing = None
        if existing is not None:
            previous_retry_count = existing.transfer.retry_count

    decision = decide_retry(failure, previous_retry_count, resume_eligible=resume_eligible)

    transfer_state = (
        DownloadFileState.FAILED_TERMINAL
        if decision.action == RetryAction.FAIL_TERMINAL
        else DownloadFileState.FAILED_RETRYABLE
    )
    next_retry_count = previous_retry_count + (1 if decision.will_retry else 0)

    file_id = None
    try:
        file_id = file_id_for_download_item(file_item)
    except Exception:
        file_id = None

    try:
        log_line = format_retry_decision_log_line(
            decision,
            session_id=config_var_str("__INVOCATION_RANDOM_ID__", "unknown"),
            file_id=file_id,
            repo_path=getattr(file_item, "path", None),
            received_bytes=received_bytes,
            concurrency=concurrency,
        )
        log.info(log_line)
    except Exception as log_ex:  # pragma: no cover - logging must never break sync
        log.debug(f"could not format retry decision log: {log_ex}")

    # the same decision plus a paired file_state event, on the DOWNLOAD_EVENT channel
    try:
        session_id = config_var_str("__INVOCATION_RANDOM_ID__", "unknown")
        _events_emit_retry_decision(
            decision,
            session_id=session_id,
            file_id=file_id,
            repo_path=getattr(file_item, "path", None),
            received_bytes=received_bytes,
            concurrency=concurrency,
        )
        _events_emit_file_state(
            session_id=session_id,
            file_id=file_id,
            repo_path=getattr(file_item, "path", None),
            state=transfer_state,
            received_bytes=received_bytes,
            retry_count=next_retry_count,
            last_failure_class=failure.failure_class.value,
        )
    except Exception as ev_ex:  # pragma: no cover - events must never break sync
        log.debug(f"could not emit retry decision event: {ev_ex}")

    save_resume_sidecar(
        info_map_table,
        file_item,
        transfer_state,
        received_bytes=received_bytes,
        last_failure_class=failure.failure_class.value,
        retry_count=next_retry_count,
    )

    try:
        source_url = source_url_for_file_item(info_map_table, file_item)
        _observability_record_retry_decision(
            decision,
            url=source_url,
            bytes_received=received_bytes,
        )
    except Exception as obs_ex:  # pragma: no cover - instrumentation must never break sync
        log.debug(f"observability record_retry_decision failed: {obs_ex}")

    return decision


def record_promoted_outcome(info_map_table, file_item, promoted_bytes):
    """Record a promoted temp file as a successful transfer for the throughput sampler."""
    try:
        _observability_record_outcome(
            outcome=DownloadOutcome.SUCCESS,
            url=source_url_for_file_item(info_map_table, file_item),
            bytes_received=promoted_bytes,
        )
    except Exception as obs_ex:  # pragma: no cover
        log.debug(f"observability record_outcome failed: {obs_ex}")


# -- progress reporting for the high fan-out loops ----------------


def emit_throttled_progress(cmd, prog_msg, increment_by, index, total, throttle_attr):
    """Advance the progress counter every item, but throttle the log line to ~4x/sec
    (first and last item always logged). In the high fan-out loops the per-item
    "Progress N of M" line, not the real work, was the dominant cost of the phase; the
    counter still advances per item so Central's running total stays exact.
    ``throttle_attr`` names the attribute on ``cmd`` holding the last log timestamp."""
    # ignore_progress is a PythonBatchCommandBase class attribute, reached through the
    # instance so this module needs no pybatch import
    if not (cmd.report_own_progress and not cmd.ignore_progress):
        return
    if increment_by:
        cmd.increment_progress(increment_by)
    now = time.monotonic()
    last = getattr(cmd, throttle_attr, None)
    if last is None or index >= total - 1 or (now - last) >= 0.25:
        setattr(cmd, throttle_attr, now)
        log.info(f"{cmd.progress_msg()} {prog_msg}")


def verify_progress_log(cmd, prog_msg, increment_by, file_index, total_items):
    """Throttled per-file progress for the verify loop, see emit_throttled_progress."""
    emit_throttled_progress(cmd, prog_msg, increment_by, file_index, total_items,
                            "_verify_last_progress_log")


def bad_file_progress(cmd, report_progress, prog_msg, file_index, total_items):
    """Bad/missing-file lines are logged unconditionally up to the warn threshold and
    throttled beyond it - a mass failure would otherwise flood the log. Bookkeeping and
    the retry_decision events are never throttled."""
    threshold = cmd.max_bad_files_to_redownload
    if (threshold is None
            or not count_all_bad_files()
            or cmd.num_bad_files <= max(int(threshold), 1)):
        report_progress(increment_by=0, prog_msg=prog_msg)
    else:
        verify_progress_log(cmd, prog_msg, 0, file_index, total_items)


def emit_verify_progress(cmd, done_bytes, planned_bytes, force=False):
    """``verifying_downloads`` session_state tick with per-phase byte progress,
    throttled to 1/sec so it never slows the verify loop."""
    try:
        now = time.monotonic()
        last = getattr(cmd, "_verify_last_emit", None)
        if not force and last is not None and (now - last) < 1.0:
            return
        cmd._verify_last_emit = now
        _events_emit_session_state(
            session_id=config_var_str("__INVOCATION_RANDOM_ID__", "unknown"),
            state="verifying_downloads",
            phase_bytes_done=int(done_bytes),
            phase_bytes_planned=int(planned_bytes),
            reason="verify_progress",
        )
    except Exception as ex:  # pragma: no cover - instrumentation must never break sync
        log.debug(f"could not emit verify progress tick: {ex}")


# -- the checksum verify pass -------------------------------------


def count_all_bad_files() -> bool:
    """True when the verify loop counts ALL bad/missing files and the redownload pass
    is budget-bounded. Off (kill switch) restores the legacy count cliff exactly."""
    return config_var_bool("DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES", True)


def redownload_pass_enabled(max_bad_files_to_redownload) -> bool:
    """max_bad_files_to_redownload None/0 means "verify only" - the in-process
    check-checksum command and old scripts rely on that."""
    return bool(max_bad_files_to_redownload)


def resolve_verify_workers(num_items: int) -> int:
    """Worker count for the parallel verify pass. DOWNLOAD_PARALLEL_WORKERS==0 means
    auto (os.cpu_count()); 1 means serial."""
    if not config_var_bool("DOWNLOAD_PARALLEL_VERIFY", False):
        return 1
    if num_items <= 1:
        return 1
    configured = config_var_int("DOWNLOAD_PARALLEL_WORKERS", 0)
    if configured <= 0:
        configured = os.cpu_count() or 1
    workers = min(configured, num_items)
    return max(1, workers)


def precompute_verify_hashes(file_item):
    """Read-only, independent per-file hashing, runs in a worker thread - hashlib
    releases the GIL during update(), so this gives real speedup. Touches NO
    process-global state, only the filesystem and the passed-in file_item. Returns
    (final_path_matches, temp_is_file, temp_checksum); the temp sha1 is unused unless
    the final path failed to match, but hashing it anyway keeps the worker
    branch-free."""
    final_path = Path(file_item.download_path)
    temp_path = temp_path_for_download_item(file_item)
    final_path_matches = checksum_matches(final_path, file_item.checksum)
    temp_is_file = temp_path.is_file()
    temp_checksum = get_file_sha1(temp_path) if temp_is_file else None
    return final_path_matches, temp_is_file, temp_checksum


def precompute_all_verify_hashes(dl_file_items):
    """Hash results for every download item, a list aligned 1:1 with dl_file_items
    whether the hashing ran on the thread pool or serially."""
    workers = resolve_verify_workers(len(dl_file_items))
    if workers <= 1:
        return [precompute_verify_hashes(fi) for fi in dl_file_items]
    try:
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="instl-verify") as pool:
            # executor.map preserves input order, so results stay aligned
            return list(pool.map(precompute_verify_hashes, dl_file_items))
    except Exception as ex:  # pragma: no cover - parallelism must never break sync
        log.warning(f"parallel verify pool failed ({ex}); falling back to serial hashing")
        return [precompute_verify_hashes(fi) for fi in dl_file_items]


# -- the budget-bounded redownload pass ---------------------------


class RedownloadBudget:
    """Bounds the redownload pass by total bytes and/or wall seconds
    (DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES / DOWNLOAD_REDOWNLOAD_MAX_SECONDS); 0 means
    unlimited. The seconds budget measures ACTIVE time: paused time is passed in by
    the caller and subtracted, so an outage hold does not burn the budget."""

    def __init__(self, max_total_bytes: int, max_seconds: int) -> None:
        self.max_total_bytes = max(int(max_total_bytes), 0)
        self.max_seconds = max(int(max_seconds), 0)
        self.bytes_spent = 0
        self.started_at = time.monotonic()

    @classmethod
    def from_config(cls) -> "RedownloadBudget":
        # both default to 0 (unlimited) - a non-zero default would abandon slow-network
        # recoveries that do succeed (16 large wtars at ~5 min each is over an hour)
        return cls(
            max_total_bytes=config_var_int("DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES", 0),
            max_seconds=config_var_int("DOWNLOAD_REDOWNLOAD_MAX_SECONDS", 0),
        )

    def spend_bytes(self, num_bytes: int) -> None:
        self.bytes_spent += max(int(num_bytes or 0), 0)

    def active_seconds(self, paused_seconds: float = 0.0) -> float:
        return (time.monotonic() - self.started_at) - paused_seconds

    def exhausted_reason(self, paused_seconds: float = 0.0):
        """Short reason when a budget dimension is spent, None while budget is left.
        Checked between files - a file in flight is never abandoned mid-transfer."""
        if self.max_total_bytes and self.bytes_spent >= self.max_total_bytes:
            return f"max total bytes {self.max_total_bytes} reached"
        if self.max_seconds and self.active_seconds(paused_seconds) >= self.max_seconds:
            return f"max seconds {self.max_seconds} reached"
        return None


class PauseTrackingChannel:
    """Delegating wrapper around the download control channel that measures time spent
    blocked in wait_if_paused, so RedownloadBudget can exclude pause time from its
    seconds budget. All other channel calls pass through."""

    def __init__(self, channel) -> None:
        self._channel = channel
        self.paused_seconds = 0.0

    def wait_if_paused(self, poll_seconds: float = 0.5) -> None:
        before = time.monotonic()
        self._channel.wait_if_paused(poll_seconds)
        self.paused_seconds += time.monotonic() - before

    def __getattr__(self, name):
        return getattr(self._channel, name)


def redownload_bad_files(dler, info_map_table, files_to_redownload, report_progress) -> int:
    """Redownload the bad files through ``dler``, returning how many were recovered so
    the caller can subtract that from its bad-file count. Each file gets its own bounded
    retry-with-backoff loop and is never split across iterations, so blocking between
    attempts keeps the atomicity invariant: no temp .part is promoted while paused. A
    terminal failure on one file does not abort the pass."""
    control_channel = get_global_channel()
    retry_enabled = config_var_bool("DOWNLOAD_RETRY_POLICY_ENABLED", True)
    budget = None
    if count_all_bad_files():
        budget = RedownloadBudget.from_config()
        control_channel = PauseTrackingChannel(control_channel)
    files_to_redownload = list(files_to_redownload)
    num_recovered = 0
    for file_index, file_item in enumerate(files_to_redownload):
        if budget is not None:
            exhausted_reason = budget.exhausted_reason(control_channel.paused_seconds)
            if exhausted_reason:
                files_left = len(files_to_redownload) - file_index
                budget_msg = (f"redownload budget exhausted ({exhausted_reason}) after "
                              f"{budget.bytes_spent} bytes / {budget.active_seconds(control_channel.paused_seconds):.1f}s; "
                              f"leaving {files_left} of {len(files_to_redownload)} bad files unrecovered")
                log.warning(budget_msg)
                report_progress(increment_by=0, prog_msg=budget_msg)
                break
        try:
            redownload_one_file(dler, file_item, info_map_table, control_channel,
                                retry_enabled, report_progress,
                                position=(file_index + 1, len(files_to_redownload)))
            num_recovered += 1
            if budget is not None:
                budget.spend_bytes(getattr(file_item, "size", 0) or 0)
        except Exception as ex:
            # terminal for this file: retries exhausted or non-retryable
            download_path = getattr(file_item, "download_path", "unknown")
            log.error(f"""giving up redownloading {download_path}, {ex}""")
            report_progress(increment_by=0,
                            prog_msg=f"""failed to redownload {download_path}, {ex}""")
    return num_recovered


def redownload_one_file(dler, file_item, info_map_table, control_channel, retry_enabled,
                        report_progress, position=None):
    """Download a single bad file, retrying with control-channel-aware backoff; raises
    when terminally unrecoverable, so returning means recovered. wait_if_paused holds at
    the top of each attempt WITHOUT consuming a retry, so a network outage waits instead
    of burning the retry budget; sleep_backoff lets a try_now cut the wait short."""
    attempt = 0
    while True:
        control_channel.wait_if_paused()

        download_url = info_map_table.get_sync_url_for_file_item(file_item)
        download_path = file_item.download_path
        temp_path = temp_path_for_download_item(file_item)
        remove_stale_temp_for_download_item(file_item)
        try:
            dler(path=download_path, url=download_url, checksum=file_item.checksum, temp_path=temp_path)
        except Exception as ex:
            decision = emit_retry_decision(
                info_map_table,
                file_item,
                classify_exception(ex),
                received_bytes=0,
                resume_eligible=False,
                previous_retry_count_override=attempt,
            ) if retry_enabled else None

            if decision is None or not decision.will_retry:
                raise

            attempt += 1
            log.info(f"""retry {attempt} for {download_path} after {decision.failure_class.value}, waiting {decision.delay_seconds:.1f}s""")
            # try_now wakes this early; pause is re-checked on the next iteration
            sleep_backoff(decision.delay_seconds, channel=control_channel)
            continue

        redownloaded_bytes = Path(download_path).stat().st_size
        save_resume_sidecar(
            info_map_table,
            file_item,
            DownloadFileState.VERIFIED,
            received_bytes=redownloaded_bytes,
        )
        try:
            _observability_record_outcome(
                outcome=DownloadOutcome.SUCCESS,
                url=download_url,
                bytes_received=redownloaded_bytes,
            )
        except Exception as obs_ex:  # pragma: no cover
            log.debug(f"observability record_outcome failed: {obs_ex}")
        # increment_by=0: recovery was never in the progress plan, so counting it
        # would overshoot the total. The position goes in the text instead, or a
        # long pass shows one frozen "Progress N of M" throughout.
        if position is not None:
            prog_msg = f"redownloaded {position[0]} of {position[1]}: {file_item.download_path}"
        else:
            prog_msg = f"redownloaded {file_item.download_path}"
        report_progress(increment_by=0, prog_msg=prog_msg)
        return


# -- download phase session_state events --------------------------


def _download_event_context():
    """Session id + rollout flags for a download event, applying the telemetry kill
    switch. Each instl invocation is its own process, so a later `copy` must re-read the
    flag that the `sync` before it honored."""
    rollout_flags = _events_active_flags_from_config(config_vars)
    telemetry_enabled = bool(rollout_flags.get("DOWNLOAD_TELEMETRY_ENABLED", True))
    _events_set_telemetry_enabled(telemetry_enabled)
    return config_var_str("__INVOCATION_RANDOM_ID__", "unknown"), rollout_flags, telemetry_enabled


def emit_download_started(files_planned, bytes_planned):
    """Emit the capability + ``downloading`` session_state at the start of the curl
    download phase. Must run inside ``run-process`` - that is what Central watches."""
    try:
        session_id, rollout_flags, telemetry_enabled = _download_event_context()
        concurrency_planned = config_var_int("PARALLEL_SYNC", 0) or None
        try:
            validated_hosts = resolve_validated_hosts(
                config_var_list("DOWNLOAD_RESUME_VALIDATED_HOSTS"),
                config_var_str("BASE_LINKS_URL"),
            )
        except Exception:
            validated_hosts = []
        _events_emit_capability(
            session_id=session_id,
            resume_enabled=config_var_bool("DOWNLOAD_RESUME_ENABLED", False),
            validated_hosts=validated_hosts,
            feature_flags=rollout_flags,
            central_ux_enabled=bool(rollout_flags.get("DOWNLOAD_CENTRAL_UX_ENABLED", False)),
            telemetry_enabled=telemetry_enabled,
            retry_policy_enabled=bool(rollout_flags.get("DOWNLOAD_RETRY_POLICY_ENABLED", True)),
        )
        _events_emit_session_state(
            session_id=session_id,
            state="downloading",
            files_planned=files_planned,
            bytes_planned=bytes_planned,
            concurrency_planned=concurrency_planned,
            reason="download_started",
        )
    except Exception as ex:  # pragma: no cover - instrumentation must never break sync
        log.debug(f"could not emit download started events: {ex}")


def emit_download_state(state, reason=None, files_planned=None, bytes_planned=None):
    """Emit a post-download ``session_state`` transition, so Central knows which phase is
    running once curl is done - checksum verify, then copy/unwtar, can take minutes."""
    try:
        session_id, _rollout_flags, _telemetry_enabled = _download_event_context()
        _events_emit_session_state(
            session_id=session_id,
            state=state,
            files_planned=files_planned,
            bytes_planned=bytes_planned,
            reason=reason,
        )
    except Exception as ex:  # pragma: no cover - instrumentation must never break sync
        log.debug(f"could not emit download state {state!r}: {ex}")
