#!/usr/bin/env python3

import sys
import os
import abc

import utils
from . import connectionBase
from configVar import var_stack


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
        self.instlObj.calc_user_cache_dir_var() # this will set USER_CACHE_DIR if it was not explicitly defined

    # Overridden by InstlInstanceSync_url, or parallel sync classes
    def create_sync_instructions(self):
        self.instlObj.batch_accum.set_current_section('sync')
        return 0

    def create_no_sync_instructions(self):
        """ an inheriting syncer can override this function to do something in case no files needed syncing """
        pass

    def read_remote_info_map(self):
        """ Reads the info map of the static files available for syncing.
            Writes the map to local sync folder for reference and debugging.
        """
        info_map_file_url = None
        try:
            with self.instlObj.info_map_table.reading_files_context():
                os.makedirs(var_stack.ResolveVarToStr("LOCAL_REPO_BOOKKEEPING_DIR"), exist_ok=True)
                os.makedirs(var_stack.ResolveVarToStr("LOCAL_REPO_REV_BOOKKEEPING_DIR"), exist_ok=True)

                if "INSTL_FOLDER_BASE_URL" not in var_stack:
                    if "REPO_REV_FOLDER_HIERARCHY" not in var_stack:
                        var_stack.set_var("REPO_REV_FOLDER_HIERARCHY").append(self.instlObj.repo_rev_to_folder_hierarchy(var_stack.ResolveVarToStr("REPO_REV")))
                    var_stack.set_var("INSTL_FOLDER_BASE_URL").append("$(BASE_LINKS_URL)/$(REPO_NAME)/$(REPO_REV_FOLDER_HIERARCHY)/instl")

                if "INFO_MAP_FILE_URL" not in var_stack:
                    var_stack.set_var("INFO_MAP_FILE_URL").append(var_stack.ResolveStrToStr("$(INSTL_FOLDER_BASE_URL)/info_map.txt"))

                info_map_file_url = var_stack.ResolveVarToStr("INFO_MAP_FILE_URL")
                info_map_file_expected_checksum = None
                if "INFO_MAP_CHECKSUM" in var_stack:
                    info_map_file_expected_checksum = var_stack.ResolveVarToStr("INFO_MAP_CHECKSUM")
                local_copy_of_info_map_in = var_stack.ResolveVarToStr("LOCAL_COPY_OF_REMOTE_INFO_MAP_PATH")
                local_copy_of_info_map_out = utils.download_from_file_or_url(in_url=info_map_file_url,
                                                in_target_path=local_copy_of_info_map_in,
                                                translate_url_callback=connectionBase.translate_url,
                                                cache_folder=self.instlObj.get_default_sync_dir(continue_dir="cache", make_dir=True),
                                                expected_checksum=info_map_file_expected_checksum)
                assert local_copy_of_info_map_in == local_copy_of_info_map_out, local_copy_of_info_map_in +" != "+ local_copy_of_info_map_out
                self.instlObj.read_info_map_from_file(local_copy_of_info_map_out)
                self.instlObj.progress("read info_map {}".format(info_map_file_url))

                additional_info_maps = self.instlObj.items_table.get_details_for_active_iids("info_map", unique_values=True)
                for additional_info_map in additional_info_maps:
                    # try to get the zipped info_map
                    additional_info_map_file_name = var_stack.ResolveStrToStr("{}$(WZLIB_EXTENSION)".format(additional_info_map))
                    path_in_main_info_map = var_stack.ResolveStrToStr("instl/{}".format(additional_info_map_file_name))
                    additional_info_map_item = self.instlObj.info_map_table.get_file_item(path_in_main_info_map)
                    if not additional_info_map_item:  # zipped not found try the unzipped inf_map
                        additional_info_map_file_name = additional_info_map
                        path_in_main_info_map = var_stack.ResolveStrToStr("instl/{}".format(additional_info_map))
                        additional_info_map_item = self.instlObj.info_map_table.get_file_item(path_in_main_info_map)

                    checksum = additional_info_map_item.checksum if additional_info_map_item else None

                    info_map_file_url = var_stack.ResolveStrToStr("$(INSTL_FOLDER_BASE_URL)/{}".format(additional_info_map_file_name))
                    local_copy_of_info_map_in = var_stack.ResolveStrToStr("$(LOCAL_REPO_REV_BOOKKEEPING_DIR)/{}".format(additional_info_map))
                    local_copy_of_info_map_out = utils.download_from_file_or_url(in_url=info_map_file_url,
                                                in_target_path=local_copy_of_info_map_in,
                                                translate_url_callback=connectionBase.translate_url,
                                                cache_folder=self.instlObj.get_default_sync_dir("cache", make_dir=True),
                                                expected_checksum=checksum)
                    assert local_copy_of_info_map_in == local_copy_of_info_map_out, local_copy_of_info_map_in +" != "+ local_copy_of_info_map_out
                    self.instlObj.read_info_map_from_file(local_copy_of_info_map_out)
                    self.instlObj.progress("read info_map {}".format(info_map_file_url))

                new_have_info_map_path = var_stack.ResolveVarToStr("NEW_HAVE_INFO_MAP_PATH")
                self.instlObj.info_map_table.write_to_file(new_have_info_map_path, field_to_write=('path', 'flags', 'revision', 'checksum', 'size'))
        except Exception:
            print("Exception reading info_map:", info_map_file_url)
            raise

    def mark_required_items(self):
        """ Mark all files that are needed for installation.
            Folders containing these these files are also marked.
            All required items are written to required_info_map.txt for reference.
        """
        self.instlObj.info_map_table.mark_required_files_for_active_items()
        required_file_path = var_stack.ResolveVarToStr("REQUIRED_INFO_MAP_PATH")
        required_items_list = self.instlObj.info_map_table.get_required_items()
        self.instlObj.info_map_table.write_to_file(in_file=required_file_path, items_list=required_items_list)
        num_required_files = sum(item.fileFlag for item in required_items_list)
        self.instlObj.progress("{} files required for installation".format(num_required_files))

    def mark_download_items(self):
        """" Mark those files that need to be downloaded.
             All files marked 'required' are marked as needed download unless.
             the files that exists and have correct checksum.
        """
        self.instlObj.progress("create list of files to download")
        self.instlObj.set_sync_locations_for_active_items()
        self.instlObj.progress("check checksum of existing required files ...")
        self.instlObj.info_map_table.mark_need_download()
        need_download_file_path = var_stack.ResolveVarToStr("TO_SYNC_INFO_MAP_PATH")
        need_download_items_list = self.instlObj.info_map_table.get_download_items()
        self.instlObj.info_map_table.write_to_file(in_file=need_download_file_path, items_list=need_download_items_list)
        self.instlObj.progress("{} files to download".format(len(need_download_items_list)))

    # syncers that download from urls (url, boto) need to prepare a list of all the individual files that need updating.
    # syncers that use configuration management tools (p4, svn) do not need since the tools takes care of that.
    def prepare_list_of_sync_items(self):
        self.read_remote_info_map()  # reads the full info map from INFO_MAP_FILE_URL and writes it to the sync folder
        self.mark_required_items()  # removes items not required to be installed
        self.mark_download_items()  # removes items that are already on the user's disk
