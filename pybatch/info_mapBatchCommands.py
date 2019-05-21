from typing import List, Any
import os
import stat
import tarfile
from pathlib import Path
import logging

log = logging.getLogger(__name__)

from configVar import config_vars
import utils


from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDirs

from db import DBManager
from .fileSystemBatchCommands import Chmod
from .wtarBatchCommands import Wzip

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


class SetBaseRevision(DBManager, PythonBatchCommandBase):
    def __init__(self, base_rev, **kwargs):
        super().__init__(**kwargs)
        self.base_rev = base_rev

    def repr_own_args(self, all_args: List[str]):
        all_args.append(self.unnamed__init__param(self.base_rev))

    def progress_msg_self(self):
        return f"Set base repo-rev to {self.base_rev}"

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)
        self.info_map_table.set_base_revision(self.base_rev)


class InfoMapFullWriter(DBManager, PythonBatchCommandBase):
    """ write all info map table lines to a single file """
    fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')

    def __init__(self, out_file, in_format='text', **kwargs):
        super().__init__(**kwargs)
        self.out_file = Path(out_file)
        self.format = format

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.out_file))
        all_args.append(self.optional_named__init__param("format", self.format, 'text'))

    def progress_msg_self(self) -> str:
        return f'''Create full info_map file'''

    def __call__(self, *args, **kwargs) -> None:
        self.info_map_table.write_to_file(self.out_file, field_to_write=InfoMapFullWriter.fields_relevant_to_info_map)


class InfoMapSplitWriter(DBManager, PythonBatchCommandBase):
    """ write all info map table to files according to info_map: field in index.yaml """
    fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')

    def __init__(self, work_folder, in_format='text', **kwargs):
        super().__init__(**kwargs)
        self.work_folder = Path(work_folder)
        self.format = format

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.work_folder))
        all_args.append(self.optional_named__init__param("format", self.format, 'text'))

    def progress_msg_self(self) -> str:
        return f'''Create split info_map files'''

    def __call__(self, *args, **kwargs) -> None:
        # fill the iid_to_svn_item_t table
        self.info_map_table.populate_IIDToSVNItem()

        # get the list of info map file names
        info_map_to_item = dict()
        all_info_map_names = self.items_table.get_unique_detail_values('info_map')
        for infomap_file_name in all_info_map_names:
            self.info_map_table.mark_items_required_by_infomap(infomap_file_name)
            info_map_items = self.info_map_table.get_required_items()
            info_map_to_item[infomap_file_name] = info_map_items

        files_to_add_to_default_info_map = list()  # the named info_map files and their wzip version should be added to the default info_map
        # write each info map to file
        for infomap_file_name, info_map_items in info_map_to_item.items():
            if info_map_items:  # could be that no items are linked to the info map file
                info_map_file_path = self.work_folder.joinpath(infomap_file_name)
                self.info_map_table.write_to_file(in_file=info_map_file_path, items_list=info_map_items, field_to_write=self.fields_relevant_to_info_map)
                files_to_add_to_default_info_map.append(info_map_file_path)

                zip_infomap_file_name = config_vars.resolve_str(infomap_file_name+"$(WZLIB_EXTENSION)")
                zip_info_map_file_path = self.work_folder.joinpath(zip_infomap_file_name)
                with Wzip(info_map_file_path, self.work_folder, own_progress_count=0) as wzipper:
                    wzipper()
                files_to_add_to_default_info_map.append(zip_info_map_file_path)

        # add the default info map
        default_info_map_file_name = str(config_vars["MAIN_INFO_MAP_FILE_NAME"])
        default_info_map_file_path = self.work_folder.joinpath(default_info_map_file_name)
        info_map_items = self.info_map_table.get_items_for_default_infomap()
        self.info_map_table.write_to_file(in_file=default_info_map_file_path, items_list=info_map_items, field_to_write=self.fields_relevant_to_info_map)

        # add a line to default info map for each non default info_map created above
        with open(default_info_map_file_path, "a") as wfd:
            for file_to_add in files_to_add_to_default_info_map:
                file_checksum = utils.get_file_checksum(file_to_add)
                file_size = file_to_add.stat().st_size
                # todo: make path relative
                line_for_main_info_map = f"instl/{file_to_add.name}, f, {config_vars['TARGET_REPO_REV'].str()}, {file_checksum}, {file_size}\n"
                wfd.write(line_for_main_info_map)



class IndexYamlReader(DBManager, PythonBatchCommandBase):
    def __init__(self, index_yaml_path, **kwargs):
        super().__init__(**kwargs)
        self.index_yaml_path = Path(index_yaml_path)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.index_yaml_path))

    def progress_msg_self(self) -> str:
        return f'''read index.yaml from {self.index_yaml_path}'''

    def __call__(self, *args, **kwargs) -> None:
        from pyinstl import IndexYamlReader
        reader = IndexYamlReader(config_vars)
        reader.read_yaml_file(self.index_yaml_path)
