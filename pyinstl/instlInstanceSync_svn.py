#!/usr/bin/env python3


import utils
from .instlInstanceSyncBase import InstlInstanceSync
from configVar import var_stack


class InstlInstanceSync_svn(InstlInstanceSync):
    """  Class to create sync instruction using svn.
    """

    def __init__(self, instlObj):
        super().__init__(instlObj)

    def init_sync_vars(self):
        super().init_sync_vars()

        var_description = "InstlInstanceSync_svn.init_sync_vars"
        var_stack.set_value_if_var_does_not_exist("REPO_REV", "HEAD", description=var_description)
        bookkeeping_relative_path = utils.relative_url(var_stack.resolve("$(SYNC_BASE_URL)"), var_stack.resolve("$(BOOKKEEPING_DIR_URL)"))
        var_stack.set_var("REL_BOOKKEEPING_PATH", var_description).append(bookkeeping_relative_path)

        rel_sources = utils.relative_url(var_stack.resolve("$(SYNC_BASE_URL)"), var_stack.resolve("$(SYNC_BASE_URL)"))
        var_stack.set_var("REL_SRC_PATH", var_description).append(rel_sources)

    def create_sync_instructions(self, installState):
        super().create_sync_instructions(installState)

        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Starting sync from $(SYNC_BASE_URL)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.mkdir("$(LOCAL_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.cd("$(LOCAL_SYNC_DIR)")
        self.instlObj.batch_accum.indent_level += 1
        self.instlObj.batch_accum += " ".join(('"$(SVN_CLIENT_PATH)"', "co", '"$(BOOKKEEPING_DIR_URL)"', '"$(REL_BOOKKEEPING_PATH)"', "--revision", "$(REPO_REV)", "--depth", "infinity"))
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("instl folder file $(BOOKKEEPING_DIR_URL)?p=$(REPO_REV)")
        for iid in installState.all_items:
            with self.install_definitions_index[iid].push_var_stack_scope():
                for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                    source = var_stack.resolve_var_to_list(source_var)
                    self.instlObj.batch_accum += self.create_svn_sync_instructions_for_source(source)
                self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Sync {}".format(var_stack.resolve("iid_name")))
        for iid in installState.orphan_items:
            self.instlObj.batch_accum += self.instlObj.platform_helper.echo("Don't know how to sync " + iid)
        self.instlObj.batch_accum.indent_level -= 1
        self.instlObj.batch_accum += self.instlObj.platform_helper.echo("from $(SYNC_BASE_URL)")


    def create_svn_sync_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        source_path, source_type = source[0], source[1]
        retVal = list()
        source_url = '/'.join(("$(SYNC_BASE_URL)", source_path))
        target_path = '/'.join(("$(REL_SRC_PATH)", source_path))
        if source_type == '!file':
            source_url = '/'.join(source_url.split("/")[0:-1])  # skip the file name sync the whole folder
            target_path = '/'.join(target_path.split("/")[0:-1])  # skip the file name sync the whole folder
        command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"'+source_url+'"', '"'+target_path+'"', "--revision", "$(REPO_REV)"]
        if source_type in ('!file', '!files'):
            command_parts.extend(( "--depth", "files"))
        else:
            command_parts.extend(( "--depth", "infinity"))
        retVal.append(" ".join(command_parts))

        return retVal

