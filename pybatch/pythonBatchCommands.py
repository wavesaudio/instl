import os
import re
import stat
import sys
import subprocess
import abc
import io
import random
import string
from contextlib import ExitStack, contextmanager
import shutil
import pathlib
import re

import utils

first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')


def camel_to_snake_case(identifier):
    identifier1 = first_cap_re.sub(r'\1_\2', identifier)
    identifier2 = all_cap_re.sub(r'\1_\2', identifier1).lower()
    return identifier2


def touch(file_path):
    with open(file_path, 'a'):
        os.utime(file_path, None)


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
    instance_counter: int = 0
    total_progress: int = 0

    @abc.abstractmethod
    def __init__(self, identifier=None, **kwargs):
        PythonBatchCommandBase.instance_counter += 1
        if not isinstance(identifier, str) or not identifier.isidentifier():
            self.identifier = "obj"
        self.obj_name = camel_to_snake_case(f"{self.__class__.__name__}_{PythonBatchCommandBase.instance_counter:05}")

        self.report_own_progress = kwargs.get('report_own_progress', True)
        self.ignore_all_errors =   kwargs.get('ignore_all_errors', False)

        self.progress = 0
        if self.report_own_progress:
            PythonBatchCommandBase.total_progress += 1
            self.progress = PythonBatchCommandBase.total_progress
        self.exceptions_to_ignore = []
        self.child_batch_commands = []

    @abc.abstractmethod
    def __repr__(self):
        the_repr = f"{self.__class__.__name__}(report_own_progress={self.report_own_progress}, ignore_all_errors={self.ignore_all_errors})"
        return the_repr

    def __eq__(self, other):
        do_not_compare_keys = ('progress', 'obj_name')
        dict_self =  {k:  self.__dict__[k] for k in  self.__dict__.keys() if k not in do_not_compare_keys}
        dict_other = {k: other.__dict__[k] for k in other.__dict__.keys() if k not in do_not_compare_keys}
        is_eq = dict_self == dict_other
        return is_eq

    def __hash__(self):
        the_hash = hash(tuple(sorted(self.__dict__.items())))
        return the_hash

    def progress_msg(self):
        the_progress_msg = f"Progress {self.progress} of {PythonBatchCommandBase.total_progress};"
        return the_progress_msg

    @abc.abstractmethod
    def progress_msg_self(self):
        """ classes overriding PythonBatchCommandBase should add their own progress message
        """
        return ""

    def warning_msg_self(self):
        """ classes overriding PythonBatchCommandBase can add their own warning message
        """
        return ""

    def error_msg_self(self):
        """ classes overriding PythonBatchCommandBase can add their own error message
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
        except Exception as ex:
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
            print(f"{self.progress_msg()} WARNING; {self.warning_msg_self()}; {exc_val.__class__.__name__}: {exc_val}")
            suppress_exception = True
        else:
            print(f"{self.progress_msg()} ERROR; {self.error_msg_self()}; {exc_val.__class__.__name__}: {exc_val}")
        self.exit_self(exit_return=suppress_exception)
        return suppress_exception

    @abc.abstractmethod
    def __call__(self, *args, **kwargs):
        pass


class RunProcessBase(PythonBatchCommandBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @abc.abstractmethod
    def create_run_args(self):
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        run_args = self.create_run_args()
        print(" ".join(run_args))
        completed_process = subprocess.run(run_args, check=True)
        return None  # what to return here?

    def __repr__(self):
        raise NotImplementedError


# === classes with tests ===
class MakeRandomDirs(PythonBatchCommandBase):
    """ MakeRandomDirs is intended for use during tests - not for production
        Will create in current working directory a hierarchy of folders and files with random names so we can test copying
    """

    def __init__(self, num_levels: int, num_dirs_per_level: int, num_files_per_dir: int, file_size: int):
        super().__init__()
        self.num_levels = num_levels
        self.num_dirs_per_level = num_dirs_per_level
        self.num_files_per_dir = num_files_per_dir
        self.file_size = file_size

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(num_levels={self.num_levels}, num_dirs_per_level={self.num_dirs_per_level}, num_files_per_dir={self.num_files_per_dir}, file_size={self.file_size})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"create random directories and files under current dir {os.getcwd()}"
        return the_progress_msg

    def make_random_dirs_recursive(self, num_levels: int):
        for i_file in range(self.num_files_per_dir):
            random_file_name = ''.join(random.choice(string.ascii_lowercase) for i in range(8))
            if self.file_size == 0:
                touch(random_file_name)
            else:
                with open(random_file_name, "w") as wfd:
                    wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(self.file_size)))
        if num_levels > 0:
            for i_dir in range(self.num_dirs_per_level):
                random_dir_name = ''.join(random.choice(string.ascii_uppercase) for i in range(8))
                os.makedirs(random_dir_name, mode=0o777, exist_ok=False)
                save_cwd = os.getcwd()
                os.chdir(random_dir_name)
                self.make_random_dirs_recursive(num_levels-1)
                os.chdir(save_cwd)

    def __call__(self, *args, **kwargs):
        self.make_random_dirs_recursive(self.num_levels)


class MakeDirs(PythonBatchCommandBase):
    """ Create one or more dirs
        when remove_obstacles==True if one of the paths is a file it will be removed
        when remove_obstacles==False if one of the paths is a file 'FileExistsError: [Errno 17] File exists' will raise
        it it always OK for a dir to already exists
        Tests: TestPythonBatch.test_MakeDirs_*
    """
    def __init__(self, *paths_to_make, remove_obstacles: bool=True):
        super().__init__()
        self.paths_to_make = paths_to_make
        self.remove_obstacles = remove_obstacles
        self.cur_path = None

    def __repr__(self):
        paths_csl = ", ".join(utils.quoteme_double_list(self.paths_to_make))
        the_repr = f"""{self.__class__.__name__}({paths_csl}, remove_obstacles={self.remove_obstacles})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"mkdir {self.paths_to_make}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        retVal = 0
        for self.cur_path in self.paths_to_make:
            if self.remove_obstacles:
                if os.path.isfile(self.cur_path):
                    os.unlink(self.cur_path)
            os.makedirs(self.cur_path, mode=0o777, exist_ok=True)
            retVal += 1
        return retVal

    def error_msg_self(self):
        return f"creating {self.cur_path}"


