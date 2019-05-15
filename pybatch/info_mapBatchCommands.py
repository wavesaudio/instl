from typing import List, Any
import os
import stat
import tarfile
from collections import OrderedDict
import logging

log = logging.getLogger()

from configVar import config_vars
import utils


from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDirs

from db import DBManager
from .fileSystemBatchCommands import Chmod

"""
    batch commands that need access to the db and the info_map table
"""


class CheckDownloadFolderChecksum(DBManager, PythonBatchCommandBase):
    """ check checksums in download folder
    """
    def __init__(self, print_report=False, raise_on_bad_checksum=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.print_report = print_report
        self.raise_on_bad_checksum = raise_on_bad_checksum
        if not self.raise_on_bad_checksum:
            self.exceptions_to_ignore.append(ValueError)
        self.bad_checksum_list = list()
        self.missing_files_list = list()
        self.bad_checksum_list_exception_message = ""
        self.missing_files_exception_message = ""

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.optional_named__init__param("print_report", self.print_report, False))
        all_args.append(self.optional_named__init__param("raise_on_bad_checksum", self.raise_on_bad_checksum, False))

    def progress_msg_self(self) -> str:
        return f'''Check download folder checksum'''

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)  # read the info map file from TO_SYNC_INFO_MAP_PATH - if provided
        dl_file_items = self.info_map_table.get_download_items(what="file")

        for file_item in dl_file_items:
            if os.path.isfile(file_item.download_path):
                file_checksum = utils.get_file_checksum(file_item.download_path)
                if not utils.compare_checksums(file_checksum, file_item.checksum):
                    self.bad_checksum_list.append(" ".join(("Bad checksum:", file_item.download_path, "expected", file_item.checksum, "found", file_checksum)))
            else:
                self.missing_files_list.append(" ".join((file_item.download_path, "was not found")))
        if not self.is_checksum_ok():
            report_lines = self.report()
            if self.print_report:
                print("\n".join(report_lines))
            if self.raise_on_bad_checksum:
                exception_message = "\n".join((self.bad_checksum_list_exception_message, self.missing_files_exception_message))
                raise ValueError(exception_message)

    def is_checksum_ok(self) -> bool:
        retVal = len(self.bad_checksum_list) + len(self.missing_files_list) == 0
        return retVal

    def report(self):
        report_lines = list()
        if self.bad_checksum_list:
            report_lines.extend(self.bad_checksum_list)
            self.bad_checksum_list_exception_message = f"Bad checksum for {len(self.bad_checksum_list)} files"
            report_lines.append(self.bad_checksum_list_exception_message)
        if self.missing_files_list:
            report_lines.extend(self.missing_files_list)
            self.missing_files_exception_message = f"Missing {len(self.missing_files_list)} files"
            report_lines.append(self.missing_files_exception_message)
        return report_lines


class SetExecPermissionsInSyncFolder(DBManager, PythonBatchCommandBase):
    """ set execute permissions for files that need such permission  in the download folder """
    def __init__(self, info_map_file=None, **kwargs) -> None:
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

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def progress_msg_self(self) -> str:
        return f'''Create download directories'''

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)
        dl_dir_items = self.info_map_table.get_download_items(what="dir")
        for dl_dir in dl_dir_items:
            self.doing = f"""creating sync folder '{dl_dir}'"""
            MakeDirs(dl_dir.path)()
