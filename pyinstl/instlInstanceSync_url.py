#!/usr/bin/env python2.7
from __future__ import print_function

import logging

from pyinstl.utils import *
from pyinstl import svnTree
from instlInstanceSyncBase import InstlInstanceSync
from batchAccumulator import BatchAccumulator
from configVarStack import var_stack


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
                file_path = os.path.join(*make_one_list(self.base_path, svn_item.full_path_parts()))
                need_to_download = need_to_download_file(file_path, svn_item.checksum())
                # a hack to force download of wtars if they were not unwtared correctly.
                # Actually a full download is not needed but there is not other way to force
                # post sync processing. Also folder might exist even if unwtar was not completed.
                # So Todo: find way to force unwtar without marking the item for download.
                if not need_to_download and svn_item.name().endswith(".wtar"):
                    unwtared_folder, _ = os.path.splitext(file_path)
                    if not os.path.isdir(unwtared_folder):
                        need_to_download = True
                retVal = not need_to_download
            elif svn_item.isDir():
                retVal = len(svn_item.subs()) == 0
            return retVal

    def mark_required_items_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        remote_sub_item = self.work_info_map.get_item_at_path(source[0])
        if remote_sub_item is None:
            # if item was not found it might have been wtared. So look for wtar parts and mark them.
            item_is_wtared = self.mark_wtar_items_for_source(source)
            if not item_is_wtared:
                raise ValueError(source[0], var_stack.resolve("does not exist in remote map, IID: $(iid_iid)"))
        else:
            if source[1] == '!file':
                if not remote_sub_item.isFile():
                    raise ValueError(source[0], "has type", source[1],
                                     var_stack.resolve("but is not a file, IID: $(iid_iid)"))
                remote_sub_item.set_user_data_non_recursive(True)
            elif source[1] == '!files':
                if not remote_sub_item.isDir():
                    raise ValueError(source[0], "has type", source[1],
                                     var_stack.resolve("but is not a dir, IID: $(iid_iid)"))
                remote_sub_item.set_user_data_files_recursive(True)
            elif source[1] == '!dir' or source[1] == '!dir_cont':  # !dir and !dir_cont are only different when copying
                if not remote_sub_item.isDir():
                    raise ValueError(source[0], "has type", source[1],
                                     var_stack.resolve("but is not a dir, IID: $(iid_iid)"))
                remote_sub_item.set_user_data_all_recursive(True)


    def mark_wtar_items_for_source(self, source):
        split_source_folder, split_source_leaf = os.path.split(source[0])
        parent_folder_item = self.work_info_map.get_item_at_path(split_source_folder)
        if parent_folder_item is None:
            raise ValueError(split_source_folder, var_stack.resolve("does not exist in remote map, IID: $(iid_iid)"))

        wtar_files_count = 0
        for wtar_file in parent_folder_item.walk_items_with_filter(a_filter=svnTree.WtarFilter(split_source_leaf), what="file"):
            wtar_file.set_user_data_non_recursive(True)
            wtar_files_count += 1
        retVal = wtar_files_count > 0
        return retVal  # return True is at least one wtar file was found for the source

    def create_download_instructions(self):
        self.instlObj.batch_accum.set_current_section('sync')
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress(
            "Starting sync from $(SYNC_BASE_URL)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.mkdir("$(LOCAL_REPO_SYNC_DIR)")
        self.instlObj.batch_accum += self.instlObj.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
        self.sync_base_url = var_stack.resolve("$(SYNC_BASE_URL)")

        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        file_list, dir_list = self.work_info_map.sorted_sub_items()

        prefix_accum = BatchAccumulator()  # sub-accumulator for prefix instructions
        prefix_accum.set_current_section('sync')
        for need_item in file_list + dir_list:
            self.create_prefix_instructions_for_item(prefix_accum, need_item)
        if len(prefix_accum) > 0:
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Pre download processing")
            self.instlObj.batch_accum.merge_with(prefix_accum)
            self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        num_dirs_to_create = self.work_info_map.num_subs_in_tree(what="dir")
        logging.info("Num directories to create: %d", num_dirs_to_create)
        self.instlObj.batch_accum += self.instlObj.platform_helper.create_folders("$(TO_SYNC_INFO_MAP_PATH)")
        self.instlObj.platform_helper.num_items_for_progress_report += num_dirs_to_create
        self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Create folders")
        self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        self.work_info_map.set_user_data_all_recursive(False)  # items that need checksum will be marked True

        import time
        before_time = time.time()
        for need_item in file_list + dir_list:
            self.create_download_instructions_for_item(need_item)
        after_time = time.time()
        if self.instlObj.platform_helper.dl_tool.get_num_urls_to_download() > 0:
            elapsed_time = after_time - before_time
            print("Create urls", "time:", round(elapsed_time, 2), "sec.", self.instlObj.platform_helper.dl_tool.get_num_urls_to_download()/elapsed_time, "urls per sec.")

        var_stack.add_const_config_variable("__NUM_FILES_TO_DOWNLOAD__", "create_download_instructions",
                                           self.instlObj.platform_helper.dl_tool.get_num_urls_to_download())

        print(self.instlObj.platform_helper.dl_tool.get_num_urls_to_download(), "files to sync")
        logging.info("Num files to sync: %d", self.instlObj.platform_helper.dl_tool.get_num_urls_to_download())

        curl_config_folder = self.instlObj.get_default_sync_dir(continue_dir="curl", mkdir=True)
        safe_makedirs(curl_config_folder)
        curl_config_file_path = var_stack.resolve(os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME)"), raise_on_fail=True)
        num_config_files = int(var_stack.resolve("$(PARALLEL_SYNC)"))
        config_file_list = self.instlObj.platform_helper.dl_tool.create_config_files(curl_config_file_path,
                                                                                     num_config_files)
        logging.info("Num parallel syncs: %d", len(config_file_list))
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

        num_files_to_check = self.work_info_map.num_subs_in_tree(what="file")
        logging.info("Num files to checksum check: %d", num_files_to_check)
        if num_files_to_check > 0:
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Checking checksum...")
            self.instlObj.batch_accum += self.instlObj.platform_helper.check_checksum_for_folder(
                "$(TO_SYNC_INFO_MAP_PATH)")
            self.instlObj.platform_helper.num_items_for_progress_report += num_files_to_check
            self.instlObj.batch_accum += self.instlObj.platform_helper.progress("Check checksum done")
            self.instlObj.batch_accum += self.instlObj.platform_helper.new_line()

        self.instlObj.batch_accum += self.instlObj.platform_helper.popd()

    def create_prefix_instructions_for_item(self, accum, item, path_so_far=list()):
        if item.isSymlink():
            print("Found symlink at", item.full_path())
        elif item.isFile():
            pass
        elif item.isDir():
            pass
            # path_so_far.append(item.name())
            #file_list, dir_list = item.sorted_sub_items()
            # do something
            #for sub_item in file_list + dir_list:
            #    self.create_prefix_instructions_for_item(accum, sub_item, path_so_far)
            #path_so_far.pop()


    def create_download_instructions_for_item(self, item, path_so_far=list()):
        if item.isSymlink():
            print("Found symlink at", item.full_path())
        elif item.isFile():
            file_path = os.path.join(*make_one_list(self.local_sync_dir, item.full_path_parts()))
            need_to_download = need_to_download_file(file_path, item.checksum())
            item.set_user_data_non_recursive(need_to_download)
            if need_to_download:
                self.files_to_download += 1
                # For some files a stamp file (.done) is placed after post-download processing. Remove such file if it exist
                done_stam__path = os.path.join(*make_one_list(self.local_sync_dir, path_so_far, item.name() + ".done"))
                safe_remove_file(done_stam__path)

                source_url = '/'.join(make_one_list(self.sync_base_url, str(item.last_rev()), path_so_far, item.name()))
                self.instlObj.platform_helper.dl_tool.add_download_url(source_url, item.full_path())
        elif item.isDir():
            path_so_far.append(item.name())
            file_list, dir_list = item.sorted_sub_items()
            for sub_item in file_list + dir_list:
                self.create_download_instructions_for_item(sub_item, path_so_far)
            path_so_far.pop()
