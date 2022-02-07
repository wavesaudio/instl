import contextlib
from typing import List
from pathlib import Path

import requests
from http.cookies import SimpleCookie

from requests.cookies import cookiejar_from_dict

from configVar import config_vars
from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDir
import utils


class DownloadManager(PythonBatchCommandBase):
    def __init__(self, cookie: str = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cookie = cookie
        self.session = self.download_session()

    def repr_own_args(self, all_args: List[str]) -> None:

        if self.cookie:
            all_args.append(f"cookie=\"{self.cookie}\"")

    def progress_msg_self(self):
        the_progress_msg = f"Downloading file '"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        with self.session as dl_session:
            url = kwargs["url"]
            path = Path(kwargs["path"])
            checksum = kwargs["checksum"]
            if path.is_dir():
                filename = Path(url.split("/").pop())
                path = path.joinpath(filename)
            with MakeDir(path.parent, report_own_progress=False) as dir_maker:
                dir_maker()
            with open(path, "wb") as fo:
                timeout_seconds = int(config_vars.get("CURL_MAX_TIME", 480))
                super().increment_and_output_progress(increment_by=0,
                                                      prog_msg=f"downloaded {path}")
                read_data = dl_session.get(url, timeout=timeout_seconds)
                read_data.raise_for_status()  # must raise in case of an error. Server might return json/xml with error details, we do not want that
                fo.write(read_data.content)
            checksum_ok = utils.check_file_checksum(path, checksum)
            if not checksum_ok:
                raise ValueError(f"bad checksum for {str(path)} after reqs download")

    @staticmethod
    def get_cookie_dict_from_str(cookie_input):
        cookie_str = cookie_input or config_vars["COOKIE_JAR"].str()
        cookie = SimpleCookie()
        cookie.load(cookie_str)
        cookies = {}
        for key, morsel in cookie.items():
            if ":" in key:
                key = key.split(":")[1]
            cookies[key] = morsel.value
        return cookies

    def download_session(self):
        session = requests.Session()
        cookies = self.get_cookie_dict_from_str(self.cookie)
        session.cookies = cookiejar_from_dict(cookies)
        return session


# to be used externally
class DownloadFileAndCheckChecksum(DownloadManager):
    def __init__(self, url, path, cookie, checksum, **kwargs) -> None:
        super().__init__(cookie, **kwargs)
        self.path = path
        self.url = url
        self.cookie = cookie
        self.checksum = checksum

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"url=\"{self.url}\"")
        all_args.append(f"path=\"{self.path}\"")
        if self.cookie:
            all_args.append(f"cookie=\"{self.cookie}\"")
        all_args.append(f"checksum=\"{self.checksum}\"")

    def progress_msg_self(self):
        super().progress_msg_self()

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        try:
            with DownloadManager(cookie=self.cookie) as downloader:
                downloader(url=self.url, path=self.path, checksum=self.checksum)

        except Exception as ex:
            print("error ", str(ex))
            raise
