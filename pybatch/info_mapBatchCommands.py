from typing import List
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import logging

log = logging.getLogger(__name__)

from configVar import config_vars
from configVar import config_var_str, config_var_bool, config_var_int, config_var_list

import aYaml
import utils

from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDir
from .fileSystemBatchCommands import Chmod
from .wtarBatchCommands import Wzip
from .copyBatchCommands import CopyFileToFile
from .downloadBatchCommands import DownloadFileAndCheckChecksum, DownloadManager

from db import DBManager

from pyinstl.downloadState import (
    DownloadFileState,
    checksum_matches,
    file_id_for_download_item,
    get_file_sha1,
    load_resume_sidecar_for_download_item,
    promote_verified_temp_file,
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
)
from pyinstl.downloadCohort import (
    active_flags_from_config as _cohort_active_flags_from_config,
    resolve_cohort_from_config as _cohort_resolve_cohort_from_config,
)

"""
    batch commands that need access to the db and the info_map table
"""


def _source_url_for_file_item(info_map_table, file_item):
    try:
        return info_map_table.get_sync_url_for_file_item(file_item)
    except Exception:
        return getattr(file_item, "url", None)


def _source_metadata_from_record(record):
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
        return _source_metadata_from_record(record)
    return {}


def _resume_decision_for_file_item(info_map_table, file_item):
    bookkeeping_dir = config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
    return resume_decision_for_download_item(
        file_item,
        _source_url_for_file_item(info_map_table, file_item),
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


def _build_failure_info(failure_class, *, http_status=None, curl_exit_code=None, retry_after_seconds=None, reason=""):
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


def _emit_retry_decision(info_map_table, file_item, failure, *, received_bytes=None, resume_eligible=False, concurrency=None, previous_retry_count_override=None):
    """Compute a retry decision for file_item, persist it on the sidecar, log it, and
    return it so callers can drive the retry. None when DOWNLOAD_RETRY_POLICY_ENABLED
    is off. The redownload loop must pass previous_retry_count_override: the persisted
    count lives on the resume sidecar, which is not written when resume bookkeeping is
    disabled (the default), so reading it would always give 0 and the matrix would
    never reach its terminal attempt.
    """
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

    _save_resume_sidecar(
        info_map_table,
        file_item,
        transfer_state,
        received_bytes=received_bytes,
        last_failure_class=failure.failure_class.value,
        retry_count=next_retry_count,
    )

    try:
        source_url = _source_url_for_file_item(info_map_table, file_item)
        _observability_record_retry_decision(
            decision,
            url=source_url,
            bytes_received=received_bytes,
        )
    except Exception as obs_ex:  # pragma: no cover - instrumentation must never break sync
        log.debug(f"observability record_retry_decision failed: {obs_ex}")

    return decision


def _resume_bookkeeping_enabled():
    """Whether per-file resume sidecars should be written this run. Each is a JSON file
    written with fsync + atomic replace, so one per file in a large sync (tens of
    thousands) costs minutes of disk-flush latency, and they are only ever read back to
    drive a byte-range resume. Telemetry events are on a separate channel, not gated
    by this."""
    return config_var_bool("DOWNLOAD_RESUME_ENABLED", False)


def _save_resume_sidecar(info_map_table, file_item, transfer_state, received_bytes=None, last_failure_class=None, source_metadata=None, retry_count=0):
    if not _resume_bookkeeping_enabled():
        return None
    bookkeeping_dir = config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
    if not bookkeeping_dir:
        return None
    source_url = _source_url_for_file_item(info_map_table, file_item)
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


def _emit_throttled_progress(cmd, prog_msg, increment_by, index, total, throttle_attr):
    """Advance the progress counter every item, but throttle the log line to ~4x/sec
    (first and last item always logged). In the high fan-out loops the per-item
    "Progress N of M" line, not the real work, was the dominant cost of the phase; the
    counter still advances per item so Central's running total stays exact."""
    if not (cmd.report_own_progress and not PythonBatchCommandBase.ignore_progress):
        return
    if increment_by:
        cmd.increment_progress(increment_by)
    import time as _time
    now = _time.monotonic()
    last = getattr(cmd, throttle_attr, None)
    if last is None or index >= total - 1 or (now - last) >= 0.25:
        setattr(cmd, throttle_attr, now)
        log.info(f"{cmd.progress_msg()} {prog_msg}")


class _RedownloadBudget:
    """Bounds the redownload pass by total bytes and/or wall seconds
    (DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES / DOWNLOAD_REDOWNLOAD_MAX_SECONDS).
    A budget dimension of 0 means unlimited. The seconds budget measures ACTIVE time:
    paused time (Central pause / offline auto-pause) is passed in by the caller and
    subtracted, so an outage hold does not burn the recovery budget."""

    def __init__(self, max_total_bytes: int, max_seconds: int) -> None:
        self.max_total_bytes = max(int(max_total_bytes), 0)
        self.max_seconds = max(int(max_seconds), 0)
        self.bytes_spent = 0
        self.started_at = time.monotonic()

    @classmethod
    def from_config(cls) -> "_RedownloadBudget":
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


class _PauseTrackingChannel:
    """Delegating wrapper around the download control channel that measures time spent
    blocked in wait_if_paused, so _RedownloadBudget can exclude pause time from its
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


class CheckDownloadFolderChecksum(DBManager, PythonBatchCommandBase):
    """ check checksums in download folder, against expected checksums in info_map file
    """

    def __init__(self, print_report=True, raise_on_bad_checksum=True, max_bad_files_to_redownload=None,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.print_report = print_report
        self.raise_on_bad_checksum = raise_on_bad_checksum
        if not self.raise_on_bad_checksum:
            self.exceptions_to_ignore.append(ValueError)
        self.lists_of_files = defaultdict(list)
        self.bad_checksum_list_exception_message = ""
        self.missing_files_exception_message = ""
        self.retried_files_exception_message = ""
        self.num_bad_files = 0
        # old generated batch scripts pass this as a hard cap; None/0 still means
        # "verify only, no redownload pass" (instl check-checksum), but a positive value
        # is only a warn threshold - recovery always runs, bounded by budget
        self.max_bad_files_to_redownload = max_bad_files_to_redownload
        self._bad_files_threshold_warned = False
        self.report_lines = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.optional_named__init__param("print_report", self.print_report, False))
        all_args.append(self.optional_named__init__param("raise_on_bad_checksum", self.raise_on_bad_checksum, False))
        all_args.append(
            self.optional_named__init__param("max_bad_files_to_redownload", self.max_bad_files_to_redownload))

    def progress_msg_self(self) -> str:
        return f'''Check download folder checksum'''

    def increment_and_output_progress(self, increment_by=None, prog_counter_msg=None, prog_msg=None):
        """ override PythonBatchCommandBase.increment_and_output_progress so progress can be reported for each file
        """
        pass

    def break_file_callback(self, msg):
        super().increment_and_output_progress(increment_by=0, prog_msg=msg)

    def _emit_verify_progress(self, done_bytes, planned_bytes, force=False):
        """``verifying_downloads`` session_state tick with per-phase byte progress,
        throttled to 1/sec so it never slows the verify loop."""
        try:
            import time as _time
            now = _time.monotonic()
            last = getattr(self, "_verify_last_emit", None)
            if not force and last is not None and (now - last) < 1.0:
                return
            self._verify_last_emit = now
            _events_emit_session_state(
                session_id=config_var_str("__INVOCATION_RANDOM_ID__", "unknown"),
                state="verifying_downloads",
                phase_bytes_done=int(done_bytes),
                phase_bytes_planned=int(planned_bytes),
                reason="verify_progress",
            )
        except Exception as ex:  # pragma: no cover - instrumentation must never break sync
            log.debug(f"could not emit verify progress tick: {ex}")

    def _count_all_bad_files(self) -> bool:
        """True when the verify loop counts ALL bad/missing files and the redownload pass
        is budget-bounded. Off (kill switch) restores the legacy count cliff exactly."""
        return config_var_bool("DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES", True)

    def _redownload_pass_enabled(self) -> bool:
        """max_bad_files_to_redownload None/0 means "verify only" - the in-process
        check-checksum command and old scripts rely on that."""
        return bool(self.max_bad_files_to_redownload)

    def _bad_file_progress(self, prog_msg, file_index, total_items):
        """Bad/missing-file lines are logged unconditionally up to the warn threshold and
        throttled beyond it - a mass failure (connectivity lost mid-download leaves
        thousands of files with no .part) would flood the log. Bookkeeping and the
        retry_decision events are never throttled."""
        threshold = self.max_bad_files_to_redownload
        if (threshold is None
                or not self._count_all_bad_files()
                or self.num_bad_files <= max(int(threshold), 1)):
            super().increment_and_output_progress(increment_by=0, prog_msg=prog_msg)
        else:
            self._verify_progress_log(prog_msg, 0, file_index, total_items)

    def _verify_progress_log(self, prog_msg, increment_by, file_index, total_items):
        """Throttled per-file progress for the verify loop, see _emit_throttled_progress."""
        _emit_throttled_progress(self, prog_msg, increment_by, file_index, total_items,
                                 "_verify_last_progress_log")

    def _resolve_verify_workers(self, num_items: int) -> int:
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

    @staticmethod
    def _precompute_verify_hashes(file_item):
        """Read-only, independent per-file hashing, runs in a worker thread - hashlib
        releases the GIL during update(), so this gives real speedup. Touches NO
        process-global state (config_vars, progress/stage stack), only the filesystem and
        the passed-in file_item, both read-only. Returns (final_path_matches,
        temp_is_file, temp_checksum); the temp sha1 is unused unless the final path
        failed to match, but hashing it anyway keeps the worker branch-free."""
        final_path = Path(file_item.download_path)
        temp_path = temp_path_for_download_item(file_item)
        final_path_matches = checksum_matches(final_path, file_item.checksum)
        temp_is_file = temp_path.is_file()
        temp_checksum = get_file_sha1(temp_path) if temp_is_file else None
        return final_path_matches, temp_is_file, temp_checksum

    def _precompute_all_verify_hashes(self, dl_file_items):
        """Hash results for every download item, a list aligned 1:1 with dl_file_items
        whether the hashing ran on the thread pool or serially."""
        workers = self._resolve_verify_workers(len(dl_file_items))
        if workers <= 1:
            return [self._precompute_verify_hashes(fi) for fi in dl_file_items]
        try:
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix="instl-verify") as pool:
                # executor.map preserves input order, so results stay aligned
                return list(pool.map(self._precompute_verify_hashes, dl_file_items))
        except Exception as ex:  # pragma: no cover - parallelism must never break sync
            log.warning(f"parallel verify pool failed ({ex}); falling back to serial hashing")
            return [self._precompute_verify_hashes(fi) for fi in dl_file_items]

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)  # read the info map file from TO_SYNC_INFO_MAP_PATH - if provided
        dl_file_items = self.info_map_table.get_download_items(what="file")

        # total bytes this pass will process, so the ticks carry a determinate fraction
        verify_planned_bytes = sum(
            int(fi.size) for fi in dl_file_items if getattr(fi, "size", None) and fi.size > 0)
        verify_done_bytes = 0

        utils.wait_for_break_file_to_be_removed(
            config_vars['LOCAL_SYNC_DIR'].Path(resolve=True).joinpath("BREAK_BEFORE_CHECKSUM"),
            self.break_file_callback)

        # hashing is the only work that runs off the main thread; ALL bookkeeping below
        # runs on the main thread in the original order using these results
        precomputed = self._precompute_all_verify_hashes(dl_file_items)
        total_items = len(dl_file_items)

        for file_index, file_item in enumerate(dl_file_items):
            self.doing = f"""check checksum for '{file_item.download_path}'"""
            self._verify_progress_log(self.doing, 1, file_index, total_items)
            if getattr(file_item, "size", None) and file_item.size > 0:
                verify_done_bytes += int(file_item.size)
            self._emit_verify_progress(verify_done_bytes, verify_planned_bytes)

            final_path = Path(file_item.download_path)
            temp_path = temp_path_for_download_item(file_item)
            final_path_matches, temp_is_file, file_checksum = precomputed[file_index]
            # the verify loop deliberately writes NO resume sidecar: nothing reads a
            # verify-time transfer_state, and the ~2 atomic writes per file dominated the
            # pass (~340s of a ~344s loop over 24k files). Recovery after an interrupted
            # verify comes from mark_need_download's on-disk checksum check

            if final_path_matches:
                # already valid: no bytes transferred this session, so recording an
                # outcome here would make warm-cache runs look fast
                remove_stale_temp_for_download_item(file_item)
                continue

            if temp_is_file:
                if not utils.compare_checksums(file_checksum, file_item.checksum):
                    self.num_bad_files += 1
                    self._bad_file_progress(
                        f"bad checksum for temp download '{temp_path}'\nexpected: {file_item.checksum}, found: {file_checksum}",
                        file_index, total_items)
                    self.lists_of_files["bad_checksum"].append(" ".join(("Bad checksum:", os.fspath(temp_path),
                                                                         "expected", file_item.checksum, "found",
                                                                         file_checksum)))
                    self.lists_of_files["to redownload"].append(file_item)
                    _emit_retry_decision(
                        self.info_map_table,
                        file_item,
                        _build_failure_info(DownloadFailureClass.CHECKSUM_MISMATCH),
                        received_bytes=temp_path.stat().st_size,
                        resume_eligible=False,  # restart_required by class
                    )
                else:
                    promote_verified_temp_file(temp_path, final_path, file_item.checksum, actual_checksum=file_checksum)
                    promoted_bytes = final_path.stat().st_size
                    try:
                        _observability_record_outcome(
                            outcome=DownloadOutcome.SUCCESS,
                            url=_source_url_for_file_item(self.info_map_table, file_item),
                            bytes_received=promoted_bytes,
                        )
                    except Exception as obs_ex:  # pragma: no cover
                        log.debug(f"observability record_outcome failed: {obs_ex}")
                    self._verify_progress_log(f"promoted verified download '{final_path}'", 0, file_index, total_items)
            else:
                self.num_bad_files += 1
                self._bad_file_progress(
                    f"missing temp download '{temp_path}' for '{file_item.download_path}'",
                    file_index, total_items)
                self.lists_of_files["missing_files"].append(" ".join((os.fspath(temp_path), "was not found")))
                self.lists_of_files["to redownload"].append(file_item)
                _emit_retry_decision(
                    self.info_map_table,
                    file_item,
                    _build_failure_info(DownloadFailureClass.MISSING_AFTER_TRANSFER),
                    received_bytes=0,
                    resume_eligible=False,  # restart_required by class
                )
            if self.max_bad_files_to_redownload is not None and self.num_bad_files > self.max_bad_files_to_redownload:
                if self._count_all_bad_files():
                    # keep counting so every bad file gets a recovery chance, warn once
                    if not self._bad_files_threshold_warned:
                        self._bad_files_threshold_warned = True
                        threshold_msg = (f"more than {self.max_bad_files_to_redownload} bad or missing files found; "
                                         f"continuing to count them all, redownload will be budget-bounded")
                        log.warning(threshold_msg)
                        super().increment_and_output_progress(increment_by=0, prog_msg=threshold_msg)
                else:
                    super().increment_and_output_progress(increment_by=0,
                                                          prog_msg=f"stopping checksum check too many bad or missing files found")
                    break

        # force past the throttle so the phase bar reaches its full planned bytes
        self._emit_verify_progress(verify_done_bytes, verify_planned_bytes, force=True)

        if not self.is_checksum_ok():
            if self._count_all_bad_files():
                # recovery is attempted however many files are bad, the budget bounds it
                attempt_recovery = self._redownload_pass_enabled()
            else:
                # legacy count-cliff behavior (kill switch off)
                attempt_recovery = (self.max_bad_files_to_redownload is not None
                                    and self.num_bad_files <= self.max_bad_files_to_redownload)
            if attempt_recovery:
                utils.wait_for_break_file_to_be_removed(
                    config_vars['LOCAL_SYNC_DIR'].Path(resolve=True).joinpath("BREAK_BEFORE_REDOWNLOAD"),
                    self.break_file_callback)
                self.re_download_bad_files()

        # Central's error parser regexes on /Bad checksum/i, so do not change the format
        if not self.is_checksum_ok():  # some files still not OK after re_download_bad_files
            if self.raise_on_bad_checksum:
                exception_message = "\n".join(
                    (f'Bad checksum for {len(self.lists_of_files["bad_checksum"])} files',
                     f'Missing {len(self.lists_of_files["missing_files"])} files'))
                raise ValueError(exception_message)

    def re_download_bad_files(self):
        # each bad file gets its own bounded retry-with-backoff loop. A file is never
        # split across iterations, so blocking between attempts keeps the atomicity
        # invariant: no temp .part is promoted while paused. A terminal failure on one
        # file does not abort the pass; files left unrecovered stay counted as bad, so
        # the caller still raises 'Bad checksum ...' afterwards
        control_channel = get_global_channel()
        retry_enabled = config_var_bool("DOWNLOAD_RETRY_POLICY_ENABLED", True)
        budget = None
        if self._count_all_bad_files():
            budget = _RedownloadBudget.from_config()
            control_channel = _PauseTrackingChannel(control_channel)
        files_to_redownload = list(self.lists_of_files["to redownload"])
        with DownloadManager(cookie=config_vars["COOKIE_JAR"].str(),
                             report_own_progress=False) as dler:  # should get the cookie from the config vars
            for file_index, file_item in enumerate(files_to_redownload):
                if budget is not None:
                    exhausted_reason = budget.exhausted_reason(control_channel.paused_seconds)
                    if exhausted_reason:
                        files_left = len(files_to_redownload) - file_index
                        budget_msg = (f"redownload budget exhausted ({exhausted_reason}) after "
                                      f"{budget.bytes_spent} bytes / {budget.active_seconds(control_channel.paused_seconds):.1f}s; "
                                      f"leaving {files_left} of {len(files_to_redownload)} bad files unrecovered")
                        log.warning(budget_msg)
                        super().increment_and_output_progress(increment_by=0, prog_msg=budget_msg)
                        break
                try:
                    self._redownload_one_file(dler, file_item, control_channel, retry_enabled)
                    if budget is not None:
                        budget.spend_bytes(getattr(file_item, "size", 0) or 0)
                except Exception as ex:
                    # terminal for this file: retries exhausted or non-retryable
                    download_path = getattr(file_item, "download_path", "unknown")
                    log.error(f"""giving up redownloading {download_path}, {ex}""")
                    super().increment_and_output_progress(
                        increment_by=0,
                        prog_msg=f"""failed to redownload {download_path}, {ex}""")

    def _redownload_one_file(self, dler, file_item, control_channel, retry_enabled):
        """Download a single bad file, retrying with control-channel-aware backoff, and
        raise when it is terminally unrecoverable. wait_if_paused holds at the top of
        each attempt WITHOUT consuming a retry, so a network outage (Central pauses the
        engine on offline) waits instead of burning the retry budget. The backoff goes
        through sleep_backoff, so a try_now from Central short-circuits the wait."""
        attempt = 0
        while True:
            control_channel.wait_if_paused()

            download_url = self.info_map_table.get_sync_url_for_file_item(file_item)
            download_path = file_item.download_path
            temp_path = temp_path_for_download_item(file_item)
            remove_stale_temp_for_download_item(file_item)
            try:
                dler(path=download_path, url=download_url, checksum=file_item.checksum, temp_path=temp_path)
            except Exception as ex:
                decision = _emit_retry_decision(
                    self.info_map_table,
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
            _save_resume_sidecar(
                self.info_map_table,
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
            super().increment_and_output_progress(increment_by=0,
                                                  prog_msg=f"redownloaded {file_item.download_path}")
            self.num_bad_files -= 1
            return

    def is_checksum_ok(self) -> bool:
        retVal = self.num_bad_files == 0
        return retVal


class PrepareDownloadTempFiles(DBManager, PythonBatchCommandBase):
    """Discard stale partial artifacts before starting a restart-from-zero transfer."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def progress_msg_self(self) -> str:
        return f'''Prepare download temp files'''

    def increment_and_output_progress(self, increment_by=None, prog_counter_msg=None, prog_msg=None):
        pass

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)
        for file_item in self.info_map_table.get_download_items(what="file"):
            temp_path = temp_path_for_download_item(file_item)
            resume_decision = _resume_decision_for_file_item(self.info_map_table, file_item)
            if resume_decision.can_resume:
                _save_resume_sidecar(
                    self.info_map_table,
                    file_item,
                    DownloadFileState.QUEUED,
                    received_bytes=resume_decision.resume_from_byte,
                    source_metadata=_source_metadata_from_record(resume_decision.record),
                )
                continue
            transfer_state = DownloadFileState.INTERRUPTED if temp_path.is_file() else DownloadFileState.QUEUED
            _save_resume_sidecar(self.info_map_table, file_item, transfer_state)
            self.doing = f"""remove stale temp download '{temp_path}'"""
            if remove_stale_temp_for_download_item(file_item):
                super().increment_and_output_progress(increment_by=1, prog_msg=self.doing)


