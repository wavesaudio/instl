from http.cookies import SimpleCookie
from requests.cookies import cookiejar_from_dict
from typing import List, Any
import os
import sys
import stat
import zlib
from collections import defaultdict
from pathlib import Path
import logging
import requests
import time
import datetime

log = logging.getLogger(__name__)

from configVar import config_vars

import aYaml
import utils

from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDir
from .fileSystemBatchCommands import Chmod
from .wtarBatchCommands import Wzip
from .copyBatchCommands import CopyFileToFile
from .downloadBatchCommands import DownloadFileAndCheckChecksum, DownloadManager
from svnTree.svnTable import SVNTable

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
)

"""
    batch commands that need access to the db and the info_map table
"""


def _config_var_str(name: str, default=None):
    if name not in config_vars:
        return default
    try:
        value = config_vars[name].str()
    except Exception:
        value = str(config_vars[name])
    return value if value else default


def _config_var_bool(name: str, default=False):
    if name not in config_vars:
        return default
    return config_vars[name].bool()


def _config_var_int(name: str, default=0):
    if name not in config_vars:
        return default
    try:
        return int(config_vars[name].str())
    except Exception:
        return default


def _config_var_list(name: str):
    if name not in config_vars:
        return []
    values = config_vars[name].list()
    if len(values) == 1:
        value = str(values[0])
        if "," in value:
            values = [part.strip() for part in value.split(",")]
    return [str(value).strip() for value in values if str(value).strip()]


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
    bookkeeping_dir = _config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
    return resume_decision_for_download_item(
        file_item,
        _source_url_for_file_item(info_map_table, file_item),
        bookkeeping_dir,
        resume_enabled=_config_var_bool("DOWNLOAD_RESUME_ENABLED", False),
        validated_hosts=resolve_validated_hosts(
            _config_var_list("DOWNLOAD_RESUME_VALIDATED_HOSTS"),
            _config_var_str("BASE_LINKS_URL"),
        ),
        validated_path_prefixes=_config_var_list("DOWNLOAD_RESUME_VALIDATED_PATH_PREFIXES"),
        require_conditional=_config_var_bool("DOWNLOAD_RESUME_REQUIRE_CONDITIONAL", True),
        signed_url_min_ttl_seconds=_config_var_int("DOWNLOAD_RESUME_MIN_SIGNED_URL_TTL_SECONDS", 300),
    )


def _build_failure_info(failure_class, *, http_status=None, curl_exit_code=None, retry_after_seconds=None, reason=""):
    """Construct a minimal DownloadFailureInfo for callers that already know the class.

    Phase 3 callers in this module record classes by name (e.g. ``checksum_mismatch``,
    ``missing_temp``). This helper centralizes the conversion so retry decisions get
    the same shape whether they come from exceptions, curl exit codes, or direct
    classification at known checkpoints.
    """
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


