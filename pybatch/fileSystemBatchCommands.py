import sys
import stat
import random
import string
import itertools
from pathlib import Path
import math
import collections
from typing import List, Any, Optional, Union
import re

if sys.platform == 'win32':
    import getpass
    import win32security
    import ntsecuritycon as con
    from .WinOnlyBatchCommands import FullACLForEveryone

import utils
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase
from configVar import config_vars

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


class MakeRandomDirs(PythonBatchCommandBase, essential=True):
    """ MakeRandomDirs is intended for use during tests - not for production
        Will create in current working directory a hierarchy of folders and files with random names so we can test copying
    """

    def __init__(self, num_levels: int, num_dirs_per_level: int, num_files_per_dir: int, file_size: int, **kwargs) -> None:
        super().__init__(**kwargs)
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
            MakeRandomDataFile(random_file_name, self.file_size)()
        if num_levels > 0:
            for i_dir in range(self.num_dirs_per_level):
                random_dir_name = ''.join(random.choice(string.ascii_uppercase) for i in range(8))
                os.makedirs(random_dir_name, mode=0o777, exist_ok=False)
                save_cwd = os.getcwd()
                os.chdir(random_dir_name)
                self.make_random_dirs_recursive(num_levels-1)
                os.chdir(save_cwd)

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.make_random_dirs_recursive(self.num_levels)


class MakeDirs(PythonBatchCommandBase, essential=True):
    """ Create one or more dirs
        when remove_obstacles==True if one of the paths is a file it will be removed, and permissions/owner adjusted
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
        all_args.extend(utils.quoteme_raw_by_type(path) for path in self.paths_to_make)
        if not self.remove_obstacles:
            all_args.append(f"remove_obstacles={self.remove_obstacles}")

    def progress_msg_self(self):
        paths = ", ".join(os.path.expandvars(utils.quoteme_raw_by_type(path)) for path in self.paths_to_make)
        titula = "directory" if len(self.paths_to_make) == 1 else "directories"
        the_progress_msg = f"Create {titula} {paths}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        for self.cur_path in self.paths_to_make:
            self.cur_path = utils.ExpandAndResolvePath(self.cur_path)
            if self.remove_obstacles:
                if self.cur_path.is_file():
                    self.doing = f"""removing file that should be a folder '{self.cur_path}'"""
                    self.cur_path.unlink()
            self.doing = f"""creating a folder '{self.cur_path}'"""
            self.cur_path.mkdir(parents=True, mode=0o777, exist_ok=True)
            if self.remove_obstacles:
                if sys.platform == 'win32':
                    with FullACLForEveryone(self.cur_path, recursive=True, own_progress_count=0) as grant_permissions:
                        grant_permissions()
                elif sys.platform == 'darwin':
                    with Chown(path=self.cur_path, user_id=int(config_vars.get("ACTING_UID", -1)), group_id=int(config_vars.get("ACTING_GID", -1)), recursive=True, own_progress_count=0) as change_user:
                        change_user()

                # this is for both Mac and Windows, on Mac it will call chmod, on windows attrib
                with Chmod(self.cur_path, "a+rw", recursive=True, own_progress_count=0) as grant_permissions:
                    grant_permissions()


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
        all_args.append(utils.quoteme_raw_by_type(self.path))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_path = utils.ExpandAndResolvePath(self.path)
        if resolved_path.is_dir():
            os.utime(resolved_path)
        else:
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
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
        all_args.append(utils.quoteme_raw_by_type(self.new_path))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.new_path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.old_path = Path.cwd()
        resolved_new_path = utils.ExpandAndResolvePath(self.new_path)
        self.doing = f"""changing current directory to '{resolved_new_path}'"""
        assert resolved_new_path.is_dir(), f"directory does not exist '{resolved_new_path}'"
        os.chdir(resolved_new_path)
        assert resolved_new_path.samefile(Path.cwd()), f"failed to cd into '{resolved_new_path}'"

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
        all_args.append(utils.quoteme_raw_by_type(self.stage_name))
        all_args.append(utils.quoteme_raw_by_type(self.new_path))
        for title in self.titles:
            all_args.append(utils.quoteme_raw_by_type(title))

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
        all_args.append(utils.quoteme_raw_by_type(self.path))
        for a_flag in self.flags:
            all_args.append(utils.quoteme_raw_by_type(a_flag))

    def progress_msg_self(self):
        return f"""changing flags '{self.flags}' of file '{self.path}"""

    def get_run_args(self, run_args) -> None:
        path = os.fspath(utils.ExpandAndResolvePath(self.path))
        self.doing = f"""changing flags '{",".join(self.flags)}' of file '{path}"""

        per_system_flags = list(filter(None, [self.flags_dict[sys.platform][flag] for flag in self.flags]))
        if sys.platform == 'darwin':
            self._create_run_args_mac(per_system_flags, path, run_args)
        elif sys.platform == 'win32':
            self._create_run_args_win(per_system_flags, path, run_args)

    def _create_run_args_win(self, flags, path, run_args) -> None:
        run_args.append("attrib")
        if self.recursive:
            run_args.extend(('/S', '/D'))
        run_args.extend(flags)
        run_args.append(os.fspath(path))

    def _create_run_args_mac(self, flags, path, run_args) -> None:
        run_args.append("chflags")
        if self.ignore_all_errors:
            run_args.append("-f")
        if self.recursive:
            run_args.append("-R")
        joint_flags = ",".join(flags)  # on mac the flags must be separated by commas
        run_args.append(joint_flags)
        run_args.append(os.fspath(path))


