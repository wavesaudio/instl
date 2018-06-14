import re
import os
import stat
import sys
import shlex
import subprocess
import fnmatch
import time
import re
import shutil
import io
from contextlib import ExitStack, contextmanager
from functools import reduce
from collections import OrderedDict, defaultdict
import abc
import copy

import utils
from pyinstl.platformSpecificHelper_Python import PlatformSpecificHelperPython


class PythonBatchCommandBase(abc.ABC):
    """ PythonBatchCommandBase is the base class for all classes implementing batch commands.
        PythonBatchCommandBase implement context manager interface:
        __enter__: will print progress message (if needed)
                    derived classes should not override __enter__ and should not do any actual work here but implement
                    the work in __call__. If something must be done in __enter__ override enter_self
        __exit__: will handle exceptions and print warning/error messages, or ignore errors if needed
                 derived classes should not override __exit__. If something must be done in __exit__ override exit_self
        Derived classes must implement some additional methods:
        __repr__: must be implemented correctly so the returned string can be passed to eval to recreate the object
        __init__: must record all parameters needed to implement __repr__ and must not do any actual work!
        __call__: here the real
    """
    instance_counter = 0
    total_progress = 100
    current_progress = 0

    @abc.abstractmethod
    def __init__(self, identifier=None, report_own_progress=True, ignore_all_errors=False):
        PythonBatchCommandBase.instance_counter += 1
        if not isinstance(identifier, str) or not identifier.isidentifier():
            identifier = "obj"
        self.obj_identifier = f"{identifier}_{PythonBatchCommandBase.instance_counter:05}"
        self.report_own_progress = report_own_progress
        self.ignore_all_errors = ignore_all_errors
        if self.report_own_progress:
            PythonBatchCommandBase.current_progress += 1
        self.exceptions_to_ignore = []

    @abc.abstractmethod
    def __repr__(self):
        return f"{self.__class__.__name__}(report_own_progress={self.report_own_progress}, ignore_all_errors={self.ignore_all_errors})"

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __hash__(self):
        return hash(tuple(sorted(self.__dict__.items())))

    def progress_msg(self):
        return f"Progress {PythonBatchCommandBase.current_progress} of {PythonBatchCommandBase.total_progress};"

    def progress_msg_self(self):
        """ classes overriding PythonBatchCommandBase should add their own progress message
        """
        return ""

    def error_msg_self(self):
        """ classes overriding PythonBatchCommandBase should add their own error message
        """
        return ""

    def enter_self(self):
        """ classes overriding PythonBatchCommandBase can add code here without
            repeating __enter__, bit not do any actual work!
        """
        pass

    def __enter__(self):
        try:
            if self.report_own_progress:
                print(f"{self.progress_msg()} {self.progress_msg_self()}")
            self.enter_self()
        except Exception:
            suppress_exception = self.__exit__(*sys.exc_info())
            if not suppress_exception:
                raise
        return self

    def exit_self(self, exit_return):
        """ classes overriding PythonBatchCommandBase can add code here without
            repeating __exit__.
            exit_self will be called regardless of exceptions
            param exit_return is what __exit__ will return
        """
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        suppress_exception = False
        if self.ignore_all_errors or exc_type is None:
            suppress_exception = True
        elif exc_type in self.exceptions_to_ignore:
            print(f"{self.progress_msg()} WARNING; {exc_val}")
            suppress_exception = True
        else:
            print(f"{self.progress_msg()} ERROR; {self.error_msg_self()}; {exc_val}")
        self.exit_self(exit_return=suppress_exception)
        return suppress_exception

    @abc.abstractmethod
    def __call__(self, *args, **kwargs):
        pass


all_read_write = stat.S_IRUSR|stat.S_IWUSR|stat.S_IRGRP|stat.S_IWGRP|stat.S_IROTH|stat.S_IWOTH
all_read_write_exec = all_read_write|stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH


class chmod(PythonBatchCommandBase):
    def __init__(self, path, mode):
        super().__init__(report_own_progress=True)
        self.path=path
        self.mode=mode
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        return f"""{self.__class__.__name__}(path="{self.path}", mode={self.mode})"""

    def progress_msg_self(self):
        return f"Change mode {self.path}"

    def enter_self(self):
        self()  # -> __call__

    def __call__(self):
        os.chmod(self.path, self.mode)


class chown(PythonBatchCommandBase):
    def __init__(self, path, owner):
        super().__init__(report_own_progress=True)
        self.path=path
        self.owner=owner
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        return f"""{self.__class__.__name__}(path="{self.path}", owner={self.owner})"""

    def progress_msg_self(self):
        return f"Change owner {self.path}"

    def __call__(self):
        os.chown(self.path, uid=self.owner, gid=-1)