def _emit_retry_decision(info_map_table, file_item, failure, *, received_bytes=None, resume_eligible=False, concurrency=None):
    """Compute a retry decision for ``file_item``, persist it on the sidecar, and log it.

    Behavior is additive: the existing redownload loop in ``re_download_bad_files``
    still drives the actual retransfer. This helper records the matrix-derived
    decision (count, delay, action) so Phase 5 telemetry/UX and operators can
    explain why a file was queued for redownload or marked terminal.

    Phase 6 P6-002: ``DOWNLOAD_RETRY_POLICY_ENABLED=no`` is the kill switch
    that returns ``None`` without computing/logging a decision or touching
    the resume sidecar's retry bookkeeping. Existing redownload behavior
    is unaffected because the matrix never drove the transfer itself.
    """
    if not _config_var_bool("DOWNLOAD_RETRY_POLICY_ENABLED", True):
        return None
    bookkeeping_dir = _config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
    previous_retry_count = 0
    if bookkeeping_dir:
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
            session_id=_config_var_str("__INVOCATION_RANDOM_ID__", "unknown"),
            file_id=file_id,
            repo_path=getattr(file_item, "path", None),
            received_bytes=received_bytes,
            concurrency=concurrency,
        )
        log.info(log_line)
    except Exception as log_ex:  # pragma: no cover - logging must never break sync
        log.debug(f"could not format retry decision log: {log_ex}")

    # Phase 5 P5-001: emit the same retry decision through the unified
    # DOWNLOAD_EVENT channel and a paired file_state event so Central can
    # consume one channel instead of parsing the legacy prefix.
    try:
        session_id = _config_var_str("__INVOCATION_RANDOM_ID__", "unknown")
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

    _save_resume_sidecar_with_retry_count(
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


def _save_resume_sidecar_with_retry_count(info_map_table, file_item, transfer_state, received_bytes=None, last_failure_class=None, retry_count=None, source_metadata=None):
    """Variant of :func:`_save_resume_sidecar` that lets the caller pin ``retry_count``."""
    bookkeeping_dir = _config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
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
            session_id=_config_var_str("__INVOCATION_RANDOM_ID__", "unknown"),
            repository_major_version=_config_var_str("TARGET_MAJOR_VERSION") or _config_var_str("SYNC_BASE_URL_MAIN_ITEM"),
            transfer_state=transfer_state,
            received_bytes=received_bytes,
            last_failure_class=last_failure_class,
            retry_count=retry_count if retry_count is not None else 0,
            source_metadata=source_metadata,
        )
    except Exception as ex:
        log.warning(f"could not save download resume sidecar for {getattr(file_item, 'path', 'unknown')}: {ex}")
        return None