class Unlock(ChFlags, essential=True, kwargs_defaults={"ignore_all_errors": True}):
    """ Remove the system's read-only flag (not permissions).
        For changing permissions use chmod.
    """
    def __init__(self, path, **kwargs):
        super().__init__(path, "unlocked", **kwargs)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.path))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} '{self.path}'"""


class AppendFileToFile(PythonBatchCommandBase, essential=True):
    """ append the content of 'source_file' to 'target_file'"""
    def __init__(self, source_file, target_file, **kwargs):
        super().__init__(**kwargs)
        self.source_file = source_file
        self.target_file = target_file

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""source_file={utils.quoteme_raw_by_type(self.source_file)}""")
        all_args.append( f"""target_file={utils.quoteme_raw_by_type(self.target_file)}""")

    def progress_msg_self(self):
        the_progress_msg = f"Append {self.source_file} to {self.target_file}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_source = utils.ExpandAndResolvePath(self.source_file)
        resolved_target = utils.ExpandAndResolvePath(self.target_file)
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
        self.user_id: int  = int(user_id)   if user_id  else -1
        self.group_id: int = int(group_id)  if group_id else -1
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""path={utils.quoteme_raw_by_type(self.path)}""")
        all_args.append( f"""user_id={utils.quoteme_raw_by_type(self.user_id)}""")
        all_args.append( f"""group_id={utils.quoteme_raw_by_type(self.group_id)}""")

    def get_run_args(self, run_args) -> None:
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
        the_path = os.fspath(utils.ExpandAndResolvePath(self.path))
        run_args.append(the_path)

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} {self.user_id}:{self.group_id} '{self.path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        if (self.user_id, self.group_id) != (-1, -1):
            # os.chown is not recursive so call the system's chown
            if self.recursive:
                self.doing = f"""change owner (recursive) of '{self.path}' to '{self.user_id}:{self.group_id}'"""
                return super().__call__(args, kwargs)
            else:
                resolved_path = utils.ExpandAndResolvePath(self.path)
                self.doing = f"""change owner of '{resolved_path}' to '{self.user_id}:{self.group_id}'"""
                os.chown(resolved_path, uid=int(self.user_id), gid=int(self.group_id))


class Chmod(RunProcessBase, essential=True):
    """ change mode read.write/execute permissions for a file or folder"""

    if sys.platform == 'darwin':
        symbolic_mode_re = re.compile("""^(?P<who>[augo]+)(?P<operation>[+\-=])(?P<perm>[rwxX]+)$""")
    elif sys.platform == 'win32':
        symbolic_mode_re = re.compile("""^(?P<who>[augo]+)(?P<operation>\+)(?P<perm>[rwx]+)$""")

    all_read = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    all_exec = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    all_read_write = all_read | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    all_read_write_exec = all_read_write | all_exec
    user_read_write_exec = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    all_read_exec = all_read | all_exec
    who_2_perm = {'u': {'r': stat.S_IRUSR, 'w': stat.S_IWUSR, 'x': stat.S_IXUSR},
                  'g': {'r': stat.S_IRGRP, 'w': stat.S_IWGRP, 'x': stat.S_IXGRP},
                  'o': {'r': stat.S_IROTH, 'w': stat.S_IWOTH, 'x': stat.S_IXOTH}}
    if sys.platform == 'win32':
        win_perms = {'r': con.FILE_GENERIC_READ,
                 'w': con.FILE_GENERIC_WRITE|con.FILE_GENERIC_READ,
                 'x': con.FILE_GENERIC_EXECUTE}

    def __init__(self, path, mode, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""path={utils.quoteme_raw_by_type(self.path)}""")

        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        all_args.append( f"""mode={the_mode}""")

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} {self.mode} '{self.path}'"""

    def parse_symbolic_mode_mac(self, symbolic_mode_str):
        """ parse chmod symbolic mode string e.g. uo+xw
            return the mode as a number (e.g 766) and the operation (e.g. =|+|-)
        """
        match = self.symbolic_mode_re.match(symbolic_mode_str)
        if not match:
            raise ValueError(f"invalid symbolic mode for chmod: {symbolic_mode_str}")
        symbolic_who = match.group('who')
        if 'a' in symbolic_who:
            symbolic_who = 'ugo'

        symbolic_perm = match.group('perm')
        actual_perms = 0
        for w in symbolic_who:
            for p in symbolic_perm:
                actual_perms |= Chmod.who_2_perm[w][p]
        return actual_perms, match.group('operation')

    def parse_symbolic_mode_win(self, symbolic_mode_str):
        """ parse chmod symbolic mode string e.g. uo+xw
            return the mode as a number (e.g 766) and the operation (e.g. =|+|-)
        """
        flags = 0
        match = self.symbolic_mode_re.match(symbolic_mode_str)
        if not match:
            raise ValueError(f"invalid symbolic mode for chmod: {symbolic_mode_str}")
        if match.group('operation') != '+':
            raise ValueError(f"on Windows the only chmod operation allowed is '+' not {match.group('operation')}")
        symbolic_who = match.group('who')
        if 'a' in symbolic_who:
            symbolic_who = 'ugo'

        actual_who = list()
        for w in symbolic_who:
            if w == "u":
                actual_who.append(getpass.getuser())
            elif w == "g":
                actual_who.append("Users")
            elif w == "o":
                actual_who.append("Everyone")

        actual_perms = match.group('perm')
        for p in actual_perms:
            flags |= self.win_perms[p]
        return actual_who, flags, match.group('operation')

    def get_run_args(self, run_args) -> None:
        the_path = os.fspath(utils.ExpandAndResolvePath(self.path))
        if sys.platform == 'darwin':
            run_args.append("chmod")
            if self.ignore_all_errors:
                run_args.append("-f")
            if self.recursive:
                run_args.append("-R")
            run_args.append(self.mode)
            run_args.append(the_path)
        elif sys.platform == 'win32':
            run_args.append('attrib')
            if 'w' in self.mode:
                run_args.append("-R")
            if self.recursive:
                run_args.append(the_path+"\\**")
                run_args.append('/S')
            else:
                run_args.append(the_path)
            run_args.append('/D')

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        if sys.platform == 'darwin':
            # os.chmod is not recursive so call the system's chmod
            if self.recursive:
                self.doing = f"""change mode (recursive) of '{self.path}' to '{self.mode}''"""
                return super().__call__(args, kwargs)
            else:
                resolved_path = utils.ExpandAndResolvePath(self.path)
                path_stats = resolved_path.stat()
                flags, op = self.parse_symbolic_mode_mac(self.mode)
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

        elif sys.platform == 'win32':
            if self.recursive:
                self.doing = f"""change mode (recursive) of '{self.path}' to '{self.mode}''"""
                self.shell = True
                return super().__call__(args, kwargs)
            else:
                resolved_path = utils.ExpandAndResolvePath(self.path)
                who, perms, operation = self.parse_symbolic_mode_win(self.mode)
                self.doing = f"""change mode of '{resolved_path}' to '{who}, {perms}, {operation}''"""

                # on windows uncheck the read-only flag
                if 'w' in self.mode:
                    os.chmod(resolved_path, stat.S_IWRITE)
                accounts = list()
                for name in who:
                    user, domain, type = win32security.LookupAccountName("", name)
                    accounts.append(user)

                sd = win32security.GetFileSecurity(os.fspath(resolved_path), win32security.DACL_SECURITY_INFORMATION)
                dacl = sd.GetSecurityDescriptorDacl()
                for account in accounts:
                    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, perms, account)
                sd.SetSecurityDescriptorDacl(1, dacl, 0)
                win32security.SetFileSecurity(os.fspath(resolved_path), win32security.DACL_SECURITY_INFORMATION, sd)


