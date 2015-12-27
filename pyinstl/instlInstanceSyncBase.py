#!/usr/bin/env python2.7
from __future__ import print_function

import os
import abc

import utils
import connectionBase
from configVar import var_stack


def is_user_data_false_or_dir_empty(svn_item):
    retVal = not svn_item.user_data
    if svn_item.isDir():
        retVal = len(svn_item.subs) == 0
    return retVal


class InstlInstanceSync(object):
    """  Base class for sync object .
    """
    __metaclass__ = abc.ABCMeta


    def __init__(self, instlObj):
        self.instlObj = instlObj  # instance of the instl application
        self.installState = None  # object holding batch instructions
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
                with utils.open_for_read_file_or_url(public_key_file, connectionBase.translate_url, self.instlObj.path_searcher) as file_fd:
                    public_key_text = file_fd.read()
                    var_stack.set_var("PUBLIC_KEY", "from " + public_key_file).append(public_key_text)
        self.instlObj.calc_user_cache_dir_var() # this will set USER_CACHE_DIR if it was not explicitly defined

    # Overridden by InstlInstanceSync_url, or parallel sync classes
    def create_sync_instructions(self, installState):
        self.instlObj.batch_accum.set_current_section('sync')
        self.installState = installState

    def read_remote_info_map(self):
        """ Reads the info map of the static files available for syncing.
            Writes the map to local sync folder for reference and debugging.
        """
        try:
            utils.safe_makedirs(var_stack.resolve("$(LOCAL_REPO_BOOKKEEPING_DIR)", raise_on_fail=True))
            utils.safe_makedirs(var_stack.resolve("$(LOCAL_REPO_REV_BOOKKEEPING_DIR)", raise_on_fail=True))
            info_map_file_url = var_stack.resolve("$(INFO_MAP_FILE_URL)")
            local_copy_of_info_map = var_stack.resolve("$(LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH)")
            utils.download_from_file_or_url(info_map_file_url,
                                      local_copy_of_info_map,
                                      connectionBase.translate_url,
                                      cache=True,
                                      expected_checksum=var_stack.resolve("$(INFO_MAP_FILE_URL_CHECKSUM)"))

            self.instlObj.info_map_table.read_from_file(var_stack.resolve("$(LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH)"), a_format="text")
            utils.smart_copy_file(var_stack.resolve("$(LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH)"),
                                  var_stack.resolve("$(NEW_HAVE_INFO_MAP_PATH)"))
        except:
            print("Exception reading info_map:", info_map_file_url)
            raise

    def mark_required_items(self):
        """ Mark all files that are needed for installation.
            Folders containing these these files are also marked.
            All required items are written to required_info_map.txt for reference.
        """
        for iid in self.installState.full_install_items:
            with self.instlObj.install_definitions_index[iid] as installi:
                for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                    source = var_stack.resolve_var_to_list(source_var)
                    self.instlObj.info_map_table.mark_required_for_source(source)
        self.instlObj.info_map_table.mark_required_completion()
        self.instlObj.info_map_table.write_to_file(var_stack.resolve("$(REQUIRED_INFO_MAP_PATH)"),  filter_name="all-required", in_format="text")

    def mark_download_items(self):
        """" Mark those files that need to be downloaded.
             All files marked 'required' are marked as needed download unless.
             the files that exists and have correct checksum.
        """
        self.instlObj.info_map_table.mark_need_download(self.local_sync_dir)
        self.instlObj.info_map_table.write_to_file(var_stack.resolve("$(TO_SYNC_INFO_MAP_PATH)"), filter_name="need-download-all")

    # syncers that download from urls (url, boto) need to prepare a list of all the individual files that need updating.
    # syncers that use configuration management tools (p4, svn) do not need since the tools takes care of that.
    def prepare_list_of_sync_items(self):
        self.read_remote_info_map()  # reads the full info map from INFO_MAP_FILE_URL and writes it to the sync folder
        self.mark_required_items()  # removes items not required to be installed
        self.mark_download_items()  # removes items that are already on the user's disk
