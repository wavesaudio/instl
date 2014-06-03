#!/usr/bin/env python2.7
from __future__ import print_function
import logging

from pyinstl.utils import *
from instlInstanceSyncBase import InstlInstanceSync
#from configVarList import var_list
from configVarStack import var_stack as var_list


class InstlInstanceSync_svn(InstlInstanceSync):
    """  Class to create sync instruction using svn.
    """
    def __init__(self, instlObj):
        self.ii = instlObj

    def init_sync_vars(self):
        var_description = "from InstlInstanceBase.init_sync_vars"
        self.check_prerequisite_var_existence(("SYNC_BASE_URL", "SVN_CLIENT_PATH"))

        var_list.set_value_if_var_does_not_exist("REPO_REV", "HEAD", description=var_description)
        bookkeeping_relative_path = relative_url(var_list.resolve("$(SYNC_BASE_URL)"), var_list.resolve("$(BOOKKEEPING_DIR_URL)"))
        var_list.set_var("REL_BOOKKIPING_PATH", var_description).append(bookkeeping_relative_path)

        rel_sources = relative_url(var_list.resolve("$(SYNC_BASE_URL)"), var_list.resolve("$(SYNC_BASE_URL)/$(SOURCE_PREFIX)"))
        var_list.set_var("REL_SRC_PATH", var_description).append(rel_sources)

    def create_sync_instructions(self, installState):
        self.ii.batch_accum.set_current_section('sync')
        self.ii.batch_accum += self.ii.platform_helper.progress("Starting sync from $(SYNC_BASE_URL)/$(SOURCE_PREFIX)")
        self.ii.batch_accum += self.ii.platform_helper.mkdir("$(LOCAL_SYNC_DIR)")
        self.ii.batch_accum += self.ii.platform_helper.cd("$(LOCAL_SYNC_DIR)")
        self.ii.batch_accum.indent_level += 1
        self.ii.batch_accum += " ".join(('"$(SVN_CLIENT_PATH)"', "co", '"$(BOOKKEEPING_DIR_URL)"', '"$(REL_BOOKKIPING_PATH)"', "--revision", "$(REPO_REV)", "--depth", "infinity"))
        self.ii.batch_accum += self.ii.platform_helper.progress("instl folder file $(BOOKKEEPING_DIR_URL)?p=$(REPO_REV)")
        for iid  in installState.full_install_items:
            installi = self.ii.install_definitions_index[iid]
            if installi.source_list():
                for source in installi.source_list():
                    self.ii.batch_accum += self.create_svn_sync_instructions_for_source(source)
            self.ii.batch_accum += self.ii.platform_helper.progress("Sync {installi.name}".format(**locals()))
        for iid in installState.orphan_install_items:
            self.ii.batch_accum += self.ii.platform_helper.echo("Don't know how to sync "+iid)
        self.ii.batch_accum.indent_level -= 1
        self.ii.batch_accum += self.ii.platform_helper.echo("from $(SYNC_BASE_URL)/$(SOURCE_PREFIX)")


    def create_svn_sync_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        retVal = list()
        source_url =   '/'.join( ("$(SYNC_BASE_URL)/$(SOURCE_PREFIX)", source[0]) )
        target_path =  '/'.join( ("$(REL_SRC_PATH)", source[0]) )
        if source[1] == '!file':
            source_url = '/'.join( source_url.split("/")[0:-1]) # skip the file name sync the whole folder
            target_path = '/'.join( target_path.split("/")[0:-1]) # skip the file name sync the whole folder
        command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"'+source_url+'"', '"'+target_path+'"', "--revision", "$(REPO_REV)"]
        if source[1] in ('!file', '!files'):
            command_parts.extend( ( "--depth", "files") )
        else:
            command_parts.extend( ( "--depth", "infinity") )
        retVal.append(" ".join(command_parts))

        logging.info("... %s; (%s)", source[0], source[1])
        return retVal