def _download_event_context():
    """Session id + rollout flags for a download event, applying the telemetry kill
    switch. Each instl invocation is its own process, so a later `copy` must re-read the
    flag that the `sync` before it honored."""
    rollout_flags = _cohort_active_flags_from_config(config_vars)
    telemetry_enabled = bool(rollout_flags.get("DOWNLOAD_TELEMETRY_ENABLED", True))
    _events_set_telemetry_enabled(telemetry_enabled)
    return config_var_str("__INVOCATION_RANDOM_ID__", "unknown"), rollout_flags, telemetry_enabled


def _emit_download_started(files_planned, bytes_planned):
    """Emit the capability + ``downloading`` session_state at the start of the curl
    download phase. Must run from a batch command inside ``run-process`` - that is the
    output Central watches."""
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
            adaptive_concurrency_enabled=config_var_bool("DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED", False),
            validated_hosts=validated_hosts,
            cohort=_cohort_resolve_cohort_from_config(config_vars),
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


class ReportDownloadStarted(PythonBatchCommandBase, essential=False, call__call__=True, is_context_manager=False, kwargs_defaults={'own_progress_count': 0, 'report_own_progress': False}):
    """Emit capability + ``downloading`` session_state at the start of the curl download
    phase, with the planned file / byte counts so Central can show the totals."""

    def __init__(self, files_planned=0, bytes_planned=0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.files_planned = files_planned
        self.bytes_planned = bytes_planned

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.optional_named__init__param("files_planned", self.files_planned, 0))
        all_args.append(self.optional_named__init__param("bytes_planned", self.bytes_planned, 0))

    def progress_msg_self(self) -> str:
        return f'''Report download started'''

    def __call__(self, *args, **kwargs) -> None:
        _emit_download_started(self.files_planned, self.bytes_planned)


