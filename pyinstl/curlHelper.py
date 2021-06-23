#!/usr/bin/env python3.9


import os
import abc
import itertools
from pathlib import Path, PurePath
import sys
import functools
import logging
log = logging.getLogger()

import utils
from configVar import config_vars  # √
from . import connectionBase


class CUrlHelper(object, metaclass=abc.ABCMeta):
    """ Create download commands. Each function should be overridden to implement the download
        on specific platform using a specific copying tool. All functions return
        a list of commands, even if there is only one. This will allow to return
        multiple commands if needed.
    """
    curl_write_out_str = r'%{url_effective}, %{size_download} bytes, %{time_total} sec., %{speed_download} bps.\n'
    # for debugging:
    curl_extra_write_out_str = r'    num_connects:%{num_connects}, time_namelookup: %{time_namelookup}, time_connect: %{time_connect}, time_pretransfer: %{time_pretransfer}, time_redirect: %{time_redirect}, time_starttransfer: %{time_starttransfer}\n\n'

    def __init__(self) -> None:
        self.urls_to_download = list()
        self.urls_to_download_last = list()
        self.short_win_paths_cache = dict()

    def add_download_url(self, url, path, verbatim=False, size=0, download_last=False):
        if verbatim:
            translated_url = url
        else:
            translated_url = connectionBase.connection_factory(config_vars).translate_url(url)
        if download_last:
            self.urls_to_download_last.append((translated_url, path, size))
        else:
            self.urls_to_download.append((translated_url, path, size))

    def get_num_urls_to_download(self):
        return len(self.urls_to_download)+len(self.urls_to_download_last)

    def download_from_config_file(self, config_file):
        pass

    def fix_path(self, in_some_path_to_fix):
        """  On Windows: to overcome cUrl inability to handle path with unicode chars, we try to calculate the windows
                short path (DOS style 8.3 chars). The function that does that, win32api.GetShortPathName,
                does not work for paths that do not yet exist so we need to also create the folder.
                However if the creation requires admin permissions - it could fail -
                in which case we revert to using the long path.
        """

        fixed_path = PurePath(in_some_path_to_fix)
        if 'Win' in utils.get_current_os_names():
            # to overcome cUrl inability to handle path with unicode chars, we try to calculate the windows
            # short path (DOS style 8.3 chars). The function that does that, win32api.GetShortPathName,
            # does not work for paths that do not yet exist so we need to also create the folder.
            # However if the creation requires admin permissions - it could fail -
            # in which case we revert to using the long path.
            import win32api
            fixed_path_parent = str(fixed_path.parent)
            fixed_path_name = str(fixed_path.name)
            if fixed_path_parent not in self.short_win_paths_cache:
                try:
                    os.makedirs(fixed_path_parent, exist_ok=True)
                    short_parent_path = win32api.GetShortPathName(fixed_path_parent)
                    self.short_win_paths_cache[fixed_path_parent] = short_parent_path
                except Exception as e:  # failed to mkdir or get the short path? never mind, just use the full path
                    self.short_win_paths_cache[fixed_path_parent] = fixed_path_parent
                    log.warning(f"""warning creating short path failed for {fixed_path}, {e}, using long path""")

            short_file_path = os.path.join(self.short_win_paths_cache[fixed_path_parent], fixed_path_name)
            fixed_path = short_file_path.replace("\\", "\\\\")
        return fixed_path

    def create_config_files(self, curl_config_file_path, num_config_files):
        file_name_list = list()

        if self.get_num_urls_to_download() > 0:
            connect_time_out = str(config_vars.setdefault("CURL_CONNECT_TIMEOUT", "16"))
            max_time = str(config_vars.setdefault("CURL_MAX_TIME", "180"))
            retries = str(config_vars.setdefault("CURL_RETRIES", "2"))
            retry_delay = str(config_vars.setdefault("CURL_RETRY_DELAY", "8"))

            sync_urls_cookie = str(config_vars.get("COOKIE_FOR_SYNC_URLS", ""))

            actual_num_config_files = int(max(0, min(len(self.urls_to_download), num_config_files)))
            if self.urls_to_download_last:
                actual_num_config_files += 1
            num_digits = max(len(str(actual_num_config_files)), 2)
            file_name_list = ["-".join((os.fspath(curl_config_file_path), str(file_i).zfill(num_digits))) for file_i in range(actual_num_config_files)]

            # open the files make sure they have r/w permissions and are utf-8
            wfd_list = list()
            for file_name in file_name_list:
                wfd = utils.utf8_open_for_write(file_name, "w")
                wfd_list.append(wfd)

            # write the header in each file
            for wfd in wfd_list:
                basename = os.path.basename(wfd.name)
                if sync_urls_cookie:
                    cookie_text = f"cookie = {sync_urls_cookie}\n"
                else:
                    cookie_text = ""
                curl_write_out_str = CUrlHelper.curl_write_out_str
                file_header_text = f"""
insecure
raw
fail
silent
show-error
compressed
create-dirs
connect-timeout = {connect_time_out}
max-time = {max_time}
retry = {retries}
retry-delay = {retry_delay}
{cookie_text}
write-out = "Progress: ... of ...; {basename}: {curl_write_out_str}"


"""
                wfd.write(file_header_text)

            last_file = None
            if self.urls_to_download_last:
                last_file = wfd_list.pop()

            def url_sorter(l, r):
                """ smaller files should be downloaded first so the progress bar gets moving early. """
                return l[2] - r[2]  # non Info.xml files are sorted by size

            wfd_cycler = itertools.cycle(wfd_list)
            url_num = 0
            sorted_by_size = sorted(self.urls_to_download, key=functools.cmp_to_key(url_sorter))
            for url, path, size in sorted_by_size:
                fixed_path = self.fix_path(path)
                wfd = next(wfd_cycler)
                wfd.write(f'''url = "{url}"\noutput = "{fixed_path}"\n\n''')
                url_num += 1

            for wfd in wfd_list:
                wfd.close()

            for url, path, size in self.urls_to_download_last:
                fixed_path = self.fix_path(path)
                last_file.write(f'''url = "{url}"\noutput = "{fixed_path}"\n\n''')
                url_num += 1

            # insert None which means "wait" before the config file that downloads urls_to_download_last.
            # but only if there were actually download files other than urls_to_download_last.
            # it might happen that there are only urls_to_download_last - so no need to "wait".
            if last_file and len(wfd_list) > 0:
                file_name_list.insert(-1, None)

        return file_name_list
