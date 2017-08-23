#!/usr/bin/env python3

import sys
import os
import abc

import utils
from . import connectionBase
from configVar import var_stack


def is_user_data_false_or_dir_empty(svn_item):
    retVal = not svn_item.user_data
    if svn_item.isDir():
        retVal = len(svn_item.subs) == 0
    return retVal


class InstlInstanceSync(object, metaclass=abc.ABCMeta):
    """  Base class for sync object .
    """

    def __init__(self, instlObj):
        self.instlObj = instlObj  # instance of the instl application
        self.local_sync_dir = None  # will be resolved from $(LOCAL_REPO_SYNC_DIR)
        self.files_to_download = 0

    def init_sync_vars(self):
        """ Prepares variables for sync. Will raise ValueError if a mandatory variable
            is not defined.
        """
        prerequisite_vars = var_stack.ResolveVarToList("__SYNC_PREREQUISITE_VARIABLES__")
        self.instlObj.check_prerequisite_var_existence(prerequisite_vars)

        if "PUBLIC_KEY" not in var_stack:
            if "PUBLIC_KEY_FILE" in var_stack:
                public_key_file = var_stack.ResolveVarToStr("PUBLIC_KEY_FILE")
                with utils.open_for_read_file_or_url(public_key_file, connectionBase.translate_url, self.instlObj.path_searcher) as open_file:
                    public_key_text = open_file.fd.read()
                    var_stack.set_var("PUBLIC_KEY", "from " + public_key_file).append(public_key_text)
        self.instlObj.calc_user_cache_dir_var() # this will set USER_CACHE_DIR if it was not explicitly defined

    # Overridden by InstlInstanceSync_url, or parallel sync classes
    def create_sync_instructions(self):
        self.instlObj.batch_accum.set_current_section('sync')
        return 0

    def create_no_sync_instructions(self):
        """ an inheriting syncer can override this function to do something incase no files needed syncing """
        pass

    def read_remote_info_map(self):
        """ Reads the info map of the static files available for syncing.
            Writes the map to local sync folder for reference and debugging.
        """
        info_map_file_url = None
        try:
            os.makedirs(var_stack.ResolveVarToStr("LOCAL_REPO_BOOKKEEPING_DIR"), exist_ok=True)
            os.makedirs(var_stack.ResolveVarToStr("LOCAL_REPO_REV_BOOKKEEPING_DIR"), exist_ok=True)
            info_map_file_url = var_stack.ResolveVarToStr("INFO_MAP_FILE_URL")
            local_copy_of_info_map = var_stack.ResolveVarToStr("LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH")
            utils.download_from_file_or_url(info_map_file_url,
                                      local_copy_of_info_map,
                                      connectionBase.translate_url,
                                      cache=True,
                                      expected_checksum=var_stack.ResolveVarToStr("INFO_MAP_FILE_URL_CHECKSUM"))

            self.instlObj.read_info_map_from_file(local_copy_of_info_map)
            self.instlObj.info_map_table.write_to_file(var_stack.ResolveVarToStr("NEW_HAVE_INFO_MAP_PATH"), field_to_write=('path', 'flags', 'revision', 'checksum', 'size'))
            #utils.smart_copy_file(local_copy_of_info_map,
            #                      var_stack.ResolveVarToStr("NEW_HAVE_INFO_MAP_PATH"))
        except Exception:
            print("Exception reading info_map:", info_map_file_url)
            raise

    def mark_required_items(self):
        """ Mark all files that are needed for installation.
            Folders containing these these files are also marked.
            All required items are written to required_info_map.txt for reference.
        """
        self.instlObj.info_map_table.mark_required_files_for_active_items()
        self.instlObj.info_map_table.mark_required_completion()
        required_file_path = var_stack.ResolveVarToStr("REQUIRED_INFO_MAP_PATH")
        required_items_list = self.instlObj.info_map_table.get_required_items()
        self.instlObj.info_map_table.write_to_file(in_file=required_file_path, items_list=required_items_list)

    def mark_download_items(self):
        """" Mark those files that need to be downloaded.
             All files marked 'required' are marked as needed download unless.
             the files that exists and have correct checksum.
        """
        self.instlObj.set_sync_locations_for_active_items()
        self.instlObj.info_map_table.mark_need_download()
        need_download_file_path = var_stack.ResolveVarToStr("TO_SYNC_INFO_MAP_PATH")
        need_download_items_list = self.instlObj.info_map_table.get_download_items()
        self.instlObj.info_map_table.write_to_file(in_file=need_download_file_path, items_list=need_download_items_list)

    # syncers that download from urls (url, boto) need to prepare a list of all the individual files that need updating.
    # syncers that use configuration management tools (p4, svn) do not need since the tools takes care of that.
    def prepare_list_of_sync_items(self):
        self.read_remote_info_map()  # reads the full info map from INFO_MAP_FILE_URL and writes it to the sync folder
        self.mark_required_items()  # removes items not required to be installed
        self.mark_download_items()  # removes items that are already on the user's disk
