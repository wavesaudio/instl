from typing import List, Any, Union
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
        the_repr = f'''{self.__class__.__name__}()'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
"""
