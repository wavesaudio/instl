from typing import List
from pathlib import Path

import requests
from http.cookies import SimpleCookie

from requests.cookies import cookiejar_from_dict

from configVar import config_vars
from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDir
import utils


# this class can be used internally, it will create the session ar the init phase and will only need
# the cookie, the rest of the params will be passed to the call method, this way it will allow this class
# to be called while lopping on multiple files without having the need to create a new connection each time
class DownloadManager(PythonBatchCommandBase):
    def __init__(self, cookie: str = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cookie = cookie
        self.session = self.download_session()
        self.url = None

    def repr_own_args(self, all_args: List[str]) -> None:
        if self.cookie:
            all_args.append(self.named__init__param("cookie", self.cookie))

    def __call__(self, *args, **kwargs):
        with self.session as dl_session:
            url = self.url = kwargs["url"]
            path = Path(kwargs["path"])
            checksum = kwargs["checksum"]
            if path.is_dir():
                filename = Path(url.split("/").pop())
                path = path.joinpath(filename)
            with MakeDir(path.parent, report_own_progress=False) as dir_maker:
                dir_maker()
            with open(path, "wb") as fo:
                self.doing = f"downloading file {path}"
                timeout_seconds = int(config_vars.get("CURL_MAX_TIME", 480))
                read_data = dl_session.get(url, timeout=timeout_seconds)
                read_data.raise_for_status()  # must raise in case of an error. Server might return json/xml with error details, we do not want that
                fo.write(read_data.content)

            checksum_ok = utils.check_file_checksum(path, checksum)
            if not checksum_ok:
                raise ValueError(f"bad checksum for {str(path)} after reqs download")

    def progress_msg_self(self) -> str:
        return f'downloading file {self.url}'

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


# the purpose of this class is to wrap download manager, and use it outside installer script, for example: central
class DownloadFileAndCheckChecksum(DownloadManager):
    def __init__(self, url, path, cookie, checksum, **kwargs) -> None:
        super().__init__(cookie, **kwargs)
        self.path = path
        self.url = url
        self.cookie = cookie
        self.checksum = checksum

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("url", self.url))
        all_args.append(self.named__init__param("path", self.path))
        if self.cookie:
            all_args.append(self.named__init__param("cookie", self.cookie))
        all_args.append(self.named__init__param("checksum", self.checksum))

    def __call__(self, *args, **kwargs):
        with DownloadManager(cookie=self.cookie, report_own_progress=False) as downloader:
            downloader(url=self.url, path=self.path, checksum=self.checksum)
