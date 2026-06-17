#!/usr/bin/env python3.12
"""pyinstl.client package.

This package is the result of a pure structural decomposition (extract-module
refactor) of the former god-object pyinstl/instlClient.py. The InstlClient base
class implementation is split across focused mixin submodules and composed here.
No behavior was changed: method names, signatures and emitted output are
identical.

The original module pyinstl/instlClient.py is kept as a thin shim that
re-exports the same public surface (InstlClient, InstlClientFactory) from this
package.

The sibling client modules (instlClientSync/Copy/Remove/Report/Uninstall) are
intentionally left as-is; they keep importing `from .instlClient import
InstlClient`, which still resolves through the shim.
"""
import os
from collections import defaultdict

import utils
from configVar import config_vars
from pybatch import *
from ..instlInstanceBase import InstlInstanceBase

from ._core import _CoreClientMixin
from ._install_items import _InstallItemsClientMixin
from ._require import _RequireClientMixin
from ._actions import _ActionsClientMixin
from ._binaries import _BinariesClientMixin
from ._sync_locations import _SyncLocationsClientMixin
from ._remove_sources import _RemoveSourcesClientMixin
from ._naming import _NamingClientMixin


class InstlClient(_CoreClientMixin,
                  _InstallItemsClientMixin,
                  _RequireClientMixin,
                  _ActionsClientMixin,
                  _BinariesClientMixin,
                  _SyncLocationsClientMixin,
                  _RemoveSourcesClientMixin,
                  _NamingClientMixin,
                  InstlInstanceBase):
    """ Base class for all client operations: sync, copy, synccopy, uninstall, remove """
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.total_self_progress: int = 15000
        self.internal_progress = int(self.total_self_progress / 100) * 2
        self.read_defaults_file(super().__thisclass__.__name__)
        self.action_type_to_progress_message = dict()
        self.__all_iids_by_target_folder = defaultdict(utils.unique_list)
        self.__no_copy_iids_by_sync_folder = defaultdict(utils.unique_list)
        self.auxiliary_iids = utils.unique_list()
        self.main_install_targets = list()

    @property
    def all_iids_by_target_folder(self):
        return self.__all_iids_by_target_folder

    @property
    def no_copy_iids_by_sync_folder(self):
        return self.__no_copy_iids_by_sync_folder

    def sort_all_items_by_target_folder(self, consider_direct_sync=True):
        direct_sync_iids = list()
        folder_to_iid_list = self.items_table.target_folders_to_items()
        for IID, folder, tag, direct_sync_indicator in folder_to_iid_list:
            direct_sync = self.get_direct_sync_status_from_indicator(direct_sync_indicator)
            if direct_sync and consider_direct_sync:
                sync_folder = os.path.join(folder)
                self.__no_copy_iids_by_sync_folder[sync_folder].append(IID)
                direct_sync_iids.append(IID)
            else:
                norm_folder = os.path.normpath(folder)
                self.__all_iids_by_target_folder[norm_folder].append(IID)

        config_vars['__FULL_LIST_OF_DIRECT_SYNC_TARGETS__'] = direct_sync_iids

        for folder_iids_list in self.__all_iids_by_target_folder.values():
            folder_iids_list.sort()

        for folder_copy_iids_list in self.__no_copy_iids_by_sync_folder.values():
            folder_copy_iids_list.sort()

        folder_to_iid_list = self.items_table.source_folders_to_items_without_target_folders()
        for adjusted_source, IID, tag in folder_to_iid_list:
            relative_sync_folder = self.relative_sync_folder_for_source_table(adjusted_source, tag)
            sync_folder = os.path.join("$(LOCAL_REPO_SYNC_DIR)", relative_sync_folder)
            self.__no_copy_iids_by_sync_folder[sync_folder].append(IID)


def InstlClientFactory(initial_vars, command):
    retVal = None

    match command:
        case "sync":
            from ..instlClientSync import InstlClientSync
            retVal = InstlClientSync(initial_vars)
        case "copy":
            from ..instlClientCopy import InstlClientCopy
            retVal = InstlClientCopy(initial_vars)
        case "remove":
            from ..instlClientRemove import InstlClientRemove
            retVal = InstlClientRemove(initial_vars)
        case "uninstall":
            from ..instlClientUninstall import InstlClientUninstall
            retVal = InstlClientUninstall(initial_vars)
        case 'report-installed' | 'report-update' | 'report-versions' | 'report-gal' | 'read-yaml' | 'short-index':
            from ..instlClientReport import InstlClientReport
            retVal = InstlClientReport(initial_vars)
        case "synccopy":
            from ..instlClientSync import InstlClientSync
            from ..instlClientCopy import InstlClientCopy

            class InstlClientSyncCopy(InstlClientSync, InstlClientCopy):
                def __init__(self, sc_initial_vars=None) -> None:
                    super().__init__(sc_initial_vars)
                    self.calc_user_cache_dir_var()

                def do_synccopy(self):
                    self.do_sync()
                    self.do_copy()
                    self.batch_accum += Progress("Done synccopy")
            retVal = InstlClientSyncCopy(initial_vars)
    return retVal
