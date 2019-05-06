import os
from pathlib import Path
from typing import List

import logging
log = logging.getLogger()

from .baseClasses import PythonBatchCommandBase
import utils


class MacDock(PythonBatchCommandBase):
    """ Change Dock items (Mac only)
        If 'path_to_item' is not None item will be added to the dock labeled 'label_for_item'
        or removed if remove==True
        Dock will restarted if restart_the_doc==True
    """
    def __init__(self, path_to_item=None, label_for_item=None, restart_the_doc=False, remove=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_item = path_to_item
        self.label_for_item = label_for_item
        self.restart_the_doc = restart_the_doc
        self.remove = remove

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.optional_named__init__param('path_to_item', self.path_to_item, None))
        all_args.append(self.optional_named__init__param('label_for_item', self.label_for_item, None))
        all_args.append(self.optional_named__init__param('restart_the_doc', self.restart_the_doc, False))
        all_args.append(self.optional_named__init__param('remove', self.remove, False))

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} '{self.path_to_item}' as '{self.label_for_item}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        dock_util_command = list()
        if self.remove:
            dock_util_command.append("--remove")
            if self.label_for_item:
                dock_util_command.append(self.label_for_item)
            if not self.restart_the_doc:
                dock_util_command.append("--no-restart")
        else:
            if not self.path_to_item:
                if self.restart_the_doc:
                    dock_util_command.append("--restart")
                else:
                    log.warning("mac-dock confusing options, both --path and --restart were not supplied")
            else:
                dock_util_command.append("--add")
                resolved_path_to_item = os.fspath(utils.ResolvedPath(self.path_to_item))
                dock_util_command.append(resolved_path_to_item)
                if self.label_for_item:
                    dock_util_command.append("--label")
                    dock_util_command.append(self.label_for_item)
                    dock_util_command.append("--replacing")
                    dock_util_command.append(self.label_for_item)
        if not self.restart_the_doc:
            dock_util_command.append("--no-restart")
        self.doing = dock_util_command
        utils.dock_util(dock_util_command)


class CreateSymlink(PythonBatchCommandBase, essential=True):
    def __init__(self, path_to_symlink: os.PathLike, path_to_target: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_symlink = path_to_symlink
        self.path_to_target = path_to_target

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path_to_symlink))
        all_args.append(self.unnamed__init__param(self.path_to_target))

    def progress_msg_self(self) -> str:
        return f"""Create symlink '{self.path_to_symlink}' to '{self.path_to_target}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        path_to_target = utils.ResolvedPath(self.path_to_target)
        path_to_symlink = Path(os.path.expandvars(self.path_to_symlink))
        try:
            path_to_symlink.unlink()
        except:
            pass
        self.doing = f"""create symlink '{path_to_symlink}' to target '{path_to_target}'"""
        path_to_symlink.symlink_to(path_to_target)


class RmSymlink(PythonBatchCommandBase, essential=True):
    """remove a symlink not it's target
    - It's OK is the symlink or the target does not exist
    - but exception will be raised if path is a folder
    """
    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.path))

    def progress_msg_self(self):
        return f"""Remove symlink '{self.path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        expanded_path = os.path.expandvars(self.path)
        unresolved_path = Path(expanded_path)
        self.doing = f"""removing symlink '{unresolved_path}'"""
        if unresolved_path.is_symlink():
            unresolved_path.unlink()
        elif unresolved_path.exists():
            log.warning(f"RmSymlink, not a symlink: {unresolved_path}")
        else:
            log.warning(f"RmSymlink, not found: {unresolved_path}")


