import os
import shutil
from pathlib import Path
from typing import List
from configVar import config_vars
import logging

from utils import dock_util
from .subprocessBatchCommands import ShellCommand

log = logging.getLogger(__name__)

from .baseClasses import PythonBatchCommandBase
from .removeBatchCommands import RmDir, RmFile, RmFileOrDir
import utils


class MacDock(PythonBatchCommandBase):
    """ Change Dock items (Mac only)
        If 'path_to_item' is not None item will be added to the dock labeled 'label_for_item'
        or removed if remove==True
        Dock will restarted if restart_the_doc==True
    """

    def __init__(self, path_to_item=None, label_for_item=None, restart_the_doc=False, remove=False, username=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_item = path_to_item
        self.label_for_item = label_for_item
        self.restart_the_doc = restart_the_doc
        self.remove = remove
        self.username = username # for testing purposes, during run we should have this info from config_vars

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.optional_named__init__param('path_to_item', self.path_to_item))
        all_args.append(self.optional_named__init__param('label_for_item', self.label_for_item))
        all_args.append(self.optional_named__init__param('username', self.username))
        all_args.append(self.optional_named__init__param('restart_the_doc', self.restart_the_doc, False))
        all_args.append(self.optional_named__init__param('remove', self.remove, False))

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} setting '{self.path_to_item}'  """

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)

        home_dir = str(config_vars['HOME_DIR']) if 'HOME_DIR' in config_vars else "~"
        username = str(config_vars['ACTING_UNAME']) if 'ACTING_UNAME' in config_vars else self.username
        dock_bundle = 'com.apple.dock'
        plist_buddy_path = "/usr/libexec/PlistBuddy"
        mac_dock_path = f"{home_dir}/Library/Preferences/com.apple.dock.plist"
        if self.restart_the_doc:
            dock_cmd = "killall Dock"
        else:
            dock_cmd = ''

        if self.remove:
            app_name = self.label_for_item or Path(self.path_to_item).name.split(".")[0]
            get_records_number = f"awk '/{app_name}/" + " {print NR-1}'"
            dock_cmd = f''' {plist_buddy_path} -c "Delete persistent-apps:`sudo -u {username} defaults read {dock_bundle} persistent-apps | grep file-label |''' + \
                       get_records_number + \
                       f'''`" {mac_dock_path} ; ''' + \
                       dock_cmd
        elif self.path_to_item:
            plist_template = f'''"<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key>
                                      <string>{self.path_to_item}</string><key>_CFURLStringType</key>
                                      <integer>0</integer></dict></dict></dict>"'''
            dock_cmd = f'''sudo -u {username} defaults write {dock_bundle} persistent-apps -array-add {plist_template}  ; {dock_cmd}'''

        log.info(dock_cmd)
        with ShellCommand(dock_cmd, report_own_progress=False, stderr_means_err=False) as shell_cmd_macdoc:
            shell_cmd_macdoc()


class CreateSymlink(PythonBatchCommandBase):
    """ create a symbolic link (MacOS only)"""

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
        path_to_target = utils.ExpandAndResolvePath(self.path_to_target)
        path_to_symlink = Path(os.path.expandvars(self.path_to_symlink))
        self.doing = f"""create symlink '{path_to_symlink}' to target '{path_to_target}'"""
        with RmFile(path_to_symlink, report_own_progress=False, resolve_path=False) as rf:
            rf()
        path_to_symlink.symlink_to(path_to_target)


class RmSymlink(PythonBatchCommandBase):
    """remove a symlink not it's target
    - It's OK is the symlink or the target does not exist
    - but exception will be raised if path is a folder
     (MacOS only)
    """

    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path: os.PathLike = path
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path))

    def progress_msg_self(self):
        return f"""Remove symlink '{self.path}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        expanded_path = os.path.expandvars(self.path)
        unresolved_path = Path(expanded_path)
        self.doing = f"""removing symlink '{unresolved_path}'"""
        if unresolved_path.is_symlink():
            with RmFile(unresolved_path, report_own_progress=False, resolve_path=False) as rf:
                rf()
        elif unresolved_path.exists():
            log.warning(f"RmSymlink, not a symlink: {unresolved_path}")
        else:
            log.warning(f"RmSymlink, not found: {unresolved_path}")


