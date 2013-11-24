#!/usr/bin/env python2.7
from __future__ import print_function
import logging

import pyinstl.log_utils
from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *
from pyinstl import svnTree
from instlInstanceSyncBase import InstlInstanceSync


class InstlInstanceSync_url(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """
    @func_log_wrapper
    def __init__(self, instlInstance):
        self.instlInstance = instlInstance
        self.remote_info_map = svnTree.SVNTree()
        self.target_os_remote_info_map = None
        self.need_map = svnTree.SVNTree()
        self.target_os_need_map = None
        self.have_map = svnTree.SVNTree()
        self.have_map_path = None
        self.new_have_map_path = None

    @func_log_wrapper
    def init_sync_vars(self):
        var_description = "from InstlInstanceBase.init_sync_vars"
        if "SYNC_BASE_URL" not in self.instlInstance.cvl:
            raise ValueError("'SYNC_BASE_URL' was not defined")
        if "GET_URL_CLIENT_PATH" not in self.instlInstance.cvl:
            raise ValueError("'GET_URL_CLIENT_PATH' was not defined")
        get_url_client_full_path = self.instlInstance.search_paths_helper.find_file_with_search_paths(self.instlInstance.cvl.get_str("GET_URL_CLIENT_PATH"))
        self.instlInstance.cvl.set_variable("GET_URL_CLIENT_PATH", var_description).append(get_url_client_full_path)

        if "REPO_REV" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("REPO_REV", var_description).append("HEAD")
        if "BASE_SRC_URL" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("BASE_SRC_URL", var_description).append("$(SYNC_BASE_URL)/$(TARGET_OS)")

        if "LOCAL_SYNC_DIR" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("LOCAL_SYNC_DIR", var_description).append(
                self.instlInstance.get_default_sync_dir())

        if "BOOKKEEPING_DIR_URL" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("BOOKKEEPING_DIR_URL").append("$(SYNC_BASE_URL)/instl")
        bookkeeping_relative_path = relative_url(self.instlInstance.cvl.get_str("SYNC_BASE_URL"), self.instlInstance.cvl.get_str("BOOKKEEPING_DIR_URL"))
        self.instlInstance.cvl.set_variable("REL_BOOKKIPING_PATH", var_description).append(bookkeeping_relative_path)

        rel_sources = relative_url(self.instlInstance.cvl.get_str("SYNC_BASE_URL"), self.instlInstance.cvl.get_str("BASE_SRC_URL"))
        self.instlInstance.cvl.set_variable("REL_SRC_PATH", var_description).append(rel_sources)

        if "INFO_MAP_FILE_URL" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("INFO_MAP_FILE_URL").append("$(SYNC_BASE_URL)/$(REPO_REV)/instl/info_map.txt")

        if "LOCAL_BOOKKEEPING_PATH" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("LOCAL_BOOKKEEPING_PATH").append("$(LOCAL_SYNC_DIR)/bookkeeping")

        for identifier in ("SYNC_BASE_URL", "GET_URL_CLIENT_PATH", "REL_SRC_PATH", "REPO_REV", "BASE_SRC_URL", "BOOKKEEPING_DIR_URL"):
            logging.debug("... %s: %s", identifier, self.instlInstance.cvl.get_str(identifier))

    @func_log_wrapper
    def read_remote_info_map(self):
        safe_makedirs(self.instlInstance.cvl.get_str("LOCAL_BOOKKEEPING_PATH"))
        info_map_path = os.path.join(self.instlInstance.cvl.get_str("LOCAL_BOOKKEEPING_PATH"), self.instlInstance.cvl.get_str("REPO_REV"))
        safe_makedirs(info_map_path)
        info_map_path = os.path.join(info_map_path, "info_map.txt")
        download_from_file_or_url(self.instlInstance.cvl.get_str("INFO_MAP_FILE_URL"), info_map_path)
        self.remote_info_map.read_from_file(info_map_path, format="text")
        self.target_os_remote_info_map = self.remote_info_map.get_sub(self.instlInstance.cvl.get_str("TARGET_OS"))

    @func_log_wrapper
    def create_sync_instructions(self, installState):
        self.installState = installState
        self.read_remote_info_map()
        self.target_os_need_map = self.need_map.add_sub(self.target_os_remote_info_map.name(), self.target_os_remote_info_map.flags(), self.target_os_remote_info_map.last_rev())
        self.create_need_list()
        #for iid in self.installState.orphan_install_items:
        #    self.installState.append_instructions('sync', self.instlInstance.create_echo_command("Don't know how to sync "+iid))
        #self.need_list_to_ought()
        #self.ought_and_have_to_sync()
        #self.create_download_instructions()
        #logging.info("... %s", out_file)
        need_map_path = os.path.join(self.instlInstance.cvl.get_str("LOCAL_BOOKKEEPING_PATH"), "need_info_map.txt")
        self.need_map.write_to_file(need_map_path, in_format="text", report_level=1)
        self.create_download_instructions()
        self.have_map_path = os.path.join(self.instlInstance.cvl.get_str("LOCAL_BOOKKEEPING_PATH"), "have_info_map.txt")
        if os.path.isfile(self.have_map_path):
            self.have_map.read_from_file(self.have_map_path, format="text")
        self.new_have_map_path = os.path.join(self.instlInstance.cvl.get_str("LOCAL_BOOKKEEPING_PATH"), "new_have_info_map.txt")
        if os.path.isfile(self.new_have_map_path):
            os.remove(self.new_have_map_path)
        self.merge_need_and_have()
        self.clean_uneeded_items()

    @func_log_wrapper
    def clean_uneeded_items(self):
        self.need_map.recursive_remove_depth_first()

    @func_log_wrapper
    def merge_need_and_have(self):
        for need_item in self.need_map.walk_items(what="file"):
            have_item = self.have_map.get_sub(need_item[0])
            if have_item is None:   # not found in have map
                 self.have_map.add_sub(*need_item)
            else:                    # found in have map
                if have_item.last_rev() == need_item[2]:
                    self.need_map.user_data = False
                elif have.last_rev() < need_item[2]:
                    have_item.set_flags(need_item[1])
                    have_item.set_last_rev(need_item[2])
                    self.need_map.user_data = True
                elif have.last_rev() > need_item[2]: # weird, but need to get the older version
                    have_item.set_flags(need_item[1])
                    have_item.set_last_rev(need_item[2])
                    self.need_map.user_data = True

    @func_log_wrapper
    def create_need_list(self):
        for iid  in self.installState.full_install_items:
            installi = self.instlInstance.install_definitions_index[iid]
            if installi.source_list():
                for source in installi.source_list():
                    self.create_need_list_for_source(source)

    @func_log_wrapper
    def create_need_list_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        _sub = self.target_os_remote_info_map.get_sub(source[0])
        if source[1] == '!file':
            if _sub.isFile():
                self.target_os_need_map.add_sub(source[0], _sub.flags(), _sub.last_rev())
        if source[1] == '!files':
            if _sub.isDir():
                for _sub_file in _sub.values():
                    if _sub_file.isFile():
                        self.target_os_need_map.add_sub((source[0], _sub_file), _sub_file.flags(), _sub_file.last_rev())
        if source[1] == '!dir':
            self.target_os_need_map.add_sub_tree_recursive(source[0].split("/")[:-1], _sub)
        if source[1] == '!dir_cont':
            self.target_os_need_map.add_sub_tree_recursive(source[0].split("/")[:-1], _sub)

    def download_info_map(self):
        """$(SYNC_BASE_URL)/instl/info_map.txt"""
        pass

    def need_list_to_ought(self):
        pass

    def ought_and_have_to_sync(self):
        pass

    def create_download_instructions(self):
        num_files = self.need_map.num_subs_in_tree(what="file")
        self.num_items_for_progress_report = num_files + 1 # one for a dummy first item
        self.current_item_for_progress_report = 0
        self.installState.append_instructions('sync', self.instlInstance.platform_helper.create_echo_command("Progress: synced {self.current_item_for_progress_report} of {self.num_items_for_progress_report}; from $(BASE_SRC_URL)".format(**locals())))
        self.current_item_for_progress_report += 1
        self.installState.extend_instructions('sync', self.instlInstance.platform_helper.make_directory_cmd("$(LOCAL_SYNC_DIR)"))
        self.installState.extend_instructions('sync', self.instlInstance.platform_helper.change_directory_cmd("$(LOCAL_SYNC_DIR)"))
        self.installState.indent_level += 1
        for need_item in self.need_map.values():
            self.create_download_instructions_for_item(need_item)
        self.installState.indent_level -= 1
        self.installState.append_instructions('sync', self.instlInstance.platform_helper.create_echo_command("Progress: synced {self.current_item_for_progress_report} of {self.num_items_for_progress_report};  from $(BASE_SRC_URL)".format(**locals())))


    def create_download_instructions_for_item(self, item, path_so_far = list()):
        if item.isFile():
            source_url =   '/'.join( ["$(SYNC_BASE_URL)", str(item.last_rev())] + path_so_far + [item.name()] )
            self.installState.extend_instructions('sync', self.instlInstance.platform_helper.dl_tool.create_download_file_to_file_command(source_url, item.name()))
            self.installState.append_instructions('sync', self.instlInstance.platform_helper.create_echo_command("Progress: synced {self.current_item_for_progress_report} of {self.num_items_for_progress_report};".format(**locals())))
            self.current_item_for_progress_report += 1
        elif item.isDir():
            path_so_far.append(item.name())
            self.installState.extend_instructions('sync', self.instlInstance.platform_helper.make_directory_cmd(item.name()))
            self.installState.extend_instructions('sync', self.instlInstance.platform_helper.change_directory_cmd(item.name()))
            self.installState.indent_level += 1
            for sub_item in item.values():
                self.create_download_instructions_for_item(sub_item, path_so_far)
            self.installState.indent_level -= 1
            self.installState.extend_instructions('sync', self.instlInstance.platform_helper.change_directory_cmd(".."))
            path_so_far.pop()