class SymlinkToSymlinkFile(PythonBatchCommandBase, essential=True):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, symlink_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symlink_to_convert = symlink_to_convert

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.symlink_to_convert))

    def progress_msg_self(self) -> str:
        return f"""Create symlink file '{self.symlink_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        symlink_to_convert = Path(os.path.expandvars(self.symlink_to_convert))
        self.doing = f"""convert real symlink '{symlink_to_convert}' to .symlink file"""
        if symlink_to_convert.is_symlink():
            target_path = symlink_to_convert.resolve()
            link_value = os.readlink(symlink_to_convert)
            if target_path.is_dir() or target_path.is_file():
                symlink_text_path = symlink_to_convert.with_name(f"{symlink_to_convert.name}.symlink")
                symlink_text_path.write_text(link_value)
                symlink_to_convert.unlink()


class SymlinkFileToSymlink(PythonBatchCommandBase, essential=True):
    """ replace a file with extension '.symlink' to a real symlink.
        the '.symlink' should contain the text of the target of the symlink. And was created with SymlinkToSymlinkFile.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, symlink_file_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symlink_file_to_convert = os.fspath(symlink_file_to_convert)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.symlink_file_to_convert))

    def progress_msg_self(self) -> str:
        return f"""Resolve symlink '{self.symlink_file_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        symlink_file_to_convert = utils.ResolvedPath(self.symlink_file_to_convert)
        symlink_target = symlink_file_to_convert.read_text()
        self.doing = f"""convert symlink file '{symlink_file_to_convert}' to real symlink to target '{symlink_target}'"""
        symlink = Path(symlink_file_to_convert.parent, symlink_file_to_convert.stem)
        if symlink.is_symlink() or symlink.is_file():
            symlink.unlink()
        elif symlink.is_dir():
            raise IsADirectoryError(f"a directory was found where a symlink was expected {symlink}")
        symlink.symlink_to(symlink_target)
        symlink_file_to_convert.unlink()


class CreateSymlinkFilesInFolder(PythonBatchCommandBase, essential=True):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, folder_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_convert = folder_to_convert
        self.last_symlink_file = None
        self.doing = f"""convert real symlinks in '{self.folder_to_convert}' to .symlink files"""

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.folder_to_convert))

    def progress_msg_self(self) -> str:
        return f"""Create symlinks files in '{self.folder_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        valid_symlinks = list()
        broken_symlinks = list()
        resolved_folder_to_convert = utils.ResolvedPath(self.folder_to_convert)
        for root, dirs, files in os.walk(resolved_folder_to_convert, followlinks=False):
            for item in files + dirs:
                item_path = os.path.join(root, item)
                if os.path.islink(item_path):
                    link_value = os.readlink(item_path)
                    target_path = os.path.realpath(item_path)
                    self.last_symlink_file = item_path
                    with SymlinkToSymlinkFile(item_path, own_progress_count=0) as symlink_converter:
                        symlink_converter()
                        self.doing = symlink_converter.doing
                    if os.path.isdir(target_path) or os.path.isfile(target_path):
                        valid_symlinks.append((item_path, link_value))
                    else:
                        broken_symlinks.append((item_path, link_value))
        if len(broken_symlinks) > 0:
            log.warning("Found broken symlinks")
            for symlink_file, link_value in broken_symlinks:
                log.warning(f"""{symlink_file} -?, {link_value}""")


class ResolveSymlinkFilesInFolder(PythonBatchCommandBase, essential=True):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, folder_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_convert = folder_to_convert
        self.last_symlink_file = None
        self.report_own_progress = False

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.folder_to_convert))
        if self.own_progress_count > 1:
            all_args.append(self.named__init__param("own_progress_count", self.own_progress_count))

    def progress_msg_self(self) -> str:
        return f"""Resolve symlinks in '{self.folder_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_folder_to_convert = utils.ResolvedPath(self.folder_to_convert)
        for root, dirs, files in os.walk(resolved_folder_to_convert, followlinks=False):
            for item in files:
                item_path = Path(root, item)
                if item_path.suffix == ".symlink":
                    self.last_symlink_file = os.fspath(item_path)
                    self.doing = f"""resolve symlink file '{self.last_symlink_file}'"""
                    with SymlinkFileToSymlink(item_path, own_progress_count=0) as symlink_converter:
                        symlink_converter()

