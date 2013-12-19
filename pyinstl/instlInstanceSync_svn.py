#!/usr/bin/env python2.7
from __future__ import print_function
import logging

from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *
from instlInstanceSyncBase import InstlInstanceSync


class InstlInstanceSync_svn(InstlInstanceSync):
    """  Class to create sync instruction using svn.
    """
    @func_log_wrapper
    def __init__(self, instlInstance):
        self.ii = instlInstance

    @func_log_wrapper
    def init_sync_vars(self):
        var_description = "from InstlInstanceBase.init_sync_vars"
        if "SYNC_BASE_URL" not in self.ii.cvl:
            raise ValueError("'SYNC_BASE_URL' was not defined")
        if "SVN_CLIENT_PATH" not in self.ii.cvl:
            raise ValueError("'SVN_CLIENT_PATH' was not defined")
        svn_client_full_path = self.ii.search_paths_helper.find_file_with_search_paths(self.ii.cvl.get_str("SVN_CLIENT_PATH"))
        self.ii.cvl.set_variable("SVN_CLIENT_PATH", var_description).append(svn_client_full_path)

        self.ii.cvl.set_value_if_var_does_not_exist("REPO_REV", "HEAD", description=var_description)
        self.ii.cvl.set_value_if_var_does_not_exist("BASE_SRC_URL", "$(SYNC_BASE_URL)/$(TARGET_OS)", description=var_description)
        self.ii.cvl.set_value_if_var_does_not_exist("LOCAL_SYNC_DIR", self.ii.get_default_sync_dir(), description=var_description)
        self.ii.cvl.set_value_if_var_does_not_exist("BOOKKEEPING_DIR_URL", "$(SYNC_BASE_URL)/instl", description=var_description)
        bookkeeping_relative_path = relative_url(self.ii.cvl.get_str("SYNC_BASE_URL"), self.ii.cvl.get_str("BOOKKEEPING_DIR_URL"))
        self.ii.cvl.set_variable("REL_BOOKKIPING_PATH", var_description).append(bookkeeping_relative_path)

        rel_sources = relative_url(self.ii.cvl.get_str("SYNC_BASE_URL"), self.ii.cvl.get_str("BASE_SRC_URL"))
        self.ii.cvl.set_variable("REL_SRC_PATH", var_description).append(rel_sources)

        for identifier in ("SYNC_BASE_URL", "SVN_CLIENT_PATH", "REL_SRC_PATH", "REPO_REV", "BASE_SRC_URL", "BOOKKEEPING_DIR_URL"):
            logging.debug("... %s: %s", identifier, self.ii.cvl.get_str(identifier))

    @func_log_wrapper
    def create_sync_instructions(self, installState):
        self.ii.batch_accum.set_current_section('sync')
        num_items_for_progress_report = len(installState.full_install_items) + 2 # one for a dummy last item, one for index sync
        self.ii.batch_accum += self.ii.platform_helper.progress("from $(BASE_SRC_URL)")
        self.ii.batch_accum.indent_level += 1
        self.ii.batch_accum += self.ii.platform_helper.mkdir("$(LOCAL_SYNC_DIR)")
        self.ii.batch_accum += self.ii.platform_helper.cd("$(LOCAL_SYNC_DIR)")
        self.ii.batch_accum.indent_level += 1
        self.ii.batch_accum += " ".join(('"$(SVN_CLIENT_PATH)"', "co", '"$(BOOKKEEPING_DIR_URL)"', '"$(REL_BOOKKIPING_PATH)"', "--revision", "$(REPO_REV)", "--depth", "infinity"))
        self.ii.batch_accum += self.ii.platform_helper.progress("index file $(BOOKKEEPING_DIR_URL)")
        for iid  in installState.full_install_items:
            installi = self.ii.install_definitions_index[iid]
            if installi.source_list():
                for source in installi.source_list():
                    self.ii.batch_accum += self.create_svn_sync_instructions_for_source(source)
            self.ii.batch_accum += self.ii.platform_helper.progress("{installi.iid}: {installi.name}".format(**locals()))
        for iid in installState.orphan_install_items:
            self.ii.batch_accum += self.ii.platform_helper.echo("Don't know how to sync "+iid)
        self.ii.batch_accum.indent_level -= 1
        self.ii.batch_accum += self.ii.platform_helper.echo("from $(BASE_SRC_URL)")
        

    @func_log_wrapper
    def create_svn_sync_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        retVal = list()
        source_url =   '/'.join( ("$(BASE_SRC_URL)", source[0]) )
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

