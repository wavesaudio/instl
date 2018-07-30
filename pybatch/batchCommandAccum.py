import sys
import io
import pathlib
from contextlib import contextmanager
import logging
import time
from collections import defaultdict

from .baseClasses import PythonBatchCommandBase
python_batch_log_level = logging.WARNING


def batch_repr(batch_obj):
    assert isinstance(batch_obj, (PythonBatchCommandBase, PythonBatchCommandAccum))
    if sys.platform == "darwin":
        return batch_obj.repr_batch_mac()

    elif sys.platform == "win32":
        return batch_obj.repr_batch_win()


class PythonBatchCommandAccum(object):

    def __init__(self):
        self.current_section: str = None
        self.section_context_stacks = defaultdict(list)
        self.context_stack = [list()]
        self.creation_time = time.strftime('%d-%m-%y_%H-%M')

    def append(self, other):
        self.context_stack[-1].append(other)
        return self

    def __iadd__(self, other):
        self.context_stack[-1].append(other)
        return self

    def __enter__(self):
        self.clear()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def clear(self):
        self.context_stack = [list()]

    @contextmanager
    def sub_accum(self, context):
        self.context_stack[-1].append(context)
        self.context_stack.append(context.child_batch_commands)
        yield self
        self.context_stack.pop()

    def _python_opening_code(self):
        instl_folder = pathlib.Path(__file__).joinpath("..", "..").resolve()
        oc = f"""# Creation time: {self.creation_time}
import sys
sys.path.append(r'{instl_folder}')
from pybatch import *\n
"""
        return oc

    def _python_closing_code(self):
        oc = f"# eof\n\n"
        return oc

    def __repr__(self):
        def _repr_helper(batch_items, io_str, indent):
            indent_str = "    "*indent
            if isinstance(batch_items, list):
                for item in batch_items:
                    _repr_helper(item, io_str, indent)
                    _repr_helper(item.child_batch_commands, io_str, indent+1)
            elif batch_items.is_context_manager:
                io_str.write(f"""{indent_str}with {repr(batch_items)} as {batch_items.obj_name}:\n""")
                io_str.write(f"""{indent_str}    {batch_items.obj_name}()\n""")
            else:
                io_str.write(f"""{indent_str}{repr(batch_items)}""")
        PythonBatchCommandBase.total_progress = 0
        io_str = io.StringIO()
        io_str.write(self._python_opening_code())
        _repr_helper(self.context_stack[0], io_str, 0)
        io_str.write(self._python_closing_code())
        return io_str.getvalue()

    def repr_batch_win(self):
        def _repr_helper(batch_items, io_str):
            if isinstance(batch_items, list):
                for item in batch_items:
                    _repr_helper(item, io_str)
                    _repr_helper(item.child_batch_commands, io_str)
            else:
                io_str.write(batch_repr(batch_items))
        PythonBatchCommandBase.total_progress = 0
        io_str = io.StringIO()
        #io_str.write(self._python_opening_code())
        _repr_helper(self.context_stack[0], io_str)
        #io_str.write(self._python_closing_code())
        return io_str.getvalue()

    def repr_batch_mac(self):
        return ""
