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


class InfoMapBase(DBManager, PythonBatchCommandBase):
    def __init__(self, info_map_file=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.info_map_file = info_map_file

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        if self.info_map_file is not None:
            the_repr += f'''info_map_file={utils.quoteme_raw_by_type(self.info_map_file)}'''
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f'''{self.__class__.__name__}'''

    def __call__(self, *args, **kwargs) -> None:
        if self.info_map_file:
            resolved_info_map_path = utils.ResolvedPath(self.info_map_file)
            self.info_map_table.read_from_file(resolved_info_map_path, a_format="text", disable_indexes_during_read=True)


class CheckDownloadFolderChecksum(InfoMapBase):
    def __init__(self, info_map_file=None, print_report=False, raise_on_bad_checksum=False, **kwargs) -> None:
        super().__init__(info_map_file, **kwargs)
        self.print_report = print_report
        self.raise_on_bad_checksum = raise_on_bad_checksum
        if not self.raise_on_bad_checksum:
            self.exceptions_to_ignore.append(ValueError)
        self.bad_checksum_list = list()
        self.missing_files_list = list()
        self.bad_checksum_list_exception_message = ""
        self.missing_files_exception_message = ""

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        if self.info_map_file is not None:
            the_repr += f'''info_map_file={utils.quoteme_raw_by_type(self.info_map_file)}'''
        if self.print_report:
            the_repr += f''', print_report={self.print_report}'''
        if self.raise_on_bad_checksum:
            the_repr += f''', raise_on_bad_checksum={self.raise_on_bad_checksum}'''
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f'''Check download folder checksum'''

    def __call__(self, *args, **kwargs) -> None:
        super().__call__()  # read the info map file from TO_SYNC_INFO_MAP_PATH - if provided
        if self.info_map_file is None:
            dl_file_items = self.info_map_table.get_download_items(what="file")
        else:
            dl_file_items = self.info_map_table.get_items(what="file")
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


class SetExecPermissionsInSyncFolder(InfoMapBase):
    def __init__(self, info_map_file=None, **kwargs) -> None:
        super().__init__(info_map_file, **kwargs)

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        if self.info_map_file is not None:
            the_repr += f'''info_map_file={utils.quoteme_raw_by_type(self.info_map_file)}'''
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f'''Set exec permissions in download folder'''

    def __call__(self, *args, **kwargs) -> None:
        super().__call__()  # read the info map file from REQUIRED_INFO_MAP_PATH - if provided
        if self.info_map_file is not None:
            # REQUIRED_INFO_MAP_PATH contains only the required files so get the paths
            # of the executable files
            exec_file_paths = self.info_map_table.get_exec_file_paths()
        else:
            # info_map_file already read, and contains all files, so get the paths
            # of the *required* executable files
            exec_file_paths = self.info_map_table.get_required_exec_file_paths()
        for file_item_path in exec_file_paths:
            if os.path.isfile(file_item_path):
                Chmod(file_item_path, "a+x", own_progress_count=0)()


class CreateSyncFolders(InfoMapBase):
    def __init__(self, info_map_file=None, **kwargs) -> None:
        super().__init__(info_map_file, **kwargs)

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        if self.info_map_file is not None:
            the_repr += f'''info_map_file={utils.quoteme_raw_by_type(self.info_map_file)}'''
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f'''Create download directories'''

    def __call__(self, *args, **kwargs) -> None:
        super().__call__()  # read the info map file from TO_SYNC_INFO_MAP_PATH - if provided
        if self.info_map_file is None:
            dl_dir_items = self.info_map_table.get_download_items(what="dir")
        else:
            dl_dir_items = self.info_map_table.get_items(what="dir")
        for dl_dir in dl_dir_items:
            self.doing = f"""creating sync folder '{dl_dir}'"""
            MakeDirs(dl_dir.path)()
