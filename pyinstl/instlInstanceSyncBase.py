#!/usr/bin/env python2.7
from __future__ import print_function
import abc

from pyinstl import svnTree
from pyinstl.utils import *
from configVarStack import var_stack

def is_user_data_false_or_dir_empty(svn_item):
    retVal = not svn_item.user_data
    if svn_item.isDir():
        retVal = len(svn_item.subs()) == 0
    return retVal

class InstlInstanceSync(object):
    """  Base class for sync object .
    """
    __metaclass__ = abc.ABCMeta


    def __init__(self, instlObj):
        self.instlObj = instlObj  # instance of the instl application
        self.installState = None  # object holding batch instructions
        self.work_info_map = svnTree.SVNTree()
        self.have_map = svnTree.SVNTree()  # info map of what was already downloaded
        self.local_sync_dir = None  # will be resolved from $(LOCAL_REPO_SYNC_DIR)
        self.files_to_download = 0

    def init_sync_vars(self):
        """ Prepares variables for sync. Will raise ValueError if a mandatory variable
            is not defined.
        """
        prerequisite_vars = var_stack.resolve_var_to_list("__SYNC_PREREQUISITE_VARIABLES__")
        self.instlObj.check_prerequisite_var_existence(prerequisite_vars)


        if "PUBLIC_KEY" not in var_stack:
            if "PUBLIC_KEY_FILE" in var_stack:
                public_key_file = var_stack.resolve("$(PUBLIC_KEY_FILE)")
                with open_for_read_file_or_url(public_key_file, self.instlObj.path_searcher) as file_fd:
                    public_key_text = file_fd.read()
                    var_stack.set_var("PUBLIC_KEY", "from " + public_key_file).append(public_key_text)

    def create_sync_instructions(self, installState):
        self.instlObj.batch_accum.set_current_section('sync')
        self.installState = installState

    def read_remote_info_map(self):
        """ Reads the info map of the static files available for syncing.
            Writes the map to local sync folder for reference and debugging.
        """
        try:
            safe_makedirs(var_stack.resolve("$(LOCAL_REPO_BOOKKEEPING_DIR)", raise_on_fail=True))
            safe_makedirs(var_stack.resolve("$(LOCAL_REPO_REV_BOOKKEEPING_DIR)", raise_on_fail=True))
            download_from_file_or_url(var_stack.resolve("$(INFO_MAP_FILE_URL)"),
                                      var_stack.resolve("$(LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH)", raise_on_fail=True),
                                      cache=True,
                                      expected_checksum=var_stack.resolve("$(INFO_MAP_FILE_URL_CHECKSUM)"))
            self.work_info_map.read_info_map_from_file(var_stack.resolve("$(LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH)"),
                                                       a_format="text")
        except:
            raise

    def filter_out_unrequired_items(self):
        """ Removes from work_info_map items not required to be installed.
            First all items are marked False.
            Items required by each install source are then marked True.
            Finally items marked False and empty directories are removed.
        """
        self.work_info_map.set_user_data_all_recursive(False)
        for iid in self.installState.full_install_items:
            with self.instlObj.install_definitions_index[iid] as installi:
                for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                    source = var_stack.resolve_var_to_list(source_var)
                    self.mark_required_items_for_source(source)
        self.work_info_map.recursive_remove_depth_first(is_user_data_false_or_dir_empty)
        self.work_info_map.write_to_file(var_stack.resolve("$(REQUIRED_INFO_MAP_PATH)"), in_format="text")

    def read_have_info_map(self):
        """ Reads the map of files previously synced - if there is one.
        """
        have_info_map_path = var_stack.resolve("$(HAVE_INFO_MAP_PATH)")
        if os.path.isfile(have_info_map_path):
            self.have_map.read_info_map_from_file(have_info_map_path, a_format="text")

    def filter_out_already_synced_items(self):
        """ Removes from work_info_map items not required to be synced and updates the in-memory have map.
            First all items are marked True.
            Items found in have map are then marked False - provided their "have" version is equal to required version.
            Finally all items marked False and empty directories are removed.
        """
        self.work_info_map.set_user_data_all_recursive(True)
        for need_item in self.work_info_map.walk_items(what="file"):
            have_item = self.have_map.get_item_at_path(need_item.full_path_parts())
            if have_item is None:  # not found in have map
                self.have_map.new_item_at_path(need_item.full_path_parts(),
                                               need_item.flags(),
                                               need_item.last_rev(),
                                               need_item.checksum(),
                                               # no need to copy the url to the have_map
                                               create_folders=True)
            else:  # found in have map
                if have_item.last_rev() == need_item.last_rev():
                    need_item.user_data = False
                elif have_item.last_rev() < need_item.last_rev():
                    have_item.set_flags(need_item.flags())
                    have_item.set_last_rev(need_item.last_rev())
                elif have_item.last_rev() > need_item.last_rev():  # weird, but need to get the older version
                    have_item.set_flags(need_item.flags())
                    have_item.set_last_rev(need_item.last_rev())
        self.work_info_map.recursive_remove_depth_first(is_user_data_false_or_dir_empty)
        self.work_info_map.write_to_file(var_stack.resolve("$(TO_SYNC_INFO_MAP_PATH)", raise_on_fail=True), in_format="text")
        self.have_map.write_to_file(var_stack.resolve("$(NEW_HAVE_INFO_MAP_PATH)", raise_on_fail=True), in_format="text")

    # syncers that download from urls (url, boto) need to prepare a list of all the individual files that need updating.
    # syncers that use configuration management tools (p4, svn) do not need since the tools takes care of that.
    def prepare_list_of_sync_items(self):
        self.read_remote_info_map()  # reads the full info map from INFO_MAP_FILE_URL and writes it to the sync folder
        self.filter_out_unrequired_items()  # removes items not required to be installed
        self.read_have_info_map()  # reads the info map of items already synced
        self.filter_out_already_synced_items()  # removes items that are already on the user's disk
