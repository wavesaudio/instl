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


class MakeDirs(PythonBatchCommandBase, essential=True):
    """ Create one or more dirs
        when remove_obstacles==True if one of the paths is a file it will be removed
        when remove_obstacles==False if one of the paths is a file 'FileExistsError: [Errno 17] File exists' will raise
        it it always OK for a dir to already exists
        Tests: TestPythonBatch.test_MakeDirs_*
    """
    def __init__(self, *paths_to_make, remove_obstacles: bool=True) -> None:
        super().__init__()
        self.paths_to_make = paths_to_make
        self.remove_obstacles = remove_obstacles
        self.cur_path = None
        self.own_progress_count = len(self.paths_to_make)

    def __repr__(self):
        paths_csl = ", ".join(utils.quoteme_raw_string(os.fspath(path)) for path in self.paths_to_make)
        the_repr = f"""{self.__class__.__name__}({paths_csl}"""
        if not self.remove_obstacles:
            the_repr += f", remove_obstacles={self.remove_obstacles}"
        the_repr += ")"
        return the_repr

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
    def __init__(self, *paths_to_make, remove_obstacles: bool=True) -> None:
        super().__init__(*paths_to_make, remove_obstacles=remove_obstacles)


class Touch(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike) -> None:
        super().__init__()
        self.path = path

    def __repr__(self):

        the_repr = f"""{self.__class__.__name__}(path={utils.quoteme_raw_string(os.fspath(self.path))})"""
        return the_repr

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.path}'"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        with open(resolved_path, 'a') as tfd:
            os.utime(resolved_path, None)


class Cd(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike) -> None:
        super().__init__()
        self.new_path: os.PathLike = path
        self.old_path: os.PathLike = None

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.new_path))})"""
        return the_repr

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} to '{self.new_path}'"""

    def __call__(self, *args, **kwargs):
        self.old_path = os.getcwd()
        resolved_new_path = utils.ResolvedPath(self.new_path)
        self.doing = f"""changing current directory to '{resolved_new_path}'"""
        os.chdir(resolved_new_path)

    def exit_self(self, exit_return):
        os.chdir(self.old_path)


class CdSection(Cd, essential=False):
    def __init__(self, path: os.PathLike, *titles) -> None:
        super().__init__(path)
        self.new_path: os.PathLike = path
        self.old_path: os.PathLike = None
        self.titles = titles

    def __repr__(self):
        if len(self.titles) == 1:
            quoted_titles = utils.quoteme_double(self.titles[0])
        else:
            quoted_titles = ", ".join((utils.quoteme_double(title) for title in self.titles))
        the_repr = f"""{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.new_path))}"""
        if quoted_titles:
            the_repr += f""", {quoted_titles}"""
        the_repr += ")"
        return the_repr

    def progress_msg_self(self):
        return f"""Cd to '{self.new_path}'"""

    def __call__(self, *args, **kwargs):
        self.old_path = os.getcwd()
        resolved_new_path = Path(os.path.expandvars(self.new_path))
        self.doing = f"""changing current directory to '{resolved_new_path}'"""
        os.chdir(resolved_new_path)

    def exit_self(self, exit_return):
        os.chdir(self.old_path)


