#!/usr/bin/env python3


import os
import pathlib
from collections import defaultdict
import shutil
import urllib

import utils
from .instlInstanceSyncBase import InstlInstanceSync
from configVar import var_stack
from . import connectionBase


class InstlInstanceSync_url(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj):
        super().__init__(instlObj)
        self.sync_base_url = None

    def init_sync_vars(self):
        super().init_sync_vars()
        self.local_sync_dir = var_stack.ResolveVarToStr("LOCAL_REPO_SYNC_DIR")

    def create_sync_folders(self):
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Create folders ...")
        need_download_dirs_list = self.instlObj.info_map_table.get_download_items(what="dir")
        self.instlObj.batch_accum += self.instlObj.platform_helper.create_folders("$(TO_SYNC_INFO_MAP_PATH)")
        self.instlObj.platform_helper.num_items_for_progress_report += len(need_download_dirs_list)
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Create folders done")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()
        self.instlObj.progress("{} folders to create".format(len(need_download_dirs_list)))

    def get_cookie_for_sync_urls(self, sync_base_url):
        """ get the cookie for sync_base_url and set config var
            COOKIE_FOR_SYNC_URLS to the text of the cookie
        """
        net_loc = urllib.parse.urlparse(sync_base_url).netloc
        the_cookie = connectionBase.connection_factory().get_cookie(net_loc)
        if the_cookie:
            # the_cookie is actually a tuple ('Cookie', cookie_text)
            # we only need the second part
            var_stack.set_var("COOKIE_FOR_SYNC_URLS").append(the_cookie[1])

    def create_sync_urls(self, in_file_list):
        """ Create urls and local download paths for a list of file items.
            in_file_list is a list of SVNRow objects
            A url for a file can come from two sources:
            - If the file item has a predefined url it will be used, otherwise
            - the url is a concatenation of the base url, the file's repo-rev
            and the partial path. E.g.:
            "http://some.base.url/" + "727/" + "path/to/file"
            The download path is the resolved file item's download_path
        """
        self.sync_base_url = var_stack.ResolveVarToStr("SYNC_BASE_URL")
        self.get_cookie_for_sync_urls(self.sync_base_url)
        for file_item in in_file_list:
            source_url = file_item.url
            if source_url is None:
                source_url = '/'.join(utils.make_one_list(self.sync_base_url, str(file_item.revision), file_item.path))
            self.instlObj.platform_helper.dl_tool.add_download_url(source_url, file_item.download_path, verbatim=source_url==file_item.url, size=file_item.size)
        self.instlObj.progress("created sync urls for {} files".format(len(in_file_list)))

    def create_curl_download_instructions(self):
        """ Download is done be creating files with instructions for curl - curl config files.
            Another file is created containing invocations of curl with each of the config files
            - the parallel run file.
            curl_config_folder: the folder where curl config files and parallel run file will be placed.
            num_config_files: the maximum number of curl config files.
            actual_num_config_files: actual number of curl config files created. Might be smaller
            than num_config_files, or might be 0 if downloading is not required.
        """
        main_out_file_dir, main_out_file_leaf = os.path.split(var_stack.ResolveVarToStr("__MAIN_OUT_FILE__"))
        curl_config_folder = os.path.join(main_out_file_dir, "curl")
        os.makedirs(curl_config_folder, exist_ok=True)
        curl_config_file_path = var_stack.ResolveStrToStr(os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME)"))
        num_config_files = int(var_stack.ResolveVarToStr("PARALLEL_SYNC"))
        config_file_list = self.instlObj.platform_helper.dl_tool.create_config_files(curl_config_file_path, num_config_files)

        actual_num_config_files = len(config_file_list)
        if actual_num_config_files > 0:
            if actual_num_config_files > 1:
                dl_start_message = "Downloading with {} processes in parallel".format(actual_num_config_files)
            else:
                dl_start_message = "Downloading with 1 process"
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress(dl_start_message)

            parallel_run_config_file_path = var_stack.ResolveStrToStr(
                os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME).parallel-run"))
            self.instlObj.batch_accum += self.instlObj.platform_helper.dl_tool.download_from_config_files(
                parallel_run_config_file_path, config_file_list)

            num_files_to_download = int(var_stack.ResolveVarToStr("__NUM_FILES_TO_DOWNLOAD__"))
            if num_files_to_download > 1:
                dl_end_message = "Downloading {} files done".format(num_files_to_download)
            else:
                dl_end_message = "Downloading 1 file done"
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress(dl_end_message, self.files_to_download)
            self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

    def create_check_checksum_instructions(self, in_file_list):
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Check checksum ...")
        self.instlObj.batch_accum += self.instlObj.platform_helper.check_checksum_for_folder("$(TO_SYNC_INFO_MAP_PATH)")
        self.instlObj.platform_helper.num_items_for_progress_report += len(in_file_list)
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Check checksum done")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()
        self.instlObj.progress("created checksum checks {} files".format(len(in_file_list)))

    def create_instructions_to_remove_redundant_files_in_sync_folder(self):
        """ Remove files in the sync folder that are not in info_map
            sync folder is scanned and list of files is created - the list has both the full path to file and partial path
            as it appears in the info_map db. The list is processed against the db which returns the indexes of the redundant
            files. The full path versions of the indexed files is used to create remove instructions
        """
        pure_local_sync_dir = pathlib.PurePath(self.local_sync_dir)
        files_to_check = list()
        for root, dirs, files in os.walk(self.local_sync_dir, followlinks=False):
            try: dirs.remove("bookkeeping")
            except Exception: pass # todo: use FOLDER_EXCLUDE_REGEX
            try: files.remove(".DS_Store")
            except Exception: pass  # todo: use FILE_EXCLUDE_REGEX
            for disk_item in files:
                item_full_path = pathlib.PurePath(root, disk_item)
                item_partial_path = item_full_path.relative_to(pure_local_sync_dir).as_posix()
                files_to_check.append((item_partial_path, item_full_path))
        redundant_files_indexes = self.instlObj.info_map_table.get_files_that_should_be_removed_from_sync_folder(files_to_check)
        for i in redundant_files_indexes:
            self.instlObj.batch_accum += self.instlObj.platform_helper.rmfile(str(files_to_check[i][1]))
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Removed redundant file "+str(files_to_check[i][1]))
        return len(redundant_files_indexes)

    def create_download_instructions(self):
        self.instlObj.batch_accum.set_current_section('sync')

        already_synced_num_files, already_synced_num_bytes = self.instlObj.info_map_table.get_not_to_download_num_files_and_size()
        file_list, bytes_to_sync = self.instlObj.info_map_table.get_to_download_files_and_size()
        to_sync_num_files = len(file_list)
        var_stack.add_const_config_variable("__NUM_FILES_TO_DOWNLOAD__", "create_download_instructions", len(file_list))
        var_stack.add_const_config_variable("__NUM_BYTES_TO_DOWNLOAD__", "create_download_instructions", bytes_to_sync)

        # notify user how many files and bytes to sync
        print(to_sync_num_files, "of", to_sync_num_files+already_synced_num_files, "files to sync")
        print(bytes_to_sync, "of", bytes_to_sync+already_synced_num_bytes, "bytes to sync")

        if already_synced_num_files > 0:
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress("files in cache", already_synced_num_files)

        if to_sync_num_files == 0:
            return to_sync_num_files

        mount_points_to_size = total_sizes_by_mount_point(file_list)

        for m_p in sorted(mount_points_to_size):
            free_bytes = shutil.disk_usage(m_p).free
            print(mount_points_to_size[m_p], "bytes to sync to drive", "".join(("'", m_p, "'")), free_bytes-mount_points_to_size[m_p], "bytes will remain")

        self.create_sync_folders()

        self.create_sync_urls(file_list)

        self.create_curl_download_instructions()
        self.instlObj.create_sync_folder_manifest_command("after-sync", back_ground=True)
        self.create_check_checksum_instructions(file_list)
        return to_sync_num_files

    def create_sync_instructions(self):
        self.instlObj.progress("create sync instructions ...")
        self.instlObj.create_sync_folder_manifest_command("before-sync", back_ground=False)
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Start sync")
        retVal = super().create_sync_instructions()
        self.prepare_list_of_sync_items()

        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Starting sync from $(SYNC_BASE_URL)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.mkdir("$(LOCAL_REPO_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        retVal += self.create_instructions_to_remove_redundant_files_in_sync_folder()
        retVal += self.create_download_instructions()
        self.instlObj.batch_accum.set_current_section('post-sync')
        self.chown_for_synced_folders()

        self.instlObj.batch_accum += self.instlObj.platform_helper.copy_file_to_file("$(NEW_HAVE_INFO_MAP_PATH)",
                                                                                     "$(HAVE_INFO_MAP_PATH)")

        self.instlObj.batch_accum += self.instlObj.platform_helper.popd()
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Done sync")
        self.instlObj.progress("create sync instructions done")
        return retVal

    def create_no_sync_instructions(self):
        """ in case no files needed syncing """
        self.instlObj.batch_accum.set_current_section('post-sync')
        self.instlObj.batch_accum += self.instlObj.platform_helper.copy_file_to_file("$(NEW_HAVE_INFO_MAP_PATH)",
                                                                                     "$(HAVE_INFO_MAP_PATH)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Done sync")

    def chown_for_synced_folders(self):
        """ if sync is done under admin permissions owner of files and folders will be root
            chown_for_synced_folders will change owner to the user that created the batch file.
            Currently this was found to be relevant for Mac only.
        """
        if var_stack.ResolveVarToStr("__CURRENT_OS__") != "Mac":
            return  # owner issue only relevant on Mac
        download_roots = self.instlObj.info_map_table.get_download_roots()
        if download_roots:
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Adjust ownership and permissions ...")
            for dr in download_roots:
                self.instlObj.batch_accum += self.instlObj.platform_helper.chown("$(__USER_ID__)", "$(__GROUP_ID__)", dr, recursive=True)
            self.instlObj.batch_accum += self.instlObj.platform_helper.chmod("-R -f a+rwX", dr)
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Adjust ownership and permissions done")
            self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()


def total_sizes_by_mount_point(file_list):
    mount_points_to_size = defaultdict(int)
    for a_file in file_list:
        mount_p = utils.find_mount_point(a_file.download_path)
        mount_points_to_size[mount_p] += a_file.size
    return mount_points_to_size