class cd(PythonBatchCommandBase):
    def __init__(self, path):
        super().__init__(report_own_progress=True)
        self.new_path = path
        self.old_path = None

    def __repr__(self):
        return f"""{self.__class__.__name__}(path="{self.new_path}")"""

    def progress_msg_self(self):
        return f"cd to {self.new_path}"

    def __call__(self):
        self.old_path = os.getcwd()
        os.chdir(self.new_path)

    def enter_self(self):
        self()  # -> __call__

    def exit_self(self, exit_return):
        os.chdir(self.old_path)


class make_dirs(PythonBatchCommandBase):
    def __init__(self, *paths_to_make, remove_obstacles=True):
        super().__init__(report_own_progress=True)
        self.paths_to_make = paths_to_make
        self.remove_obstacles = remove_obstacles
        self.cur_path = None

    def __repr__(self):
        paths_csl = ", ".join(utils.quoteme_double_list(self.paths_to_make))
        return f"""{self.__class__.__name__}({paths_csl}, remove_obstacles={self.remove_obstacles})"""

    def progress_msg_self(self):
        return f"mkdir {self.paths_to_make}"

    def __call__(self):
        for self.cur_path in self.paths_to_make:
            if self.remove_obstacles:
                if os.path.isfile(self.cur_path):
                    os.unlink(self.cur_path)
            os.makedirs(self.cur_path, mode=0o777, exist_ok=True)

    def enter_self(self):
        self()  # -> __call__

    def error_msg_self(self):
        return f"creating {self.cur_path}"


class section(PythonBatchCommandBase):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def __repr__(self):
        return f"""{self.__class__.__name__}(name="{self.name}")"""

    def progress_msg_self(self):
        return f"{self.name} ..."

    def __call__(self, *args, **kwargs):
        pass


class RunProcess(PythonBatchCommandBase):
    def __init__(self):
        super().__init__()

    def create_run_args(self):
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        run_args = self.create_run_args()
        completed_process = subprocess.run(run_args)


class copy_dir_to_dir(RunProcess):
    def __init__(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=False):
        super().__init__()
        self.src_dir = src_dir
        self.trg_dir = trg_dir
        self.link_dest = link_dest
        self.ignore = ignore
        self.preserve_dest_files = preserve_dest_files

    def __repr__(self):
        return f"""{self.__class__.__name__}(src_dir="{self.src_dir}", trg_dir="{self.trg_dir}", link_dest={self.link_dest}, ignore={self.ignore}, preserve_dest_files={self.preserve_dest_files})"""

    def create_run_args(self):
        run_args = list()
        if self.src_dir.endswith("/"):
            self.src_dir.rstrip("/")
        ignore_spec = self.create_ignore_spec(self.ignore)
        if not self.preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""

        run_args.extend(["rsync", "--owner", "--group", "-l", "-r", "-E", delete_spec, *ignore_spec, self.src_dir, self.trg_dir])
        if self.link_dest:
            the_link_dest = os.path.join(self.src_dir, "..")
            run_args.append(f''''--link-dest="{the_link_dest}"''')

        return run_args

    def create_ignore_spec(self, ignore):
        retVal = []
        if ignore:
            if isinstance(ignore, str):
                ignore = (ignore,)
            retVal.extend(["--exclude=" + utils.quoteme_single(ignoree) for ignoree in ignore])
        return retVal

    def progress_msg_self(self):
        return f"{self}"


class Dummy(PythonBatchCommandBase):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def __repr__(self):
        return f"""{self.__class__.__name__}(name="{self.name}")"""

    def progress_msg_self(self):
        return f"Dummy {self.name} ..."

    def enter_self(self):
        print(f"Dummy __enter__ {self.name}")

    def exit_self(self, exit_return):
        print(f"Dummy __exit__ {self.name}")

    def __call__(self, *args, **kwargs):
        print(f"Dummy __call__ {self.name}")


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

    def __repr__(self):
        io_str = io.StringIO()
        self._repr_helper(self.context_stack[0], io_str, -1)
        return io_str.getvalue()

    def _repr_helper(self, batch_items, io_str, indent):
        indent += 1
        indent_str = " "*4*indent
        if isinstance(batch_items, list):
            io_str.write(indent_str)
            io_str.write("[\n")
            for item in batch_items:
                self._repr_helper(item, io_str, indent)
                io_str.write("\n")
            io_str.write(indent_str)
            io_str.write("]\n")
        elif isinstance(batch_items, dict):
            io_str.write(indent_str)
            io_str.write("{\n")
            for item, values in batch_items.items():
                io_str.write(indent_str)
                io_str.write(" "*4)
                io_str.write(item)
                io_str.write(":\n")
                self._repr_helper(values, io_str, indent)
            io_str.write(indent_str)
            io_str.write("},\n")
        else:
            io_str.write(indent_str)
            io_str.write(batch_items)
            io_str.write(",")

    def __iadd__(self, other):
        self.context_stack[-1].append(repr(other))
        return self

    @contextmanager
    def sub_section(self, context):
        self.context_stack.append(list())
        yield self
        previous_list = self.context_stack.pop()
        self.context_stack[-1].append({repr(context): previous_list})

    def create_code(self):
        obj_counter = 0
        def _create_code_helper(batch_items, io_str, indent):
            nonlocal obj_counter
            indent_str = "    "*indent
            if isinstance(batch_items, list):
                for item in batch_items:
                    _create_code_helper(item, io_str, indent)
            elif isinstance(batch_items, dict):
                for item, values in batch_items.items():
                    _create_code_helper(item, io_str, indent)
                    _create_code_helper(values, io_str, indent+1)
            else:
                obj_counter += 1
                obj_name = "obj_"+str(obj_counter)
                io_str.write(f"""{indent_str}with {batch_items} as {obj_name}:\n""")
                io_str.write(f"""{indent_str}    {obj_name}()\n""")
        io_str = io.StringIO()
        _create_code_helper(self.context_stack[0], io_str, 0)
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

