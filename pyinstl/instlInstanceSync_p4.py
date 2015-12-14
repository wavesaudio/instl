#!/usr/bin/env python2.7
from __future__ import print_function

from instlInstanceSyncBase import InstlInstanceSync
from configVar import var_stack


class InstlInstanceSync_p4(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj):
        super(InstlInstanceSync_p4, self).__init__(instlObj)

    def init_sync_vars(self):
        super(InstlInstanceSync_p4, self).init_sync_vars()

    def create_sync_instructions(self, installState):
        super(InstlInstanceSync_p4, self).create_sync_instructions(installState)
        self.create_download_instructions()
        self.instlObj.batch_accum.set_current_section('post-sync')

    def create_download_instructions(self):
        self.instlObj.batch_accum.set_current_section('sync')
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Starting sync from $(SYNC_BASE_URL)")
        self.sync_base_url = var_stack.resolve("$(SYNC_BASE_URL)")

        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        for iid in self.installState.full_install_items:
            with self.install_definitions_index[iid]:
                for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                    source = var_stack.resolve_var_to_list(source_var)
                    self.p4_sync_for_source(source)

    def p4_sync_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        if source[1] == '!file':
            self.instlObj.batch_accum += " ".join(("p4", "sync", '"$(SYNC_BASE_URL)/' + source[0] + '"$(REPO_REV)'))
        elif source[1] == '!files':
            print("p4 does not know yet to sync !files")
        elif source[1] == '!dir' or source[1] == '!dir_cont':  # !dir and !dir_cont are only different when copying
            self.instlObj.batch_accum += " ".join(("p4", "sync", '"$(SYNC_BASE_URL)/' + source[0] + '/..."$(REPO_REV)'))
