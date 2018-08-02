from typing import List, Any
import tempfile
import stat
import tarfile
from collections import OrderedDict
from configVar import config_vars
import collections
import zlib

from .batchCommands import *

"""
class Dummy(PythonBatchCommandBase, essential=True):
    def __init__(self, identifier=None, **kwargs) -> None:
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
"""


class SymlinkToSymlinkFile(PythonBatchCommandBase, essential=True):
    def __init__(self, symlink_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symlink_to_convert = pathlib.Path(symlink_to_convert)

    def __repr__(self) -> str:
        the_repr = f'''SymlinkToSymlinkFile(r"{os.fspath(self.symlink_to_convert)}")'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
         if self.symlink_to_convert.is_symlink():
            target_path = self.symlink_to_convert.resolve()
            link_value = os.readlink(self.symlink_to_convert)
            if target_path.is_dir() or target_path.is_file():
                symlink_text_path = self.symlink_to_convert.with_name(f"{self.symlink_to_convert.name}.symlink")
                symlink_text_path.write_text(link_value)
                self.symlink_to_convert.unlink()


class SymlinkFileToSymlink(PythonBatchCommandBase, essential=True):
    def __init__(self, identifier=None, **kwargs) -> None:
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
