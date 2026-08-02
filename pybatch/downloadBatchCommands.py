from typing import List
import os
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
        self._ensured_dirs = set()

    def repr_own_args(self, all_args: List[str]) -> None:
        if self.cookie:
            all_args.append(self.named__init__param("cookie", self.cookie))

    def __call__(self, *args, **kwargs):
        # NOT `with self.session`: Session.__exit__ closes the connection pool, so
        # every file would pay a fresh TCP + TLS handshake. Closed once, in exit_self.
        dl_session = self.session
        url = self.url = kwargs["url"]
        path = Path(kwargs["path"])
        checksum = kwargs["checksum"]
        if path.is_dir():
            filename = Path(url.split("/").pop())
            path = path.joinpath(filename)
        temp_path = Path(kwargs["temp_path"]) if kwargs.get("temp_path") else path
        self._ensure_dir(path.parent)
        self._ensure_dir(temp_path.parent)
        with open(temp_path, "wb") as fo:
            self.doing = f"downloading file {temp_path}"
            timeout_seconds = int(config_vars.get("CURL_MAX_TIME", 480))
            read_data = dl_session.get(url, timeout=timeout_seconds)
            read_data.raise_for_status()  # must raise in case of an error. Server might return json/xml with error details, we do not want that
            fo.write(read_data.content)

        checksum_ok = utils.check_file_checksum(temp_path, checksum)
        if not checksum_ok:
            raise ValueError(f"bad checksum for {str(temp_path)} after reqs download")
        if temp_path != path:
            os.replace(temp_path, path)

    def _ensure_dir(self, dir_path: Path) -> None:
        """MakeDir once per directory per session, not once per file. MakeDir's
        "already exists, just fix permissions" branch runs FixAllPermissions
        unconditionally, which is two child processes on Windows (attrib, icacls).
        The first file in a directory still goes through MakeDir in full."""
        key = os.fspath(dir_path)
        if key in self._ensured_dirs:
            return
        with MakeDir(dir_path, report_own_progress=False) as dir_maker:
            dir_maker()
        self._ensured_dirs.add(key)

    def exit_self(self, exit_return) -> None:
        """Close the pooled session once the whole batch of downloads is done."""
        try:
            self.session.close()
        except Exception:
            pass  # a close failure must never fail the surrounding batch step

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
        # headroom over the default 10 for a pass that walks thousands of files
        # against one host; the pool only pays off if it survives between calls
        pool_size = max(1, int(config_vars.setdefault("DOWNLOAD_SESSION_POOL_SIZE", "16")))
        adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size,
                                                pool_maxsize=pool_size)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
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
