#import sys
import stat
import random
import string
import itertools
from pathlib import Path
import math
from typing import Union
import re
import glob

import utils
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase
from .removeBatchCommands import RmFile
from configVar import config_vars

if sys.platform == 'win32':
    import getpass
    import win32security
    import ntsecuritycon as con
    from .WinOnlyBatchCommands import FullACLForEveryone


def touch(file_path):
    with open(file_path, 'a'):
        os.utime(file_path, None)


# regex to find some characters that should be escaped in dos, but are not
dos_escape_regex = re.compile(r"""(?<!\^)([<|&>])""", re.MULTILINE)


def escape_me_dos_callback(match_obj):
    replacement = "^" + match_obj.group(1)
    return replacement


def dos_escape(some_string):
    # 1. remove ^><|'s from end of string - they cause CMD to ask for 'More?' or 'The syntax of the command is incorrect.'
    retVal = some_string.rstrip("^><|")
    # 2. replace some chars with ?
    retVal = re.sub("""[\r\n]""", "?", retVal)
    # 3. escape some chars, but only of they are not already escaped
    retVal = dos_escape_regex.sub(escape_me_dos_callback, retVal)
    return retVal


class MakeRandomDirs(PythonBatchCommandBase):
    """ MakeRandomDirs is intended for use during tests - not for production
        Will create in current working directory a hierarchy of folders and files with random names so we can test copying
    """

    def __init__(self, num_levels: int, num_dirs_per_level: int, num_files_per_dir: int, file_size: int,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.num_levels = num_levels
        self.num_dirs_per_level = num_dirs_per_level
        self.num_files_per_dir = num_files_per_dir
        self.file_size = file_size

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("num_levels", self.num_levels))
        all_args.append(self.named__init__param("num_dirs_per_level", self.num_dirs_per_level))
        all_args.append(self.named__init__param("num_files_per_dir", self.num_files_per_dir))
        all_args.append(self.named__init__param("file_size", self.file_size))

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
                mode = int(config_vars.get("MKDIR_SYMBOLIC_MODE", 0o755))
                os.makedirs(random_dir_name, mode=mode, exist_ok=False)
                save_cwd = os.getcwd()
                os.chdir(random_dir_name)
                self.make_random_dirs_recursive(num_levels - 1)
                os.chdir(save_cwd)

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.make_random_dirs_recursive(self.num_levels)