def _emit_download_state(state, reason=None, files_planned=None, bytes_planned=None):
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


class ReportDownloadState(PythonBatchCommandBase, essential=False, call__call__=True, is_context_manager=False, kwargs_defaults={'own_progress_count': 0, 'report_own_progress': False}):
    """Emit a post-download ``session_state`` transition (Verifying / Installing). Only
    moves the state machine: ``own_progress_count=0`` / ``report_own_progress=False``
    so it never perturbs the progress total."""

    def __init__(self, state, reason=None, phase_bytes_planned=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.state = state
        self.reason = reason
        # arms the copy-phase byte accumulator; may be assigned after construction, but
        # must be set before the script is serialized
        self.phase_bytes_planned = phase_bytes_planned

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.state))
        all_args.append(self.optional_named__init__param("reason", self.reason, None))
        all_args.append(self.optional_named__init__param("phase_bytes_planned", self.phase_bytes_planned, None))

    def progress_msg_self(self) -> str:
        return f'''Report download state {self.state}'''

    def __call__(self, *args, **kwargs) -> None:
        _emit_download_state(self.state, reason=self.reason)
        if self.state == "copying" and self.phase_bytes_planned is not None:
            try:
                from pybatch.copyPhaseProgress import begin_copy_phase
                begin_copy_phase(self.phase_bytes_planned,
                                 config_var_str("__INVOCATION_RANDOM_ID__", "unknown"))
            except Exception as ex:  # pragma: no cover - instrumentation must never break copy
                log.debug(f"could not begin copy phase: {ex}")


