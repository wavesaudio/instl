#!/usr/bin/env python2.7
from __future__ import print_function

import logging

from pyinstl.utils import *
from pyinstl import svnTree
from instlInstanceSyncBase import InstlInstanceSync
from configVarList import var_list


class InstlInstanceSync_p4(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """
    def __init__(self, instlObj):
        self.instlObj = instlObj      # instance of the instl application
        self.installState = None                # object holding batch instructions
        self.work_info_map = svnTree.SVNTree()  # here most of the work is done: first info map from server is read, later unneeded items
                                                # are filtered out and then items that are already downloaded are filtered out. So finally
                                                # the download instructions are created from the remaining items.
        self.have_map = svnTree.SVNTree()       # info map of what was already downloaded
        self.files_to_download = 0

    def init_sync_vars(self):
        """ Prepares variables for sync. Will raise ValueError if a mandatory variable
            is not defined.
        """
        var_description = "from InstlInstanceBase.init_sync_vars"
        self.instlObj.check_prerequisite_var_existence(("SYNC_BASE_URL", "DOWNLOAD_TOOL_PATH", "REPO_REV"))

        safe_makedirs(var_list.get_str("LOCAL_REPO_BOOKKEEPING_DIR"))

        for identifier in ("SYNC_BASE_URL", "DOWNLOAD_TOOL_PATH", "REPO_REV"):
            #print(identifier, var_list.get_str(identifier))
            logging.debug("%s: %s", identifier, var_list.get_str(identifier))

    def create_sync_instructions(self, installState):
        self.instlObj.batch_accum.set_current_section('sync')
        self.installState = installState
        self.create_download_instructions()
        self.instlObj.batch_accum.set_current_section('post-sync')

    def create_download_instructions(self):
        self.instlObj.batch_accum.set_current_section('sync')
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Starting sync from $(SYNC_BASE_URL)")
        self.sync_base_url = var_list.resolve_string("$(SYNC_BASE_URL)")

        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        for iid  in self.installState.full_install_items:
            installi = self.instlObj.install_definitions_index[iid]
            if installi.source_list():
                for source in installi.source_list():
                    self.p4_sync_for_source(source)

    def p4_sync_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        if source[1] == '!file':
            self.instlObj.batch_accum += " ".join( ("p4", "sync", '"$(SYNC_BASE_URL)/'+source[0]+'"$(REPO_REV)') )
        elif source[1] == '!files':
            print("p4 does not know yet to sync !files")
        elif source[1] == '!dir' or source[1] == '!dir_cont': # !dir and !dir_cont are only different when copying
            self.instlObj.batch_accum += " ".join( ("p4", "sync", '"$(SYNC_BASE_URL)/'+source[0]+'/..."$(REPO_REV)') )