class ChFlags(RunProcessBase, essential=True):
    """ Mac specific to change system flags on files or dirs.
        These flags are different from permissions.
        For changing permissions use chmod.
    """
    def __init__(self, path, flag: str, recursive=False, ignore_errors=True) -> None:
        super().__init__(ignore_all_errors=ignore_errors)
        self.flags_dict = {'darwin': {'hidden': 'hidden', 'nohidden': 'nohidden', 'locked': 'uchg', 'unlocked': 'nouchg'},
                           'win32': {'hidden': '+H', 'nohidden': '-H', 'locked': '+R', 'unlocked': '-R'}}
        self.path = path
        self.flag = flag
        self.recursive = recursive
        self.ignore_errors = ignore_errors

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path={utils.quoteme_raw_string(os.fspath(self.path))}, flag="{self.flag}", recursive={self.recursive}, ignore_errors={self.ignore_errors})"""
        return the_repr

    def progress_msg_self(self):
        return f"""changing flag '{self.flag}' of file '{self.path}"""

    def create_run_args(self):
        path = os.fspath(utils.ResolvedPath(self.path))
        self.doing = f"""changing flag '{self.flag}' of file '{path}"""
        flag = self.flags_dict[sys.platform][self.flag]
        if sys.platform == 'darwin':
            retVal = self._create_run_args_mac(flag, path)
        elif sys.platform == 'win32':
            retVal = self._create_run_args_win(flag, path)
        return retVal

    def _create_run_args_win(self, flag, path):
        run_args = list()
        run_args.append("attrib")
        if self.recursive:
            run_args.extend(('/S', '/D'))
        run_args.append(flag)
        run_args.append(os.fspath(path))
        return run_args

    def _create_run_args_mac(self, flag, path):
        run_args = list()
        run_args.append("chflags")
        if self.ignore_errors:
            run_args.append("-f")
        if self.recursive:
            run_args.append("-R")
        run_args.append(flag)
        run_args.append(os.fspath(path))
        return run_args


class Unlock(ChFlags, essential=True):
    """
        Remove the system's read-only flag, this is different from permissions.
        For changing permissions use chmod.
    """
    def __init__(self, path, recursive=False, ignore_errors=True):
        super().__init__(path, "unlocked", recursive=recursive, ignore_errors=ignore_errors)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path={utils.quoteme_raw_string(os.fspath(self.path))}, recursive={self.recursive}, ignore_errors={self.ignore_errors})"""
        return the_repr

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} '{self.path}'"""


class RmFile(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike) -> None:
        """ remove a file
            - It's OK is the file does not exist
            - but exception will be raised if path is a folder
        """
        super().__init__()
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.path))})"""
        return the_repr

    def progress_msg_self(self):
        return f"""Remove file '{self.path}'"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        self.doing = f"""removing file '{resolved_path}'"""
        resolved_path.unlink()
        return None


class RmDir(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike) -> None:
        """ remove a directory.
            - it's OK if the directory does not exist.
            - all files and directory under path will be removed recursively
            - exception will be raised if the path if a folder
        """
        super().__init__()
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.path))})"""
        return the_repr

    def progress_msg_self(self):
        return f"""Remove directory '{self.path}'"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        self.doing = f"""removing folder '{resolved_path}'"""
        shutil.rmtree(resolved_path)
        return None


class RmFileOrDir(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike):
        """ remove a file or directory.
            - it's OK if the path does not exist.
            - all files and directory under path will be removed recursively
        """
        super().__init__()
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path={utils.quoteme_raw_string(os.fspath(self.path))})"""
        return the_repr

    def progress_msg_self(self):
        return f"""Remove '{self.path}'"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        if resolved_path.is_file():
            self.doing = f"""removing file'{resolved_path}'"""
            resolved_path.unlink()
        elif resolved_path.is_dir():
            self.doing = f"""removing folder'{resolved_path}'"""
            shutil.rmtree(resolved_path)


class AppendFileToFile(PythonBatchCommandBase, essential=True):
    def __init__(self, source_file, target_file):
        super().__init__()
        self.source_file = source_file
        self.target_file = target_file

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(source_file={utils.quoteme_raw_string(os.fspath(self.source_file))}, target_file={utils.quoteme_raw_string(os.fspath(self.target_file))})"""
        return the_repr

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
        return None