class SetExecPermissionsInSyncFolder(DBManager, PythonBatchCommandBase):
    """ set execute permissions for files that need such permission  in the download folder
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def progress_msg_self(self) -> str:
        return f'''Set exec permissions in download folder'''

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)  # read the info map file from REQUIRED_INFO_MAP_PATH - if provided
        exec_file_paths = self.info_map_table.get_exec_file_paths()
        for file_item_path in exec_file_paths:
            if os.path.isfile(file_item_path):
                Chmod(file_item_path, "a+x", own_progress_count=0)()


class CreateSyncFolders(DBManager, PythonBatchCommandBase):
    """ create the download folder hierarchy
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if "own_progress_count" not in kwargs:
            self.own_progress_count = self.info_map_table.num_items(item_filter="need-download-dirs")

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def progress_msg_self(self) -> str:
        return f'''Create download directories'''

    def increment_and_output_progress(self, increment_by=None, prog_counter_msg=None, prog_msg=None):
        """ override PythonBatchCommandBase.increment_and_output_progress so progress can be reported for each file
        """
        pass

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)
        dl_dir_items = self.info_map_table.get_download_items(what="dir")
        total_dirs = len(dl_dir_items)
        for dir_index, dl_dir in enumerate(dl_dir_items):
            # direct_sync items have absolute path in member dl_dir.download_path
            # cached items have relative path in member dl_dir.path
            path_to_create = dl_dir.download_path if dl_dir.download_path else dl_dir.path
            # creating the sync-cache tree means thousands of MakeDir calls, and a log
            # line for each was a large chunk of the pre-download time
            _emit_throttled_progress(self, f"create sync folder {path_to_create}", 1,
                                     dir_index, total_dirs, "_sync_folder_last_log")
            self.doing = f"""creating sync folder '{path_to_create}'"""
            with MakeDir(path_to_create, report_own_progress=False) as dir_maker:
                dir_maker()


