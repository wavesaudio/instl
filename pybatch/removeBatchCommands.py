import os
import shutil
import glob
from typing import List
import logging

import utils
from pybatch import PythonBatchCommandBase

log = logging.getLogger()


class RmFile(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike, **kwargs) -> None:
        """ remove a file
            - It's OK is the file does not exist
            - but exception will be raised if path is a folder
        """
        super().__init__(**kwargs)
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


class RmDir(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike, **kwargs) -> None:
        """ remove a directory.
            - it's OK if the directory does not exist.
            - all files and directory under path will be removed recursively
            - exception will be raised if the path is not a folder
        """
        super().__init__(**kwargs)
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
        #assert not os.fspath(resolved_path).startswith("/p4client")
        shutil.rmtree(resolved_path)


class RmFileOrDir(PythonBatchCommandBase, essential=True):
    def __init__(self, path: os.PathLike, **kwargs):
        """ remove a file or directory.
            - it's OK if the path does not exist.
            - all files and directory under path will be removed recursively
        """
        super().__init__(**kwargs)
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(path={utils.quoteme_raw_string(os.fspath(self.path))})"""
        return the_repr

    def progress_msg_self(self):
        return f"""Remove '{self.path}'"""

    def __call__(self, *args, **kwargs):
        resolved_path = utils.ResolvedPath(self.path)
        #assert not os.fspath(resolved_path).startswith("/p4client")
        if resolved_path.is_file():
            self.doing = f"""removing file'{resolved_path}'"""
            resolved_path.unlink()
        elif resolved_path.is_dir():
            self.doing = f"""removing folder'{resolved_path}'"""
            shutil.rmtree(resolved_path)


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
                            log.warning(f"""failed to remove {file_to_remove_full_path}, {ex}""")
                    try:
                        self.doing = f"""removing empty folder '{root_path}'"""
                        os.rmdir(root_path)
                    except Exception as ex:
                        log.warning(f"""failed to remove {root_path}, {ex}""")


class RmGlob(PythonBatchCommandBase, essential=True):
    def __init__(self, pattern: os.PathLike, **kwargs) -> None:
        """ remove files matching a pattern
            - it's OK if the directory does not exist.
            - all files and directory matching the pattern will be removed recursively
        """
        super().__init__(**kwargs)
        self.pattern: os.PathLike = pattern
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.pattern))})"""
        return the_repr

    def progress_msg_self(self):
        return f"""Remove pattern '{self.pattern}'"""

    def __call__(self, *args, **kwargs):
        list_to_remove = glob.glob(os.path.expandvars(self.pattern))
        for item in list_to_remove:
            with RmFileOrDir(item, progress_count=0) as rfod:
                rfod()
