import os
import stat
import random
import string
import shutil
from pathlib import Path
import shlex
import collections
from typing import List, Any, Optional, Union
import re

import utils
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase

def touch(file_path):
    with open(file_path, 'a'):
        os.utime(file_path, None)


# regex to find some characters that should be escaped in dos, but are not
dos_escape_regex = re.compile("""(?<!\^)([<|&>])""", re.MULTILINE)


def escape_me_dos_callback(match_obj):
    replacement = "^"+match_obj.group(1)
    return replacement


def dos_escape(some_string):
    # 1. remove ^><|'s from end of string - they cause CMD to ask for 'More?' or 'The syntax of the command is incorrect.'
    retVal = some_string.rstrip("^><|")
    # 2. replace some chars with ?
    retVal = re.sub("""[\r\n]""", "?", retVal)
    # 3. escape some chars, but only of they are not already escaped
    retVal = dos_escape_regex.sub(escape_me_dos_callback, retVal)
    return retVal


# === classes with tests ===
class MakeRandomDirs(PythonBatchCommandBase, essential=True):
    """ MakeRandomDirs is intended for use during tests - not for production
        Will create in current working directory a hierarchy of folders and files with random names so we can test copying
    """

    def __init__(self, num_levels: int, num_dirs_per_level: int, num_files_per_dir: int, file_size: int) -> None:
        super().__init__()
        self.num_levels = num_levels
        self.num_dirs_per_level = num_dirs_per_level
        self.num_files_per_dir = num_files_per_dir
        self.file_size = file_size

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"""num_levels={self.num_levels}""")
        all_args.append(f"""num_dirs_per_level={self.num_dirs_per_level}""")
        all_args.append(f"""num_files_per_dir={self.num_files_per_dir}""")
        all_args.append(f"""file_size={self.file_size}""")

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


class MakeDirs(PythonBatchCommandBase, essential=True):
    """ Create one or more dirs
        when remove_obstacles==True if one of the paths is a file it will be removed
        when remove_obstacles==False if one of the paths is a file 'FileExistsError: [Errno 17] File exists' will raise
        it it always OK for a dir to already exists
        Tests: TestPythonBatch.test_MakeDirs_*
    """
    def __init__(self, *paths_to_make, remove_obstacles: bool=True, **kwargs) -> None:
        """ MakeDirs(*paths_to_make, remove_obstacles) """
        super().__init__(**kwargs)
        self.paths_to_make = paths_to_make
        self.remove_obstacles = remove_obstacles
        self.cur_path = None
        self.own_progress_count = len(self.paths_to_make)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.extend(utils.quoteme_raw_string(os.fspath(path)) for path in self.paths_to_make)
        if not self.remove_obstacles:
            all_args.append(f"remove_obstacles={self.remove_obstacles}")

    def progress_msg_self(self):
        paths = ", ".join(os.path.expandvars(utils.quoteme_raw_string(path)) for path in self.paths_to_make)
        titula = "directory" if len(self.paths_to_make) == 1 else "directories"
        the_progress_msg = f"Create {titula} {paths}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        for self.cur_path in self.paths_to_make:
            resolved_path_to_make = utils.ResolvedPath(self.cur_path)
            if self.remove_obstacles:
                if os.path.isfile(resolved_path_to_make):
                    self.doing = f"""removing file that should be a folder '{resolved_path_to_make}'"""
                    os.unlink(resolved_path_to_make)
            self.doing = f"""creating a folder '{resolved_path_to_make}'"""
            resolved_path_to_make.mkdir(parents=True, mode=0o777, exist_ok=True)


class MakeDirsWithOwner(MakeDirs, essential=True):
    """ a stand in to replace platform_helper.mkdir_with_owner
        ToDo: with owner functionality should be implemented in MakeDirs
    """
    def __init__(self, *paths_to_make, remove_obstacles: bool=True, **kwargs) -> None:
        super().__init__(*paths_to_make, remove_obstacles=remove_obstacles, **kwargs)


