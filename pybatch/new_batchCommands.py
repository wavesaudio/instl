from typing import List, Any
import tempfile
import stat
import shlex

from .batchCommands import *

"""
class Dummy(PythonBatchCommandBase):
    def __init__(self, identifier=None, **kwargs):
        super().__init__(**kwargs)

    def __repr__(self):
        the_repr = f""
        return the_repr

    def repr_batch_win(self):
        the_repr = f""
        return the_repr

    def repr_batch_mac(self):
        the_repr = f""
        return the_repr

    def progress_msg_self(self):
        return ""

    def __call__(self, *args, **kwargs):
        pass
"""