class Chmod(PythonBatchCommandBase):
    all_read = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    all_read_write = all_read | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    all_read_write_exec = all_read_write | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

    def __init__(self, path, mode):
        super().__init__()
        self.path = path
        self.mode = mode
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}", mode={self.mode})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"Change mode {self.path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        os.chmod(self.path, self.mode)
        return None


class Touch(PythonBatchCommandBase):
    def __init__(self, path: os.PathLike):
        super().__init__()
        self.path = path

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"Touch {self.path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        with open(self.path, 'a'):
            os.utime(self.path, None)


class Cd(PythonBatchCommandBase):
    def __init__(self, path: os.PathLike):
        super().__init__()
        self.new_path: os.PathLike = path
        self.old_path: os.PathLike = None

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.new_path}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"cd to {self.new_path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        self.old_path = os.getcwd()
        os.chdir(self.new_path)
        return None

    def exit_self(self, exit_return):
        os.chdir(self.old_path)


class ChFlags(RunProcessBase):
    """ Mac specific to change system flags on files or dirs.
        These flags are different from permissions.
        For changing permissions use chmod.
    """
    def __init__(self, path, flag: str, recursive=False, ignore_errors=True):
        super().__init__(ignore_all_errors=ignore_errors)
        self.path = path
        self.flag = flag
        self.recursive = recursive
        self.ignore_errors = ignore_errors

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}", flag="{self.flag}", recursive={self.recursive}, ignore_errors={self.ignore_errors})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"change flag {self.flag} on file {self.path}"
        return the_progress_msg

    def create_run_args(self):
        run_args = list()
        run_args.append("chflags")
        if self.ignore_errors:
            run_args.append("-f")
        if self.recursive:
            run_args.append("-R")
        run_args.append(self.flag)
        run_args.append(self.path)
        return run_args


class Unlock(ChFlags):
    """
        Remove the system's read-only flag, this is different from permissions.
        For changing permissions use chmod.
    """
    def __init__(self, path, recursive=False, ignore_errors=True):
        super().__init__(path, "nouchg", recursive=recursive, ignore_errors=ignore_errors)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}", recursive={self.recursive}, ignore_errors={self.ignore_errors})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"unlocking file {self.path}"
        return the_progress_msg


