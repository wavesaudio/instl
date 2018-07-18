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
class Dummy(PythonBatchCommandBase):
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
