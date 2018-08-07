#!/usr/bin/env python3

from collections import defaultdict
import urllib
import sys
if sys.platform == 'win32':
    import win32api

from .instlInstanceSyncBase import InstlInstanceSync
from . import connectionBase
from pybatch import *


class InstlInstanceSync_url(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj) -> None:
        super().__init__(instlObj)
        self.sync_base_url = None

    def init_sync_vars(self):
        super().init_sync_vars()
        self.local_sync_dir = config_vars["LOCAL_REPO_SYNC_DIR"].str()

    def create_sync_folders(self):
        create_sync_folders_accum_transaction = Section('create_sync_folders')

        create_sync_folders_accum_transaction += Progress("Create folders ...")
        need_download_dirs_num = self.instlObj.info_map_table.num_items(item_filter="need-download-dirs")
        create_sync_folders_accum_transaction += MakeDirs("$(TO_SYNC_INFO_MAP_PATH)")
        # TODO
        # self.instlObj.platform_helper.num_items_for_progress_report += need_download_dirs_num
        create_sync_folders_accum_transaction += Progress("Create folders done")
        self.instlObj.progress(f"{need_download_dirs_num} folders to create")
        return create_sync_folders_accum_transaction

    def get_cookie_for_sync_urls(self, sync_base_url):
        """ get the cookie for sync_base_url and set config var
            COOKIE_FOR_SYNC_URLS to the text of the cookie
        """
        net_loc = urllib.parse.urlparse(sync_base_url).netloc
        the_cookie = connectionBase.connection_factory().get_cookie(net_loc)
        if the_cookie:
            # the_cookie is actually a tuple ('Cookie', cookie_text)
            # we only need the second part
            config_vars["COOKIE_FOR_SYNC_URLS"] = the_cookie[1]

    def create_sync_urls(self, in_file_list):
        """ Create urls and local download paths for a list of file items.
            in_file_list is a list of SVNRow objects
            A url for a file can come from two sources:
            - If the file item has a predefined url it will be used, otherwise
            - the url is a concatenation of the base url, the file's repo-rev
            and the partial path. E.g.:
            "http://some.base.url/" + "07/27" + "/path/to/file"
            The download path is the resolved file item's download_path
        """
        self.sync_base_url = config_vars["SYNC_BASE_URL"].str()
        self.get_cookie_for_sync_urls(self.sync_base_url)
        for file_item in in_file_list:
            source_url = file_item['url']
            if source_url is None:
                repo_rev_folder_hierarchy = self.instlObj.repo_rev_to_folder_hierarchy(file_item['revision'])
                source_url = '/'.join(utils.make_one_list(self.sync_base_url, repo_rev_folder_hierarchy, file_item['path']))
            self.instlObj.platform_helper.dl_tool.add_download_url(source_url, file_item['download_path'], verbatim=source_url==['url'], size=file_item['size'])
        self.instlObj.progress(f"created sync urls for {len(in_file_list)} files")

    def create_curl_download_instructions(self):
        """ Download is done be creating files with instructions for curl - curl config files.
            Another file is created containing invocations of curl with each of the config files
            - the parallel run file.
            curl_config_folder: the folder where curl config files and parallel run file will be placed.
            num_config_files: the maximum number of curl config files.
            actual_num_config_files: actual number of curl config files created. Might be smaller
            than num_config_files, or might be 0 if downloading is not required.
        """
        create_curl_download_instructions_accum_transaction = Section('create_curl_download_instructions')

        main_out_file_dir, main_out_file_leaf = os.path.split(config_vars["__MAIN_OUT_FILE__"].str())
        curl_config_folder = os.path.join(main_out_file_dir, "curl")
        os.makedirs(curl_config_folder, exist_ok=True)
        curl_config_file_path = config_vars.resolve_str(os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME)"))
        num_config_files = int(config_vars["PARALLEL_SYNC"])
        # TODO: Move class someplace else
        config_file_list = self.instlObj.platform_helper.dl_tool.create_config_files(curl_config_file_path, num_config_files)

        actual_num_config_files = len(config_file_list)
        if actual_num_config_files > 0:
            if actual_num_config_files > 1:
                dl_start_message = f"Downloading with {actual_num_config_files} processes in parallel"
            else:
                dl_start_message = "Downloading with 1 process"
            create_curl_download_instructions_accum_transaction += Progress(dl_start_message)

            parallel_run_config_file_path = config_vars.resolve_str(
                os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME).parallel-run"))
            self.create_parallel_run_config_file(parallel_run_config_file_path, config_file_list)
            create_curl_download_instructions_accum_transaction += ParallelRun(parallel_run_config_file_path, True)

            num_files_to_download = int(config_vars["__NUM_FILES_TO_DOWNLOAD__"])
            if num_files_to_download > 1:
                dl_end_message = f"Downloading {num_files_to_download} files done"
            else:
                dl_end_message = "Downloading 1 file done"
            create_curl_download_instructions_accum_transaction += Progress(dl_end_message)
            return create_curl_download_instructions_accum_transaction

    def create_parallel_run_config_file(self, parallel_run_config_file_path, config_files):
        with utils.utf8_open(parallel_run_config_file_path, "w") as wfd:
            utils.make_open_file_read_write_for_all(wfd)
            for config_file in config_files:
                if sys.platform == 'win32':
                    # curl on windows has problem with path to config files that have unicode characters
                    normalized_path = win32api.GetShortPathName(config_file)
                wfd.write(config_vars.resolve_str(f'''"$(DOWNLOAD_TOOL_PATH)" --config "{normalized_path}"\n'''))

    def create_check_checksum_instructions(self, num_files):
        create_check_checksum_instructions_accum_transaction = Section('create_check_checksum_instructions')

        create_check_checksum_instructions_accum_transaction += Progress("Check checksum ...")
        create_check_checksum_instructions_accum_transaction += CheckDownloadFolderChecksum("$(TO_SYNC_INFO_MAP_PATH)")
        self.instlObj.platform_helper.num_items_for_progress_report += num_files
        create_check_checksum_instructions_accum_transaction += Progress("Check checksum done")
        self.instlObj.progress(f"created checksum checks {num_files} files")
        return create_check_checksum_instructions_accum_transaction

    def create_instructions_to_remove_redundant_files_in_sync_folder(self):
        """ Remove files in the sync folder that are not in info_map
            sync folder is scanned and list of files is created - the list has both the full path to file and partial path
            as it appears in the info_map db. The list is processed against the db which returns the indexes of the redundant
            files. The full path versions of the indexed files is used to create remove instructions
        """
        self.instlObj.progress("removing redundant files from sync folder")
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
        rm_commands = []
        for i in redundant_files_indexes:
            rm_commands += RmFile(str(files_to_check[i][1]))
            rm_commands += Progress(f"Removed redundant file {files_to_check[i][1]}")
        return rm_commands

    def create_download_instructions(self):
        download_instructions_accum_transaction = Section('download_instructions')

        already_synced_num_files, already_synced_num_bytes = self.instlObj.info_map_table.get_not_to_download_num_files_and_size()
        to_sync_num_files, bytes_to_sync = self.instlObj.info_map_table.get_to_download_num_files_and_size()
        config_vars["__NUM_FILES_TO_DOWNLOAD__"] = to_sync_num_files
        config_vars["__NUM_BYTES_TO_DOWNLOAD__"] = bytes_to_sync

        # notify user how many files and bytes to sync
        self.instlObj.progress(f"{to_sync_num_files} of {to_sync_num_files+already_synced_num_files} files to sync")
        self.instlObj.progress(f"{bytes_to_sync} of {bytes_to_sync+already_synced_num_bytes} bytes to sync")

        if already_synced_num_files > 0:
            download_instructions_accum_transaction += Progress(f"{already_synced_num_files} files already in cache")

        if to_sync_num_files == 0:
            return download_instructions_accum_transaction

        file_list = self.instlObj.info_map_table.get_download_items_sync_info()
        if False:   # need to rethink how to calc mount point sizes efficiently
            mount_points_to_size = total_sizes_by_mount_point(file_list)

            for m_p in sorted(mount_points_to_size):
                free_bytes = shutil.disk_usage(m_p).free
                print(mount_points_to_size[m_p], "bytes to sync to drive", "".join(("'", m_p, "'")), free_bytes-mount_points_to_size[m_p], "bytes will remain")

        download_instructions_accum_transaction += self.create_sync_folders()
        self.create_sync_urls(file_list)
        download_instructions_accum_transaction += self.create_curl_download_instructions()

        download_instructions_accum_transaction += self.instlObj.create_sync_folder_manifest_command("after-sync", back_ground=True)
        download_instructions_accum_transaction += self.create_check_checksum_instructions(to_sync_num_files)
        return download_instructions_accum_transaction

    def create_sync_instructions(self):
        sections = []
        self.instlObj.progress("create sync instructions ...")
        before_sync_accum_transaction = Section("before_sync")
        before_sync_accum_transaction += self.instlObj.create_sync_folder_manifest_command("before-sync", back_ground=False)
        sections.append(before_sync_accum_transaction)

        sync_accum_transaction = Section("sync")
        sync_accum_transaction += Progress("Start sync")
        self.prepare_list_of_sync_items()

        sync_accum_transaction += Progress("Starting sync from $(SYNC_BASE_URL)")
        sync_accum_transaction += MakeDirs("$(LOCAL_REPO_SYNC_DIR)")

        with sync_accum_transaction.sub_accum(Cd("$(LOCAL_REPO_SYNC_DIR)")) as cd_local_repo_sync_dir_accum_transaction:
            cd_local_repo_sync_dir_accum_transaction += self.create_instructions_to_remove_redundant_files_in_sync_folder()
            cd_local_repo_sync_dir_accum_transaction += self.create_download_instructions()

            with cd_local_repo_sync_dir_accum_transaction.sub_accum(Section("post_sync")) as post_sync_accum_transaction:
                self.chown_for_synced_folders()
                post_sync_accum_transaction += CopyFileToFile("$(NEW_HAVE_INFO_MAP_PATH)", "$(HAVE_INFO_MAP_PATH)")

        self.instlObj.progress("create sync instructions done")
        sync_accum_transaction += Progress("Done sync")
        sections.append(sync_accum_transaction)
        return sections

    def create_no_sync_instructions(self):
        """ in case no files needed syncing """
        no_sync_instructions_accum_transacion = Section('post_sync')
        no_sync_instructions_accum_transacion += CopyFileToFile("$(NEW_HAVE_INFO_MAP_PATH)", "$(HAVE_INFO_MAP_PATH)")
        no_sync_instructions_accum_transacion += Progress("Done sync")
        return no_sync_instructions_accum_transacion

    def chown_for_synced_folders(self):
        """ if sync is done under admin permissions owner of files and folders will be root
            chown_for_synced_folders will change owner to the user that created the batch file.
            Currently this was found to be relevant for Mac only.
        """
        if config_vars["__CURRENT_OS__"].str() != "Mac":
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
