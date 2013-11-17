#!/usr/bin/env python2.7
from __future__ import print_function
import logging

import pyinstl.log_utils
from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *
from pysvnsrv import svnTree
from instlInstanceSyncBase import InstlInstanceSync


class InstlInstanceSync_url(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """
    @func_log_wrapper
    def __init__(self, instlInstance):
        self.instlInstance = instlInstance
        self.need_map = svnTree.SVNTree()

    @func_log_wrapper
    def init_sync_vars(self):
        var_description = "from InstlInstanceBase.init_sync_vars"
        if "STAT_LINK_REPO_URL" not in self.instlInstance.cvl:
            raise ValueError("'STAT_LINK_REPO_URL' was not defined")
        if "GET_URL_CLIENT_PATH" not in self.instlInstance.cvl:
            raise ValueError("'GET_URL_CLIENT_PATH' was not defined")
        get_url_client_full_path = self.instlInstance.search_paths_helper.find_file_with_search_paths(self.instlInstance.cvl.get_str("GET_URL_CLIENT_PATH"))
        self.instlInstance.cvl.set_variable("GET_URL_CLIENT_PATH", var_description).append(get_url_client_full_path)

        if "REPO_REV" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("REPO_REV", var_description).append("HEAD")
        if "BASE_SRC_URL" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("BASE_SRC_URL", var_description).append("$(STAT_LINK_REPO_URL)/$(TARGET_OS)")

        if "LOCAL_SYNC_DIR" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("LOCAL_SYNC_DIR", var_description).append(self.instlInstance.get_default_sync_dir())

        if "BOOKKEEPING_DIR_URL" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("BOOKKEEPING_DIR_URL").append("$(STAT_LINK_REPO_URL)/instl")
        bookkeeping_relative_path = relative_url(self.instlInstance.cvl.get_str("STAT_LINK_REPO_URL"), self.instlInstance.cvl.get_str("BOOKKEEPING_DIR_URL"))
        self.instlInstance.cvl.set_variable("REL_BOOKKIPING_PATH", var_description).append(bookkeeping_relative_path)

        rel_sources = relative_url(self.instlInstance.cvl.get_str("STAT_LINK_REPO_URL"), self.instlInstance.cvl.get_str("BASE_SRC_URL"))
        self.instlInstance.cvl.set_variable("REL_SRC_PATH", var_description).append(rel_sources)

        if "INFO_MAP_FILE_URL" not in self.instlInstance.cvl:
            self.instlInstance.cvl.set_variable("INFO_MAP_FILE_URL").append("$(STAT_LINK_REPO_URL)/instl/info_map.txt")

        for identifier in ("STAT_LINK_REPO_URL", "GET_URL_CLIENT_PATH", "REL_SRC_PATH", "REPO_REV", "BASE_SRC_URL", "BOOKKEEPING_DIR_URL"):
            logging.debug("... %s: %s", identifier, self.instlInstance.cvl.get_str(identifier))

    @func_log_wrapper
    def create_sync_instructions(self, installState):
        self.create_need_list(installState)
        for iid in installState.orphan_install_items:
            installState.append_instructions('sync', self.instlInstance.create_echo_command("Don't know how to sync "+iid))
        self.instlInstance.svnTree.read_from_file(self.instlInstance.cvl.get_str("INFO_MAP_FILE_URL"), format="text")
        self.need_list_to_ought()
        self.ought_and_have_to_sync()
        self.create_download_instructions()
        out_file = self.instlInstance.cvl.get_str("__MAIN_OUT_FILE__")
        logging.info("... %s", out_file)

    @func_log_wrapper
    def create_need_list(self, installState):
        for iid  in installState.full_install_items:
            installi = self.instlInstance.install_definitions_index[iid]
            if installi.source_list():
                for source in installi.source_list():
                    self.create_need_list_for_source(source)

    @func_log_wrapper
    def create_need_list_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        _sub = self.instlInstance.svnTree.get_sub(source[0])
        if source[1] == '!file':
            if _sub.isFile():
                self.need_map.add_sub(source[0], _sub.flags(), _sub.last_rev())
        if source[1] == '!files':
            if _sub.isDir():
                for _sub_file in _sub.values():
                    if _sub_file.isFile():
                self.need_map.add_sub((source[0], _sub_file), _sub_file.flags(), _sub_file.last_rev())
        if source[1] == '!dir':
            self.need_map.add_sub_recursive(_sub)
        if source[1] == '!dir_cont':
            self.need_map.add_sub_recursive(_sub)
        return retVal

    def download_info_map(self):
         "$(STAT_LINK_REPO_URL)/instl/info_map.txt

    def need_list_to_ought(self):
        pass

    def ought_and_have_to_sync(self):
        pass

    def create_download_instructions(selfs):
        pass