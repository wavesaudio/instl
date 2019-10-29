from typing import List, Any, Union
import tempfile
import stat
import tarfile
from collections import OrderedDict
from configVar import config_vars
import collections
import zlib

from .fileSystemBatchCommands import *
from .copyBatchCommands import *

"""
class Dummy(PythonBatchCommandBase):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}()'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
    
    def error_dict_self(self, exc_val):
        pass
"""


class CopyDirToDirEx(PythonBatchCommandBase):
    def __init__(self,
                 src,
                 dst,
                 user_id: Union[int, str, None],
                 group_id: Union[int, str, None],
                 **kwargs):
        super().__init__(**kwargs)
        self.src = src
        self.dst = dst
        self.user_id: Union[int, str]  = user_id   if user_id  else -1
        self.group_id: Union[int, str] = group_id  if group_id else -1

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        params = list()
        params.append(self.unnamed__init__param(os.fspath(self.src)))
        params.append(self.unnamed__init__param(os.fspath(self.dst)))
        params.append(self.optional_named__init__param("user_id", self.user_id, -1))
        params.append(self.optional_named__init__param("group_id", self.group_id, -1))
        params_text = ", ".join(filter(None, params))
        if params_text:
            the_repr += params_text
        the_repr += ")"
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def can_copy_be_avoided(self, src, dst) -> bool:
        retVal = False
        if "__REPAIR_INSTALLED_ITEMS__" not in config_vars['__MAIN_INSTALL_IIDS__'].list():
            avoid_copy_markers = list(config_vars.get('COPY_IGNORE_MARKERS', []))
            if avoid_copy_markers:
                src_top_files = [src_file for src_file in os.scandir(src) if src_file.name in avoid_copy_markers and src_file.is_file]
                dst_top_files = [dst_file for dst_file in os.scandir(dst) if dst_file.name in avoid_copy_markers and dst_file.is_file]

                for marker in avoid_copy_markers:
                    if marker in src_top_files and marker in dst_top_files:
                        src_file = next([src_file for src_file in src_top_files if src_file.name == marker])
                        src_stats = src_file.stat(follow_symlinks=False)
                        dst_file = next([dst_file for dst_file in dst_top_files if dst_file.name == marker])
                        dst_stats = dst_file.stat(follow_symlinks=False)

                        # first compare inodes
                        retVal = src_stats.st_ino == dst_stats.st_ino
                        # 2nd compare checksum
                        if not retVal:
                            src_marker_checksum = utils.get_file_checksum(src_file.path)
                            dst_marker_checksum = utils.get_file_checksum(dst_file.path)
                        retVal = utils.compare_checksums(src_marker_checksum, dst_marker_checksum)
                        break
        return retVal

    def get_wtar_base_names(self, the_dir):
        retVal = list()
        for root,dirs, files in os.walk(the_dir):
            for a_file in files:
                if utils.is_first_wtar_file(a_file):
                    retVal.append(utils.original_name_from_wtar_name(a_file))
        if retVal:
            retVal.append('*.wtar*')
        return retVal

    def __call__(self, *args, **kwargs) -> None:
        expanded_src = os.path.expandvars(self.src)
        expanded_dst = os.path.expandvars(self.dst)
        expanded_final_dst = os.path.join(expanded_dst, os.path.basename(expanded_src))

        ignore_patterns = list(config_vars.get('COPY_IGNORE_PATTERNS', []))
        ignore_patterns.extend(self.get_wtar_base_names(expanded_src))

        with CopyDirToDir(expanded_src,
                          expanded_dst,
                          ignore_if_not_exist=False,
                          symlinks_as_symlinks=True,
                          ignore_patterns=ignore_patterns,
                          hard_links=True,
                          ignore_dangling_symlinks=False,
                          delete_extraneous_files=True) as cdtd:
            cdtd()
        with Chown(path=expanded_final_dst, user_id=self.user_id, group_id=self.group_id, recursive=True) as cho:
            cho();
        with Chmod(path=expanded_final_dst, mode="a+rw", recursive=True, ignore_all_errors=True) as chm:
            chm()
        with Unlock(expanded_final_dst) as ul:
            ul()

    def error_dict_self(self, exc_val):
        pass