class SymlinkToSymlinkFile(PythonBatchCommandBase):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
         (MacOS only)
    """

    def __init__(self, symlink_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symlink_to_convert = Path(symlink_to_convert)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.symlink_to_convert))

    def progress_msg_self(self) -> str:
        return f"""Convert symlink file '{self.symlink_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        symlink_to_convert = Path(os.path.expandvars(self.symlink_to_convert))
        self.doing = f"""convert real symlink '{symlink_to_convert}' to .symlink file"""
        if symlink_to_convert.is_symlink():
            link_value = os.readlink(symlink_to_convert)
            symlink_text_path = symlink_to_convert.with_name(f"{symlink_to_convert.name}.symlink")
            symlink_text_path.write_text(link_value)
            with RmFile(symlink_to_convert, report_own_progress=False, resolve_path=False) as rf:
                rf()


class SymlinkFileToSymlink(PythonBatchCommandBase):
    """ replace a file with extension '.symlink' to a real symlink.
        the '.symlink' should contain the text of the target of the symlink. And was created with SymlinkToSymlinkFile.
        This will allow uploading symlinks to cloud storage does not support symlinks
         (MacOS only)
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
        symlink_file_to_convert = utils.ExpandAndResolvePath(self.symlink_file_to_convert)
        symlink_target = symlink_file_to_convert.read_text()
        self.doing = f"""convert symlink file '{symlink_file_to_convert}' to real symlink to target '{symlink_target}'"""
        symlink = Path(symlink_file_to_convert.parent, symlink_file_to_convert.stem)
        it_was = None
        if symlink.is_symlink():
            with RmFile(symlink, report_own_progress=False, resolve_path=False) as rf:
                rf()
            it_was = "symlink"
        elif symlink.is_file():
            with RmFile(symlink, report_own_progress=False, resolve_path=False) as rf:
                rf()
            it_was = "file"
        elif symlink.is_dir():
            with RmDir(symlink, report_own_progress=False) as rd:
                rd()
            it_was = "folder"

        if symlink.exists():
            raise IsADirectoryError(f"{it_was} '{symlink}' a  was found and could not be removed")

        symlink.symlink_to(symlink_target)
        symlink_file_to_convert.unlink()


class CreateSymlinkFilesInFolder(PythonBatchCommandBase):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
         (MacOS only)
    """

    def __init__(self, folder_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_convert = Path(folder_to_convert)
        self.last_symlink_file = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.folder_to_convert))

    def progress_msg_self(self) -> str:
        return f"""Create symlinks files in '{self.folder_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        self.doing = f"""convert real symlinks in '{self.folder_to_convert}' to .symlink files"""
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_folder_to_convert = utils.ExpandAndResolvePath(self.folder_to_convert)
        for root, dirs, files in os.walk(resolved_folder_to_convert, followlinks=False):
            for item in files + dirs:
                item_path = Path(root, item)
                if item_path.is_symlink():
                    try:
                        self.last_symlink_file = item_path
                        with SymlinkToSymlinkFile(item_path, own_progress_count=0) as symlink_converter:
                            self.doing = f"""convert symlink '{item_path}' to .symlink file"""
                            symlink_converter()
                    except:
                        log.warning(f"failed to convert {item_path}")


class ResolveSymlinkFilesInFolder(PythonBatchCommandBase):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
         (MacOS only)
    """

    def __init__(self, folder_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_convert = folder_to_convert
        self.last_symlink_file = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.folder_to_convert))

    def progress_msg_self(self) -> str:
        return f"""Resolve symlinks in '{self.folder_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_folder_to_convert = utils.ExpandAndResolvePath(self.folder_to_convert)
        for root, dirs, files in os.walk(resolved_folder_to_convert, followlinks=False):
            for item in files:
                item_path = Path(root, item)
                if item_path.suffix == ".symlink":
                    self.last_symlink_file = os.fspath(item_path)
                    self.doing = f"""resolve symlink file '{self.last_symlink_file}'"""
                    with SymlinkFileToSymlink(item_path, own_progress_count=0) as symlink_converter:
                        symlink_converter()