class MakeDir(PythonBatchCommandBase,
              kwargs_defaults={'remove_obstacles': True, 'chowner': False, 'recursive_chmod': False}):
    """ Create a folder. Parent folders are created as needed.
options:
remove_obstacles:
        when remove_obstacles==True if one of the paths is a file it will be removed, and permissions/owner adjusted
        when remove_obstacles==False if one of the paths is a file 'FileExistsError: [Errno 17] File exists' will raise
        it it always OK for a dir to already exists
    """

    def __init__(self, path_to_make, **kwargs) -> None:
        """ MakeDir(path_to_make, remove_obstacles) """
        super().__init__(**kwargs)
        self.path_to_make = path_to_make

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path_to_make))

    def progress_msg_self(self):
        the_progress_msg = f"Create directory {self.path_to_make}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        """
            When creating a folder go over each non existing parent directory
            and try to create it. This gives a chance to handle errors individually for each dir
            and in case of failure we can reprot the dir place that failed to be created.
        """
        PythonBatchCommandBase.__call__(self, *args, **kwargs)

        # using all_kwargs_dict will make sure sub commands will inherit args like ignore_all_errors
        kwargs_for_subcommands = self.all_kwargs_dict()
        kwargs_for_subcommands['report_own_progress'] = False
        kwargs_for_subcommands['recursive'] = self.recursive_chmod

        self.path_to_make = utils.ExpandAndResolvePath(self.path_to_make)
        parents_stack = list()  # list of non-existing parents
        _parent_path = self.path_to_make
        while not _parent_path.is_dir():
            if _parent_path.is_symlink() or _parent_path.is_file() and self.remove_obstacles:  # yes that can happen
                with RmFile(_parent_path, **kwargs_for_subcommands) as remover:
                    remover()
            parents_stack.append(_parent_path)
            _parent_path = _parent_path.parent

        if parents_stack:
            parents_stack.reverse()
            for _dir_to_create in parents_stack:
                for _try in range(2):
                    try:
                        # we know _dir_to_create does not exist
                        self.doing = f"""creating folder '{_dir_to_create}'"""
                        mode = int(config_vars.get("MKDIR_SYMBOLIC_MODE", 0o755))
                        _dir_to_create.mkdir(parents=True, mode=mode, exist_ok=True)
                        # if dir was created fix it's permissions
                        if self.chowner:
                            with Chown(path=_dir_to_create, user_id=int(config_vars.get("ACTING_UID", -1)),
                                       group_id=int(config_vars.get("ACTING_GID", -1)),
                                       **kwargs_for_subcommands) as change_user:
                                change_user()
                        break
                    except PermissionError as per_err:
                        if _try == 0:
                            # if dir was not created fix it's parent permissions, we know _dir_to_create.parent does exist
                            self.doing = f"""fix permissions for '{_dir_to_create.parent}'"""
                            with FixAllPermissions(_dir_to_create.parent, **kwargs_for_subcommands) as perm_allower:
                                perm_allower()
                        else:
                            raise
                    except FileExistsError as fe_err:
                        if _try == 0 and self.remove_obstacles:
                            if _dir_to_create.is_file():
                                self.doing = f"""removing file that should be a folder '{_dir_to_create}'"""
                                with FixAllPermissions(_dir_to_create, **kwargs_for_subcommands) as perm_allower:
                                    perm_allower()
                                _dir_to_create.unlink()
                        else:
                            raise
        else:  # all folders already exists, just fix permissions
            with FixAllPermissions(self.path_to_make, **kwargs_for_subcommands) as perm_allower:
                perm_allower()
            if self.chowner:
                with Chown(path=self.path_to_make, user_id=int(config_vars.get("ACTING_UID", -1)),
                           group_id=int(config_vars.get("ACTING_GID", -1)), **kwargs_for_subcommands) as change_user:
                    change_user()


class MakeDirs(MakeDir):
    """ for compatibility with older index.yaml's that might have MakeDirs in them"""

    def __init__(self, *args, **kwargs) -> None:
        """ MakeDirs(path_to_make) """
        super().__init__(path_to_make=args[0], **kwargs)


class Touch(PythonBatchCommandBase):
    """ Create an empty file if it does not already exist or update modification time to now if file exist"""

    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_path = utils.ExpandAndResolvePath(self.path)
        if resolved_path.is_dir():
            os.utime(resolved_path)
        else:
            with MakeDir(resolved_path.parent, report_own_progress=False) as md:
                md()
                with open(resolved_path, 'a') as tfd:
                    os.utime(resolved_path, None)


class Cd(PythonBatchCommandBase):
    """ change current working directory to 'path'
        when called as a context manager (with statement), previous working directory will be restored on __exit__
    """

    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.new_path: os.PathLike = path
        self.old_path: os.PathLike = None
        self.resolved_new_path = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.new_path))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.new_path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.old_path = Path.cwd()
        self.resolved_new_path = utils.ExpandAndResolvePath(self.new_path)
        self.doing = f"""changing current directory to '{self.resolved_new_path}'"""
        os.chdir(self.resolved_new_path)
        assert self.resolved_new_path.samefile(Path.cwd()), f"failed to cd into '{self.resolved_new_path}'"

    def exit_self(self, exit_return):
        os.chdir(self.old_path)

    def error_dict_self(self, exc_type, exc_val, exc_tb) -> None:
        super().error_dict_self(exc_type, exc_val, exc_tb)
        if self.resolved_new_path.is_dir():
            dir_listing = utils.single_disk_item_listing(self.resolved_new_path)
            self._error_dict['permissions'] = dir_listing


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
        all_args.append(self.unnamed__init__param(self.stage_name))
        all_args.append(self.unnamed__init__param(self.new_path))
        for title in self.titles:
            all_args.append(self.unnamed__init__param(title))

    def stage_str(self):
        the_str = f"""{self.stage_name}<{self.new_path}>"""
        return the_str

    def progress_msg_self(self):
        return f"""Cd to '{self.new_path}'"""