class ChmodAndChown(PythonBatchCommandBase, essential=True):
    """ change mode and owner for file or folder"""

    def __init__(self, path: os.PathLike, mode, user_id: Union[int, str, None], group_id: Union[int, str, None], **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode
        self.user_id: Union[int, str]  = user_id   if user_id  else -1
        self.group_id: Union[int, str] = group_id  if group_id else -1

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append( f"""path={utils.quoteme_raw_by_type(self.path)}""")

        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        all_args.append( f"""mode={the_mode}""")

        all_args.append( f"""user_id={utils.quoteme_raw_by_type(self.user_id)}""")
        all_args.append( f"""group_id={utils.quoteme_raw_by_type(self.group_id)}""")

    def progress_msg_self(self):
        return f"""Chmod and Chown {self.mode} '{self.path}' {self.user_id}:{self.group_id}"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_path = utils.ExpandAndResolvePath(self.path)
        self.doing = f"""Chmod and Chown {self.mode} '{resolved_path}' {self.user_id}:{self.group_id}"""
        with Chown(path=resolved_path, user_id=self.user_id, group_id=self.group_id, recursive=self.recursive, own_progress_count=0) as owner_chaner:
            owner_chaner()
        with Chmod(path=resolved_path, mode=self.mode, recursive=self.recursive, own_progress_count=0) as mode_changer:
            mode_changer()


class Ls(PythonBatchCommandBase, essential=True, kwargs_defaults={"work_folder": None}):
    """ create a listing for one or more folders, similar to unix ls command"""
    def __init__(self, folder_to_list, out_file=None, ls_format='*', out_file_append=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_list = Path(folder_to_list)
        self.out_file = out_file
        self.ls_format = ls_format
        self.out_file_append = out_file_append

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.folder_to_list))
        all_args.append(self.optional_named__init__param("out_file", self.out_file, None))
        all_args.append(self.optional_named__init__param("ls_format", self.ls_format, '*'))
        all_args.append(self.optional_named__init__param("out_file_append", self.out_file_append, False))

    def progress_msg_self(self) -> str:
        return f"""List {os.fspath(self.folder_to_list)} to '{os.fspath(self.out_file)}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        the_listing = utils.disk_item_listing(self.folder_to_list, ls_format=self.ls_format)
        with utils.write_to_file_or_stdout(self.out_file, append_to_file=self.out_file_append) as wfd:
            wfd.write(the_listing)


class FileSizes(PythonBatchCommandBase, essential=True):
    """ create a list of files in a folder and their sizes
        file paths are listed relative to the top folder
        format is csv: partial-path-to-file, size-of-file
        files and folders are filtered according to
        useful for admin commands
    """

    def __init__(self, folder_to_scan, out_file, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_scan = folder_to_scan
        self.out_file = out_file

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.folder_to_scan))
        all_args.append(utils.quoteme_raw_by_type(self.out_file))

    def progress_msg_self(self) -> str:
        return f"""File sizes in {self.folder_to_scan}"""

    def compile_exclude_regexi(self):
        forbidden_folder_regex_list = list(config_vars.get("FOLDER_EXCLUDE_REGEX", [".*"]))
        self.compiled_forbidden_folder_regex = utils.compile_regex_list_ORed(forbidden_folder_regex_list)
        forbidden_file_regex_list = list(config_vars.get("FILE_EXCLUDE_REGEX", [".*"]))
        self.compiled_forbidden_file_regex = utils.compile_regex_list_ORed(forbidden_file_regex_list)

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.compile_exclude_regexi()
        with open(self.out_file, "w") as wfd:
            utils.chown_chmod_on_fd(wfd)
            if os.path.isfile(self.folder_to_scan):
                file_size = os.path.getsize(self.folder_to_scan)
                wfd.write(f"{self.folder_to_scan}, {file_size}\n")
            else:
                folder_to_scan_name_len = len(self.folder_to_scan)+1 # +1 for the last '\'
                if not self.compiled_forbidden_folder_regex.search(self.folder_to_scan):
                    for root, dirs, files in utils.excluded_walk(self.folder_to_scan, file_exclude_regex=self.compiled_forbidden_file_regex, dir_exclude_regex=self.compiled_forbidden_folder_regex, followlinks=False):
                        for a_file in files:
                            full_path = os.path.join(root, a_file)
                            file_size = os.path.getsize(full_path)
                            partial_path = full_path[folder_to_scan_name_len:]
                            wfd.write(f"{partial_path}, {file_size}\n")


