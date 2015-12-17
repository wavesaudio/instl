#!/usr/bin/env python2.7
from __future__ import print_function

import os

import svnTree
import utils
from instlInstanceSyncBase import InstlInstanceSync
from batchAccumulator import BatchAccumulator
from configVar import var_stack


class InstlInstanceSync_url(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj):
        super(InstlInstanceSync_url, self).__init__(instlObj)

    def init_sync_vars(self):
        super(InstlInstanceSync_url, self).init_sync_vars()

        self.local_sync_dir = var_stack.resolve("$(LOCAL_REPO_SYNC_DIR)")

    def create_sync_instructions(self, installState):
        super(InstlInstanceSync_url, self).create_sync_instructions(installState)
        self.prepare_list_of_sync_items()
        self.create_download_instructions()
        self.instlObj.batch_accum.set_current_section('post-sync')
        self.instlObj.batch_accum += self.instlObj.platform_helper.copy_file_to_file("$(NEW_HAVE_INFO_MAP_PATH)",
                                                                                     "$(HAVE_INFO_MAP_PATH)")

    class RemoveIfChecksumOK:
        def __init__(self, base_path):
            self.base_path = base_path

        def __call__(self, svn_item):
            retVal = None
            if svn_item.isFile():
                file_path = os.path.join(*utils.make_one_list(self.base_path, svn_item.full_path_parts()))
                need_to_download = utils.need_to_download_file(file_path, svn_item.checksum)
                # a hack to force download of wtars if they were not unwtared correctly.
                # Actually a full download is not needed but there is not other way to force
                # post sync processing. Also folder might exist even if unwtar was not completed.
                # So Todo: find way to force unwtar without marking the item for download.
                if not need_to_download and svn_item.name.endswith(".wtar"):
                    unwtared_folder, _ = os.path.splitext(file_path)
                    if not os.path.isdir(unwtared_folder):
                        need_to_download = True
                retVal = not need_to_download
            elif svn_item.isDir():
                retVal = len(svn_item.subs) == 0
            return retVal

    def create_download_instructions(self):
        self.instlObj.batch_accum.set_current_section('sync')
        file_list, bytes_to_sync = self.info_map_table.get_to_download_list_and_size()
        if len(file_list) == 0:
            print("0 files to sync")
            print("0 bytes to sync")
            return
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress(
            "Starting sync from $(SYNC_BASE_URL)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.mkdir("$(LOCAL_REPO_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
        self.sync_base_url = var_stack.resolve("$(SYNC_BASE_URL)")

        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        self.instlObj.batch_accum += self.instlObj.platform_helper.create_folders("$(TO_SYNC_INFO_MAP_PATH)")
        # todo: fix create_folders call, from which info_map it will read?
        # self.instlObj.platform_helper.num_items_for_progress_report += num_dirs_to_create
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Create folders")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        for file_item in file_list:
            source_url = file_item.url
            if source_url is None:
                source_url = '/'.join(utils.make_one_list(self.sync_base_url, str(file_item.revision_remote), file_item.path))
            self.instlObj.platform_helper.dl_tool.add_download_url(source_url, file_item.path, verbatim=source_url==file_item.url)
        var_stack.add_const_config_variable("__NUM_FILES_TO_DOWNLOAD_OLD__", "create_download_instructions",
                                            self.instlObj.platform_helper.dl_tool.get_num_urls_to_download())

        print(self.instlObj.platform_helper.dl_tool.get_num_urls_to_download(), "files to sync")
        print(bytes_to_sync, "bytes to sync")

        curl_config_folder = var_stack.resolve("$(LOCAL_REPO_BOOKKEEPING_DIR)/curl", raise_on_fail=True)
        utils.safe_makedirs(curl_config_folder)
        curl_config_file_path = var_stack.resolve(os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME)"), raise_on_fail=True)
        num_config_files = int(var_stack.resolve("$(PARALLEL_SYNC)"))
        config_file_list = self.instlObj.platform_helper.dl_tool.create_config_files(curl_config_file_path,
                                                                                     num_config_files)
        if len(config_file_list) > 0:
            self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress(
                "Downloading with " + str(len(config_file_list)) + " processes in parallel")
            parallel_run_config_file_path = var_stack.resolve(
                os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME).parallel-run"))
            self.instlObj.batch_accum += self.instlObj.platform_helper.dl_tool.download_from_config_files(
                parallel_run_config_file_path, config_file_list)
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress(
                "Downloading " + str(self.files_to_download) + " files done", self.files_to_download)
            self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Checking checksum...")
        # todo: fix check_checksum call, from which info_map it will read?
        self.instlObj.batch_accum += self.instlObj.platform_helper.check_checksum_for_folder("$(TO_SYNC_INFO_MAP_PATH)")
        self.instlObj.platform_helper.num_items_for_progress_report += len(file_list)
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Check checksum done")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        self.instlObj.batch_accum += self.instlObj.platform_helper.popd()