class ChFlags(RunProcessBase):
    """ Change system flags (not permissions) on files or dirs.
        For changing permissions use chmod.
        Not implemented for linux
    """
    flags_dict = {
        'darwin': {'hidden': 'hidden', 'nohidden': 'nohidden', 'locked': 'uchg', 'unlocked': 'nouchg', 'system': None,
                   'nosystem': None},
        'win32': {'hidden': '+H', 'nohidden': '-H', 'locked': '+R', 'unlocked': '-R', 'system': '+S', 'nosystem': '-S'}}

    def __init__(self, path, *flags, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path

        if sys.platform in self.flags_dict:  # ignore
            for flag in flags:
                assert flag in self.flags_dict[sys.platform], f"{flag} is not a valid flag"
            self.flags = sorted(flags)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path))
        for a_flag in self.flags:
            all_args.append(self.unnamed__init__param(a_flag))

    def progress_msg_self(self):
        return f"""changing flags '{self.flags}' of file '{self.path}"""

    def get_run_args(self, run_args) -> None:
        if sys.platform in self.flags_dict:  # avoid linux
            path = os.fspath(utils.ExpandAndResolvePath(self.path))
            self.doing = f"""changing flags '{",".join(self.flags)}' of file '{path}"""

            per_system_flags = list(filter(None, [self.flags_dict[sys.platform][flag] for flag in self.flags]))
            if sys.platform == 'darwin':
                self._create_run_args_mac(per_system_flags, path, run_args)
            elif sys.platform == 'win32':
                if self.recursive:
                    self._create_run_args_win_recursive(per_system_flags, path, run_args)
                else:
                    self._create_run_args_win_non_recursive(per_system_flags, path, run_args)

    def _create_run_args_win_recursive(self, flags, path, run_args) -> None:
        run_args.append("attrib")
        run_args.extend(flags)
        path = os.fspath(path) + r"\*"
        run_args.extend(('/S', '/D'))
        run_args.append(path)

    def _create_run_args_win_non_recursive(self, flags, path, run_args) -> None:
        run_args.append("attrib")
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

    def error_dict_self(self, exc_type, exc_val, exc_tb):
        try:
            if sys.platform == 'darwin':
                list_of_errors = re.findall("chflags: (?P<_path>.+): Permission denied", self.stderr)
                if list_of_errors:
                    list_of_listings = list()
                    for _error in list_of_errors:
                        dir_listing = utils.single_disk_item_listing(_error, output_format="json")
                        list_of_listings.append(dir_listing)
                    self._error_dict["ls of problem files"] = list_of_listings
        except:  # populating the error dict should continue, even if error_dict_self failed
            pass

    def __call__(self, *args, **kwargs):
        if sys.platform in self.flags_dict:  # avoid linux for the time being
            if sys.platform == "win32":
                if self.recursive:
                    # on windows calling attrib recursively has to be do in two stages,
                    # once for the top folder, and once for the child folders and files
                    self.recursive = False
                    RunProcessBase.__call__(self, *args, **kwargs)
                    self.recursive = True
                    RunProcessBase.__call__(self, *args, **kwargs)
                else:
                    RunProcessBase.__call__(self, *args, **kwargs)
            else:
                RunProcessBase.__call__(self, *args, **kwargs)