class SetBaseRevision(DBManager, PythonBatchCommandBase):
    """ Updates revisions in info_map database table svn_item_t.
        revisions that are smaller than base_rev are changed to base_rev
        Admin pybatch class, used in deployment, not during installation
    """
    def __init__(self, base_rev, **kwargs):
        super().__init__(**kwargs)
        self.base_rev = base_rev

    def repr_own_args(self, all_args: List[str]):
        all_args.append(self.unnamed__init__param(self.base_rev))

    def progress_msg_self(self):
        return f"Set base-repo-rev to repo-rev#{self.base_rev}"

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)
        self.info_map_table.set_base_revision(self.base_rev)


class InfoMapFullWriter(DBManager, PythonBatchCommandBase):
    """ write all info map table lines to a single file
        Admin pybatch class, used in deployment, not during installation
    """
    fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')

    def __init__(self, out_file, in_format='text', **kwargs):
        super().__init__(**kwargs)
        self.out_file = Path(out_file)
        self.format = in_format

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.out_file))
        all_args.append(self.optional_named__init__param("in_format", self.format, 'text'))

    def progress_msg_self(self) -> str:
        return f'''Create full info_map file'''

    def __call__(self, *args, **kwargs) -> None:
        self.info_map_table.write_to_file(self.out_file, field_to_write=InfoMapFullWriter.fields_relevant_to_info_map)


