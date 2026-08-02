from typing import List
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
import logging

log = logging.getLogger(__name__)

from configVar import config_vars
from configVar import config_var_str

import aYaml
import utils

from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDir
from .fileSystemBatchCommands import Chmod
from .wtarBatchCommands import Wzip
from .copyBatchCommands import CopyFileToFile
from .downloadBatchCommands import DownloadFileAndCheckChecksum, DownloadManager

from db import DBManager

# the download-domain helpers these commands drive
from pyinstl import downloadVerify
from pyinstl.downloadState import (
    DownloadFileState,
    promote_verified_temp_file,
    remove_stale_temp_for_download_item,
    temp_path_for_download_item,
)
from pyinstl.downloadFailures import DownloadFailureClass

"""
    batch commands that need access to the db and the info_map table
"""


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

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)  # read the info map file from TO_SYNC_INFO_MAP_PATH - if provided
        dl_file_items = self.info_map_table.get_download_items(what="file")
        # this class overrides increment_and_output_progress to a no-op, so helpers that
        # must still output a line are handed the base class' one
        report_progress = super().increment_and_output_progress

        # total bytes this pass will process, so the ticks carry a determinate fraction
        verify_planned_bytes = sum(
            int(fi.size) for fi in dl_file_items if getattr(fi, "size", None) and fi.size > 0)
        verify_hashed_bytes = 0

        def report_hashed(file_item):
            # the phase bar follows the hashing, which is all of the phase's real work;
            # a fallback to serial hashing can re-report an item, hence the clamp
            nonlocal verify_hashed_bytes
            if getattr(file_item, "size", None) and file_item.size > 0:
                verify_hashed_bytes += int(file_item.size)
            downloadVerify.emit_verify_progress(
                self, min(verify_hashed_bytes, verify_planned_bytes), verify_planned_bytes)

        utils.wait_for_break_file_to_be_removed(
            config_vars['LOCAL_SYNC_DIR'].Path(resolve=True).joinpath("BREAK_BEFORE_CHECKSUM"),
            self.break_file_callback)

        # hashing is the only work that runs off the main thread; ALL bookkeeping below
        # runs on the main thread in the original order using these results
        precomputed = downloadVerify.precompute_all_verify_hashes(dl_file_items,
                                                                  on_item_hashed=report_hashed)
        total_items = len(dl_file_items)

        for file_index, file_item in enumerate(dl_file_items):
            self.doing = f"""check checksum for '{file_item.download_path}'"""
            downloadVerify.verify_progress_log(self, self.doing, 1, file_index, total_items)

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
                    downloadVerify.bad_file_progress(
                        self, report_progress,
                        f"bad checksum for temp download '{temp_path}'\nexpected: {file_item.checksum}, found: {file_checksum}",
                        file_index, total_items)
                    self.lists_of_files["bad_checksum"].append(" ".join(("Bad checksum:", os.fspath(temp_path),
                                                                         "expected", file_item.checksum, "found",
                                                                         file_checksum)))
                    self.lists_of_files["to redownload"].append(file_item)
                    downloadVerify.emit_retry_decision(
                        self.info_map_table,
                        file_item,
                        downloadVerify.build_failure_info(DownloadFailureClass.CHECKSUM_MISMATCH),
                        received_bytes=temp_path.stat().st_size,
                        resume_eligible=False,  # restart_required by class
                    )
                else:
                    promote_verified_temp_file(temp_path, final_path, file_item.checksum, actual_checksum=file_checksum)
                    downloadVerify.record_promoted_outcome(self.info_map_table, file_item,
                                                           final_path.stat().st_size)
                    downloadVerify.verify_progress_log(self, f"promoted verified download '{final_path}'",
                                                       0, file_index, total_items)
            else:
                self.num_bad_files += 1
                downloadVerify.bad_file_progress(
                    self, report_progress,
                    f"missing temp download '{temp_path}' for '{file_item.download_path}'",
                    file_index, total_items)
                self.lists_of_files["missing_files"].append(" ".join((os.fspath(temp_path), "was not found")))
                self.lists_of_files["to redownload"].append(file_item)
                downloadVerify.emit_retry_decision(
                    self.info_map_table,
                    file_item,
                    downloadVerify.build_failure_info(DownloadFailureClass.MISSING_AFTER_TRANSFER),
                    received_bytes=0,
                    resume_eligible=False,  # restart_required by class
                )
            if self.max_bad_files_to_redownload is not None and self.num_bad_files > self.max_bad_files_to_redownload:
                if downloadVerify.count_all_bad_files():
                    # keep counting so every bad file gets a recovery chance, warn once
                    if not self._bad_files_threshold_warned:
                        self._bad_files_threshold_warned = True
                        threshold_msg = (f"more than {self.max_bad_files_to_redownload} bad or missing files found; "
                                         f"continuing to count them all, redownload will be budget-bounded")
                        log.warning(threshold_msg)
                        report_progress(increment_by=0, prog_msg=threshold_msg)
                else:
                    report_progress(increment_by=0,
                                    prog_msg=f"stopping checksum check too many bad or missing files found")
                    break

        if not self.is_checksum_ok():
            if downloadVerify.count_all_bad_files():
                # recovery is attempted however many files are bad, the budget bounds it
                attempt_recovery = downloadVerify.redownload_pass_enabled(self.max_bad_files_to_redownload)
            else:
                # legacy count-cliff behavior (kill switch off)
                attempt_recovery = (self.max_bad_files_to_redownload is not None
                                    and self.num_bad_files <= self.max_bad_files_to_redownload)
            if attempt_recovery:
                utils.wait_for_break_file_to_be_removed(
                    config_vars['LOCAL_SYNC_DIR'].Path(resolve=True).joinpath("BREAK_BEFORE_REDOWNLOAD"),
                    self.break_file_callback)
                self.re_download_bad_files()

        # forced past the throttle only here, AFTER any recovery: driving the bar to full
        # before a redownload pass that can run for an hour is what made the phase look done
        # while it was still working
        downloadVerify.emit_verify_progress(self, verify_planned_bytes, verify_planned_bytes, force=True)

        # Central's error parser regexes on /Bad checksum/i, so do not change the format
        if not self.is_checksum_ok():  # some files still not OK after re_download_bad_files
            if self.raise_on_bad_checksum:
                exception_message = "\n".join(
                    (f'Bad checksum for {len(self.lists_of_files["bad_checksum"])} files',
                     f'Missing {len(self.lists_of_files["missing_files"])} files'))
                raise ValueError(exception_message)

    def re_download_bad_files(self):
        """Retry the files the verify loop rejected and discount the ones that came back
        good; downloadVerify.redownload_bad_files owns the pause-aware retry loop."""
        with DownloadManager(cookie=config_vars["COOKIE_JAR"].str(),
                             report_own_progress=False) as dler:  # should get the cookie from the config vars
            self.num_bad_files -= downloadVerify.redownload_bad_files(
                dler, self.info_map_table, self.lists_of_files["to redownload"],
                super().increment_and_output_progress, cmd=self)

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
        dl_file_items = self.info_map_table.get_download_items(what="file")
        total_items = len(dl_file_items)
        # every item's record, written in one batch below. Nothing writes a sidecar
        # during the curl transfer, so this pass is what makes resume-after-interrupt
        # work at all - it may be batched, never skipped
        sidecar_records = []
        for item_index, file_item in enumerate(dl_file_items):
            temp_path = temp_path_for_download_item(file_item)
            self.doing = f"""prepare temp download {item_index + 1} of {total_items} '{temp_path}'"""
            # increment_by=0: this command carries own_progress_count=0, so the position
            # goes in the text or a pass over every download item shows nothing at all
            downloadVerify.emit_throttled_progress(self, self.doing, 0, item_index, total_items,
                                                   "_prepare_temp_last_log")
            resume_decision = downloadVerify.resume_decision_for_file_item(self.info_map_table, file_item)
            if resume_decision.can_resume:
                sidecar_records.append(downloadVerify.build_resume_sidecar(
                    self.info_map_table,
                    file_item,
                    DownloadFileState.QUEUED,
                    received_bytes=resume_decision.resume_from_byte,
                    source_metadata=downloadVerify.source_metadata_from_record(resume_decision.record),
                ))
                continue
            transfer_state = DownloadFileState.INTERRUPTED if temp_path.is_file() else DownloadFileState.QUEUED
            # built before the temp is removed: the record's receivedBytes comes from it
            sidecar_records.append(downloadVerify.build_resume_sidecar(
                self.info_map_table, file_item, transfer_state))
            remove_stale_temp_for_download_item(file_item)
        # replace: this pass enumerates the whole session, so it also compacts away
        # whatever a previous session left behind
        downloadVerify.save_resume_sidecars(sidecar_records, replace=True)


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
        downloadVerify.emit_download_started(self.files_planned, self.bytes_planned)


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
        downloadVerify.emit_download_state(self.state, reason=self.reason)
        if self.state == "copying" and self.phase_bytes_planned is not None:
            try:
                from pybatch.copyPhaseProgress import begin_copy_phase
                begin_copy_phase(self.phase_bytes_planned,
                                 config_var_str("__INVOCATION_RANDOM_ID__", "unknown"))
            except Exception as ex:  # pragma: no cover - instrumentation must never break copy
                log.debug(f"could not begin copy phase: {ex}")
        elif self.state == "completed":
            try:
                from pybatch.copyPhaseProgress import end_copy_phase
                end_copy_phase()
            except Exception as ex:  # pragma: no cover - instrumentation must never break copy
                log.debug(f"could not end copy phase: {ex}")


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
            downloadVerify.emit_throttled_progress(self, f"create sync folder {path_to_create}", 1,
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