class Unlock(ChFlags, kwargs_defaults={"ignore_all_errors": True}):
    """ Remove the system's read-only flag (not permissions).
        For changing permissions use chmod.
    """

    def __init__(self, path, **kwargs):
        super().__init__(path, "unlocked", **kwargs)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} '{self.path}'"""


class AppendFileToFile(PythonBatchCommandBase):
    """ append the content of 'source_file' to 'target_file'"""

    def __init__(self, source_file, target_file, **kwargs):
        super().__init__(**kwargs)
        self.source_file = source_file
        self.target_file = target_file

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("source_file", self.source_file))
        all_args.append(self.named__init__param("target_file", self.target_file))

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


class Chown(RunProcessBase, call__call__=True):
    """ change owner (either user, group or both) of file or folder
        if 'path' is a folder and recursive==True, ownership will be changed recursively
    """

    def __init__(self, path, user_id: Union[int, str, None], group_id: Union[int, str, None], **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.user_id: int = int(user_id) if user_id else -1
        self.group_id: int = int(group_id) if group_id else -1
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("path", self.path))
        all_args.append(self.named__init__param("user_id", self.user_id))
        all_args.append(self.named__init__param("group_id", self.group_id))

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

    def error_dict_self(self, exc_type, exc_val, exc_tb):
        try:
            if self.recursive:
                if sys.platform == 'darwin':
                    list_of_errors = re.findall("chown: (?P<_path>.+): Operation not permitted", self.stderr)
                    if list_of_errors:
                        list_of_listings = list()
                        for _error in list_of_errors:
                            dir_listing = utils.single_disk_item_listing(_error, output_format="json")
                            list_of_listings.append(dir_listing)
                        self._error_dict["ls of problem files"] = list_of_listings
            else:
                dir_listing = utils.single_disk_item_listing(self.path, output_format="json")
                self._error_dict["ls of problem file"] = dir_listing
        except:  # populating the error dict should continue, even if error_dict_self failed
            pass


class Chmod(RunProcessBase):
    """ change mode read.write/execute permissions for a file or folder"""

    if sys.platform == 'darwin':
        symbolic_mode_re = re.compile(r"""^(?P<who>[augo]+)(?P<operation>[+\-=])(?P<perm>[rwxX]+)$""")
    elif sys.platform == 'win32':
        symbolic_mode_re = re.compile(r"""^(?P<who>[augo]+)(?P<operation>\+)(?P<perm>[rwxX]+)$""")

    all_read = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    all_exec = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    all_read_write = all_read | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    all_read_write_exec = all_read_write | all_exec
    user_read_write_exec = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    all_read_exec = all_read | all_exec
    who_2_perm = {'u': {'r': stat.S_IRUSR, 'w': stat.S_IWUSR, 'x': stat.S_IXUSR, 'X': stat.S_IXUSR},
                  'g': {'r': stat.S_IRGRP, 'w': stat.S_IWGRP, 'x': stat.S_IXGRP, 'X': stat.S_IXGRP},
                  'o': {'r': stat.S_IROTH, 'w': stat.S_IWOTH, 'x': stat.S_IXOTH, 'X': stat.S_IXOTH}}
    if sys.platform == 'win32':
        win_perms = {'r': con.FILE_GENERIC_READ,
                     'w': con.FILE_GENERIC_WRITE | con.FILE_GENERIC_READ,
                     'x': con.FILE_GENERIC_EXECUTE,
                     'X': con.FILE_GENERIC_EXECUTE}

    def __init__(self, path, mode, ignore_if_not_exist=False, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode
        self.ignore_if_not_exist = ignore_if_not_exist

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("path", self.path))

        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        all_args.append(f"""mode={the_mode}""")
        if self.ignore_if_not_exist:
            all_args.append(f"""ignore_if_not_exist=True""")

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} {self.mode} '{self.path}'"""

    def parse_symbolic_mode_mac(self, symbolic_mode_str, current_stats):
        """ parse chmod symbolic mode string e.g. uo+xw
            return the mode as a number (e.g 766) and the operation (e.g. =|+|-)
            in case of 'X' the required mode depends on existing mode
        """
        current_mode, current_mode_oct = stat.S_IMODE(current_stats[stat.ST_MODE]), oct(
            stat.S_IMODE(current_stats[stat.ST_MODE]))
        perms_and_operation = list()
        for match in self.symbolic_mode_re.finditer(symbolic_mode_str):
            symbolic_who = match.group('who')
            if 'a' in symbolic_who:
                symbolic_who = 'ugo'

            symbolic_perm = match.group('perm')
            if stat.S_ISDIR(stat.S_IFMT(current_stats[stat.ST_MODE])):
                symbolic_perm = symbolic_perm.lower()  # for a dir we want X to mean x
                any_exec_permission = False
            else:
                any_exec_permission = current_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            actual_perms = 0
            for w in symbolic_who:
                for p in symbolic_perm:
                    if p == 'X':
                        if any_exec_permission:
                            # for non-dir 'X' means to extend the exec permission if such permission exist
                            actual_perms |= Chmod.who_2_perm[w]['x']
                    else:
                        actual_perms |= Chmod.who_2_perm[w][p]
            perms_and_operation.append((actual_perms, match.group('operation')))
        if not perms_and_operation:
            ValueError(f"no valid symbolic mode was found in {symbolic_mode_str}")
        return perms_and_operation

    def parse_symbolic_mode_win(self, symbolic_mode_str):
        """ parse chmod symbolic mode string e.g. uo+xw

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

        actual_names = list()
        actual_codes = list()
        for w in symbolic_who:
            if w == "u":
                actual_names.append(getpass.getuser())
            elif w == "g":
                actual_codes.append("S-1-5-32-549")
            elif w == "o":
                actual_codes.append("S-1-1-0")
        actual_who = {"names": actual_names,"codes": actual_codes}

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
                run_args.append(the_path + "\\**")
                run_args.append('/S')
            else:
                run_args.append(the_path)
            run_args.append('/D')

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_path = utils.ExpandAndResolvePath(self.path)
        if self.ignore_if_not_exist and not resolved_path.exists():
            self.doing = f"""skip change mode of '{resolved_path}' - does not exist'"""
            return
        if sys.platform == 'darwin':
            # os.chmod is not recursive so call the system's chmod
            if self.recursive:
                self.doing = f"""change mode (recursive) of '{self.path}' to '{self.mode}'"""
                return super().__call__(args, kwargs)
            else:
                path_stats = resolved_path.stat()
                current_mode, current_mode_oct = stat.S_IMODE(path_stats[stat.ST_MODE]), oct(
                    stat.S_IMODE(path_stats[stat.ST_MODE]))
                for flags, op in self.parse_symbolic_mode_mac(self.mode, path_stats):
                    mode_to_set = flags
                    if op == '+':
                        mode_to_set |= current_mode
                    elif op == '-':
                        mode_to_set = current_mode & ~flags
                    if mode_to_set != current_mode:
                        self.doing = f"""change mode of '{resolved_path}' to '{self.mode}'"""
                        os.chmod(resolved_path, mode_to_set)
                    else:
                        self.doing = f"""skip change mode of '{resolved_path}' mode is already '{mode_to_set}'"""

        elif sys.platform == 'win32':
            if self.recursive:
                self.doing = f"""change mode (recursive) of '{self.path}' to '{self.mode}'"""
                self.shell = True
                return super().__call__(args, kwargs)
            else:
                who, perms, operation = self.parse_symbolic_mode_win(self.mode)
                self.doing = f"""change mode of '{resolved_path}' to '{who}, {perms}, {operation}'"""

                # on windows uncheck the read-only flag
                if 'w' in self.mode:
                    os.chmod(resolved_path, stat.S_IWRITE)
                accounts = list()
                for sid in who["codes"]:
                    user = win32security.ConvertStringSidToSid(sid)
                    accounts.append(user)

                for name in who["names"]:
                    user, domain, type = win32security.LookupAccountName("", name)
                    accounts.append(user)

                sd = win32security.GetFileSecurity(os.fspath(resolved_path), win32security.DACL_SECURITY_INFORMATION)
                dacl = sd.GetSecurityDescriptorDacl()
                for account in accounts:
                    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, perms, account)
                sd.SetSecurityDescriptorDacl(1, dacl, 0)
                win32security.SetFileSecurity(os.fspath(resolved_path), win32security.DACL_SECURITY_INFORMATION, sd)

    def error_dict_self(self, exc_type, exc_val, exc_tb):
        try:
            if self.recursive:
                if sys.platform == 'darwin':
                    # parse macOs's error message
                    list_of_errors = re.findall("Unable to change file mode on (?P<_path>.+): Operation not permitted",
                                                self.stderr)
                    if list_of_errors:
                        list_of_listings = list()
                        for _error in list_of_errors:
                            dir_listing = utils.single_disk_item_listing(_error, output_format="json")
                            list_of_listings.append(dir_listing)
                        self._error_dict["ls of problem files"] = list_of_listings
            else:
                dir_listing = utils.single_disk_item_listing(self.path, output_format="json")
                self._error_dict["ls of problem file"] = dir_listing

        except:  # populating the error dict should continue, even if error_dict_self failed
            pass