class InfoMapSplitWriter(DBManager, PythonBatchCommandBase):
    """ write all info map table to files according to info_map: field in index.yaml
        Admin pybatch class, used in deployment, not during installation
    """
    fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')

    def __init__(self, work_folder, in_format='text', **kwargs):
        super().__init__(**kwargs)
        self.work_folder = Path(work_folder)
        self.format = in_format

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.work_folder))
        all_args.append(self.optional_named__init__param("in_format", self.format, 'text'))

    def progress_msg_self(self) -> str:
        return f'''Create split info_map files'''

    def __call__(self, *args, **kwargs) -> None:
        # fill the iid_to_svn_item_t table
        self.info_map_table.populate_IIDToSVNItem()

        # get the list of info map file names
        info_map_to_item = dict()
        all_info_map_names = self.items_table.get_unique_detail_values('info_map')
        for infomap_file_name in all_info_map_names:
            info_map_file_path = self.work_folder.joinpath(infomap_file_name)
            if info_map_file_path.is_file():
                log.info(f"{infomap_file_name} was found so no need to create it")
                # file already exists, probably copied from the "Common" repository
                # just checking that the fie is also zipped
                zip_infomap_file_name = config_vars.resolve_str(infomap_file_name + "$(WZLIB_EXTENSION)")
                zip_info_map_file_path = self.work_folder.joinpath(zip_infomap_file_name)
                if not zip_info_map_file_path.is_file():
                    raise FileNotFoundError(f"found {info_map_file_path} but not {zip_info_map_file_path}")
            else:
                self.info_map_table.mark_items_required_by_infomap(infomap_file_name)
                info_map_items = self.info_map_table.get_required_items()
                info_map_to_item[infomap_file_name] = info_map_items

        files_to_add_to_default_info_map = list()  # the named info_map files and their wzip version should be added to the default info_map
        # write each info map to file
        for infomap_file_name, info_map_items in info_map_to_item.items():
            if info_map_items:  # could be that no items are linked to the info map file
                info_map_file_path = self.work_folder.joinpath(infomap_file_name)
                self.info_map_table.write_to_file(in_file=info_map_file_path, items_list=info_map_items,
                                                  field_to_write=self.fields_relevant_to_info_map)
                files_to_add_to_default_info_map.append(info_map_file_path)

                zip_infomap_file_name = config_vars.resolve_str(infomap_file_name + "$(WZLIB_EXTENSION)")
                zip_info_map_file_path = self.work_folder.joinpath(zip_infomap_file_name)
                with Wzip(info_map_file_path, self.work_folder, own_progress_count=0) as wzipper:
                    wzipper()
                files_to_add_to_default_info_map.append(zip_info_map_file_path)

        # add the default info map
        default_info_map_file_name = str(config_vars["MAIN_INFO_MAP_FILE_NAME"])
        default_info_map_file_path = self.work_folder.joinpath(default_info_map_file_name)
        info_map_items = self.info_map_table.get_items_for_default_infomap()
        self.info_map_table.write_to_file(in_file=default_info_map_file_path, items_list=info_map_items,
                                          field_to_write=self.fields_relevant_to_info_map)
        with Wzip(default_info_map_file_path, self.work_folder, own_progress_count=0) as wzipper:
            wzipper()

        # add a line to default info map for each non default info_map created above
        with utils.utf8_open_for_read(default_info_map_file_path, "a") as wfd:
            for file_to_add in files_to_add_to_default_info_map:
                file_checksum = utils.get_file_checksum(file_to_add)
                file_size = file_to_add.stat().st_size
                # todo: make path relative
                line_for_main_info_map = f"instl/{file_to_add.name}, f, {config_vars['TARGET_REPO_REV'].str()}, {file_checksum}, {file_size}\n"
                wfd.write(line_for_main_info_map)