class RsyncCopyBase(RunProcessBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
        super().__init__()
        self.src: os.PathLike = src
        self.trg: os.PathLike = trg
        self.link_dest = link_dest
        self.ignore = ignore
        self.preserve_dest_files = preserve_dest_files

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(src="{self.src}", trg="{self.trg}", link_dest={self.link_dest}, ignore={self.ignore}, preserve_dest_files={self.preserve_dest_files})"""
        return the_repr

    def create_run_args(self):
        run_args = list()
        ignore_spec = self.create_ignore_spec(self.ignore)
        if not self.preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""

        run_args.extend(["rsync", "--owner", "--group", "-l", "-r", "-E", "--hard-links", delete_spec, *ignore_spec])
        if self.link_dest:
            src_base, src_leaf = os.path.split(self.src)
            target_relative_to_source = os.path.relpath(src_base, self.trg)  # rsync expect --link-dest to be relative to target
            the_link_dest_arg = f'''--link-dest="{target_relative_to_source}"'''
            run_args.append(the_link_dest_arg)
        run_args.extend([self.src, self.trg])
        return run_args

    def create_ignore_spec(self, ignore: bool):
        retVal = []
        if ignore:
            if isinstance(ignore, str):
                ignore = (ignore,)
            retVal.extend(["--exclude=" + utils.quoteme_single(ignoree) for ignoree in ignore])
        return retVal

    def progress_msg_self(self):
        the_progress_msg = f"{self}"
        return the_progress_msg


class CopyDirToDir(RsyncCopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
       src = src.rstrip("/")
       super().__init__(src=src, trg=trg, link_dest=link_dest, ignore=ignore, preserve_dest_files=preserve_dest_files)


class CopyDirContentsToDir(RsyncCopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
        if not src.endswith("/"):
            src += "/"
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore=ignore, preserve_dest_files=preserve_dest_files)


class CopyFileToDir(RsyncCopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
        src = src.rstrip("/")
        if not trg.endswith("/"):
            trg += "/"
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore=ignore, preserve_dest_files=preserve_dest_files)


class CopyFileToFile(RsyncCopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
       src = src.rstrip("/")
       trg = trg.rstrip("/")
       super().__init__(src=src, trg=trg, link_dest=link_dest, ignore=ignore, preserve_dest_files=preserve_dest_files)


class RmFile(PythonBatchCommandBase):
    def __init__(self, path: os.PathLike):
        """ remove a file
            - t's OK is the file does not exist
            - but exception will be raised if the path if a folder
        """
        super().__init__()
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"remove file {self.path}"
        return the_progress_msg

    def error_msg_self(self):
        if os.path.isdir(self.path):
            retVal = "cannot remove file that is actually a folder"
        else:
            retVal = ""
        return retVal

    def __call__(self, *args, **kwargs):
        os.remove(self.path)
        return None


class RmDir(PythonBatchCommandBase):
    def __init__(self, path: os.PathLike):
        """ remove a directory.
            - it's OK if the directory does not exist.
            - all files and directory under path will be removed recursively
            - exception will be raised if the path if a folder
        """
        super().__init__()
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"remove file {self.path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        shutil.rmtree(self.path)
        return None


class RmFileOrDir(PythonBatchCommandBase):
    def __init__(self, path: os.PathLike):
        """ remove a file or directory.
            - it's OK if the path does not exist.
            - all files and directory under path will be removed recursively
        """
        super().__init__()
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"remove file {self.path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        if os.path.isfile(self.path):
            os.remove(self.path)
        elif os.path.isdir(self.path):
            shutil.rmtree(self.path)
        return None


class AppendFileToFile(PythonBatchCommandBase):
    def __init__(self, source_file, target_file):
        super().__init__()
        self.source_file = source_file
        self.target_file = target_file

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(source_file="{self.source_file}", target_file="{self.target_file}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"appending {self.source_file} to {self.target_file}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        with open(self.target_file, "a") as wfd:
            with open(self.source_file, "r") as rfd:
                wfd.write(rfd.read())
        return None


# === classes without tests (yet) ===
class Section(PythonBatchCommandBase):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(name="{self.name}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"{self.name} ..."
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        pass


class Chown(RunProcessBase):
    def __init__(self, user_id: int, group_id: int, path: os.PathLike, recursive: bool=False):
        super().__init__()
        self.user_id = user_id
        self.group_id = group_id
        self.path = path
        self.recursive = recursive
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(user_id={self.user_id}, group_id={self.group_id}, path="{self.path}", recursive={self.recursive})"""
        return the_repr

    def create_run_args(self):
        run_args = list()
        run_args.append("chown")
        run_args.append("-f")
        if self.recursive:
            run_args.append("-R")
        run_args.append("".join((self.user_id, ":", self.group_id)))
        run_args.append(utils.quoteme_double(self.path))
        return run_args

    def progress_msg_self(self):
        the_progress_msg = f"Change owner {self.path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        # os.chown is not recursive so call the system's chown
        if self.recursive:
            return super().__call__(args, kwargs)
        else:
            os.chown(self.path, uid=self.user_id, gid=self.group_id)
            return None


class Dummy(PythonBatchCommandBase):
    def __init__(self, name):
        super().__init__()
        self.name = name

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(name="{self.name}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"Dummy {self.name} ..."
        return the_progress_msg

    def enter_self(self):
        print(f"Dummy __enter__ {self.name}")

    def exit_self(self, exit_return):
        print(f"Dummy __exit__ {self.name}")

    def __call__(self, *args, **kwargs):
        print(f"Dummy __call__ {self.name}")


class BatchCommandAccum(object):

    def __init__(self):
        self.context_stack = [list()]

    def __iadd__(self, other):
        self.context_stack[-1].append(other)
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

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

# todo:
# override PythonBatchCommandBase for all commands
# windows!
# check and map errors: for each command find which errors can be returned, which exception they raise, which can be ignored. Map all errors to a number and message.
# check and map errors: for RunProcess special handling of exception subprocess.CalledProcessError
# intro code
# configVars?
# comments ?
# echos - most will automatically produced by the commands
# total progress calculation
# accumulator transactions
# handle completed_process
# tests: for each test add a test to verify failure is handled correctly
# time measurements
# InstlAdmin