class MakeRandomDataFile(PythonBatchCommandBase, essential=True):
    """ MakeRandomDataFile is intended for use during tests - not for production
        Will create a file with random data of the requested size
    """

    def __init__(self, file_path: int, file_size: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.file_path = file_path
        self.file_size = file_size
        if self.file_size < 0:
            raise ValueError(f"MakeRandomDataFile file_size cannot be negative")

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"""file_path={utils.quoteme_raw_by_type(self.file_path)}""")
        all_args.append(f"""file_size={self.file_size}""")

    def progress_msg_self(self):
        the_progress_msg = f"create file with {self.file_size} bytes of random data {self.file_path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        with open(self.file_path, "w") as wfd:
            utils.chown_chmod_on_fd(wfd)
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(self.file_size)))


class SplitFile(PythonBatchCommandBase, essential=True):
    """ Split a file to one or more parts, each part at most max_size bytes.
        The sizes of parts are attempted to be equal
        The parts are named with the same name the original with extensions, .aa. .ab, ...
        if remove_original is true the original file is removed
        if max_size is 0, the file is just renamed with extension .aa
    """
    def __init__(self, file_to_split, max_size=0, remove_original=True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.file_to_split = Path(file_to_split)
        self.max_size = max_size
        self. remove_original = remove_original
        self.num_parts = 0

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"""file_to_split={utils.quoteme_raw_by_type(self.file_to_split)}""")
        all_args.append(f"""max_size={self.max_size}""")
        all_args.append(f"""remove_original={self.remove_original}""")

    def progress_msg_self(self):
        the_progress_msg = f"split file {self.file_to_split} to {self.num_parts} parts"
        return the_progress_msg

    def calc_splits(self, original_size):
        """ return a list of files names and sizes"""
        retVal = list()

        if self.max_size == 0:  # just rename the file
            self.num_parts = 1
            part_size = original_size
        else:
            self.num_parts = (original_size // self.max_size) + (1 if original_size % self.max_size > 0 else 0)
            part_size = math.ceil(original_size / self.num_parts)

        # calc how many char the extension (.aa, .ab,...) should be
        # minimum is 2, but there can be more if number of parts > 26*26
        extension_length = 2
        num_ext_combinations = len(string.ascii_lowercase)**extension_length
        while num_ext_combinations < self.num_parts:
            num_ext_combinations *= len(string.ascii_lowercase)
            extension_length += 1

        name_iter = itertools.product(string.ascii_lowercase, repeat=extension_length)
        remaining_size = original_size
        original_extension = self.file_to_split.suffix
        for p in range(self.num_parts):
            part_path = self.file_to_split.with_suffix(f"{original_extension}.{''.join(next(name_iter))}")
            if remaining_size <= part_size:
                retVal.append((remaining_size, part_path))
                remaining_size = 0
            else:
                retVal.append((part_size, part_path))
                remaining_size -= part_size
        return retVal

    def __call__(self, *args, **kwargs):
        original_size = self.file_to_split.stat().st_size
        splits = self.calc_splits(original_size)
        print(f"original: {original_size}, max_size: {self.max_size}, self.num_parts: {len(splits)}, part_size: {splits[0][0]} naive total {len(splits)*splits[0][0]}")
        print("\n   ".join(str(s[1]) for s in splits))
        with open(self.file_to_split, "rb") as fts:
            for part_size, part_path in splits:
                with open(part_path, "wb") as pfd:
                    utils.chown_chmod_on_fd(pfd)
                    pfd.write(fts.read(part_size))
        if self.remove_original:
            self.file_to_split.unlink()


class JoinFile(PythonBatchCommandBase, essential=True):
    def __init__(self, file_to_join, remove_parts=True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.file_to_join = Path(file_to_join)
        self.remove_parts = remove_parts

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"""file_to_join={utils.quoteme_raw_by_type(self.file_to_join)}""")
        all_args.append(f"""remove_parts={self.remove_parts}""")

    def progress_msg_self(self):
        the_progress_msg = f"join file {self.file_to_join}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        if not self.file_to_join.name.endswith(".aa"):
            raise ValueError(f"name of file to join must end with .aa not: {self.file_to_join.name}")
        files_to_join = utils.find_split_files(self.file_to_join)
        joined_file_path = self.file_to_join.parent.joinpath(self.file_to_join.stem)
        with open(joined_file_path, "wb") as wfd:
            utils.chown_chmod_on_fd(wfd)
            for part_file in files_to_join:
                with open(part_file, "rb") as rfd:
                    wfd.write(rfd.read())
        if self.remove_parts:
            for part_file in files_to_join:
                os.unlink(part_file)
