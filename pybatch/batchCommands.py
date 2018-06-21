import os
import stat
import random
import string
import shutil

import utils
from .baseClasses import *


def touch(file_path):
    with open(file_path, 'a'):
        os.utime(file_path, None)


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
        paths_csl = ", ".join(utils.quoteme_double_list((os.fspath(path) for path in self.paths_to_make)))
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


class Touch(PythonBatchCommandBase):
    def __init__(self, path: os.PathLike):
        super().__init__()
        self.path = path

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.path)}")"""
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
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.new_path)}")"""
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
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.path)}", flag="{self.flag}", recursive={self.recursive}, ignore_errors={self.ignore_errors})"""
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
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.path)}", recursive={self.recursive}, ignore_errors={self.ignore_errors})"""
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
       src = os.fspath(src).rstrip("/")
       super().__init__(src=src, trg=trg, link_dest=link_dest, ignore=ignore, preserve_dest_files=preserve_dest_files)


class CopyDirContentsToDir(RsyncCopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
        if not os.fspath(src).endswith("/"):
            src = os.fspath(src)+"/"
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore=ignore, preserve_dest_files=preserve_dest_files)


class CopyFileToDir(RsyncCopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
        src = os.fspath(src).rstrip("/")
        if not os.fspath(trg).endswith("/"):
            trg = os.fspath(trg)+"/"
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore=ignore, preserve_dest_files=preserve_dest_files)


class CopyFileToFile(RsyncCopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore=None, preserve_dest_files=False):
       src = os.fspath(src).rstrip("/")
       trg = os.fspath(trg).rstrip("/")
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
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.path)}")"""
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
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.path)}")"""
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
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.path)}")"""
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
        the_repr = f"""{self.__class__.__name__}(source_file="{os.fspath(self.source_file)}", target_file="{os.fspath(self.target_file)}")"""
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
        the_repr = f"""{self.__class__.__name__}(user_id={self.user_id}, group_id={self.group_id}, path="{os.fspath(self.path)}", recursive={self.recursive})"""
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


class Chmod(RunProcessBase):
    all_read = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    all_exec = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    all_read_write = all_read | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    all_read_write_exec = all_read_write | all_exec
    all_read_exec = all_read | all_exec
    who_2_perm = {'u': {'r': stat.S_IRUSR, 'w': stat.S_IWUSR, 'x': stat.S_IXUSR},
                  'g': {'r': stat.S_IRGRP, 'w': stat.S_IWGRP, 'x': stat.S_IXGRP},
                  'o': {'r': stat.S_IROTH, 'w': stat.S_IWOTH, 'x': stat.S_IXOTH}}

    def __init__(self, path, mode, recursive: bool=False, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode
        self.recursive = recursive

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path="{os.fspath(self.path)}", mode='{self.mode}', recursive={self.recursive}"""
        if self.ignore_all_errors:
            the_repr += f"ignore_all_errors={self.ignore_all_errors})"
        else:
            the_repr += ")"
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"Change mode {self.path}"
        return the_progress_msg

    def parse_symbolic_mode(self, symbolic_mode_str):
        """ parse chmod symbolic mode string e.g. uo+xw
            return the mode as a number (e.g 766) and the operation (e.g. =|+|-)
        """
        flags = 0
        symbolic_mode_re = re.compile("""^(?P<who>[augo]+)(?P<op>\+|-|=)(?P<perm>[rwx]+)$""")
        match = symbolic_mode_re.match(symbolic_mode_str)
        if not match:
            raise ValueError(f"invalid symbolic mode for chmod: {symbolic_mode_str}")
        who = match.group('who')
        if 'a' in who:
            who = 'ugo'
        perm = match.group('perm')
        for w in who:
            for p in perm:
                flags |= Chmod.who_2_perm[w][p]
        return flags, match.group('op')

    def create_run_args(self):
        run_args = list()
        run_args.append("chmod")
        if self.ignore_all_errors:
            run_args.append("-f")
        if self.recursive:
            run_args.append("-R")
        run_args.append(self.mode)
        run_args.append(self.path)
        return run_args

    def __call__(self, *args, **kwargs):
        # os.chmod is not recursive so call the system's chmod
        if self.recursive:
            return super().__call__(args, kwargs)
        else:
            flags, op = self.parse_symbolic_mode(self.mode)
            mode_to_set = flags
            if op == '+':
                current_mode = stat.S_IMODE(os.stat(self.path)[stat.ST_MODE])
                mode_to_set |= current_mode
            elif op == '-':
                current_mode = stat.S_IMODE(os.stat(self.path)[stat.ST_MODE])
                mode_to_set = current_mode & ~flags

            os.chmod(self.path, mode_to_set)
        return None

# todo:
# override PythonBatchCommandBase for all commands
# windows!
# check and map errors: for each command find which errors can be returned, which exception they raise, which can be ignored. Map all errors to a number and message.
# check and map errors: for RunProcess special handling of exception subprocess.CalledProcessError
# capture subprocess.run output
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
