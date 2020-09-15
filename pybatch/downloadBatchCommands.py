from typing import List
from pathlib import Path

from configVar import config_vars
from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import MakeDir
import utils


class DownloadFileAndCheckChecksum(PythonBatchCommandBase):
    def __init__(self, url, path, checksum, **kwargs) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.path = Path(path)
        self.checksum = checksum

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.url))
        all_args.append(self.unnamed__init__param(self.path))
        all_args.append(self.unnamed__init__param(self.checksum))

    def progress_msg_self(self):
        the_progress_msg = f"Downloading '{self.url}' to '{self.path}'"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        session = kwargs['session']
        with MakeDir(self.path.parent, report_own_progress=False) as dir_maker:
            dir_maker()
        with open(self.path, "wb") as fo:
            timeout_seconds = int(config_vars.get("CURL_MAX_TIME", 480))
            read_data = session.get(self.url, timeout=timeout_seconds)
            read_data.raise_for_status()  # must raise in case of an error. Server might return json/xml with error details, we do not want that
            fo.write(read_data.content)
        checksum_ok = utils.check_file_checksum(self.path, self.checksum)
        if not checksum_ok:
            raise ValueError(f"bad checksum for {self.path} even after re-download")