class Touch(PythonBatchCommandBase, essential=True):
    """ Create an empty file if it does not already exist or update modification time to now if file exist"""
    def __init__(self, path: os.PathLike,**kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(os.fspath(self.path)))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.path}'"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        with open(resolved_path, 'a') as tfd:
            os.utime(resolved_path, None)


class Cd(PythonBatchCommandBase, essential=True):
    """ change current working directory to 'path'
        when called as a context manager (with statement), previous working directory will be restored on __exit__
    """
    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.new_path: os.PathLike = path
        self.old_path: os.PathLike = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(os.fspath(self.new_path)))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.new_path}'"""

    def __call__(self, *args, **kwargs):
        self.old_path = os.getcwd()
        resolved_new_path = utils.ResolvedPath(self.new_path)
        self.doing = f"""changing current directory to '{resolved_new_path}'"""
        os.chdir(resolved_new_path)
        assert os.getcwd() == os.fspath(resolved_new_path)

    def exit_self(self, exit_return):
        os.chdir(self.old_path)


class CdStage(Cd, essential=False):
    """ change current working directory to 'path' and enter a new Stage
        when called as a context manager (with statement), previous working directory will be restored on __exit__
    """
    def __init__(self, stage_name: str, path: os.PathLike, *titles, **kwargs) -> None:
        super().__init__(path, **kwargs)
        self.stage_name = stage_name
        self.new_path: os.PathLike = path
        self.old_path: os.PathLike = None
        self.titles = sorted(titles)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(self.stage_name))
        all_args.append(utils.quoteme_raw_string(self.new_path))
        for title in self.titles:
            all_args.append(utils.quoteme_raw_string(title))

    def stage_str(self):
        the_str = f"""{self.stage_name}<{self.new_path}>"""
        return the_str

    def progress_msg_self(self):
        return f"""Cd to '{self.new_path}'"""


class ChFlags(RunProcessBase, essential=True):
    """ Change system flags (not permissions) on files or dirs.
        For changing permissions use chmod.
    """
    flags_dict = {'darwin': {'hidden': 'hidden', 'nohidden': 'nohidden', 'locked': 'uchg', 'unlocked': 'nouchg', 'system': None, 'nosystem': None},
                           'win32': {'hidden': '+H', 'nohidden': '-H', 'locked': '+R', 'unlocked': '-R', 'system': '+S', 'nosystem': '-S'}}

    def __init__(self, path, *flags: List[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path

        for flag in flags:
            assert flag in self.flags_dict[sys.platform], f"{flag} is not a valid flag"
        self.flags = sorted(flags)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(os.fspath(self.path)))
        for a_flag in self.flags:
            all_args.append(utils.quoteme_raw_if_string(a_flag))

    def progress_msg_self(self):
        return f"""changing flags '{self.flags}' of file '{self.path}"""

    def create_run_args(self):
        path = os.fspath(utils.ResolvedPath(self.path))
        self.doing = f"""changing flags '{",".join(self.flags)}' of file '{path}"""

        per_system_flags = list(filter(None, [self.flags_dict[sys.platform][flag] for flag in self.flags]))
        if sys.platform == 'darwin':
            retVal = self._create_run_args_mac(per_system_flags, path)
        elif sys.platform == 'win32':
            retVal = self._create_run_args_win(per_system_flags, path)
        return retVal

    def _create_run_args_win(self, flags, path):
        run_args = list()
        run_args.append("attrib")
        if self.recursive:
            run_args.extend(('/S', '/D'))
        run_args.extend(flags)
        run_args.append(os.fspath(path))
        return run_args

    def _create_run_args_mac(self, flags, path):
        run_args = list()
        run_args.append("chflags")
        if self.ignore_all_errors:
            run_args.append("-f")
        if self.recursive:
            run_args.append("-R")
        joint_flags = ",".join(flags)  # on mac the flags must be separated by commas
        run_args.append(joint_flags)
        run_args.append(os.fspath(path))
        return run_args


class Unlock(ChFlags, essential=True, kwargs_defaults={"ignore_all_errors": True}):
    """ Remove the system's read-only flag (not permissions).
        For changing permissions use chmod.
    """
    def __init__(self, path, **kwargs):
        super().__init__(path, "unlocked", **kwargs)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(os.fspath(self.path)))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} '{self.path}'"""


class AppendFileToFile(PythonBatchCommandBase, essential=True):
    """ append the content of 'source_file' to 'target_file'"""
    def __init__(self, source_file, target_file):
        super().__init__()
        self.source_file = source_file
        self.target_file = target_file

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""source_file={utils.quoteme_raw_string(os.fspath(self.source_file))}""")
        all_args.append( f"""target_file={utils.quoteme_raw_string(os.fspath(self.target_file))}""")

    def progress_msg_self(self):
        the_progress_msg = f"Append {self.source_file} to {self.target_file}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        resolved_source = utils.ResolvedPath(self.source_file)
        resolved_target = utils.ResolvedPath(self.target_file)
        self.doing = f"Append {resolved_source} to {resolved_target}"
        with open(self.target_file, "a") as wfd:
            with open(self.source_file, "r") as rfd:
                wfd.write(rfd.read())