class ChmodAndChown(PythonBatchCommandBase):
    """ change mode and owner for file or folder"""

    def __init__(self, path: os.PathLike, mode, user_id: Union[int, str, None], group_id: Union[int, str, None],
                 **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode
        self.user_id: Union[int, str] = user_id if user_id else -1
        self.group_id: Union[int, str] = group_id if group_id else -1

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("path", self.path))

        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        all_args.append(f"""mode={the_mode}""")

        all_args.append(self.named__init__param("user_id", self.user_id))
        all_args.append(self.named__init__param("group_id", self.group_id))

    def progress_msg_self(self):
        return f"""Chmod and Chown {self.mode} '{self.path}' {self.user_id}:{self.group_id}"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_path = utils.ExpandAndResolvePath(self.path)
        self.doing = f"""Chmod and Chown {self.mode} '{resolved_path}' {self.user_id}:{self.group_id}"""
        with Chown(path=resolved_path, user_id=self.user_id, group_id=self.group_id, recursive=self.recursive,
                   own_progress_count=0) as owner_chaner:
            owner_chaner()
        with Chmod(path=resolved_path, mode=self.mode, recursive=self.recursive, own_progress_count=0) as mode_changer:
            mode_changer()


class Ls(PythonBatchCommandBase, kwargs_defaults={"work_folder": None}):
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


class FileSizes(PythonBatchCommandBase):
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
        self.compiled_forbidden_folder_regex = None
        self.compiled_forbidden_file_regex = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.folder_to_scan))
        all_args.append(self.unnamed__init__param(self.out_file))

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
                folder_to_scan_name_len = len(self.folder_to_scan) + 1  # +1 for the last '\'
                if not self.compiled_forbidden_folder_regex.search(self.folder_to_scan):
                    for root, dirs, files in utils.excluded_walk(self.folder_to_scan,
                                                                 file_exclude_regex=self.compiled_forbidden_file_regex,
                                                                 dir_exclude_regex=self.compiled_forbidden_folder_regex,
                                                                 followlinks=False):
                        for a_file in files:
                            full_path = os.path.join(root, a_file)
                            file_size = os.path.getsize(full_path)
                            partial_path = full_path[folder_to_scan_name_len:]
                            wfd.write(f"{partial_path}, {file_size}\n")


class MakeRandomDataFile(PythonBatchCommandBase):
    """ MakeRandomDataFile is intended for use during tests - not for production
        Will create a file with random data of the requested size
    """

    def __init__(self, file_path, file_size: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.file_path = file_path
        self.file_size = file_size
        if self.file_size < 0:
            raise ValueError(f"MakeRandomDataFile file_size cannot be negative")

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("file_path", self.file_path))
        all_args.append(self.named__init__param("file_size", self.file_size))

    def progress_msg_self(self):
        the_progress_msg = f"create file with {self.file_size} bytes of random data {self.file_path}"
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        with open(self.file_path, "w") as wfd:
            utils.chown_chmod_on_fd(wfd)
            wfd.write(
                ''.join(random.choice(string.ascii_lowercase + string.ascii_uppercase) for i in range(self.file_size)))


class SplitFile(PythonBatchCommandBase):
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
        self.remove_original = remove_original
        self.num_parts = 0

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("file_to_split", self.file_to_split))
        all_args.append(self.named__init__param("max_size", self.max_size))
        all_args.append(self.named__init__param("remove_original", self.remove_original))

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
        num_ext_combinations = len(string.ascii_lowercase) ** extension_length
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
        print(
            f"original: {original_size}, max_size: {self.max_size}, self.num_parts: {len(splits)}, part_size: {splits[0][0]} naive total {len(splits) * splits[0][0]}")
        print("\n   ".join(str(s[1]) for s in splits))
        with open(self.file_to_split, "rb") as fts:
            for part_size, part_path in splits:
                with open(part_path, "wb") as pfd:
                    utils.chown_chmod_on_fd(pfd)
                    pfd.write(fts.read(part_size))
        if self.remove_original:
            with RmFile(self.file_to_split, report_own_progress=False) as rf:
                rf()


class JoinFile(PythonBatchCommandBase):
    def __init__(self, file_to_join, remove_parts=True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.file_to_join = Path(file_to_join)
        self.remove_parts = remove_parts

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("file_to_join", self.file_to_join))
        all_args.append(self.named__init__param("remove_parts", self.remove_parts))

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
                with RmFile(part_file, report_own_progress=False) as part_remover:
                    part_remover()


class FixAllPermissions(PythonBatchCommandBase):

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)
        self.path = path

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("path", self.path))

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} '{self.path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.doing = f"""allowing all permissions for'{self.path}'"""
        # chflags first since (at least on Mac) it has higher priority (e.g. you cannot chmod a-w on files with flags uchg set,
        # but you can chflags nouchg on files with a-w set)
        with ChFlags(self.path, 'nohidden', 'unlocked', 'nosystem', report_own_progress=False,
                     recursive=self.recursive) as chflager:
            chflager()
        if sys.platform in ('darwin', 'linux'):
            the_mode = config_vars.get("FIX_ALL_PERMISSIONS_SYMBOLIC_MODE", "u+rwx,go+rx").str()
            with Chmod(path=self.path, mode=the_mode, report_own_progress=False, recursive=self.recursive) as chmoder:
                chmoder()
        elif sys.platform == 'win32':
            with FullACLForEveryone(path=self.path, report_own_progress=False, recursive=self.recursive) as acler:
                acler()


class Glober(PythonBatchCommandBase):
    """ run a given class on a list of file created from a glob pattern
        for example to delete all file is a folder ending with .h:
        with Glober(glob_pattern="/A/b/*.h", class_to_run=RmFile, target_param_name="path") as glober:
            glober()
    """
    def __init__(self, glob_pattern, class_to_run, target_param_name, *argv_for_glob_handler, **kwargs_for_glob_handler):
        """
        :param glob_pattern:  the glob pattern to run on,
                syntax as defined in https://docs.python.org/3.6/library/pathlib.html#pathlib.Path.glob
        :param class_to_run: class_to_run, the class that handles each of the file in the list create by glob
        :param target_param_name: the name of the param to pass to class_to_run with the file path
        :param argv_for_glob_handler: positional args to pass to class_to_run __init__()
        :param kwargs_for_glob_handler: named args to pass to class_to_run __init__()
        """
        super().__init__()
        self.glob_pattern = glob_pattern
        self.target_param_name = target_param_name
        self.class_to_run = class_to_run
        self.argv_for_glob_handler = list(argv_for_glob_handler)
        self.kwargs_for_glob_handler = kwargs_for_glob_handler
        pass

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.glob_pattern))
        all_args.append(self.class_to_run.__name__)
        if self.target_param_name:
            all_args.append(self.unnamed__init__param(self.target_param_name))
        else:
            all_args.append("None")  # by not calling unnamed__init__param we make sure None will bewitten without quotes
        for positional_arg in self.argv_for_glob_handler:
            all_args.append(self.unnamed__init__param(positional_arg))
        for name, value in self.kwargs_for_glob_handler.items():
            all_args.append(self.named__init__param(name, value))
        pass

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} '{self.glob_pattern}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.doing = f"""running {self.class_to_run} on glob pattern'{self.glob_pattern}'"""
        self.kwargs_for_glob_handler['report_own_progress'] = False

        if not self.target_param_name:
            self.argv_for_glob_handler.insert(0, None)

        for a_path in glob.glob(self.glob_pattern):
            if self.target_param_name:
                self.kwargs_for_glob_handler[self.target_param_name] = a_path
                with self.class_to_run(*self.argv_for_glob_handler, **self.kwargs_for_glob_handler) as handler:
                    handler()
            else:
                self.argv_for_glob_handler[0] = a_path
                with self.class_to_run(*self.argv_for_glob_handler, **self.kwargs_for_glob_handler) as handler:
                    handler()


if sys.platform == "darwin":
    import fcntl

    def exclusive_lock_fileno(fileno):
        fcntl.flock(fileno, fcntl.LOCK_EX)

    def exclusive_unlock_fileno(fileno):
        fcntl.flock(fileno, fcntl.LOCK_UN)

elif sys.platform == "win32":
    pass
    # import win32con, win32file, pywintypes
    # LOCK_EX = win32con.LOCKFILE_EXCLUSIVE_LOCK
    # LOCK_SH = 0 # the default
    # # LOCK_NB = win32con.LOCKFILE_FAIL_IMMEDIATELY
    # # _ _overlapped = pywintypes.OVERLAPPED()
    # def exclusive_lock_fileno(fileno):
    #     hfile = win32file._get_osfhandle(fileno)
    #     win32file.LockFileEx(hfile, flags, 0, 0xffff0000, _ _overlapped)
    #
    # def exclusive_unlock_fileno(fileno):
    #     hfile = win32file._get_osfhandle(fileno)
    #     win32file.UnlockFileEx(hfile, 0, 0xffff0000, _ _overlapped)


class AdvisoryFileLock(PythonBatchCommandBase, call__call__=False):
    def __init__(self, path_to_file, lock_extension=".lock", **kwargs):
        super().__init__(**kwargs)
        self.path_to_file = Path(path_to_file)
        self.lock_extension = lock_extension
        lock_file_name = self.path_to_file.name + lock_extension
        self.lock_file_path = self.path_to_file.with_name(lock_file_name)
        self.lock_fileno = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path_to_file))
        all_args.append(self.optional_named__init__param('lock_extension', self.lock_extension, ".lock"))

    def __call__(self):
        pass

    def progress_msg_self(self) -> str:
        return f"""Locking file '{self.path_to_file}'"""

    def enter_self(self) -> None:
        print(f"before open: {self.lock_file_path}")
        self.lock_fileno = open(self.lock_file_path, "w")
        exclusive_lock_fileno(self.lock_fileno)
        print(f"before lock: {self.lock_file_path}")
        print(f"after lock: {self.lock_file_path}")

    def exit_self(self, exit_return) -> None:
        print(f"before unlock: {self.lock_file_path}")
        exclusive_unlock_fileno(self.lock_fileno)
        self.lock_fileno.close()
        print(f"after unlock: {self.lock_file_path}")
