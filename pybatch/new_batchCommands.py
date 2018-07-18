from typing import List, Any
import tempfile
import stat
import tarfile
from collections import OrderedDict
from configVar import config_vars

from .batchCommands import *

"""
class Dummy(PythonBatchCommandBase):
    def __init__(self, identifier=None, **kwargs) -> None:
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
"""


class RemoveEmptyFolders(PythonBatchCommandBase):
    def __init__(self, folder_to_remove: os.PathLike, files_to_ignore: List = [], **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_remove = folder_to_remove
        self.files_to_ignore = list(files_to_ignore)

    def __repr__(self) -> str:
        the_repr = f'''RemoveEmptyFolders(folder_to_remove=r"{self.folder_to_remove}", files_to_ignore={self.files_to_ignore})'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
       for root_path, dir_names, file_names in os.walk(self.folder_to_remove, topdown=False, onerror=None, followlinks=False):
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
                            os.remove(file_to_remove_full_path)
                        except Exception as ex:
                            print("failed to remove", file_to_remove_full_path, ex)
                    try:
                        os.rmdir(root_path)
                    except Exception as ex:
                        print("failed to remove", root_path, ex)