class Chown(RunProcessBase, call__call__=True, essential=True):
    """ change owner (either user, group or both) of file or folder
        if 'path' is a folder and recursive==True, ownership will be changed recursively
    """
    def __init__(self, path: os.PathLike, user_id: Union[int, str, None], group_id: Union[int, str, None], **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.user_id: Union[int, str]  = user_id   if user_id  else -1
        self.group_id: Union[int, str] = group_id  if group_id else -1
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""path={utils.quoteme_raw_string(os.fspath(self.path))}""")
        all_args.append( f"""user_id={utils.quoteme_raw_string(os.fspath(self.user_id))}""")
        all_args.append( f"""group_id={utils.quoteme_raw_string(os.fspath(self.group_id))}""")

    def create_run_args(self):
        run_args = list()
        run_args.append("chown")
        run_args.append("-f")
        if self.recursive:
            run_args.append("-R")
        user_and_group = ""
        if self.user_id != -1:
            user_and_group += f"{self.user_id}"
        if self.group_id != -1:
            user_and_group += f":{self.group_id}"
        run_args.append(user_and_group)
        the_path = os.fspath(utils.ResolvedPath(self.path))
        run_args.append(the_path)
        return run_args

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} {self.user_id}:{self.group_id} '{self.path}'"""

    def __call__(self, *args, **kwargs):
        if (self.user_id, self.group_id) != (-1, -1):
            # os.chown is not recursive so call the system's chown
            if self.recursive:
                return super().__call__(args, kwargs)
            else:
                resolved_path = utils.ResolvedPath(self.path)
                self.doing = f"""change owner of '{resolved_path}' to '{self.user_id}:{self.group_id}'"""
                os.chown(resolved_path, uid=int(self.user_id), gid=int(self.group_id))


class Chmod(RunProcessBase, essential=True):
    """ change mode read.write/execute permissions for a file or folder"""

    all_read = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    all_exec = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    all_read_write = all_read | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    all_read_write_exec = all_read_write | all_exec
    user_read_write_exec = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    all_read_exec = all_read | all_exec
    who_2_perm = {'u': {'r': stat.S_IRUSR, 'w': stat.S_IWUSR, 'x': stat.S_IXUSR},
                  'g': {'r': stat.S_IRGRP, 'w': stat.S_IWGRP, 'x': stat.S_IXGRP},
                  'o': {'r': stat.S_IROTH, 'w': stat.S_IWOTH, 'x': stat.S_IXOTH}}

    def __init__(self, path, mode, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""path={utils.quoteme_raw_string(os.fspath(self.path))}""")

        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        all_args.append( f"""mode={the_mode}""")

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} {self.mode} '{self.path}'"""

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
        if sys.platform == 'darwin':
            run_args.append("chmod")
            if self.ignore_all_errors:
                run_args.append("-f")
            if self.recursive:
                run_args.append("-R")
            run_args.append(self.mode)
        elif sys.platform == 'win32':
            run_args.append('attrib')
            if self.recursive:
                run_args.append('/s')
        run_args.append(utils.ResolvedPath(self.path))
        return run_args

    def __call__(self, *args, **kwargs):
        # os.chmod is not recursive so call the system's chmod
        if self.recursive:
            return super().__call__(args, kwargs)
        else:
            resolved_path = utils.ResolvedPath(self.path)
            path_stats = resolved_path.stat()
            flags, op = self.parse_symbolic_mode(self.mode)
            mode_to_set = flags
            current_mode = stat.S_IMODE(path_stats[stat.ST_MODE])
            if op == '+':
                mode_to_set |= current_mode
            elif op == '-':
                mode_to_set = current_mode & ~flags
            if mode_to_set != current_mode:
                self.doing = f"""change mode of '{resolved_path}' to '{mode_to_set}''"""
                os.chmod(resolved_path, mode_to_set)
            else:
                self.doing = f"""skip change mode of '{resolved_path}' mode is already '{mode_to_set}''"""


class ChmodAndChown(PythonBatchCommandBase, essential=True):
    """ change mode and owner for file or folder"""

    def __init__(self, path: os.PathLike, mode, user_id: Union[int, str, None], group_id: Union[int, str, None], **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode
        self.user_id: Union[int, str]  = user_id   if user_id  else -1
        self.group_id: Union[int, str] = group_id  if group_id else -1

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""path={utils.quoteme_raw_string(os.fspath(self.path))}""")

        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        all_args.append( f"""mode={the_mode}""")

        all_args.append( f"""user_id={utils.quoteme_raw_if_string(self.user_id)}""")
        all_args.append( f"""group_id={utils.quoteme_raw_if_string(self.group_id)}""")

    def progress_msg_self(self):
        return f"""Chmod and Chown {self.mode} '{self.path}' {self.user_id}:{self.group_id}"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        self.doing = f"""Chmod and Chown {self.mode} '{resolved_path}' {self.user_id}:{self.group_id}"""
        Chown(path=resolved_path, user_id=self.user_id, group_id=self.group_id, recursive=self.recursive, own_progress_count=0)()
        Chmod(path=resolved_path, mode=self.mode, recursive=self.recursive, own_progress_count=0)()


class Ls(PythonBatchCommandBase, essential=True):
    """ create a listing for one or more folders, similar to unix ls command"""
    def __init__(self, *folders_to_list, out_file=None, ls_format='*', **kwargs) -> None:
        super().__init__(**kwargs)
        self.ls_format = ls_format
        self.out_file = out_file
        assert self.out_file is not None
        self.folders_to_list = sorted(folders_to_list)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.extend(utils.quoteme_raw_string(os.fspath(path)) for path in self.folders_to_list)
        all_args.append( f"""out_file={utils.quoteme_raw_string(os.fspath(self.out_file))}""")
        all_args.append( f"""ls_format='{self.ls_format}'""")

    def progress_msg_self(self) -> str:
        return f"""List {utils.quoteme_raw_if_list(self.folders_to_list, one_element_list_as_string=True)} to '{self.out_file}'"""

    def __call__(self, *args, **kwargs) -> None:
        resolved_folder_list = [utils.ResolvedPath(folder_path) for folder_path in self.folders_to_list]
        the_listing = utils.disk_item_listing(*resolved_folder_list, ls_format=self.ls_format)
        with utils.write_to_file_or_stdout(self.out_file) as wfd:
            wfd.write(the_listing)

# todo:
# override PythonBatchCommandBase for all commands
# time measurements
# InstlAdmin
