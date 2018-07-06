#!/usr/bin/env python3


from .instlInstanceSyncBase import InstlInstanceSync
from configVar import config_vars


class InstlInstanceSync_boto(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj):
        super().__init__(instlObj)

    def init_sync_vars(self):
        super().init_sync_vars()
        self.local_sync_dir = config_vars["LOCAL_REPO_SYNC_DIR"].str()
