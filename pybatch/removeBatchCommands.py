import os
import stat
import shutil
import re
from pathlib import Path
from typing import List
import logging
import utils
from pybatch import PythonBatchCommandBase
from configVar import config_vars

log = logging.getLogger(__name__)


class RmFile(PythonBatchCommandBase, kwargs_defaults={'resolve_path': True}):
    """remove a file
    - if path is symlink - the symlink's target will be removed
    - It's OK is the file does not exist
    - but exception will be raised if path is a folder
    """
    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path))

    def progress_msg_self(self):
        return f"""Remove file '{self.path}'"""

    def error_dict_self(self, exc_type, exc_val, exc_tb):
        try:
            file_listing = utils.single_disk_item_listing(self.path, output_format="json")
            self._error_dict["ls"] = file_listing
        except:  # populating the error dict should continue, even if error_dict_self failed
            pass

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_path = utils.ExpandAndResolvePath(self.path, resolve_path=self.resolve_path)
        for attempt in range(2):
            try:
                self.doing = f"""removing file '{resolved_path}'"""
                resolved_path.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError as pex:
                if attempt == 0:
                    # calling unlink on a folder raises PermissionError
                    if resolved_path.is_dir():
                        kwargs_for_rm_dir = self.all_kwargs_dict()
                        kwargs_for_rm_dir['report_own_progress'] = False
                        kwargs_for_rm_dir['recursive'] = True
                        with RmDir(resolved_path, **kwargs_for_rm_dir) as dir_remover:
                            dir_remover()
                        break
                    else:
                        log.info(f"Fixing permission for removing {resolved_path}")
                        from pybatch import FixAllPermissions
                        with FixAllPermissions(resolved_path, report_own_progress=False) as allower:
                            allower()
                else:
                    self.who_locks_file_error_dict(Path.unlink, resolved_path)
                    raise


class RmDir(PythonBatchCommandBase):
    """ remove a directory.
        - it's OK if the directory does not exist.
        - all files and directory under path will be removed recursively
        - exception will be raised if the path is not a folder
    """
    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path))

    def progress_msg_self(self):
        return f"""Remove directory '{self.path}'"""

    def error_dict_self(self, exc_type, exc_val, exc_tb):
        try:
            file_listing = utils.single_disk_item_listing(self.path, output_format="json")
            self._error_dict["ls"] = file_listing
        except:  # populating the error dict should continue, even if error_dict_self failed
            pass

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_path = utils.ExpandAndResolvePath(self.path)
        for attempt in range(2):
            try:
                self.doing = f"""removing folder '{resolved_path}'"""
                shutil.rmtree(resolved_path, onerror=self.who_locks_file_error_dict)
                break
            except FileNotFoundError:
                break
            except NotADirectoryError:
                kwargs_for_rm_file = self.all_kwargs_dict()
                kwargs_for_rm_file['report_own_progress'] = False
                kwargs_for_rm_file['recursive'] = False
                with RmFile(resolved_path, **kwargs_for_rm_file) as file_remover:
                    file_remover()
                break
            except PermissionError:
                if attempt == 0:
                    log.info(f"Fixing permission for removing {resolved_path}")
                    from pybatch import FixAllPermissions
                    with FixAllPermissions(resolved_path, report_own_progress=False, recursive=True) as allower:
                        allower()
                else:
                    raise


class RmFileOrDir(PythonBatchCommandBase):
    """ remove a file or directory.
    - it's OK if the path does not exist.
    - all files and directory under path will be removed recursively
    """
    def __init__(self, path: os.PathLike, **kwargs):
        super().__init__(**kwargs)
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path))

    def progress_msg_self(self):
        return f"""Remove '{self.path}'"""

    def __call__(self, *args, **kwargs):
        resolved_path = None
        retry = kwargs.get("retry", True)
        try:
            PythonBatchCommandBase.__call__(self, *args, **kwargs)
            resolved_path = utils.ExpandAndResolvePath(self.path)
            if resolved_path.is_symlink() or resolved_path.is_file():
                self.doing = f"""removing file'{resolved_path}'"""
                resolved_path.unlink()
            elif resolved_path.is_dir():
                self.doing = f"""removing folder'{resolved_path}'"""
                shutil.rmtree(resolved_path, onerror=self.who_locks_file_error_dict)
        except Exception as ex:
            if retry and resolved_path is not None:
                kwargs["retry"] = False
                log.info(f"Fixing permission for removing {resolved_path}")
                from pybatch import FixAllPermissions
                with FixAllPermissions(resolved_path, recursive=True, report_own_progress=False) as allower:
                    allower()
                self.__call__(*args, **kwargs)
            else:
                raise


