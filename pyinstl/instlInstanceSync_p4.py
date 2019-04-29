#!/usr/bin/env python3.6


from .instlInstanceSyncBase import InstlInstanceSync
from configVar import config_vars


class InstlInstanceSync_p4(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj) -> None:
        super().__init__(instlObj)

    def init_sync_vars(self):
        super().init_sync_vars()

    def create_sync_instructions(self):
        retVal = super().create_sync_instructions()
        retVal += self.create_download_instructions()
        self.instlObj.batch_accum.set_current_section('post-sync')
        return retVal

    def create_download_instructions(self):
        retVal = 0
        self.instlObj.batch_accum.set_current_section('sync')
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Start sync from $(SYNC_BASE_URL)")
        self.sync_base_url = config_vars["SYNC_BASE_URL"].str()

        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        for iid in list(config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"]):
            sources_for_iid = config_vars.resolve_list_to_list(self.items_table.get_sources_for_iid(iid))
            for source in sources_for_iid:
                self.p4_sync_for_source(source)
                retVal += 1
        return retVal

    def p4_sync_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        source_path, source_type = source[0], source[1]
        if source_type == '!file':
            self.instlObj.batch_accum += " ".join(("p4", "sync", '"$(SYNC_BASE_URL)/' + source_path + '"$(REPO_REV)'))
        elif source_type == '!dir' or source_type == '!dir_cont':  # !dir and !dir_cont are only different when copying
            self.instlObj.batch_accum += " ".join(("p4", "sync", '"$(SYNC_BASE_URL)/' + source_path + '/..."$(REPO_REV)'))
