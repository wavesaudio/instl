import os
import stat
import sys
import subprocess
import io
from contextlib import ExitStack, contextmanager
import abc

import utils
from pyinstl.platformSpecificHelper_Python import PlatformSpecificHelperPython
from pybatch import *


def repr_to_object(context_items):
    if isinstance(context_items, PythonBatchCommandBase):
        # single context item
        print("<", repr(context_items))
        with context_items as i:
            i()
    elif isinstance(context_items, list):
        # contexts in list are done one by one
        for context in context_items:
            run_contexts(context)
    elif isinstance(context_items, dict):
        # contexts in dict are under the context of the key
        for key_context, sub_contexts in context_items.items():
            print("<", repr(key_context))
            with key_context as kc:
                kc()
                run_contexts(sub_contexts)


class BatchCommandAccum(object):

    def __init__(self):
        self.context_stack = [list()]

    def __iadd__(self, other):
        self.context_stack[-1].append(other)
        return self

    @contextmanager
    def sub_section(self, context):
        self.context_stack[-1].append(context)
        self.context_stack.append(context.child_batch_commands)
        yield self
        self.context_stack.pop()

    def __repr__(self):
        def _repr_helper(batch_items, io_str, indent):
            indent_str = "    "*indent
            if isinstance(batch_items, list):
                for item in batch_items:
                    _repr_helper(item, io_str, indent)
                    _repr_helper(item.child_batch_commands, io_str, indent+1)
            else:
                io_str.write(f"""{indent_str}with {repr(batch_items)} as {batch_items.obj_name}:\n""")
                io_str.write(f"""{indent_str}    {batch_items.obj_name}()\n""")
        PythonBatchCommandBase.total_progress = 0
        io_str = io.StringIO()
        _repr_helper(self.context_stack[0], io_str, 0)
        return io_str.getvalue()


def run_contexts(context_items):
    if isinstance(context_items, PythonBatchCommandBase):
        # single context item
        print("<", repr(context_items))
        with context_items as i:
            i()
    elif isinstance(context_items, list):
        # contexts in list are done one by one
        for context in context_items:
            run_contexts(context)
    elif isinstance(context_items, dict):
        # contexts in dict are under the context of the key
        for key_context, sub_contexts in context_items.items():
            print("<", repr(key_context))
            with key_context as kc:
                kc()
                run_contexts(sub_contexts)


def three_install():
    bc = BatchCommandAccum()
    bc += Chmod(path="noautoupdate.txt", mode=Chmod.all_read_write_exec)
    with bc.sub_section(Section("copy to /Applications/Waves/Plug-Ins V9/Documents")) as sub_bc:
        sub_bc += MakeDirs("/Users/shai/Desktop/Logs/a", "/Users/shai/Desktop/Logs/b", remove_obstacles=True)
        with sub_bc.sub_section(Dummy("A")) as sub_sub_bc:
            sub_sub_bc += Dummy("A1")
            sub_sub_bc += Dummy("A2")
            sub_sub_bc += Dummy("A3")
        with sub_bc.sub_section(Cd(path="/Users/shai/Desktop/Logs")) as sub_sub_bc:
            sub_sub_bc += Chmod(path="noautoupdate.txt", mode=Chmod.all_read_write_exec)
            sub_sub_bc += CopyDirToDir(src_dir="/Users/shai/Desktop/Logs/unwtar", trg_dir="/Users/shai/Desktop/Logs/b")
        sub_bc += Dummy("Z")

    #list_cp = copy.deepcopy(bc.context_stack[0])
    bc_repr = repr(bc)
    ops = exec(f"""{bc_repr}""", globals(), locals())
    print(bc_repr, flush=True)


if __name__ == "__main__":

    three_install()

# todo:
# override PythonBatchCommandBase for all commands
# intro code
# configVars?
# error table
# comments ?
# echos - most will automatically produced by the commands
# total progress calculation
# accumulator transactions
# handle completed_process
