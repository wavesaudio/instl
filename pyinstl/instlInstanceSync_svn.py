#!/usr/bin/env python3


import utils
from .instlInstanceSyncBase import InstlInstanceSync
from configVar import config_vars


class InstlInstanceSync_svn(InstlInstanceSync):
    """  Class to create sync instruction using svn.
    """

    def __init__(self, instlObj) -> None:
        super().__init__(instlObj)

    def init_sync_vars(self):
        super().init_sync_vars()

        config_vars.setdefault("REPO_REV", "HEAD")
        bookkeeping_relative_path = utils.relative_url(config_vars["SYNC_BASE_URL"].str(), config_vars["BOOKKEEPING_DIR_URL"].str())
        config_vars["REL_BOOKKEEPING_PATH"] = bookkeeping_relative_path

        rel_sources = utils.relative_url(config_vars["SYNC_BASE_URL"].str(), config_vars["SYNC_BASE_URL"].str())
        config_vars["REL_SRC_PATH"] = rel_sources

    def create_sync_instructions(self):
        retVal = super().create_sync_instructions()

        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Start sync")
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Starting sync from $(SYNC_BASE_URL)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.mkdir("$(LOCAL_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.cd("$(LOCAL_SYNC_DIR)")
        self.instlObj.batch_accum += " ".join(('"$(SVN_CLIENT_PATH)"', "co", '"$(BOOKKEEPING_DIR_URL)"', '"$(REL_BOOKKEEPING_PATH)"', "--revision", "$(REPO_REV)", "--depth", "infinity"))
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("instl folder file $(BOOKKEEPING_DIR_URL)?p=$(REPO_REV)")
        for iid in list(config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"]):
            sources_for_iid = list(config_vars[self.items_table.get_sources_for_iid(iid)])
            for source in sources_for_iid:
                self.instlObj.batch_accum += self.create_svn_sync_instructions_for_source(source)
                retVal += 1
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress(f"""Sync {config_vars["iid_name"]}""")
        for iid in list(config_vars["__ORPHAN_INSTALL_TARGETS__"]):
            self.instlObj.batch_accum += self.instlObj.platform_helper.echo("Don't know how to sync " + iid)
        self.instlObj.batch_accum += self.instlObj.platform_helper.echo("from $(SYNC_BASE_URL)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Done sync")
        return retVal

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
        if source_type in ('!file', ):
            command_parts.extend(( "--depth", "files"))
        else:
            command_parts.extend(( "--depth", "infinity"))
        retVal.append(" ".join(command_parts))

        return retVal