def one_install():
    return
    with chmod(path="noautoupdate.txt?", mode=511) as obj_1:
        obj_1()
    with section(name="copy to /Applications/Waves/Plug-Ins V9/Documents") as obj_2:
        obj_2()
        with make_dirs("/Users/shai/Desktop/Logs/a", "/Users/shai/Desktop/Logs/b", remove_obstacles=True) as obj_3:
            obj_3()
        with Dummy(name="A") as obj_4:
            obj_4()
            with Dummy(name="A1") as obj_5:
                obj_5()
            with Dummy(name="A2") as obj_6:
                obj_6()
            with Dummy(name="A3") as obj_7:
                obj_7()
        with cd(path="/Users/shai/Desktop/Logs") as obj_8:
            obj_8()
            with chmod(path="noautoupdate.txt!", mode=511) as obj_9:
                obj_9()
            with copy_dir_to_dir(src_dir="/Users/shai/Desktop/Logs/unwtar", trg_dir="/Users/shai/Desktop/Logs/b", link_dest=False, ignore=None, preserve_dest_files=False) as obj_10:
                obj_10()
        with Dummy(name="Z") as obj_11:
            obj_11()

some_code = ("""
with chmod(path="noautoupdate.txt?", mode=511) as obj_1:
    obj_1()
with section(name="copy to /Applications/Waves/Plug-Ins V9/Documents") as obj_2:
    obj_2()
    with make_dirs("/Users/shai/Desktop/Logs/a", "/Users/shai/Desktop/Logs/b", remove_obstacles=True) as obj_3:
        obj_3()
    with Dummy(name="A") as obj_4:
        obj_4()
        with Dummy(name="A1") as obj_5:
            obj_5()
        with Dummy(name="A2") as obj_6:
            obj_6()
        with Dummy(name="A3") as obj_7:
            obj_7()
    with cd(path="/Users/shai/Desktop/Logs") as obj_8:
        obj_8()
        with chmod(path="noautoupdate.txt!", mode=511) as obj_9:
            obj_9()
        with copy_dir_to_dir(src_dir="/Users/shai/Desktop/Logs/unwtar", trg_dir="/Users/shai/Desktop/Logs/b", link_dest=False, ignore=None, preserve_dest_files=False) as obj_10:
            obj_10()
    with Dummy(name="Z") as obj_11:
        obj_11()

""")
def three_install():
    bc = BatchCommandAccum()
    bc += chmod(path="noautoupdate.txt", mode=all_read_write_exec)
    with bc.sub_section(section("copy to /Applications/Waves/Plug-Ins V9/Documents")) as sub_bc:
        sub_bc += make_dirs("/Users/shai/Desktop/Logs/a", "/Users/shai/Desktop/Logs/b", remove_obstacles=True)
        with sub_bc.sub_section(Dummy("A")) as sub_sub_bc:
            sub_sub_bc += Dummy("A1")
            sub_sub_bc += Dummy("A2")
            sub_sub_bc += Dummy("A3")
        with sub_bc.sub_section(cd(path="/Users/shai/Desktop/Logs")) as sub_sub_bc:
            sub_sub_bc += chmod(path="noautoupdate.txt", mode=all_read_write_exec)
            sub_sub_bc += copy_dir_to_dir(src_dir="/Users/shai/Desktop/Logs/unwtar", trg_dir="/Users/shai/Desktop/Logs/b")
        sub_bc += Dummy("Z")

    #list_cp = copy.deepcopy(bc.context_stack[0])
    bc_repr = bc.create_code()
    ops = exec(f"""{bc_repr}""", globals(), locals())
    print(bc_repr, flush=True)

if __name__ == "__main__":

    try:
        one_install()
    except Exception as ex:
        print("one_install", ex)
    three_install()
