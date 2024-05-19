#!/usr/bin/env python3.9


import sys
import os
from pathlib import Path
import utils
import functools
from typing import Dict, List, Optional
import logging
log = logging.getLogger()

from configVar import config_vars
from .instlClient import InstlClient
import svnTree
from pybatch import *


class InstlClientCopy(InstlClient):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.read_defaults_file(super().__thisclass__.__name__)
        self.unwtar_batch_file_counter: int = 0
        self.current_destination_folder: Optional[str] = None
        self.current_iid:  Optional[str] = None
        self.avoid_copy_markers = None
        self.calc_user_cache_dir_var()

    def do_copy(self) -> None:
        self.init_copy_vars()

        self.create_copy_instructions()

    def init_copy_vars(self) -> None:
        self.action_type_to_progress_message.update({'pre_copy': "pre-install step",
                                                'post_copy': "post-install step",
                                                'pre_copy_to_folder': "pre-copy step",
                                                'post_copy_to_folder': "post-copy step"})
        self.bytes_to_copy = 0
        # ratio between wtar file and it's uncompressed contents
        self.wtar_ratio = float(config_vars.get("WTAR_RATIO", "1.3"))

        # when running on MacOS AND installation targets MacOS some special cases need to be considered
        self.mac_current_and_target = 'Mac' in list(config_vars["__CURRENT_OS_NAMES__"]) and 'Mac' in list(config_vars["TARGET_OS"])
        self.win_current_and_target = 'Win' in list(config_vars["__CURRENT_OS_NAMES__"]) and 'Win' in list(config_vars["TARGET_OS"])

    def write_copy_debug_info(self) -> None:
        try:
            if config_vars.defined('ECHO_LOG_FILE'):
                log_file_path = config_vars["ECHO_LOG_FILE"].str()
                log_folder, log_file = os.path.split(log_file_path)
                with utils.utf8_open_for_write(os.path.join(log_folder, "sync-folder-manifest.txt"), "w") as wfd:
                    repo_sync_dir = config_vars["COPY_SOURCES_ROOT_DIR"].str()
                    wfd.write(utils.disk_item_listing(repo_sync_dir))
        except Exception:
            pass  # if it did not work - forget it

    def create_create_folders_instructions(self, folder_list: List[str]) -> None:
        with self.batch_accum.sub_accum(Stage("create folders")) as create_folders_section:
            kwargs_defaults = {'remove_obstacles': True, 'chowner': False, 'recursive_chmod': False}
            third_party_folders = [utils.ExpandAndResolvePath(config_vars.resolve_str(os.fspath(p))) for p in config_vars.get("THIRD_PARTY_FOLDERS", []).list()]
            for target_folder_path in folder_list:
                target_folder_path = utils.ExpandAndResolvePath(config_vars.resolve_str(os.fspath(target_folder_path)))
                our_folder = next((False for p in third_party_folders if p == target_folder_path), True)
                create_folders_section += MakeDir(target_folder_path, chowner=our_folder, recursive_chmod=False)

    def create_copy_instructions(self) -> None:
        self.progress("create copy instructions ...")
        # If we got here while in synccopy command, there is no need to read the info map again.
        # If we got here while in copy command, read HAVE_INFO_MAP_COPY_PATH which defaults to NEW_HAVE_INFO_MAP_PATH.
        # Copy might be called after the sync batch file was created but before it was executed
        if len(self.info_map_table.files_read_list) == 0:
            have_info_path = os.fspath(config_vars["HAVE_INFO_MAP_COPY_PATH"])
            self.info_map_table.read_from_file(have_info_path, disable_indexes_during_read=True)

        self.avoid_copy_markers = list(config_vars.get('AVOID_COPY_MARKERS', []))

        # copy and actions instructions for sources
        self.batch_accum.set_current_section('copy')
        self.batch_accum += self.create_sync_folder_manifest_command("before-copy", back_ground=True)
        self.batch_accum += Progress("Start copy from $(COPY_SOURCES_ROOT_DIR)")

        sorted_target_folder_list = sorted(self.all_iids_by_target_folder,
                                           key=lambda fold: config_vars.resolve_str(fold))

        # first create all target folders so to avoid dependency order problems such as creating links between folders
        self.create_create_folders_instructions(sorted_target_folder_list)

        self.batch_accum += self.accumulate_unique_actions_for_active_iids('pre_copy')

        if self.mac_current_and_target:
            self.pre_copy_mac_handling()

        remove_previous_sources = bool(config_vars.get("REMOVE_PREVIOUS_SOURCES",True))
        for target_folder_path in sorted_target_folder_list:
            if remove_previous_sources:
                with self.batch_accum.sub_accum(Stage("remove_previous_sources_instructions_for_target_folder", target_folder_path)) as seb_sec:
                    seb_sec += self.create_remove_previous_sources_instructions_for_target_folder(target_folder_path)
            self.create_copy_instructions_for_target_folder(target_folder_path)

        # actions instructions for sources that do not need copying, here folder_name is the sync folder
        for sync_folder_name in sorted(self.no_copy_iids_by_sync_folder.keys()):
            with self.batch_accum.sub_accum(CdStage("create_copy_instructions_for_no_copy_folder", sync_folder_name)) as folder_accum:
                folder_accum += self.create_copy_instructions_for_no_copy_folder(sync_folder_name)

        self.progress(self.bytes_to_copy, "bytes to copy")

        self.batch_accum += self.accumulate_unique_actions_for_active_iids('post_copy')

        self.batch_accum.set_current_section('post-copy')
        # Copy have_info file to "site" (e.g. /Library/Application support/... or c:\ProgramData\...)
        # for reference. But when preparing offline installers the site location is the same as the sync location
        # so copy should be avoided.
        if os.fspath(config_vars["HAVE_INFO_MAP_PATH"]) != os.fspath(config_vars["SITE_HAVE_INFO_MAP_PATH"]):
            self.batch_accum += MakeDir("$(SITE_REPO_BOOKKEEPING_DIR)", chowner=True)
            self.batch_accum += CopyFileToFile("$(HAVE_INFO_MAP_PATH)", "$(SITE_HAVE_INFO_MAP_PATH)", hard_links=False, copy_owner=True)

        self.create_require_file_instructions()

        # messages about orphan iids
        for iid in sorted(list(config_vars["__ORPHAN_INSTALL_TARGETS__"])):
            self.batch_accum += Echo(f"Don't know how to install {iid}")
        self.batch_accum += Progress("Done copy")
        self.progress("create copy instructions done")
        self.progress("")

    def calc_size_of_file_item(self, a_file_item: svnTree.SVNRow) -> int:
        """ for use with builtin function reduce to calculate the unwtarred size of a file """
        if a_file_item.is_wtar_file():
            item_size = int(float(a_file_item.size) * self.wtar_ratio)
        else:
            item_size = a_file_item.size
        return item_size

    def create_copy_instructions_for_file(self, source_path: str, name_for_progress_message: str, use_hard_links=True) -> PythonBatchCommandBase:
        retVal = AnonymousAccum()
        source_files = self.info_map_table.get_required_for_file(source_path)
        if not source_files:
            log.warning(f"""no source files for {source_path}""")
            return retVal
        num_wtars: int = functools.reduce(lambda total, item: total + item.wtarFlag, source_files, 0)
        assert (len(source_files) == 1 and num_wtars == 0) or num_wtars == len(source_files)

        if num_wtars == 0:
            source_file = source_files[0]
            source_file_full_path = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_file.path)

            retVal += CopyFileToDir(source_file_full_path, os.curdir, hard_links=use_hard_links)

            if  self.mac_current_and_target:
                if not source_file.path.endswith(".symlink"):
                    retVal += ChmodAndChown(path=source_file.name(), mode=source_file.chmod_spec(), user_id=int(config_vars.get("ACTING_UID", -1)), group_id=int(config_vars.get("ACTING_GID", -1)), recursive=False)

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
            retVal += Unwtar(first_wtar_full_path, os.curdir)
        return retVal

    def create_copy_instructions_for_dir_cont(self, source_path: str, name_for_progress_message: str, use_hard_links=True) -> PythonBatchCommandBase:
        retVal = AnonymousAccum()
        source_path_abs = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_path)
        source_items = self.info_map_table.get_items_in_dir(dir_path=source_path)

        no_wtar_items = [source_item for source_item in source_items if not source_item.wtarFlag]
        wtar_items = [source_item for source_item in source_items if source_item.wtarFlag]

        if no_wtar_items:
            retVal += CopyDirContentsToDir(
                                                        source_path_abs,
                                                        os.curdir,
                                                        hard_links=use_hard_links,
                                                        preserve_dest_files=True)  # preserve files already in destination

            self.bytes_to_copy += functools.reduce(lambda total, item: total + self.calc_size_of_file_item(item), source_items, 0)

            if self.mac_current_and_target:
                for source_item in source_items:
                    if source_item.wtarFlag == 0:
                        source_path_relative_to_current_dir = source_item.path_starting_from_dir(source_path)
                        retVal += ChmodAndChown(path=source_path_relative_to_current_dir, mode="a+rw", user_id=int(config_vars.get("ACTING_UID", -1)), group_id=int(config_vars.get("ACTING_GID", -1)), recursive=True, ignore_all_errors=True) # all copied files and folders should be rw
                        if source_item.isExecutable():
                            retVal += Chmod(source_path_relative_to_current_dir, source_item.chmod_spec(), recursive=True, ignore_all_errors=True)

        if len(wtar_items) > 0:
            retVal += Unwtar(source_path_abs, os.pardir)  # to parent otherwise unwtar will create a folder inside the current folder, e.g. Utilities/Utilities. This issue is unique to !dir_cont

        return retVal

    def create_copy_instructions_for_dir_extended(self, source_path: str, name_for_progress_message: str, use_hard_links=True) -> PythonBatchCommandBase:
        dir_item: svnTree.SVNRow = self.info_map_table.get_dir_item(source_path)
        if dir_item is not None:
            retVal = AnonymousAccum()
            source_items: List[svnTree.SVNRow] = self.info_map_table.get_items_in_dir(dir_path=source_path)
            has_wtars = any(source_item.wtarFlag for source_item in source_items)
            source_path_abs = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_path)
            self.bytes_to_copy += functools.reduce(lambda total, item: total + self.calc_size_of_file_item(item), source_items, 0)

            source_path_dir, source_path_name = os.path.split(source_path)

            # if self.mac_current_and_target:
            #     retVal += ChmodAndChown(path=source_path_name, mode="a+rw", user_id="$(ACTING_UID)", group_id="$(ACTING_GID)", recursive=True, ignore_all_errors=True) # all copied files and folders should be rw
            #     for source_item in source_items:
            #         if not source_item.is_wtar_file() and source_item.isExecutable():
            #             source_path_relative_to_current_dir = source_item.path_starting_from_dir(source_path_dir)
            #             # executable files should also get exec bit
            #             retVal += Chmod(source_path_relative_to_current_dir, source_item.chmod_spec())
            #
            # if has_wtars:
            #     retVal += Unwtar(source_path_abs, os.curdir)

            retVal += CopyBundle(source_path_abs, os.curdir, unwtar=has_wtars)
        else:
            # it might be a dir that was wtarred
            retVal = self.create_copy_instructions_for_file(source_path, name_for_progress_message, use_hard_links)
        return retVal

    def create_copy_instructions_for_dir(self, source_path: str,
                                                name_for_progress_message: str,
                                                use_hard_links=True,
                                                dont_downgrade=False) -> PythonBatchCommandBase:
        dir_item: svnTree.SVNRow = self.info_map_table.get_dir_item(source_path)
        if dir_item is not None:
            retVal = AnonymousAccum()
            source_items: List[svnTree.SVNRow] = self.info_map_table.get_items_in_dir(dir_path=source_path)
            has_wtars = any(source_item.wtarFlag for source_item in source_items)
            source_path_abs = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_path)
            retVal += CopyDirToDir(source_path_abs,
                                   os.curdir,
                                   hard_links=use_hard_links,
                                   delete_extraneous_files=True,
                                   dont_downgrade=dont_downgrade)
            self.bytes_to_copy += functools.reduce(lambda total, item: total + self.calc_size_of_file_item(item), source_items, 0)

            source_path_dir, source_path_name = os.path.split(source_path)

            if self.mac_current_and_target:
                for source_item in source_items:
                    if not source_item.is_wtar_file() and source_item.isExecutable():
                        source_path_relative_to_current_dir = source_item.path_starting_from_dir(source_path_dir)
                        # executable files should also get exec bit
                        retVal += Chmod(source_path_relative_to_current_dir, source_item.chmod_spec())

            if has_wtars > 0:
                retVal += Unwtar(source_path_abs, os.curdir)

            # change ownership on destination folder + currently copied folder name (e.g: /Applications/Waves/Plug-Ins V11/XXX.bundle/, /Applications/Waves/YYY.framework)
            if self.mac_current_and_target:
                target_folder = Path(config_vars.resolve_str(self.current_destination_folder), source_path_name).resolve() #initialized in create_copy_instructions_for_target_folder
                retVal += Chown(path=target_folder,
                                user_id=int(config_vars.get("ACTING_UID", -1)),
                                group_id=int(config_vars.get("ACTING_GID", -1)), recursive=True)
        else:
            # it might be a dir that was wtarred
            retVal = self.create_copy_instructions_for_file(source_path, name_for_progress_message)
        return retVal

    def create_copy_instructions_for_source(self, source,
                                                name_for_progress_message,
                                                use_hard_links=True,
                                                dont_downgrade=False) -> PythonBatchCommandBase:
        """ source is a tuple (source_path, tag), where tag is either !file or !dir or !dir_cont'
        """
        retVal = None
        if source[1] == '!dir':  # !dir
            retVal = self.create_copy_instructions_for_dir(source[0], name_for_progress_message, use_hard_links, dont_downgrade)
        elif source[1] == '!file':  # get a single file
            retVal = self.create_copy_instructions_for_file(source[0], name_for_progress_message, use_hard_links)
        elif source[1] == '!dir_cont':  # get all files and folders from a folder
            retVal = self.create_copy_instructions_for_dir_cont(source[0], name_for_progress_message, use_hard_links)
        else:
            raise ValueError(f"unknown source type {source[1]} for {source[0]}")
        return retVal

    # special handling when running on Mac OS
    def pre_copy_mac_handling(self) -> None:
        num_files_to_set_exec = self.info_map_table.num_items(item_filter="required-exec")
        if num_files_to_set_exec > 0:
            with self.batch_accum.sub_accum(CdStage("SetExecPermissionsInSyncFolder", "$(COPY_SOURCES_ROOT_DIR)")) as sub_bc:
                sub_bc += SetExecPermissionsInSyncFolder()

    # Todo: move function to a better location
    def pre_resolve_path(self, path_to_resolve) -> str:
        """ for some paths we cannot wait for resolution in the batch file"""
        resolved_path = config_vars.resolve_str(path_to_resolve)
        try:
            resolved_path = str(Path(resolved_path).resolve())
        except:
            pass
        return resolved_path

    def should_copy_source(self, source, target_folder_path):
        retVal = True
        reason_not_to_copy = None
        if not self.update_mode:
            top_src = config_vars["COPY_SOURCES_ROOT_DIR"].Path(resolve=True).joinpath(source[0])
            top_trg = Path(config_vars.resolve_str(target_folder_path), top_src.name)
            if top_trg.exists():
                if source[1] == "!dir":
                    trg = top_trg.joinpath("Contents")
                    if trg.exists():
                         # try to Info.xml or Info.plist under contents
                        src = top_src.joinpath("Contents")
                        for avoid_copy_marker in self.avoid_copy_markers:
                            src_marker = src.joinpath(avoid_copy_marker)
                            dst_marker = trg.joinpath(avoid_copy_marker)
                            same_checksums = utils.compare_files_by_checksum(dst_marker, src_marker)
                            if same_checksums:
                                reason_not_to_copy = f"same checksum Contents/{avoid_copy_marker}"
                                retVal = False
                                break
                    else:
                        # try to Info.xml or Info.plist at top level
                        for avoid_copy_marker in self.avoid_copy_markers:
                            src_marker = top_src.joinpath(avoid_copy_marker)
                            dst_marker = top_trg.joinpath(avoid_copy_marker)
                            same_checksums = utils.compare_files_by_checksum(dst_marker, src_marker)
                            if same_checksums:
                                reason_not_to_copy = f"same checksum {avoid_copy_marker} in top level"
                                retVal = False
                                break
                elif source[1] == "!file":
                    try:
                        if top_src.stat().st_ino == top_trg.stat().st_ino:
                            retVal = False
                            reason_not_to_copy = f"same inode"
                    except:
                        pass
        return retVal, reason_not_to_copy

    def create_copy_instructions_for_target_folder(self, target_folder_path) -> None:
        with self.batch_accum.sub_accum(CdStage("copy_to_folder", target_folder_path)) as copy_to_folder_accum:
            self.current_destination_folder = target_folder_path
            num_items_copied_to_folder = 0
            items_in_folder = sorted(self.all_iids_by_target_folder[target_folder_path])

            # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
            copy_to_folder_accum += self.accumulate_unique_actions_for_active_iids('pre_copy_to_folder', items_in_folder)

            num_symlink_items: int = 0
            for IID in items_in_folder:
                name_and_version = self.name_and_version_for_iid(iid=IID)
                with copy_to_folder_accum.sub_accum(Stage("copy", name_and_version)) as iid_accum:
                    self.current_iid = IID
                    sources_for_iid = self.items_table.get_sources_for_iid(IID)
                    resolved_sources_for_iid = [(config_vars.resolve_str(s[0]), s[1]) for s in sources_for_iid]
                    flags_for_iid = config_vars.resolve_list_to_list([flags[1] for flags in self.items_table.get_iids_and_details_for_active_iids("flags", unique_values=False, limit_to_iids=[IID])])
                    use_hard_links = 'no_hard_links' not in flags_for_iid
                    dont_downgrade = 'dont_downgrade' in flags_for_iid
                    for source in resolved_sources_for_iid:
                        self.progress(f"create copy instructions of {source[0]} to {config_vars.resolve_str(target_folder_path)}")
                        with iid_accum.sub_accum(Stage("copy source", source[0])) as source_accum:
                            num_items_copied_to_folder += 1
                            source_accum += self.accumulate_actions_for_iid(iid=IID, detail_name="pre_copy_item")
                            source_accum += self.create_copy_instructions_for_source(source, name_and_version, use_hard_links=use_hard_links, dont_downgrade=dont_downgrade)
                            source_accum += self.accumulate_actions_for_iid(iid=IID, detail_name="post_copy_item")
                            if self.mac_current_and_target:
                                num_symlink_items += self.info_map_table.count_symlinks_in_dir(source[0])
            self.current_iid = None

            # only if items were actually copied there's need to (Mac only) resolve symlinks
            if  self.mac_current_and_target:
                if num_items_copied_to_folder > 0 and num_symlink_items > 0:
                    copy_to_folder_accum += ResolveSymlinkFilesInFolder(target_folder_path, own_progress_count=num_symlink_items)

            # accumulate post_copy_to_folder actions from all items, eliminating duplicates
            if copy_to_folder_accum.is_essential():
                copy_to_folder_accum += self.accumulate_unique_actions_for_active_iids('post_copy_to_folder', items_in_folder)
            self.current_destination_folder = None

    def create_copy_instructions_for_no_copy_folder(self, sync_folder_name) -> PythonBatchCommandBase:
        """ Instructions for sources that do not need copying
            These are sources that do not have 'install_folder' section OR those with os_is_active
            'direct_sync' section.
        """
        retVal = AnonymousAccum()
        items_in_folder = self.no_copy_iids_by_sync_folder[sync_folder_name]

        # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
        retVal += self.accumulate_unique_actions_for_active_iids('pre_copy_to_folder', items_in_folder)

        num_wtars: int = 0
        for IID in sorted(items_in_folder):
            sources_from_db = self.items_table.get_sources_for_iid(IID)
            for source_from_db in sources_from_db:
                source = source_from_db[0]
                num_wtars += self.info_map_table.count_wtar_items_of_dir(source[0])
            pre_copy_item_from_db = config_vars.resolve_list_to_list(self.items_table.get_resolved_details_for_active_iid(IID, "pre_copy_item"))
            retVal += pre_copy_item_from_db
            post_copy_item_from_db = config_vars.resolve_list_to_list(self.items_table.get_resolved_details_for_active_iid(IID, "post_copy_item"))
            retVal += post_copy_item_from_db

        if num_wtars > 0:
            retVal += Unwtar(sync_folder_name, os.curdir, no_artifacts=False)

        # accumulate post_copy_to_folder actions from all items, eliminating duplicates
        post_copy_to_folder_from_db = self.accumulate_unique_actions_for_active_iids('post_copy_to_folder', items_in_folder)
        retVal += post_copy_to_folder_from_db
        return retVal