def _save_resume_sidecar(info_map_table, file_item, transfer_state, received_bytes=None, last_failure_class=None, source_metadata=None):
    bookkeeping_dir = _config_var_str("LOCAL_REPO_BOOKKEEPING_DIR")
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
            session_id=_config_var_str("__INVOCATION_RANDOM_ID__", "unknown"),
            repository_major_version=_config_var_str("TARGET_MAJOR_VERSION") or _config_var_str("SYNC_BASE_URL_MAIN_ITEM"),
            transfer_state=transfer_state,
            received_bytes=received_bytes,
            last_failure_class=last_failure_class,
            source_metadata=source_metadata,
        )
    except Exception as ex:
        log.warning(f"could not save download resume sidecar for {getattr(file_item, 'path', 'unknown')}: {ex}")
        return None


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
        self.max_bad_files_to_redownload = max_bad_files_to_redownload
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

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)  # read the info map file from TO_SYNC_INFO_MAP_PATH - if provided
        dl_file_items = self.info_map_table.get_download_items(what="file")

        utils.wait_for_break_file_to_be_removed(
            config_vars['LOCAL_SYNC_DIR'].Path(resolve=True).joinpath("BREAK_BEFORE_CHECKSUM"),
            self.break_file_callback)

        for file_item in dl_file_items:
            self.doing = f"""check checksum for '{file_item.download_path}'"""
            super().increment_and_output_progress(increment_by=1, prog_msg=self.doing)

            final_path = Path(file_item.download_path)
            temp_path = temp_path_for_download_item(file_item)
            _save_resume_sidecar(self.info_map_table, file_item, DownloadFileState.VERIFYING)

            if checksum_matches(final_path, file_item.checksum):
                already_valid_bytes = final_path.stat().st_size
                _save_resume_sidecar(
                    self.info_map_table,
                    file_item,
                    DownloadFileState.ALREADY_VALID,
                    received_bytes=already_valid_bytes,
                )
                # Cache hit: no bytes transferred this session, so do not
                # contribute to throughput. Recording as SUCCESS would make
                # warm-cache runs look fast for the wrong reason.
                remove_stale_temp_for_download_item(file_item)
                continue

            if temp_path.is_file():
                file_checksum = get_file_sha1(temp_path)
                if not utils.compare_checksums(file_checksum, file_item.checksum):
                    self.num_bad_files += 1
                    super().increment_and_output_progress(increment_by=0,
                                                          prog_msg=f"bad checksum for temp download '{temp_path}'\nexpected: {file_item.checksum}, found: {file_checksum}")
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
                    _save_resume_sidecar(
                        self.info_map_table,
                        file_item,
                        DownloadFileState.VERIFIED,
                        received_bytes=promoted_bytes,
                    )
                    try:
                        _observability_record_outcome(
                            outcome=DownloadOutcome.SUCCESS,
                            url=_source_url_for_file_item(self.info_map_table, file_item),
                            bytes_received=promoted_bytes,
                        )
                    except Exception as obs_ex:  # pragma: no cover
                        log.debug(f"observability record_outcome failed: {obs_ex}")
                    super().increment_and_output_progress(increment_by=0,
                                                          prog_msg=f"promoted verified download '{final_path}'")
            else:
                self.num_bad_files += 1
                super().increment_and_output_progress(increment_by=0,
                                                      prog_msg=f"missing temp download '{temp_path}' for '{file_item.download_path}'")
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
                super().increment_and_output_progress(increment_by=0,
                                                      prog_msg=f"stopping checksum check too many bad or missing files found")
                break

        if not self.is_checksum_ok():
            if self.max_bad_files_to_redownload is not None and self.num_bad_files <= self.max_bad_files_to_redownload:
                utils.wait_for_break_file_to_be_removed(
                    config_vars['LOCAL_SYNC_DIR'].Path(resolve=True).joinpath("BREAK_BEFORE_REDOWNLOAD"),
                    self.break_file_callback)
                self.re_download_bad_files()

        if not self.is_checksum_ok():  # some files still not OK after re_download_bad_files
            if self.raise_on_bad_checksum:
                exception_message = "\n".join(
                    (f'Bad checksum for {len(self.lists_of_files["bad_checksum"])} files',
                     f'Missing {len(self.lists_of_files["missing_files"])} files'))
                raise ValueError(exception_message)

    def re_download_bad_files(self):
        current_file_item = None
        # Phase 7 control channel: the in-process redownload loop is a
        # natural pause boundary — we hand each file to the synchronous
        # DownloadManager and never split a single file across iterations,
        # so blocking between iterations preserves the atomicity invariants
        # (D-001/D-009/D-010): no temp ``.part`` is promoted while paused.
        control_channel = get_global_channel()
        try:
            download_path = None

            with DownloadManager(cookie=config_vars["COOKIE_JAR"].str(),
                                 report_own_progress=False) as dler:  # should get the cookie from the config vars
                for file_item in self.lists_of_files["to redownload"]:
                    control_channel.wait_if_paused()
                    current_file_item = file_item
                    download_url = self.info_map_table.get_sync_url_for_file_item(file_item)
                    download_path = file_item.download_path
                    temp_path = temp_path_for_download_item(file_item)
                    remove_stale_temp_for_download_item(file_item)
                    dler(path=download_path, url=download_url, checksum=file_item.checksum, temp_path=temp_path)
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
                    current_file_item = None
        except Exception as ex:
            log.error(f"""Exception while redownloading {download_path}, {ex}""")
            super().increment_and_output_progress(increment_by=0,
                                                  prog_msg=f"""Exception while redownloading {download_path}, {ex}""")
            if current_file_item is not None:
                _emit_retry_decision(
                    self.info_map_table,
                    current_file_item,
                    classify_exception(ex),
                    received_bytes=0,
                    resume_eligible=False,
                )

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
        for dl_dir in dl_dir_items:
            # direct_sync items have absolute path in member dl_dir.download_path
            # cached items have relative path in member dl_dir.path
            path_to_create = dl_dir.download_path if dl_dir.download_path else dl_dir.path
            super().increment_and_output_progress(increment_by=1, prog_msg=f"create sync folder {path_to_create}")
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
