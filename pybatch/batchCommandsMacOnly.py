import os
import pathlib

from .baseClasses import PythonBatchCommandBase
import utils


class MacDock(PythonBatchCommandBase):
    def __init__(self, path_to_item, label_for_item, restart_the_doc, remove=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_item = path_to_item
        self.label_for_item = label_for_item
        self.restart_the_doc = restart_the_doc
        self.remove = remove

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.path_to_item)}, {utils.quoteme_raw_string(self.label_for_item)}, restart_the_doc={self.restart_the_doc}, remove={self.remove})'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} '{path_to_item}' as '{self.label_for_item}'"""

    def __call__(self, *args, **kwargs) -> None:
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
                    print("mac-dock confusing options, both --path and --restart were not supplied")
            else:
                dock_util_command.append("--add")
                dock_util_command.append(self.path_to_item)
                if self.label_for_item:
                    dock_util_command.append("--label")
                    dock_util_command.append(self.label_for_item)
                    dock_util_command.append("--replacing")
                    dock_util_command.append(self.label_for_item)
        if not self.restart_the_doc:
            dock_util_command.append("--no-restart")
        utils.dock_util(dock_util_command)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({
            'path_to_item': self.path_to_item,
            'label_for_item': self.label_for_item,
        })


class CreateSymlink(PythonBatchCommandBase, essential=True):
    def __init__(self, path_to_symlink: os.PathLike, path_to_target: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path_to_symlink = path_to_symlink
        self.path_to_target = path_to_target

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.path_to_symlink))}, {utils.quoteme_raw_string(os.fspath(self.path_to_target))})'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} '{self.path_to_symlink}' to '{self.path_to_target}'"""

    def __call__(self, *args, **kwargs) -> None:
        os.symlink(os.path.expandvars(self.path_to_target), os.path.expandvars(self.path_to_symlink))

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({
            'path_to_symlink': self.path_to_symlink,
            'path_to_target': self.path_to_target,
        })


class SymlinkToSymlinkFile(PythonBatchCommandBase, essential=True):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, symlink_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symlink_to_convert = symlink_to_convert

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.symlink_to_convert))})'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} '{self.symlink_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        symlink_to_convert = pathlib.Path(os.path.expandvars(self.symlink_to_convert))
        if symlink_to_convert.is_symlink():
            target_path = symlink_to_convert.resolve()
            link_value = os.readlink(symlink_to_convert)
            if target_path.is_dir() or target_path.is_file():
                symlink_text_path = symlink_to_convert.with_name(f"{symlink_to_convert.name}.symlink")
                symlink_text_path.write_text(link_value)
                symlink_to_convert.unlink()

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({
            'symlink_to_convert': self.symlink_to_convert,
        })


class SymlinkFileToSymlink(PythonBatchCommandBase, essential=True):
    """ replace a file with extension '.symlink' to a real symlink.
        the '.symlink' should contain the text of the target of the symlink. And was created with SymlinkToSymlinkFile.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, symlink_file_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symlink_file_to_convert = os.fspath(symlink_file_to_convert)

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.symlink_file_to_convert))})'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} '{self.symlink_file_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        symlink_file_to_convert = pathlib.Path(os.path.expandvars(self.symlink_file_to_convert))
        symlink_target = symlink_file_to_convert.read_text()
        symlink = pathlib.Path(symlink_file_to_convert.parent, symlink_file_to_convert.stem)
        if symlink.is_symlink() or symlink.is_file():
            symlink.unlink()
        elif symlink.is_dir():
            raise IsADirectoryError(f"a directory was found where a symlink was expected {symlink}")
        symlink.symlink_to(symlink_target)
        symlink_file_to_convert.unlink()

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({
            'symlink_file_to_convert': self.symlink_file_to_convert,
        })


class CreateSymlinkFilesInFolder(PythonBatchCommandBase, essential=True):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, folder_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_convert = pathlib.Path(folder_to_convert)
        self.last_symlink_file = None

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.folder_to_convert)})'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} in '{self.folder_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        valid_symlinks = list()
        broken_symlinks = list()
        expanded_folder_to_convert = os.path.expandvars(self.folder_to_convert)
        for root, dirs, files in os.walk(expanded_folder_to_convert, followlinks=False):
            for item in files + dirs:
                item_path = os.path.join(root, item)
                if os.path.islink(item_path):
                    link_value = os.readlink(item_path)
                    target_path = os.path.realpath(item_path)
                    self.last_symlink_file = item_path
                    with SymlinkToSymlinkFile(item_path) as symlink_converter:
                        symlink_converter()
                    if os.path.isdir(target_path) or os.path.isfile(target_path):
                        valid_symlinks.append((item_path, link_value))
                    else:
                        broken_symlinks.append((item_path, link_value))
        if len(broken_symlinks) > 0:
            print("Found broken symlinks")
            for symlink_file, link_value in broken_symlinks:
                print(symlink_file, "-?>", link_value)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({
            'folder_to_convert': self.folder_to_convert,
            'last_symlink_file': self.last_symlink_file
        })


class ResolveSymlinkFilesInFolder(PythonBatchCommandBase, essential=True):
    """ replace a symlink with a file with te same name + the extension '.symlink'
        the '.symlink' will contain the text of the target of the symlink.
        This will allow uploading symlinks to cloud storage does not support symlinks
    """
    def __init__(self, folder_to_convert: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.folder_to_convert = pathlib.Path(folder_to_convert)
        self.last_symlink_file = None

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.folder_to_convert))})'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} in '{self.folder_to_convert}'"""

    def __call__(self, *args, **kwargs) -> None:
        expanded_folder_to_convert = os.path.expandvars(self.folder_to_convert)
        for root, dirs, files in os.walk(expanded_folder_to_convert, followlinks=False):
            for item in files:
                item_path = pathlib.Path(root, item)
                if item_path.suffix == ".symlink":
                    self.last_symlink_file = os.fspath(item_path)
                    with SymlinkFileToSymlink(item_path) as symlink_converter:
                        symlink_converter()

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({
            'folder_to_convert': self.folder_to_convert,
            'target_path': self.target_path,
            'last_symlink_file': self.last_symlink_file
        })

