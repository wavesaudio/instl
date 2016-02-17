#!/usr/bin/env python3


import os

import utils
from .instlInstanceSyncBase import InstlInstanceSync
from .batchAccumulator import BatchAccumulator
from configVar import var_stack


class InstlInstanceSync_url(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj):
        super().__init__(instlObj)
        self.sync_base_url = None

    def init_sync_vars(self):
        super().init_sync_vars()
        self.local_sync_dir = var_stack.resolve("$(LOCAL_REPO_SYNC_DIR)")

    def create_sync_folders(self):
        self.instlObj.batch_accum += self.instlObj.platform_helper.create_folders("$(TO_SYNC_INFO_MAP_PATH)")
        # todo: fix create_folders call, from which info_map it will read?
        # self.instlObj.platform_helper.num_items_for_progress_report += num_dirs_to_create
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Create folders")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

    def create_sync_urls(self, in_file_list):
        self.sync_base_url = var_stack.resolve("$(SYNC_BASE_URL)")
        for file_item in in_file_list:
            source_url = file_item.url
            if source_url is None:
                source_url = '/'.join(utils.make_one_list(self.sync_base_url, str(file_item.revision_remote), file_item.path))
            self.instlObj.platform_helper.dl_tool.add_download_url(source_url, file_item.path, verbatim=source_url==file_item.url)

    def create_curl_download_instructions(self):
        curl_config_folder = var_stack.resolve("$(LOCAL_REPO_BOOKKEEPING_DIR)/curl", raise_on_fail=True)
        utils.safe_makedirs(curl_config_folder)
        curl_config_file_path = var_stack.resolve(os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME)"), raise_on_fail=True)
        num_config_files = int(var_stack.resolve("$(PARALLEL_SYNC)"))
        config_file_list = self.instlObj.platform_helper.dl_tool.create_config_files(curl_config_file_path, num_config_files)

        actual_num_config_files = len(config_file_list)
        if actual_num_config_files > 0:
            dl_start_message = "Downloading with {actual_num_config_files} process{dl_start_message_plural}"
            dl_start_message_plural = "es in parallel" if actual_num_config_files > 1 else ""
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress(dl_start_message.format(**locals()))

            parallel_run_config_file_path = var_stack.resolve(
                os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME).parallel-run"))
            self.instlObj.batch_accum += self.instlObj.platform_helper.dl_tool.download_from_config_files(
                parallel_run_config_file_path, config_file_list)

            num_files_to_download = int("$(__NUM_FILES_TO_DOWNLOAD__)" @ var_stack)
            dl_end_message = "Downloading {num_files_to_download} file{dl_end_message_plural} done"
            dl_end_message_plural = "s" if num_files_to_download > 1 else ""
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress(
                dl_end_message.format(**locals()), self.files_to_download)
            self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

    def create_check_checksum_instructions(self, in_file_list):
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Checking checksum...")
        self.instlObj.batch_accum += self.instlObj.platform_helper.check_checksum_for_folder("$(TO_SYNC_INFO_MAP_PATH)")
        self.instlObj.platform_helper.num_items_for_progress_report += len(in_file_list)
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Check checksum done")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

    def create_remove_unwanted_files_in_sync_folder_instructions(self):
        """ Remove files in the sync folder that are not in info_map
        """
        prefix_len = len(self.local_sync_dir)+1
        files_checked = 0
        for root, dirs, files in os.walk(self.local_sync_dir, followlinks=False):
            try: dirs.remove("bookkeeping")
            except: pass # todo: use FOLDER_EXCLUDE_REGEX
            try: files.remove(".DS_Store")
            except: pass  # todo: use FILE_EXCLUDE_REGEX
            for disk_item in files:
                files_checked += 1
                item_full_path = os.path.join(root, disk_item)
                item_partial_path = item_full_path[prefix_len:]
                file_item = self.instlObj.info_map_table.get_item(item_path=item_partial_path, what="file")
                if file_item is None:  # file was not found in info_map
                    self.instlObj.batch_accum += self.instlObj.platform_helper.rmfile(item_full_path)
                    self.instlObj.batch_accum += self.instlObj.platform_helper.progress("removed redundant file "+item_full_path)

    def create_download_instructions(self):
        """ remove files in sync folder that do not appear in the info map table
        """
        self.instlObj.batch_accum.set_current_section('sync')

        file_list, bytes_to_sync = self.instlObj.info_map_table.get_to_download_files_and_size()
        var_stack.add_const_config_variable("__NUM_FILES_TO_DOWNLOAD__", "create_download_instructions", len(file_list))
        var_stack.add_const_config_variable("__NUM_BYTES_TO_DOWNLOAD__", "create_download_instructions", bytes_to_sync)

        # notify user how many files and bytes to sync
        print(len(file_list), "files to sync")
        print(bytes_to_sync, "bytes to sync")

        if len(file_list) == 0:
             return

        self.create_sync_folders()

        self.create_sync_urls(file_list)

        self.create_curl_download_instructions()
        self.create_check_checksum_instructions(file_list)

    def create_sync_instructions(self, installState):
        super().create_sync_instructions(installState)
        self.prepare_list_of_sync_items()

        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Starting sync from $(SYNC_BASE_URL)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.mkdir("$(LOCAL_REPO_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        self.create_remove_unwanted_files_in_sync_folder_instructions()
        self.create_download_instructions()
        self.instlObj.batch_accum.set_current_section('post-sync')
        self.instlObj.batch_accum += self.instlObj.platform_helper.copy_file_to_file("$(NEW_HAVE_INFO_MAP_PATH)",
                                                                                     "$(HAVE_INFO_MAP_PATH)")

        self.instlObj.batch_accum += self.instlObj.platform_helper.popd()
