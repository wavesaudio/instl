from typing import List, Any
import os
import stat
import zlib
from collections import defaultdict
from pathlib import Path
import logging

log = logging.getLogger(__name__)

from configVar import config_vars
import aYaml
import utils


from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDir
from .fileSystemBatchCommands import Chmod
from .wtarBatchCommands import Wzip
from .copyBatchCommands import CopyFileToFile

from db import DBManager

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

    def increment_and_output_progress(self, increment_by=None, prog_counter_msg=None, prog_msg=None):
        """ override PythonBatchCommandBase.increment_and_output_progress so progress can be reported for each file
        """
        pass

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)  # read the info map file from TO_SYNC_INFO_MAP_PATH - if provided
        dl_file_items = self.info_map_table.get_download_items(what="file")

        for file_item in dl_file_items:
            super().increment_and_output_progress(increment_by=1, prog_msg=f"check checksum for '{file_item.download_path}'")
            self.doing = f"""check checksum for '{file_item.download_path}'"""
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
        self.own_progress_count = self.info_map_table.num_items(item_filter="need-download-dirs")

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def progress_msg_self(self) -> str:
        return f'''Create download directories'''

    def increment_and_output_progress(self):
        """ override PythonBatchCommandBase.increment_and_output_progress so progress can be reported for each file
        """
        pass

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)
        dl_dir_items = self.info_map_table.get_download_items(what="dir")
        for dl_dir in dl_dir_items:
            super().increment_and_output_progress(increment_by=1, prog_msg=f"create sync folder {dl_dir}")
            self.doing = f"""creating sync folder '{dl_dir}'"""
            if dl_dir.download_path:  # direct_sync items have absolute path in member .download_path
                MakeDir(dl_dir.download_path)()
            else:  # cache items have relative path in member .path
                MakeDir(dl_dir.path)()


class SetBaseRevision(DBManager, PythonBatchCommandBase):
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
            info_map_file_path = self.work_folder.joinpath(infomap_file_name)
            if info_map_file_path.is_file():
                log.info(f"{infomap_file_name} was found so no need to create it")
                # file already exists, probably copied from the "Common" repository
                # just checking that the fie is also zipped
                zip_infomap_file_name = config_vars.resolve_str(infomap_file_name+"$(WZLIB_EXTENSION)")
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
    def __init__(self, index_yaml_path, **kwargs):
        super().__init__(**kwargs)
        self.index_yaml_path = Path(index_yaml_path)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.index_yaml_path))

    def progress_msg_self(self) -> str:
        return f'''read index.yaml from {self.index_yaml_path}'''

    def __call__(self, *args, **kwargs) -> None:
        from pyinstl import IndexYamlReaderBase
        reader = IndexYamlReaderBase(config_vars)
        reader.read_yaml_file(self.index_yaml_path)


class ShortIndexYamlCreator(DBManager, PythonBatchCommandBase):
    def __init__(self, short_index_yaml_path, **kwargs):
        super().__init__(**kwargs)
        self.short_index_yaml_path = Path(short_index_yaml_path)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.short_index_yaml_path))

    def progress_msg_self(self) -> str:
        return f'''write short index.yaml to {self.short_index_yaml_path}'''

    def __call__(self, *args, **kwargs) -> None:
        short_index_data = self.items_table.get_data_for_short_index()  # IID, GUID, NAME, VERSION, generation
        short_index_dict = defaultdict(dict)
        for data_line in short_index_data:
            short_index_dict[data_line[0]]['guid'] = data_line[1]
            if data_line[4] and data_line[1] != data_line[4]:  # uninstall gui
                short_index_dict[data_line[0]]['guid'] = list((data_line[1], data_line[4]))
            if data_line[2]:
                short_index_dict[data_line[0]]['name'] = data_line[2]
            if data_line[3] or data_line[4]:
                short_index_dict[data_line[0]]['version'] = data_line[3]

        defines_dict = config_vars.repr_for_yaml(which_vars=['AUXILIARY_IIDS'], resolve=True, ignore_unknown_vars=False)
        defines_yaml_doc = aYaml.YamlDumpDocWrap(defines_dict, '!define', "Definitions",
                                                 explicit_start=True, sort_mappings=True)

        index_yaml_doc = aYaml.YamlDumpDocWrap(value=short_index_dict, tag="!index",
                                               explicit_start=True, explicit_end=False,
                                               sort_mappings=True, include_comments=False)

        with utils.utf8_open_for_write(self.short_index_yaml_path, "w") as wfd:
            aYaml.writeAsYaml(defines_yaml_doc, wfd)
            aYaml.writeAsYaml(index_yaml_doc, wfd)


class CopySpecificRepoRev(DBManager, PythonBatchCommandBase):
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
        main_info_map_file_name = "info_map.txt"+zip_extension
        main_info_map_file = revision_instl_folder_path.joinpath(main_info_map_file_name)
        main_info_map_checksum = utils.get_file_checksum(main_info_map_file)

        config_vars["INFO_MAP_FILE_URL"] = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/"+main_info_map_file_name
        config_vars["INFO_MAP_CHECKSUM"] = main_info_map_checksum

        # create checksum for the main index.yaml file, either wzipped or not
        index_file_name = "index.yaml"+zip_extension
        index_file_path = revision_instl_folder_path.joinpath(index_file_name)

        config_vars["INDEX_CHECKSUM"] = utils.get_file_checksum(index_file_path)
        config_vars["INDEX_URL"] = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/"+index_file_name

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