class Chown(RunProcessBase, call__call__=True, essential=True):
    def __init__(self, user_id: Union[int, str, None], group_id: Union[int, str, None], path: os.PathLike, recursive: bool=False, **kwargs):
        super().__init__(**kwargs)
        self.user_id: Union[int, str]  = user_id   if user_id  else -1
        self.group_id: Union[int, str] = group_id  if group_id else -1
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
        user_and_group = ""
        if self.user_id != -1:
            user_and_group += f"{self.user_id}"
        if self.group_id != -1:
            user_and_group += f":{self.group_id}"
        run_args.append(user_and_group)
        run_args.append(self.path)
        return run_args

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} {self.user_id}:{self.group_id} '{self.path}'"""

    def __call__(self, *args, **kwargs):
        # os.chown is not recursive so call the system's chown
        if self.recursive:
            return super().__call__(args, kwargs)
        else:
            resolved_path = utils.ResolvedPath(self.path)
            self.doing = f"""change owner of '{resolved_path}' to '{self.user_id}:{self.group_id}''"""
            os.chown(resolved_path, uid=int(self.user_id), gid=int(self.group_id))
            return None


class Chmod(RunProcessBase, essential=True):
    all_read = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    all_exec = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    all_read_write = all_read | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    all_read_write_exec = all_read_write | all_exec
    user_read_write_exec = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
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
        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        the_repr = f"""{self.__class__.__name__}(path={utils.quoteme_raw_string(os.fspath(self.path))}, mode={the_mode}, recursive={self.recursive}"""
        if self.ignore_all_errors:
            the_repr += f", ignore_all_errors={self.ignore_all_errors})"
        else:
            the_repr += ")"
        return the_repr

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
        run_args.append(self.path)
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
            if op == '+':
                current_mode = stat.S_IMODE(path_stats[stat.ST_MODE])
                mode_to_set |= current_mode
            elif op == '-':
                current_mode = stat.S_IMODE(path_stats[stat.ST_MODE])
                mode_to_set = current_mode & ~flags

            self.doing = f"""change mode of '{resolved_path}' to '{mode_to_set}''"""
            os.chmod(resolved_path, mode_to_set)
        return None


