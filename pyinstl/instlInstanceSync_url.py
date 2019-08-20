#!/usr/bin/env python3.6

from collections import defaultdict
import urllib
import sys
from pathlib import PurePath
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
        self.local_sync_dir = os.fspath(config_vars["LOCAL_REPO_SYNC_DIR"])

    def create_sync_folders(self):

        create_sync_folders_commands = AnonymousAccum()

        create_sync_folders_commands += Progress("Create folders ...")
        need_download_dirs_num = self.instlObj.info_map_table.num_items(item_filter="need-download-dirs")
        create_sync_folders_commands += CreateSyncFolders()
        # TODO
        # self.instlObj.platform_helper.num_items_for_progress_report += need_download_dirs_num
        self.instlObj.progress(f"{need_download_dirs_num} folders to create")

        all_sync_dirs = set(config_vars["ALL_SYNC_DIRS"])
        for sync_dir in sorted(all_sync_dirs):
            if config_vars["__CURRENT_OS__"].str() == "Mac":
                create_sync_folders_commands += Chown(path=sync_dir, user_id=int(config_vars.get("ACTING_UID", -1)), group_id=int(config_vars.get("ACTING_GID", -1)), recursive=True)
            elif config_vars["__CURRENT_OS__"].str() == "Win":
                create_sync_folders_commands += FullACLForEveryone(path=sync_dir)

        return create_sync_folders_commands

    def get_cookie_for_sync_urls(self, sync_base_url):
        """ get the cookie for sync_base_url and set config var
            COOKIE_FOR_SYNC_URLS to the text of the cookie
        """
        net_loc = urllib.parse.urlparse(sync_base_url).netloc
        the_cookie = connectionBase.connection_factory(config_vars).get_cookie(net_loc)
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
        url_start_cache = dict()
        for file_item in in_file_list:
            source_url = file_item.url
            if source_url is None:
                repo_rev_folder_hierarchy = self.instlObj.repo_rev_to_folder_hierarchy(file_item.revision)
                sync_base_url = self.instlObj.info_map_table.get_sync_base_url_for_iid(file_item.needed_for_iid, "$(SYNC_BASE_URL)", url_start_cache)
                source_url = '/'.join(utils.make_one_list(sync_base_url, repo_rev_folder_hierarchy, file_item.path))
            self.instlObj.dl_tool.add_download_url(source_url, file_item.download_path, verbatim=source_url==['url'], size=file_item.size, download_last=source_url.endswith('Info.xml'))
        self.instlObj.progress(f"created download urls for {len(in_file_list)} files")

    def create_curl_download_instructions(self):
        """ Download is done be creating files with instructions for curl - curl config files.
            Another file is created containing invocations of curl with each of the config files
            - the parallel run file.
            curl_config_folder: the folder where curl config files and parallel run file will be placed.
            num_config_files: the maximum number of curl config files.
            actual_num_config_files: actual number of curl config files created. Might be smaller
            than num_config_files, or might be 0 if downloading is not required.
        """
        dl_commands = AnonymousAccum()

        main_out_file_dir, main_out_file_leaf = os.path.split(os.fspath(config_vars["__MAIN_OUT_FILE__"]))
        curl_config_folder = os.path.join(main_out_file_dir, main_out_file_leaf+"_curl")
        os.makedirs(curl_config_folder, exist_ok=True)
        curl_config_file_path = config_vars.resolve_str(os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME)"))
        num_config_files = int(config_vars["PARALLEL_SYNC"])
        # TODO: Move class someplace else
        config_file_list = self.instlObj.dl_tool.create_config_files(curl_config_file_path, num_config_files)

        actual_num_config_files = len(config_file_list)
        if actual_num_config_files > 0:
            if actual_num_config_files > 1:
                dl_start_message = f"Downloading with {actual_num_config_files} processes in parallel"
            else:
                dl_start_message = "Downloading with 1 process"
            dl_commands += Progress(dl_start_message)

            num_files_to_download = int(config_vars["__NUM_FILES_TO_DOWNLOAD__"])

            parallel_run_config_file_path = config_vars.resolve_str(
                os.path.join(curl_config_folder, "$(CURL_CONFIG_FILE_NAME).parallel-run"))
            self.create_parallel_run_config_file(parallel_run_config_file_path, config_file_list)
            dl_commands += ParallelRun(parallel_run_config_file_path, shell=False, own_progress_count=num_files_to_download, report_own_progress=False)

            if num_files_to_download > 1:
                dl_end_message = f"Downloading {num_files_to_download} files done"
            else:
                dl_end_message = "Downloading 1 file done"

            dl_commands += Progress(dl_end_message)

            return dl_commands

    def create_parallel_run_config_file(self, parallel_run_config_file_path, config_files):
        with utils.utf8_open_for_write(parallel_run_config_file_path, "w") as wfd:
            for config_file in config_files:
                if config_file is None:  # None means to insert a wait
                    wfd.write("wait\n")
                else:
                    if sys.platform == 'win32':
                        # curl on windows has problem with path to config files that have unicode characters
                        normalized_path = win32api.GetShortPathName(config_file)
                    else:
                        normalized_path = config_file
                    wfd.write(config_vars.resolve_str(f'''"$(DOWNLOAD_TOOL_PATH)" --config "{normalized_path}"\n'''))

    def create_check_checksum_instructions(self, num_files):
        check_checksum_instructions_accum = AnonymousAccum()

        check_checksum_instructions_accum += Progress("Check checksum ...", own_progress_count=num_files)
        check_checksum_instructions_accum += CheckDownloadFolderChecksum()
        self.instlObj.progress(f"created checksum checks {num_files} files")
        return check_checksum_instructions_accum

    def create_instructions_to_remove_redundant_files_in_sync_folder(self):
        """ Remove files in the sync folder that are not in info_map
            sync folder is scanned and list of files is created - the list has both the full path to file and partial path
            as it appears in the info_map db. The list is processed against the db which returns the indexes of the redundant
            files. The full path versions of the indexed files is used to create remove instructions
        """
        self.instlObj.progress("removing redundant files from sync folder")
        pure_local_sync_dir = PurePath(self.local_sync_dir)
        files_to_check = list()
        for root, dirs, files in os.walk(self.local_sync_dir, followlinks=False):
            try: dirs.remove("bookkeeping")
            except Exception: pass # todo: use FOLDER_EXCLUDE_REGEX
            try: files.remove(".DS_Store")
            except Exception: pass  # todo: use FILE_EXCLUDE_REGEX
            for disk_item in files:
                item_full_path = PurePath(root, disk_item)
                item_partial_path = item_full_path.relative_to(pure_local_sync_dir).as_posix()
                files_to_check.append(item_partial_path)
        files_to_check.sort()
        redundant_files = self.instlObj.info_map_table.get_files_that_should_be_removed_from_sync_folder(files_to_check)
        rm_commands = AnonymousAccum()
        for f in redundant_files:
            item_full_path = pure_local_sync_dir.joinpath(f)
            #log.info(f"remove redundant {item_full_path}")
            rm_commands += RmFile(f)
        return rm_commands

    def create_download_instructions(self):
        dl_commands = AnonymousAccum()
        already_synced_num_files, already_synced_num_bytes = self.instlObj.info_map_table.get_not_to_download_num_files_and_size()
        to_sync_num_files, bytes_to_sync = self.instlObj.info_map_table.get_to_download_num_files_and_size()
        config_vars["__NUM_FILES_TO_DOWNLOAD__"] = to_sync_num_files
        config_vars["__NUM_BYTES_TO_DOWNLOAD__"] = bytes_to_sync

        # notify user how many files and bytes to download
        self.instlObj.progress(f"{to_sync_num_files} of {to_sync_num_files+already_synced_num_files} files to download")
        self.instlObj.progress(f"{bytes_to_sync} of {bytes_to_sync+already_synced_num_bytes} bytes to download")

        if already_synced_num_files > 0:
            dl_commands += Progress(f"{already_synced_num_files} files already in cache", own_progress_count=already_synced_num_files)

        if to_sync_num_files == 0:
            return dl_commands

        file_list = self.instlObj.info_map_table.get_download_items(what="file")
        if False:   # need to rethink how to calc mount point sizes efficiently
            mount_points_to_size = total_sizes_by_mount_point(file_list)

            for m_p in sorted(mount_points_to_size):
                free_bytes = shutil.disk_usage(m_p).free
                log.info(f"""{mount_points_to_size[m_p]} bytes to download to drive {"".join(("'", m_p, "'"))} {free_bytes-mount_points_to_size[m_p]} bytes will remain""")

        dl_commands += self.create_sync_folders()
        self.create_sync_urls(file_list)
        dl_commands += self.create_curl_download_instructions()

        dl_commands += self.instlObj.create_sync_folder_manifest_command("after-sync", back_ground=True)
        dl_commands += self.create_check_checksum_instructions(to_sync_num_files)
        return dl_commands

    def create_sync_instructions(self) -> int:
        super().create_sync_instructions()

        self.instlObj.progress("create download instructions ...")

        with self.instlObj.batch_accum.sub_accum(Stage("download", "$(SYNC_BASE_URL)")) as sync_accum:
            self.prepare_list_of_sync_items()

            sync_accum += MakeDirs("$(LOCAL_REPO_SYNC_DIR)")

            with sync_accum.sub_accum(Cd("$(LOCAL_REPO_SYNC_DIR)")) as local_repo_sync_dir_accum:
                with local_repo_sync_dir_accum.sub_accum(Stage("remove_redundant_files_in_sync_folder")) as rrfisf:
                    rrfisf += self.create_instructions_to_remove_redundant_files_in_sync_folder()

                local_repo_sync_dir_accum += self.create_download_instructions()

                with local_repo_sync_dir_accum.sub_accum(Stage("post_sync")) as post_sync_accum_transaction:

                    if int(config_vars["__NUM_FILES_TO_DOWNLOAD__"]) > 0:
                        post_sync_accum_transaction += self.chown_for_synced_folders()
                        self.instlObj.progress("create download instructions done")
                    post_sync_accum_transaction += CopyFileToFile("$(NEW_HAVE_INFO_MAP_PATH)", "$(HAVE_INFO_MAP_PATH)", hard_links=False, copy_owner=True)

        sync_accum += Progress("Done sync")

    def chown_for_synced_folders(self):
        """ if sync is done under admin permissions owner of files and folders will be root
            chown_for_synced_folders will change owner to the user that created the batch file.
            Currently this was found to be relevant for Mac only.
        """
        chown_accum = AnonymousAccum()
        if config_vars["__CURRENT_OS__"].str() == "Mac":  # owner issue only relevant on Mac
            download_roots = self.instlObj.info_map_table.get_download_roots()
            if download_roots:
                for dr in download_roots:
                    chown_accum += Progress(f"Adjust ownership and permissions {dr}...")
                    chown_accum += ChmodAndChown(path=dr, mode="a+rwX", user_id=int(config_vars.get("ACTING_UID", -1)), group_id=int(config_vars.get("ACTING_GID", -1)), recursive=True, ignore_all_errors=True) # all copied files and folders should be rw
        return chown_accum


def total_sizes_by_mount_point(file_list):
    mount_points_to_size = defaultdict(int)
    for a_file in file_list:
        mount_p = utils.find_mount_point(a_file.download_path)
        mount_points_to_size[mount_p] += a_file.size
    return mount_points_to_size