class IndexYamlReader(DBManager, PythonBatchCommandBase):
    """ Reads and resolves index.yaml
        Admin pybatch class, used in deployment, not during installation
    """
    def __init__(self, index_yaml_path, resolve_inheritance=True, **kwargs):
        super().__init__(**kwargs)
        self.index_yaml_path = Path(index_yaml_path)
        self.resolve_inheritance = resolve_inheritance

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.index_yaml_path))
        all_args.append(self.optional_named__init__param("resolve_inheritance", self.resolve_inheritance, True))

    def progress_msg_self(self) -> str:
        return f'''read index.yaml from {self.index_yaml_path}'''

    def __call__(self, *args, **kwargs) -> None:
        from pyinstl import IndexYamlReaderBase
        self.items_table.activate_all_oses()
        reader = IndexYamlReaderBase(config_vars)
        reader.read_yaml_file(self.index_yaml_path)
        if self.resolve_inheritance:
            self.items_table.resolve_inheritance()


class ShortIndexYamlCreator(DBManager, PythonBatchCommandBase):
    """ Create short_index.yaml from index.yaml
        Admin pybatch class, used in deployment, not during installation
    """
    def __init__(self, short_index_yaml_path, **kwargs):
        super().__init__(**kwargs)
        self.short_index_yaml_path = Path(short_index_yaml_path)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.short_index_yaml_path))

    def progress_msg_self(self) -> str:
        return f'''write short index.yaml to {self.short_index_yaml_path}'''

    def __call__(self, *args, **kwargs) -> None:
        short_index_data = self.items_table.get_data_for_short_index()  # iid, name, version_mac, version_win, install_guid, remove_guid, size_mac, size_win
        short_index_dict = defaultdict(dict)
        builtin_iids = list(config_vars["SPECIAL_BUILD_IN_IIDS"])
        for data_line in short_index_data:
            data_dict = dict(data_line)
            IID = data_dict['iid']
            if IID not in builtin_iids:
                if data_dict['name']:
                    short_index_dict[IID]['name'] = data_dict['name']

                if data_dict['version_mac'] is None and data_dict['version_win'] is None:
                    pass
                elif data_dict['version_mac'] == data_dict['version_win']:
                    short_index_dict[IID]['version'] = data_dict['version_mac']
                else:
                    if data_dict['version_mac']:
                        short_index_dict[IID]['Mac'] = {'version': data_dict['version_mac']}
                    if data_dict['version_win']:
                        short_index_dict[IID]['Win'] = {'version': data_dict['version_win']}

                if data_dict['install_guid']:
                    if data_dict['remove_guid'] != data_dict['install_guid']:  # found uninstall gui
                        short_index_dict[IID]['guid'] = list((data_dict['install_guid'], data_dict['remove_guid']))
                    else:
                        short_index_dict[IID]['guid'] = data_dict['install_guid']

                if 'size_mac' in data_dict and data_dict['size_mac']:
                    short_index_dict[IID]['size_mac'] = data_dict['size_mac']
                if 'size_win' in data_dict and data_dict['size_win']:
                    short_index_dict[IID]['size_win'] = data_dict['size_win']

        defines_dict = config_vars.repr_for_yaml(which_vars=list(config_vars['SHORT_INDEX_FILE_VARS']), resolve=True,
                                                 ignore_unknown_vars=False)
        defines_yaml_doc = aYaml.YamlDumpDocWrap(defines_dict, '!define', "Definitions",
                                                 explicit_start=True, sort_mappings=True)

        index_yaml_doc = aYaml.YamlDumpDocWrap(value=short_index_dict, tag="!index",
                                               explicit_start=True, explicit_end=False,
                                               sort_mappings=True, include_comments=False)

        with utils.utf8_open_for_write(self.short_index_yaml_path, "w") as wfd:
            aYaml.writeAsYaml(defines_yaml_doc, wfd)
            aYaml.writeAsYaml(index_yaml_doc, wfd)


