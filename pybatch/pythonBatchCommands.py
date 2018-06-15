import os
import re
import stat
import sys
import subprocess
import abc

import utils

first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')


def camel_to_snake_case(identifier):
    identifier1 = first_cap_re.sub(r'\1_\2', identifier)
    identifier2 = all_cap_re.sub(r'\1_\2', identifier1).lower()
    return identifier2


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
    total_progress = 0

    @abc.abstractmethod
    def __init__(self, identifier=None, report_own_progress=True, ignore_all_errors=False):
        PythonBatchCommandBase.instance_counter += 1
        if not isinstance(identifier, str) or not identifier.isidentifier():
            self.identifier = "obj"
        self.obj_name = camel_to_snake_case(f"{self.__class__.__name__}_{PythonBatchCommandBase.instance_counter:05}")
        self.report_own_progress = report_own_progress
        self.ignore_all_errors = ignore_all_errors
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
        is_eq = self.__dict__ == other.__dict__
        return is_eq

    def __hash__(self):
        the_hash = hash(tuple(sorted(self.__dict__.items())))
        return the_hash

    def progress_msg(self):
        the_progress_msg = f"Progress {self.progress} of {PythonBatchCommandBase.total_progress};"
        return the_progress_msg

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
            print(f"{self.progress_msg()} WARNING; {exc_val}")
            suppress_exception = True
        else:
            print(f"{self.progress_msg()} ERROR; {self.error_msg_self()}; {exc_val}")
        self.exit_self(exit_return=suppress_exception)
        return suppress_exception

    @abc.abstractmethod
    def __call__(self, *args, **kwargs):
        pass


class Chmod(PythonBatchCommandBase):
    all_read_write = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH
    all_read_write_exec = all_read_write | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

    def __init__(self, path, mode):
        super().__init__(report_own_progress=True)
        self.path = path
        self.mode = mode
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}", mode={self.mode})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"Change mode {self.path}"
        return the_progress_msg

    def __call__(self):
        os.chmod(self.path, self.mode)
        return None


class Chown(PythonBatchCommandBase):
    def __init__(self, path, owner):
        super().__init__(report_own_progress=True)
        self.path = path
        self.owner = owner
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.path}", owner={self.owner})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"Change owner {self.path}"
        return the_progress_msg

    def __call__(self):
        os.chown(self.path, uid=self.owner, gid=-1)
        return None


class Cd(PythonBatchCommandBase):
    def __init__(self, path):
        super().__init__(report_own_progress=True)
        self.new_path = path
        self.old_path = None

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{self.new_path}")"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"cd to {self.new_path}"
        return the_progress_msg

    def __call__(self):
        self.old_path = os.getcwd()
        os.chdir(self.new_path)
        return None

    def exit_self(self, exit_return):
        os.chdir(self.old_path)


class MakeDirs(PythonBatchCommandBase):
    def __init__(self, *paths_to_make, remove_obstacles=True):
        super().__init__(report_own_progress=True)
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

    def __call__(self):
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


class RunProcess(PythonBatchCommandBase):
    def __init__(self):
        super().__init__()

    @abc.abstractmethod
    def create_run_args(self):
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        run_args = self.create_run_args()
        completed_process = subprocess.run(run_args)
        return None  # what to return here?

    def __repr__(self):
        raise NotImplementedError


class CopyDirToDir(RunProcess):
    def __init__(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=False):
        super().__init__()
        self.src_dir = src_dir
        self.trg_dir = trg_dir
        self.link_dest = link_dest
        self.ignore = ignore
        self.preserve_dest_files = preserve_dest_files

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(src_dir="{self.src_dir}", trg_dir="{self.trg_dir}", link_dest={self.link_dest}, ignore={self.ignore}, preserve_dest_files={self.preserve_dest_files})"""
        return the_repr

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
        the_progress_msg = f"{self}"
        return the_progress_msg


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