class RemoveEmptyFolders(PythonBatchCommandBase, kwargs_defaults={"files_to_ignore": []}):
    """ remove all empty directories under and including 'folder_to_remove'
    - it's OK if the path does not exist.
    - 'files_to_ignore' is a list of file names will be ignored, i.e. if a folder contains only these files
    it will be considered empty and will be removed
    """
    def __init__(self, folder_to_check: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_check = folder_to_check

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.folder_to_check))

    def progress_msg_self(self) -> str:
        return f"""Remove empty directory '{self.folder_to_check}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_folder_to_check = utils.ExpandAndResolvePath(self.folder_to_check)

        # addition of "a^" to make sure empty self.files_to_ignore does not ignore any file
        files_to_ignore_regex = re.compile("|".join(self.files_to_ignore+["a^"]))

        for root_path, dir_names, file_names in os.walk(resolved_folder_to_check, topdown=False, onerror=None, followlinks=False):
            # when topdown=False os.walk creates dir_names for each root_path at the beginning and has
            # no knowledge if a directory has already been deleted.
            existing_dirs = [dir_name for dir_name in dir_names if os.path.isdir(os.path.join(root_path, dir_name))]
            if len(existing_dirs) == 0:
                num_ignored_files = 0
                for filename in file_names:
                    match = files_to_ignore_regex.match(filename)
                    if match:
                        num_ignored_files += 1
                    else:
                        break
                if len(file_names) == num_ignored_files:
                    # only remove the ignored files if the folder is to be removed
                    for filename in file_names:
                        file_to_remove_full_path = os.path.join(root_path, filename)
                        try:
                            self.doing = f"""removing ignored file '{file_to_remove_full_path}'"""
                            os.remove(file_to_remove_full_path)
                        except Exception as ex:
                            log.warning(f"""failed to remove {file_to_remove_full_path}, {ex}""")
                    try:
                        self.doing = f"""removing empty folder '{root_path}'"""
                        os.rmdir(root_path)
                    except Exception as ex:
                        log.warning(f"""failed to remove {root_path}, {ex}""")


class RmGlob(PythonBatchCommandBase):
    """ remove files matching a pattern
        - all files and folders matching the pattern will be removed
        - pattern matching is done with https://docs.python.org/3.6/library/pathlib.html#pathlib.Path.glob
        - allowing pattern to be None is temporary until new format is implemented in index
"""
    def __init__(self, path_to_folder: os.PathLike, pattern: str=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_folder: os.PathLike = path_to_folder
        self.pattern: os.PathLike = pattern
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path_to_folder))
        all_args.append(self.unnamed__init__param(self.pattern))

    def progress_msg_self(self):
        return f"""Remove pattern '{self.pattern}' from {self.path_to_folder}"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        if self.pattern is None:
            log.wanging(f"skip RmGlob of '{self.path_to_folder}' because pattern is None")
        else:
            folder = utils.ExpandAndResolvePath(self.path_to_folder)
            list_to_remove = folder.glob(self.pattern)
            for item in list_to_remove:
                with RmFileOrDir(item, own_progress_count=0) as rfod:
                    rfod()


class RmGlobs(PythonBatchCommandBase):
    """ remove files matching any pattern in the given list
        - all files and folders matching the patterns will be removed
        - pattern matching is done with https://docs.python.org/3.6/library/pathlib.html#pathlib.Path.glob
        - allowing pattern to be None is temporary until new format is implemented in index
"""
    def __init__(self, path_to_folder: os.PathLike, *patterns: List, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_folder: os.PathLike = path_to_folder
        self.patterns = sorted(patterns)
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path_to_folder))
        for pattern in self.patterns:
            all_args.append(self.unnamed__init__param(pattern))

    def progress_msg_self(self):
        return f"""Remove patterns '{self.patterns}' from {self.path_to_folder}"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        folder = utils.ExpandAndResolvePath(self.path_to_folder)
        for pattern in self.patterns:
            list_to_remove = folder.glob(pattern)
            for item in list_to_remove:
                with RmFileOrDir(item, own_progress_count=0) as rfod:
                    rfod()


#def unnamed__init__param(self, value):
#def named__init__param(self, name, value):
#def optional_named__init__param(self, name, value, default=None):

class RmDirContents(PythonBatchCommandBase):
    """ remove all items in a folder (unless item is excluded)
        but leave the folder itself
    """
    def __init__(self, path_to_folder: os.PathLike, exclude: List=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_folder: os.PathLike = path_to_folder
        if exclude is not None:
            self.exclude = sorted(exclude)
        else:
            self.exclude = []
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path_to_folder))
        all_args.append(self.optional_named__init__param("exclude", self.exclude, []))

    def progress_msg_self(self):
        return f"""Remove Dir Contents {self.path_to_folder}"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        folder_to_clean = utils.ExpandAndResolvePath(self.path_to_folder)
        for item in os.scandir(folder_to_clean):
            if item.name not in self.exclude:
                with RmFileOrDir(item.path, own_progress_count=0) as rfod:
                    rfod()