class CopySpecificRepoRev(DBManager, PythonBatchCommandBase):
    """ Copy files marked are "required" to the repo-rev folder
        Admin pybatch class, used in deployment, not during installation
    """
    def __init__(self, checkout_folder, repo_rev_folder, repo_rev, **kwargs):
        super().__init__(**kwargs)
        self.checkout_folder = Path(checkout_folder)
        self.repo_rev_folder = Path(repo_rev_folder)
        self.repo_rev = repo_rev

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.checkout_folder))
        all_args.append(self.unnamed__init__param(self.repo_rev_folder))
        all_args.append(self.unnamed__init__param(self.repo_rev))

    def progress_msg_self(self) -> str:
        return f'''Copy files of repo-rev#{self.repo_rev} from {self.checkout_folder} to {self.repo_rev_folder}'''

    def __call__(self, *args, **kwargs) -> None:
        self.info_map_table.mark_required_for_revision(self.repo_rev)
        self.info_map_table.mark_required_for_dir("instl")
        files_to_copy = self.info_map_table.get_required_items(what="file")
        for a_file in files_to_copy:
            source = Path(self.checkout_folder, a_file)
            target = Path(self.repo_rev_folder, a_file)
            print(f"copy {source} to {target}")
            with CopyFileToFile(source, target, own_progress_count=0) as cftf:
                cftf()


# CreateRepoRevFile is not a class that uses info map, but this file is the best place for this it
class CreateRepoRevFile(PythonBatchCommandBase):
    """ create a repo-rev file inside the instl folder
        Admin pybatch class, used in deployment, not during installation
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def progress_msg_self(self) -> str:
        return f'''create file for repo-rev#{config_vars["TARGET_REPO_REV"].str()}'''

    def __call__(self, *args, **kwargs) -> None:
        if "REPO_REV_FILE_VARS" not in config_vars:
            # must have a list of variable names to write to the repo-rev file
            raise ValueError("REPO_REV_FILE_VARS must be defined")
        repo_rev_vars = list(config_vars["REPO_REV_FILE_VARS"])  # list of configVars to write to the repo-rev file
        # check that the variable names from REPO_REV_FILE_VARS do not contain
        # names that must not be made public
        dangerous_intersection = set(repo_rev_vars).intersection(
            {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "PRIVATE_KEY", "PRIVATE_KEY_FILE"})
        if dangerous_intersection:
            log.warning("found", str(dangerous_intersection), "in REPO_REV_FILE_VARS, aborting")
            raise ValueError(f"file REPO_REV_FILE_VARS {dangerous_intersection} and so is forbidden to upload")

        use_zlib = bool(config_vars.get("USE_ZLIB", "False"))  # should we consider zipped files or not
        zip_extension = ""
        if use_zlib:
            zip_extension = config_vars.get("WZLIB_EXTENSION", ".wzip").str()

        revision_instl_folder_path = Path(config_vars["UPLOAD_REVISION_INSTL_FOLDER"])

        # create checksum for the main info_map file, either wzipped or not
        main_info_map_file_name = "info_map.txt" + zip_extension
        main_info_map_file = revision_instl_folder_path.joinpath(main_info_map_file_name)
        main_info_map_checksum = utils.get_file_checksum(main_info_map_file)

        config_vars[
            "INFO_MAP_FILE_URL"] = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/" + main_info_map_file_name
        config_vars["INFO_MAP_CHECKSUM"] = main_info_map_checksum

        # create checksum for the main index.yaml file, either wzipped or not
        index_file_name = "index.yaml" + zip_extension
        index_file_path = revision_instl_folder_path.joinpath(index_file_name)

        config_vars["INDEX_CHECKSUM"] = utils.get_file_checksum(index_file_path)
        config_vars[
            "INDEX_URL"] = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/" + index_file_name

        short_index_file_name = "short-index.yaml"
        short_index_file_path = revision_instl_folder_path.joinpath(short_index_file_name)
        config_vars["SHORT_INDEX_CHECKSUM"] = utils.get_file_checksum(short_index_file_path)
        config_vars[
            "SHORT_INDEX_URL"] = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/" + short_index_file_name

        config_vars["INSTL_FOLDER_BASE_URL"] = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl"
        config_vars["REPO_REV_FOLDER_HIERARCHY"] = "$(__CURR_REPO_FOLDER_HIERARCHY__)"

        # check that all variables are present
        # <class 'list'>: ['INSTL_FOLDER_BASE_URL', 'REPO_REV_FOLDER_HIERARCHY', 'SYNC_BASE_URL']
        missing_vars = [var for var in repo_rev_vars if var not in config_vars]
        if missing_vars:
            raise ValueError(f"{missing_vars} are missing cannot write repo rev file")

        # create yaml out of the variables
        variables_as_yaml = config_vars.repr_for_yaml(repo_rev_vars)
        repo_rev_yaml_doc = aYaml.YamlDumpDocWrap(variables_as_yaml, '!define', "",
                                                  explicit_start=True, sort_mappings=True)
        repo_rev_file_path = config_vars["UPLOAD_REVISION_REPO_REV_FILE"]
        with utils.utf8_open_for_write(repo_rev_file_path, "w") as wfd:
            aYaml.writeAsYaml(repo_rev_yaml_doc, out_stream=wfd, indentor=None, sort=True)
            log.info(f"""create {repo_rev_file_path}""")
