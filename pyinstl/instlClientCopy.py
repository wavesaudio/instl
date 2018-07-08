#!/usr/bin/env python3


import sys
import os
import pathlib
import utils
import functools
from typing import List

from configVar import config_vars
from .instlClient import InstlClient
from .batchAccumulator import BatchAccumulatorTransaction
import svnTree


class InstlClientCopy(InstlClient):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.unwtar_batch_file_counter: int = 0
        self.current_destination_folder: str = None
        self.current_iid: str = None

    def do_copy(self) -> None:
        self.init_copy_vars()

        # unwtar will take place directly so no need to copy those files
        self.ignore_additions = ['.wtar']
        for ignore_item in self.ignore_additions:
            ignore_item_wildcards = f'*{ignore_item}*'
            if ignore_item_wildcards not in self.patterns_copy_should_ignore:
                self.patterns_copy_should_ignore.append(ignore_item_wildcards)

        self.create_copy_instructions()

    def init_copy_vars(self) -> None:
        self.action_type_to_progress_message = {'pre_copy': "pre-install step",
                                                'post_copy': "post-install step",
                                                'pre_copy_to_folder': "pre-copy step",
                                                'post_copy_to_folder': "post-copy step"}
        self.bytes_to_copy = 0
        # ratio between wtar file and it's uncompressed contents
        self.wtar_ratio = float(config_vars.get("WTAR_RATIO", "1.3"))
        self.calc_user_cache_dir_var()  # this will set USER_CACHE_DIR if it was not explicitly defined
        self.patterns_copy_should_ignore = list(config_vars["COPY_IGNORE_PATTERNS"])

        # when running on MacOS AND installation targets MacOS some special cases need to be considered
        self.mac_current_and_target = 'Mac' in list(config_vars["__CURRENT_OS_NAMES__"]) and 'Mac' in list(config_vars["TARGET_OS"])

    def write_copy_debug_info(self) -> None:
        try:
            if config_vars.defined('ECHO_LOG_FILE'):
                log_file_path = config_vars["ECHO_LOG_FILE"].str()
                log_folder, log_file = os.path.split(log_file_path)
                with utils.utf8_open(os.path.join(log_folder, "sync-folder-manifest.txt"), "w") as wfd:
                    repo_sync_dir = config_vars["COPY_SOURCES_ROOT_DIR"].str()
                    wfd.write(utils.disk_item_listing(repo_sync_dir))
        except Exception:
            pass  # if it did not work - forget it

    def write_copy_to_folder_debug_info(self, folder_path: str) -> None:
        try:
            if config_vars.defined('ECHO_LOG_FILE'):
                log_file_path = config_vars["ECHO_LOG_FILE"].str()
                log_folder, log_file = os.path.split(log_file_path)
                manifests_log_folder = os.path.join(log_folder, "manifests")
                os.makedirs(manifests_log_folder, exist_ok=True)
                folder_path_parent, folder_name = os.path.split(config_vars.resolve_str(folder_path))
                ls_output_file = os.path.join(manifests_log_folder, folder_name+"-folder-manifest.txt")
                create_folder_ls_command_parts = [self.platform_helper.run_instl(), "ls",
                                              "--in", '"."',
                                              "--out", utils.quoteme_double(ls_output_file)]
                self.batch_accum += " ".join(create_folder_ls_command_parts)
        except Exception:
            pass  # if it did not work - forget it

    def create_create_folders_instructions(self, folder_list: List[str]) -> None:
        if len(folder_list) > 0:
            self.batch_accum += self.platform_helper.progress("Create folders ...")
            for target_folder_path in folder_list:
                if os.path.isfile(config_vars.resolve_str(target_folder_path)):
                    # weird as it maybe, some users have files where a folder should be.
                    # test for isfile is done here rather than in the batch file, because
                    # Windows does not have proper way to check "is file" in a batch.
                    self.batch_accum += self.platform_helper.rmfile(target_folder_path)
                    self.batch_accum += self.platform_helper.progress(f"Removed file that should be a folder {target_folder_path}")
                progress_num = self.platform_helper.increment_progress(1)
                self.batch_accum += self.platform_helper.mkdir_with_owner(target_folder_path, progress_num)

    def create_copy_instructions(self) -> None:
        self.progress("create copy instructions ...")
        self.create_sync_folder_manifest_command("before-copy", back_ground=True)
        # If we got here while in synccopy command, there is no need to read the info map again.
        # If we got here while in copy command, read HAVE_INFO_MAP_FOR_COPY which defaults to NEW_HAVE_INFO_MAP_PATH.
        # Copy might be called after the sync batch file was created but before it was executed
        if len(self.info_map_table.files_read_list) == 0:
            have_info_path = config_vars["HAVE_INFO_MAP_FOR_COPY"].str()
            with self.info_map_table.reading_files_context():
                self.read_info_map_from_file(have_info_path)

        # copy and actions instructions for sources
        self.batch_accum.set_current_section('copy')
        self.batch_accum += self.platform_helper.progress("Start copy")
        self.batch_accum += self.platform_helper.progress("Starting copy from $(COPY_SOURCES_ROOT_DIR)")

        self.accumulate_unique_actions_for_active_iids('pre_copy')
        self.batch_accum += self.platform_helper.new_line()

        sorted_target_folder_list = sorted(self.all_iids_by_target_folder,
                                           key=lambda fold: config_vars.resolve_str(fold))

        # first create all target folders so to avoid dependency order problems such as creating links between folders
        self.create_create_folders_instructions(sorted_target_folder_list)

        if  self.mac_current_and_target:
            self.pre_copy_mac_handling()

        remove_previous_sources = bool(config_vars.get("REMOVE_PREVIOUS_SOURCES",True))
        for target_folder_path in sorted_target_folder_list:
            if remove_previous_sources:
                self.create_remove_previous_sources_instructions_for_target_folder(target_folder_path)
            self.create_copy_instructions_for_target_folder(target_folder_path)

        # actions instructions for sources that do not need copying, here folder_name is the sync folder
        for sync_folder_name in sorted(self.no_copy_iids_by_sync_folder.keys()):
            self.create_copy_instructions_for_no_copy_folder(sync_folder_name)

        self.progress(self.bytes_to_copy, "bytes to copy")

        self.accumulate_unique_actions_for_active_iids('post_copy')

        self.batch_accum.set_current_section('post-copy')
        # Copy have_info file to "site" (e.g. /Library/Application support/... or c:\ProgramData\...)
        # for reference. But when preparing offline installers the site location is the same as the sync location
        # so copy should be avoided.
        if config_vars["HAVE_INFO_MAP_PATH"].str() != config_vars["SITE_HAVE_INFO_MAP_PATH"].str():
            progress_num = self.platform_helper.increment_progress(1)
            self.batch_accum += self.platform_helper.mkdir_with_owner("$(SITE_REPO_BOOKKEEPING_DIR)", progress_num)
            self.batch_accum += self.platform_helper.copy_file_to_file("$(HAVE_INFO_MAP_PATH)", "$(SITE_HAVE_INFO_MAP_PATH)")
            self.batch_accum += self.platform_helper.progress("Copied $(HAVE_INFO_MAP_PATH) to $(SITE_HAVE_INFO_MAP_PATH)")

        self.platform_helper.copy_tool.finalize()

        self.create_require_file_instructions()

        # messages about orphan iids
        for iid in sorted(list(config_vars["__ORPHAN_INSTALL_TARGETS__"])):
            self.batch_accum += self.platform_helper.echo("Don't know how to install " + iid)
        self.batch_accum += self.platform_helper.progress_percent("Done copy", 10)
        self.progress("create copy instructions done")
        self.progress("")

    def calc_size_of_file_item(self, a_file_item: svnTree.SVNRow) -> int:
        """ for use with builtin function reduce to calculate the unwtarred size of a file """
        if a_file_item.is_wtar_file():
            item_size = int(float(a_file_item.size) * self.wtar_ratio)
        else:
            item_size = a_file_item.size
        return item_size

    def create_copy_instructions_for_file(self, source_path: str, name_for_progress_message: str) -> int:
        retVal: int = 0  # number of essential actions (not progress, remark, ...)
        source_files = self.info_map_table.get_required_for_file(source_path)
        if not source_files:
            print("no source files for "+source_path)
            return retVal
        num_wtars: int = functools.reduce(lambda total, item: total + item.wtarFlag, source_files, 0)
        assert (len(source_files) == 1 and num_wtars == 0) or num_wtars == len(source_files)

        retVal += 1
        if num_wtars == 0:
            source_file = source_files[0]
            source_file_full_path = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_file.path)

            # patterns_copy_should_ignore is passed for the sake of completeness but is not being used further down the road in copy_file_to_dir
            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_file_full_path, ".",
                                                                                link_dest=True,
                                                                                ignore=self.patterns_copy_should_ignore)

            self.batch_accum += self.platform_helper.echo(f"copy {source_file_full_path}")

            if  self.mac_current_and_target:
                if not source_file.path.endswith(".symlink"):
                    self.batch_accum += self.platform_helper.chown("$(__USER_ID__)", "", source_file.leaf, recursive=False)
                    self.batch_accum += self.platform_helper.chmod(source_file.chmod_spec(), source_file.name())
                    self.batch_accum += self.platform_helper.echo(f"chmod {source_file.chmod_spec()} {source_file.name()}")

            self.bytes_to_copy += self.calc_size_of_file_item(source_file)
        else:  # one or more wtar files
            # do not increment retVal - unwtar_instructions will add it's own instructions
            first_wtar_item = None
            for source_wtar in source_files:
                self.bytes_to_copy += self.calc_size_of_file_item(source_wtar)
                if source_wtar.is_first_wtar_file():
                    first_wtar_item = source_wtar
            assert first_wtar_item is not None
            first_wtar_full_path = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + first_wtar_item.path)
            self.unwtar_instructions.append((first_wtar_full_path, '.'))
        return retVal

    def create_copy_instructions_for_dir_cont(self, source_path: str, name_for_progress_message: str) -> int:
        retVal: int = 0  # number of essential actions (not progress, remark, ...)
        source_path_abs = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_path)
        source_items = self.info_map_table.get_items_in_dir(dir_path=source_path)

        no_wtar_items = [source_item for source_item in source_items if not source_item.wtarFlag]
        wtar_items = [source_item for source_item in source_items if source_item.wtarFlag]

        if no_wtar_items:
            retVal += 1
            wtar_base_names = {source_item.unwtarred.split("/")[-1] for source_item in wtar_items}
            ignores = self.patterns_copy_should_ignore + list(wtar_base_names)
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(
                                                        source_path_abs,
                                                        ".",
                                                        link_dest=True,
                                                        ignore=ignores,
                                                        preserve_dest_files=True)  # preserve files already in destination

            self.bytes_to_copy += functools.reduce(lambda total, item: total + self.calc_size_of_file_item(item), source_items, 0)

            if  self.mac_current_and_target:
                for source_item in source_items:
                    if source_item.wtarFlag == 0:
                        source_path_relative_to_current_dir = source_item.path_starting_from_dir(source_path)
                        self.batch_accum += self.platform_helper.chown("$(__USER_ID__)", "", ".", recursive=True)
                        self.batch_accum += self.platform_helper.chmod("-R -f a+rw", source_path_relative_to_current_dir)  # all copied files and folders should be rw
                        if source_item.isExecutable():
                            self.batch_accum += self.platform_helper.chmod(source_item.chmod_spec(), source_path_relative_to_current_dir)

        if len(wtar_items) > 0:
            self.unwtar_instructions.append((source_path_abs, '.'))
            self.batch_accum += self.platform_helper.unlock('.', recursive=True)

            # fix permissions for any items that were unwtarred
            # unwtar moved be done with "command-list"
            # if 'Mac' in list(config_vars["__CURRENT_OS_NAMES__"]):
            #    self.batch_accum += self.platform_helper.chmod("-R -f a+rwX", ".")
        return retVal

    def can_copy_be_avoided(self, dir_item: svnTree.SVNRow, source_items: List[svnTree.SVNRow]) -> bool:
        retVal = False
        if "__REPAIR_INSTALLED_ITEMS__" not in self.main_install_targets:
            # look for Info.xml as first choice, Info.plist is seconds choice
            info_item = next((i for i in source_items if i.leaf=="Info.xml"), None) or next((i for i in source_items if i.leaf=="Info.plist"), None)
            if info_item:  # no info item - return False
                destination_folder = config_vars.resolve_str(self.current_destination_folder)
                dir_item_parent, dir_item_leaf = os.path.split(config_vars.resolve_str(dir_item.path))
                info_item_abs_path = os.path.join(destination_folder, dir_item_leaf, info_item.path[len(dir_item.path)+1:])
                retVal = utils.check_file_checksum(info_item_abs_path, info_item.checksum)
        return retVal

    def create_copy_instructions_for_dir(self, source_path: str, name_for_progress_message: str) -> int:
        retVal: int = 0  # number of essential actions (not progress, remark, ...)
        dir_item: svnTree.SVNRow = self.info_map_table.get_dir_item(source_path)
        if dir_item is not None:
            source_items: List[svnTree.SVNRow] = self.info_map_table.get_items_in_dir(dir_path=source_path)
            if self.can_copy_be_avoided(dir_item, source_items):
                self.progress(f"avoid copy of {name_for_progress_message}, Info.xml has not changed")
                return retVal
            retVal += 1
            wtar_base_names = {source_item.unwtarred.split("/")[-1] for source_item in source_items if source_item.wtarFlag}
            ignores = self.patterns_copy_should_ignore + list(wtar_base_names)
            source_path_abs = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_path)
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path_abs, ".",
                                                                               link_dest=True,
                                                                               ignore=ignores)
            self.bytes_to_copy += functools.reduce(lambda total, item: total + self.calc_size_of_file_item(item), source_items, 0)

            source_path_dir, source_path_name = os.path.split(source_path)

            if  self.mac_current_and_target:
                self.batch_accum += self.platform_helper.chown("$(__USER_ID__)", "", source_path_name, recursive=True)
                self.batch_accum += self.platform_helper.chmod("-R -f a+rw", source_path_name)  # all copied files should be rw
                for source_item in source_items:
                    if not source_item.is_wtar_file() and source_item.isExecutable():
                        source_path_relative_to_current_dir = source_item.path_starting_from_dir(source_path_dir)
                        # executable files should also get exec bit
                        self.batch_accum += self.platform_helper.chmod(source_item.chmod_spec(), source_path_relative_to_current_dir)

            if len(wtar_base_names) > 0:
                self.unwtar_instructions.append((source_path_abs, source_path_name))
                self.batch_accum += self.platform_helper.unlock(".", recursive=True)

                # fix permissions for any items that were unwtarred
                # unwtar moved be done with "command-list"
                # if 'Mac' in list(config_vars["__CURRENT_OS_NAMES__"]):
                #    self.batch_accum += self.platform_helper.chmod("-R -f a+rwX", source_path_name)
        else:
            # it might be a dir that was wtarred
            retVal += self.create_copy_instructions_for_file(source_path, name_for_progress_message)
        return retVal

    def create_copy_instructions_for_source(self, source, name_for_progress_message) -> int:
        """ source is a tuple (source_path, tag), where tag is either !file or !dir or !dir_cont'
        """
        retVal = 0
        with BatchAccumulatorTransaction(self.batch_accum, "create_copy_instructions_for_source-"+name_for_progress_message) as source_accum_transaction:
            self.batch_accum += self.platform_helper.progress(f"Copy {name_for_progress_message} ...")
            if source[1] == '!dir':  # !dir
                retVal += self.create_copy_instructions_for_dir(source[0], name_for_progress_message)
            elif source[1] == '!file':  # get a single file
                retVal += self.create_copy_instructions_for_file(source[0], name_for_progress_message)
            elif source[1] == '!dir_cont':  # get all files and folders from a folder
                retVal += self.create_copy_instructions_for_dir_cont(source[0], name_for_progress_message)
            else:
                raise ValueError("unknown source type "+source[1]+" for "+source[0])
            source_accum_transaction += retVal
        return retVal

    # special handling when running on Mac OS
    def pre_copy_mac_handling(self) -> None:
        num_files_to_set_exec = self.info_map_table.num_items(item_filter="required-exec")
        if num_files_to_set_exec > 0:
            self.batch_accum += self.platform_helper.pushd("$(COPY_SOURCES_ROOT_DIR)")
            have_info_path = config_vars["REQUIRED_INFO_MAP_PATH"].str()
            self.batch_accum += self.platform_helper.set_exec_for_folder(have_info_path)
            self.platform_helper.num_items_for_progress_report += num_files_to_set_exec
            self.batch_accum += self.platform_helper.new_line()
            self.batch_accum += self.platform_helper.popd()

    # Todo: move function to a better location
    def pre_resolve_path(self, path_to_resolve) -> str:
        """ for some paths we cannot wait for resolution in the batch file"""
        resolved_path = config_vars.resolve_str(path_to_resolve)
        try:
            resolved_path = str(pathlib.Path(resolved_path).resolve())
        except:
            pass
        return resolved_path

    def create_copy_instructions_for_target_folder(self, target_folder_path) -> None:
        with BatchAccumulatorTransaction(self.batch_accum, "create_copy_instructions_for_target_folder-"+target_folder_path) as folder_accum_transaction:
            self.current_destination_folder = target_folder_path
            self.unwtar_instructions = list()
            num_items_copied_to_folder = 0
            items_in_folder = sorted(self.all_iids_by_target_folder[target_folder_path])
            self.batch_accum += self.platform_helper.new_line()
            self.batch_accum += self.platform_helper.remark(f"- Begin folder {target_folder_path}")
            self.batch_accum += self.platform_helper.progress(f"copy to {target_folder_path} ...")
            self.batch_accum += self.platform_helper.cd(target_folder_path)

            # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
            folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('pre_copy_to_folder', items_in_folder)

            num_symlink_items: int = 0
            batch_accum_len_before = len(self.batch_accum)
            self.batch_accum += self.platform_helper.copy_tool.begin_copy_folder()
            for IID in items_in_folder:
                self.current_iid = IID
                self.batch_accum += self.platform_helper.remark(f"-- Begin iid {IID}")
                sources_for_iid = self.items_table.get_sources_for_iid(IID)
                resolved_sources_for_iid = [(config_vars.resolve_str(s[0]), s[1]) for s in sources_for_iid]
                name_and_version = self.name_and_version_for_iid(iid=IID)
                for source in resolved_sources_for_iid:
                    self.batch_accum += self.platform_helper.remark(f"--- Begin source {source[0]}")
                    num_items_copied_to_folder += 1
                    self.batch_accum += self.items_table.get_resolved_details_value_for_active_iid(iid=IID, detail_name="pre_copy_item")
                    folder_accum_transaction += self.create_copy_instructions_for_source(source, name_and_version)
                    self.batch_accum += self.items_table.get_resolved_details_value_for_active_iid(iid=IID, detail_name="post_copy_item")
                    self.batch_accum += self.platform_helper.remark(f"--- End source {source[0]}")
                    if  self.mac_current_and_target:
                        num_symlink_items += self.info_map_table.count_symlinks_in_dir(source[0])
                self.batch_accum += self.platform_helper.remark(f"-- End iid {IID}")
            self.current_iid = None

            target_folder_path_parent, target_folder_name = os.path.split(config_vars.resolve_str(target_folder_path))
            self.create_unwtar_batch_file(self.unwtar_instructions, target_folder_name)
            self.unwtar_instructions = None
            self.batch_accum += self.platform_helper.copy_tool.end_copy_folder()

            # only if items were actually copied there's need to (Mac only) resolve symlinks
            if  self.mac_current_and_target:
                if num_items_copied_to_folder > 0 and num_symlink_items > 0:
                    self.batch_accum += self.platform_helper.progress("Resolve symlinks ...")
                    self.batch_accum += self.platform_helper.resolve_symlink_files()

            # accumulate post_copy_to_folder actions from all items, eliminating duplicates
            folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('post_copy_to_folder', items_in_folder)
            self.batch_accum += self.platform_helper.remark(f"- End folder {target_folder_path}")
            self.current_destination_folder = None

    def create_copy_instructions_for_no_copy_folder(self, sync_folder_name) -> None:
        """ Instructions for sources that do not need copying
            These are sources that do not have 'install_folder' section OR those with os_is_active
            'direct_sync' section.
        """
        with BatchAccumulatorTransaction(self.batch_accum, "create_copy_instructions_for_no_copy_folder-"+sync_folder_name) as folder_accum_transaction:

            items_in_folder = self.no_copy_iids_by_sync_folder[sync_folder_name]
            self.batch_accum += self.platform_helper.new_line()
            self.batch_accum += self.platform_helper.cd(sync_folder_name)
            self.batch_accum += self.platform_helper.progress(f"Actions in {sync_folder_name} ...")

            # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
            folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('pre_copy_to_folder', items_in_folder)

            num_wtars: int = 0
            for IID in sorted(items_in_folder):
                sources_from_db = self.items_table.get_sources_for_iid(IID)
                for source_from_db in sources_from_db:
                    source = source_from_db[0]
                    num_wtars += self.info_map_table.count_wtar_items_of_dir(source[0])
                pre_copy_item_from_db = config_vars.resolve_list_to_list(self.items_table.get_resolved_details_for_active_iid(IID, "pre_copy_item"))
                self.batch_accum += pre_copy_item_from_db
                folder_accum_transaction += len(pre_copy_item_from_db)
                post_copy_item_from_db = config_vars.resolve_list_to_list(self.items_table.get_resolved_details_for_active_iid(IID, "post_copy_item"))
                self.batch_accum += post_copy_item_from_db
                folder_accum_transaction += len(post_copy_item_from_db)

            if num_wtars > 0:
                self.batch_accum += self.platform_helper.unwtar_something(sync_folder_name, no_artifacts=False, where_to_unwtar='.')
                folder_accum_transaction += 1

            # accumulate post_copy_to_folder actions from all items, eliminating duplicates
            folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('post_copy_to_folder', items_in_folder)

    def create_unwtar_batch_file(self, wtar_instructions, name_for_progress) -> None:
        if wtar_instructions:
            main_out_file_dir, main_out_file_leaf = os.path.split(config_vars["__MAIN_OUT_FILE__"].str())
            unwtar_batch_files_dir = os.path.join(main_out_file_dir, "unwtar")
            os.makedirs(unwtar_batch_files_dir, exist_ok=True)
            batch_file_path = os.path.join(unwtar_batch_files_dir, name_for_progress+"_"+str(self.unwtar_batch_file_counter)+".unwtar")
            self.unwtar_batch_file_counter += 1
            batch_file_path = config_vars.resolve_str(batch_file_path)
            with utils.utf8_open(batch_file_path, "w") as wfd:
                for wtar_inst in self.unwtar_instructions:
                    unwtar_line = config_vars.resolve_str(f"""unwtar --in "{wtar_inst[0]}" --out "{wtar_inst[1]}" --no-numbers-progress\n""")
                    self.platform_helper.increment_progress()
                    wfd.write(unwtar_line)
            self.batch_accum += self.platform_helper.progress(f"Verify {name_for_progress}")
            self.batch_accum += self.platform_helper.run_instl_command_list(batch_file_path, parallel=True)
