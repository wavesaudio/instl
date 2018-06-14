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
from contextlib import ExitStack
from functools import reduce
from collections import OrderedDict

import utils
from pyinstl.platformSpecificHelper_Python import PlatformSpecificHelperPython


class BatchCommandBase(object):
    total_progress = 100
    current_progress = 0

    def __init__(self, report_own_progress=True, ignore_all_errors=False):
        self.report_own_progress = report_own_progress
        self.ignore_all_errors = ignore_all_errors
        if self.report_own_progress:
            BatchCommandBase.current_progress += 1
        self.exceptions_to_ignore = []

    def progress_msg(self):
        return f"Progress {BatchCommandBase.current_progress} of {BatchCommandBase.total_progress};"

    def progress_msg_self(self):
        """ classes overriding BatchCommandBase should add their own progress message
        """
        return ""

    def error_msg_self(self):
        """ classes overriding BatchCommandBase should add their own error message
        """
        return ""

    def enter_self(self):
        """ classes overriding BatchCommandBase can add code here without
            repeating __enter__.
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
        """ classes overriding BatchCommandBase can add code here without
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

    def __call__(self, *args, **kwargs):
        pass


all_read_write = stat.S_IRUSR|stat.S_IWUSR|stat.S_IRGRP|stat.S_IWGRP|stat.S_IROTH|stat.S_IWOTH
all_read_write_exec = all_read_write|stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH


class chmod(BatchCommandBase):
    def __init__(self, path, mode):
        super().__init__(report_own_progress=True)
        self.path=path
        self.mode=mode
        self.exceptions_to_ignore.append(FileNotFoundError)

    def progress_msg_self(self):
        return f"Change mode {self.path}"

    def enter_self(self):
        self()  # -> __call__

    def __call__(self):
        os.chmod(self.path, self.mode)


class chown(BatchCommandBase):
    def __init__(self, path, owner):
        super().__init__(report_own_progress=True)
        self.path=path
        self.owner=owner
        self.exceptions_to_ignore.append(FileNotFoundError)

    def progress_msg_self(self):
        return f"Change owner {self.path}"

    def __call__(self):
        os.chown(self.path, uid=self.owner, gid=-1)


class cd(BatchCommandBase):
    def __init__(self, path):
        super().__init__(report_own_progress=True)
        self.new_path = path
        self.old_path = None

    def progress_msg_self(self):
        return f"cd to {self.new_path}"

    def __call__(self):
        self.old_path = os.getcwd()
        os.chdir(self.new_path)

    def enter_self(self):
        self()  # -> __call__

    def exit_self(self, exit_return):
        os.chdir(self.old_path)


class make_dirs(BatchCommandBase):
    def __init__(self, *paths_to_make, remove_obstacles=True):
        super().__init__(report_own_progress=True)
        self.paths_to_make = paths_to_make
        self.remove_obstacles = remove_obstacles
        self.cur_path = None

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


class section(BatchCommandBase):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def progress_msg_self(self):
        return f"{self.name} ..."


class RunProcess(BatchCommandBase):
    def __init__(self, run_args):
        super().__init__()
        self.run_args = run_args

    def __call__(self, *args, **kwargs):
        completed_process = subprocess.run(self.run_args)


class copy_dir_to_dir(RunProcess):
    def __init__(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=False):
        run_args = list()
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        ignore_spec = self.create_ignore_spec(ignore)
        if not preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""

        #run_args.extend(["rsync", "--owner", "--group", "-l", "-r", "-E", delete_spec, *ignore_spec, utils.quoteme_double(src_dir), utils.quoteme_double(trg_dir)])
        run_args.extend(["rsync", "--owner", "--group", "-l", "-r", "-E", delete_spec, *ignore_spec, src_dir, trg_dir])
        if link_dest:
            the_link_dest = os.path.join(src_dir, "..")
            run_args.append(f''''--link-dest="{the_link_dest}"''')

        super().__init__(run_args)

    def create_ignore_spec(self, ignore):
        retVal = []
        if ignore:
            if isinstance(ignore, str):
                ignore = (ignore,)
            retVal.extend(["--exclude=" + utils.quoteme_single(ignoree) for ignoree in ignore])
        return retVal

    def progress_msg_self(self):
        return f"{self.run_args}"


class Dummy(BatchCommandBase):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def progress_msg_self(self):
        return f"Dummy {self.name} ..."

    def enter_self(self):
        print(f"Dummy __enter__ {self.name}")

    def exit_self(self, exit_return):
        print(f"Dummy __exit__ {self.name}")

    def __call__(self, *args, **kwargs):
        print(f"Dummy __call__ {self.name}")

def one_install():
    with section("copy to /Applications/Waves/Plug-Ins V9/Documents"):
        with make_dirs("/Users/shai/Desktop/Logs/a", "/Users/shai/Desktop/Logs/b", remove_obstacles=True):
            with cd(path="/Users/shai/Desktop/Logs/wlc.log"):
                with chmod(path="noautoupdate.txt!", mode=all_read_write_exec): pass
                with copy_dir_to_dir(src_dir="/Users/shai/Desktop/Logs/unwtar", trg_dir="/Users/shai/Desktop/Logs/b") as copier:
                    copier()


def run_contexts(context_list):
    if isinstance(context_list, BatchCommandBase):
        with context_list as i:
            if callable(i):
                i()
    elif isinstance(context_list, list):
        for context in context_list:
            run_contexts(context)
    elif isinstance(context_list, dict):
        for key_context, sub_contexts in context_list.items():
            with key_context as kc:
                kc()
                run_contexts(sub_contexts)

# self.__class__.__name__

def two_install():
    ops = {section("copy to /Applications/Waves/Plug-Ins V9/Documents"):
           [make_dirs("/Users/shai/Desktop/Logs/a", "/Users/shai/Desktop/Logs/b", remove_obstacles=True),
           {Dummy("A"): [Dummy("A1"), Dummy("A2"),  Dummy("A3")]},
           [cd(path="/Users/shai/Desktop/Logs"),
           chmod(path="noautoupdate.txt!", mode=all_read_write_exec),
           copy_dir_to_dir(src_dir="/Users/shai/Desktop/Logs/unwtar", trg_dir="/Users/shai/Desktop/Logs/b")],
           Dummy("Z")]}
    run_contexts(ops)


if __name__ == "__main__":

    try:
        pass #one_install()
    except Exception as ex:
        print("one_install", ex)
    print("-")
    try:
        two_install()
    except Exception as ex:
        print("two_install", ex)
