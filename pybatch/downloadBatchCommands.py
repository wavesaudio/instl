from http.cookies import SimpleCookie
import requests
from typing import List

from configVar import config_vars
from .baseClasses import PythonBatchCommandBase
import utils


class DownloadFileAndCheckChecksum(PythonBatchCommandBase):
    def __init__(self, url, path, checksum, **kwargs) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.path = path
        self.checksum = checksum

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.url))
        all_args.append(utils.quoteme_raw_by_type(self.path))
        all_args.append(utils.quoteme_raw_by_type(self.checksum))

    def progress_msg_self(self):
        the_progress_msg = f"Downloading '{self.url}' to '{self.path}'"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        session = kwargs['session']
        with open(self.path, "wb") as fo:
            read_data = session.get(self.url)
            read_data.raise_for_status()  # must raise in case of an error. Server might return json/xml with error details, we do not want that
            fo.write(read_data.content)
        checksum_ok = utils.check_file_checksum(self.path, self.checksum)
        if not checksum_ok:  # Oren: is this the correct place to raise?
            raise ValueError(f"bad checksum for {self.path} even after re-download")
        else:
            return "file " + self.path + " was re downloaded successfully "