class ChmodAndChown(PythonBatchCommandBase, essential=True):

    def __init__(self, path: os.PathLike, mode, user_id: Union[int, str, None], group_id: Union[int, str, None], recursive: bool=False, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.mode = mode
        self.user_id: Union[int, str]  = user_id   if user_id  else -1
        self.group_id: Union[int, str] = group_id  if group_id else -1
        self.recursive = recursive

    def __repr__(self):
        the_mode = self.mode
        if isinstance(the_mode, str):
            the_mode = utils.quoteme_double(the_mode)
        the_repr = f"""{self.__class__.__name__}(path={utils.quoteme_raw_string(os.fspath(self.path))}, mode={the_mode}, recursive={self.recursive}"""
        the_repr += f''', user_id={self.user_id}, group_id={self.group_id}'''
        if self.ignore_all_errors:
            the_repr += f", ignore_all_errors={self.ignore_all_errors})"
        else:
            the_repr += ")"
        return the_repr

    def progress_msg_self(self):
        return f"""Chmod and Chown {self.mode} '{self.path}' {self.user_id}:{self.group_id}"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        self.doing = f"""Chmod and Chown {self.mode} '{resolved_path}' {self.user_id}:{self.group_id}"""
        Chown(user_id=self.user_id, group_id=self.group_id, path=resolved_path, recursive=self.recursive, progress_count=0)()
        Chmod(path=resolved_path, mode=self.mode, recursive=self.recursive, progress_count=0)()


class RemoveEmptyFolders(PythonBatchCommandBase, essential=True):
    def __init__(self, folder_to_remove: os.PathLike, files_to_ignore: List = [], **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_remove = folder_to_remove
        self.files_to_ignore = list(files_to_ignore)

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}(folder_to_remove={utils.quoteme_raw_string(os.fspath(self.folder_to_remove))}, files_to_ignore={self.files_to_ignore})'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""Remove empty directory '{self.folder_to_remove}'"""

    def __call__(self, *args, **kwargs) -> None:
        resolved_folder_to_remove = utils.ResolvedPath(self.folder_to_remove)
        for root_path, dir_names, file_names in os.walk(resolved_folder_to_remove, topdown=False, onerror=None, followlinks=False):
            # when topdown=False os.walk creates dir_names for each root_path at the beginning and has
            # no knowledge if a directory has already been deleted.
            existing_dirs = [dir_name for dir_name in dir_names if os.path.isdir(os.path.join(root_path, dir_name))]
            if len(existing_dirs) == 0:
                ignored_files = list()
                for filename in file_names:
                    if filename in self.files_to_ignore:
                        ignored_files.append(filename)
                    else:
                        break
                if len(file_names) == len(ignored_files):
                    # only remove the ignored files if the folder is to be removed
                    for filename in ignored_files:
                        file_to_remove_full_path = os.path.join(root_path, filename)
                        try:
                            self.doing = f"""removing ignored file '{file_to_remove_full_path}'"""
                            os.remove(file_to_remove_full_path)
                        except Exception as ex:
                            log.warning("failed to remove", file_to_remove_full_path, ex)
                    try:
                        self.doing = f"""removing empty folder '{root_path}'"""
                        os.rmdir(root_path)
                    except Exception as ex:
                        log.warning("failed to remove", root_path, ex)


class Ls(PythonBatchCommandBase, essential=True):
    def __init__(self, *folders_to_list, out_file=None, ls_format='*', **kwargs) -> None:
        super().__init__(**kwargs)
        self.ls_format = ls_format
        self.out_file = out_file
        assert self.out_file is not None
        self.folders_to_list = list()
        for a_folder in folders_to_list:
            self.folders_to_list.append(os.fspath(a_folder))

    def __repr__(self) -> str:
        folders_to_list = self.folders_to_list
        if len(folders_to_list) > 0:
            folders_to_list = ', '.join(utils.quoteme_raw_string(path) for path in self.folders_to_list)
        the_repr = f'''{self.__class__.__name__}({folders_to_list}, out_file={utils.quoteme_raw_string(os.fspath(self.out_file))}, ls_format='{self.ls_format}')'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""List '{utils.quoteme_raw_if_list(self.folders_to_list)}' to '{self.out_file}'"""

    def __call__(self, *args, **kwargs) -> None:
        resolved_folder_list = [utils.ResolvedPath(folder_path) for folder_path in self.folders_to_list]
        the_listing = utils.disk_item_listing(*resolved_folder_list, ls_format=self.ls_format)
        with utils.write_to_file_or_stdout(self.out_file) as wfd:
            wfd.write(the_listing)


class CUrl(RunProcessBase):
    def __init__(self, src, trg: os.PathLike, curl_path: os.PathLike, connect_time_out: int=16,
                 max_time: int=180, retires: int=2, retry_delay: int=8) -> None:
        super().__init__()
        self.src: os.PathLike = src
        self.trg: os.PathLike = trg
        self.curl_path = curl_path
        self.connect_time_out = connect_time_out
        self.max_time = max_time
        self.retires = retires
        self.retry_delay = retry_delay

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(src={utils.quoteme_raw_string(self.src)},
          trg={utils.quoteme_raw_string(self.trg)},
          curl_path={utils.quoteme_raw_string(self.curl_path)},
          connect_time_out={self.connect_time_out}, max_time={self.max_time}, retires={self.retires}, retry_delay={self.retry_delay})"""
        return the_repr

    def progress_msg_self(self):
        return f"""Download '{src}' to '{self.trg}'"""

    def create_run_args(self):
        resolved_curl_path = os.fspath(utils.ResolvedPath(self.curl_path))
        run_args = [resolved_curl_path, "--insecure", "--fail", "--raw", "--silent", "--show-error", "--compressed",
                    "--connect-timeout", self.connect_time_out, "--max-time", self.max_time,
                    "--retry", self.retires, "--retry-delay", self.retry_delay,
                    "-o", self.trg, self.src]
        # TODO
        # download_command_parts.append("write-out")
        # download_command_parts.append(CUrlHelper.curl_write_out_str)
        return run_args


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
