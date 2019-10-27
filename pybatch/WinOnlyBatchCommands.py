import os
from typing import Dict, List
import winreg
import pythoncom
from win32com.shell import shell, shellcon
from win32com.client import Dispatch, DispatchEx
import pywintypes
from pathlib import Path

from .baseClasses import PythonBatchCommandBase
from .subprocessBatchCommands import RunProcessBase
import utils


class WinShortcut(PythonBatchCommandBase, kwargs_defaults={"run_as_admin": False}):
    """ create a shortcut (windows only)"""
    def __init__(self, shortcut_path: os.PathLike, target_path: os.PathLike, run_as_admin=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.shortcut_path = shortcut_path
        self.target_path = target_path
        self.run_as_admin = run_as_admin
        self.exceptions_to_ignore.append(AttributeError)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(os.fspath(self.shortcut_path)))
        all_args.append(self.unnamed__init__param(os.fspath(self.target_path)))

    def progress_msg_self(self) -> str:
        return f"""Create shortcut '{self.shortcut_path}' to '{self.target_path}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        shortcut_path = os.path.expandvars(os.fspath(self.shortcut_path))
        target_path = os.path.expandvars(os.fspath(self.target_path))
        working_directory, target_name = os.path.split(target_path)

        shortcut_obj = pythoncom.CoCreateInstance(
            shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        persist_file = shortcut_obj.QueryInterface(pythoncom.IID_IPersistFile)
        shortcut_obj.SetPath(target_path)
        shortcut_obj.SetWorkingDirectory(working_directory)
        persist_file.Save(shortcut_path, 0)

        if self.run_as_admin:
            link_data = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLinkDataList)
            file = link_data.QueryInterface(pythoncom.IID_IPersistFile)
            file.Load(shortcut_path)
            flags = link_data.GetFlags()
            if not flags & shellcon.SLDF_RUNAS_USER:
                link_data.SetFlags(flags | shellcon.SLDF_RUNAS_USER)
                file.Save(shortcut_path, 0)


class BaseRegistryKey(PythonBatchCommandBase):
    reg_view_num_to_const = {64: winreg.KEY_WOW64_64KEY, 32: winreg.KEY_WOW64_32KEY}
    def __init__(self, top_key: str, sub_key: str, data_type: str='REG_SZ', reg_num_bits: int=64, **kwargs):
        '''
        The base registry sub_key class to be used for reading/creating/deleting keys or values in the registry
        args follow names and meaning of winreg functions such as OpenKey
        Args:
            top_key one of HKEY_CLASSES_ROOT/HKEY_CURRENT_USER/HKEY_LOCAL_MACHINE/HKEY_USERS/HKEY_CURRENT_CONFIG
            sub_key - path to sub_key's folder
            reg_num_bits - 32/64
            data_type -  REG_SZ (default) | REG_DWORD | REG_EXPAND_SZ | REG_MULTI_SZ'''
        super().__init__(**kwargs)
        self.top_key = top_key
        self.sub_key = sub_key
        self.value_name = None
        self.value_data = None
        self.data_type = data_type
        self.reg_num_bits = reg_num_bits
        self.key_handle = None
        self.permission_flag = winreg.KEY_READ
        self.ignore_if_not_exist = kwargs.get('ignore_if_not_exist', False)
        if self.ignore_if_not_exist:
            self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        self.positional_members_repr(all_args)
        self.named_members_repr(all_args)

    def positional_members_repr(self, all_args: List[str]) -> None:
        """ helper function to create repr for BaseRegistryKey common to all subclasses """
        all_args.append(utils.quoteme_double(self.top_key))
        all_args.append(utils.quoteme_raw_by_type(self.sub_key))
        if self.value_name is not None:
            all_args.append(utils.quoteme_raw_by_type(self.value_name))
        if self.value_data is not None:
            all_args.append(utils.quoteme_raw_by_type(self.value_data))

    def named_members_repr(self, all_args: List[str]) -> None:
        if self.data_type != 'REG_SZ':
            all_args.append(f"data_type={utils.quoteme_double(self.data_type)}")
        if self.reg_num_bits != 64:
            all_args.append(f"reg_num_bits={self.reg_num_bits}")
        if self.ignore_if_not_exist is not False:
            all_args.append(f"ignore_if_not_exist={self.ignore_if_not_exist}")

    def __str__(self):
        return f"{self.__class__.__name__} {self.top_key}, {self.sub_key}, {self.data_type}, {self.reg_num_bits}"

    def progress_msg_self(self) -> str:
        return "BaseRegistryKey"

    def _open_key(self):
        self.key_handle = winreg.OpenKey(getattr(winreg, self.top_key), self.sub_key, 0, (self.reg_view_num_to_const[self.reg_num_bits] | self.permission_flag))

    def _close_key(self):
        if self.key_handle is not None:
            winreg.CloseKey(self.key_handle)
            self.key_handle = None

    def exit_self(self, exit_return):
        self._close_key()

    def __call__(self, *args, **kwargs):
        raise NotImplemented()


class ReadRegistryValue(BaseRegistryKey):
    """ read a value from registry (windows only)"""
    def __init__(self, top_key: str, sub_key: str, value_name: str=None, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.value_name = value_name
        self.the_value = None

    def progress_msg_self(self) -> str:
        return f"Reading Registry {self.sub_key}\\{self.value_name} -> {self.the_value}"

    def __call__(self, *args, **kwargs) -> str:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.the_value = None
        try:
            self._open_key()
            key_val, key_type = winreg.QueryValueEx(self.key_handle, self.value_name)
            if key_type == 3:  # reg type 3 is REG_BINARY
                self.the_value = key_val
            elif key_type == 7:  # reg type 7 is REG_MULTI_SZ - A list of null-terminated strings
                self.the_value = ''.join(map(str, key_val))
            else:
                self.the_value = str(key_val)
        finally:
            self._close_key()
        if self.reply_environ_var is not None:
            os.environ[self.reply_environ_var] = self.the_value
        return self.the_value


class CreateRegistryKey(BaseRegistryKey):
    """ create a key in registry (windows only)"""
    def __init__(self, top_key: str, sub_key: str, value_data=None, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.value_data = value_data
        self.permission_flag = winreg.KEY_ALL_ACCESS

    def progress_msg_self(self) -> str:
        return f"Creating Registry sub_key {self.top_key}\\{self.sub_key}"

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        try:
            self.key_handle = winreg.CreateKeyEx(getattr(winreg, self.top_key), self.sub_key, 0, (self.reg_view_num_to_const[self.reg_num_bits] | self.permission_flag))
            if self.value_data is not None:
                winreg.SetValueEx(self.key_handle, None, 0, getattr(winreg, 'REG_SZ'), self.value_data)
        finally:
            self._close_key()


class CreateRegistryValues(BaseRegistryKey):
    """creating registry values (and sub_key if needed) based on a supplied dictionary.
       If a value already exists it will overwritten
    """
    def __init__(self, top_key: str, sub_key: str, value_dict: Dict[str, str], **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.value_dict = value_dict
        self.permission_flag = winreg.KEY_ALL_ACCESS

    def repr_own_args(self, all_args: List[str]) -> None:
        super().repr_own_args(all_args)
        all_args.append(f"value_dict={utils.quoteme_raw_by_type(self.value_dict)}")

    def progress_msg_self(self) -> str:
        return f"Creating Registry values {self.sub_key} -> {self.value_dict}"

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        try:
            self.key_handle = winreg.CreateKeyEx(getattr(winreg, self.top_key), self.sub_key, 0, (self.reg_view_num_to_const[self.reg_num_bits] | self.permission_flag))
            for value_name, value_data in self.value_dict.items():
                resolved_value_data = os.path.expandvars(value_data)
                winreg.SetValueEx(self.key_handle, value_name, 0, getattr(winreg, self.data_type), resolved_value_data)
        finally:
            self._close_key()


class DeleteRegistryKey(BaseRegistryKey):
    """ delete a key from registry (windows only) """
    def __init__(self, top_key, sub_key, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.permission_flag = winreg.KEY_ALL_ACCESS
        self.exceptions_to_ignore.append(FileNotFoundError)

    def progress_msg_self(self) -> str:
        return f"Deleting Registry sub_key {self.sub_key}\\{self.sub_key}"

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        try:
            self._open_key()
            winreg.DeleteKey(self.key_handle, "")
        except Exception as ex:
            raise


class DeleteRegistryValues(BaseRegistryKey):
    """ delete specific values from registry (windows only) """
    def __init__(self, top_key, sub_key, *values: str, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.values = list(values)
        self.permission_flag = winreg.KEY_ALL_ACCESS
        self.exceptions_to_ignore.append(FileNotFoundError)

    def repr_own_args(self, all_args: List[str]) -> None:
        self.positional_members_repr(all_args)
        all_args.extend(utils.quoteme_raw_list(self.values))
        self.named_members_repr(all_args)

    def progress_msg_self(self) -> str:
        return f"Deleting Registry values {self.sub_key} -> {self.values}"

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        try:
            self._open_key()
            for name in self.values:
                try:
                    winreg.DeleteValue(self.key_handle, name)
                except FileNotFoundError:
                    pass  # Value does not exists
        finally:
            self._close_key()


class ResHackerCompileResource(RunProcessBase):
    """ add a resource using ResHackerAddResource """
    def __init__(self, reshacker_path: os.PathLike, rc_file_path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.reshacker_path = reshacker_path
        self.rc_file_path: os.PathLike = rc_file_path

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"""reshacker_path={utils.quoteme_raw_by_type(self.reshacker_path)}""")
        all_args.append(f"""rc_file_path={utils.quoteme_raw_by_type(self.rc_file_path)}""")

    def progress_msg_self(self):
        return f"""Compile resource '{self.rc_file_path}'"""

    def get_run_args(self, run_args) -> None:
        resolved_reshacker_path = os.fspath(utils.ExpandAndResolvePath(self.reshacker_path))
        if not os.path.isfile(resolved_reshacker_path):
            raise FileNotFoundError(resolved_reshacker_path)
        resolved_rc_file_path = os.fspath(utils.ExpandAndResolvePath(self.rc_file_path))
        run_args.extend([resolved_reshacker_path,
                         "-open",
                         self.rc_file_path,
                         "-action",
                         "compile"
                         ])


class ResHackerAddResource(RunProcessBase):
    """ add a resource using ResHackerAddResource """
    def __init__(self, reshacker_path: os.PathLike, trg: os.PathLike, resource_source_file, resource_type=None, resource_name=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.reshacker_path = reshacker_path
        self.trg: os.PathLike = trg
        self.resource_source_file: os.PathLike = resource_source_file
        self.resource_type = resource_type
        self.resource_name = resource_name

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"""reshacker_path={utils.quoteme_raw_by_type(self.reshacker_path)}""")
        all_args.append(f"""trg={utils.quoteme_raw_by_type(self.trg)}""")
        all_args.append(f"""resource_source_file={utils.quoteme_raw_by_type(self.resource_source_file)}""")
        if self.resource_type:
            all_args.append( f"""resource_type={utils.quoteme_raw_by_type(self.resource_type)}""")
        if self.resource_name:
            all_args.append( f"""resource_name={utils.quoteme_raw_by_type(self.resource_name)}""")

    def progress_msg_self(self):
        if self.resource_type and self.resource_name:
            return f"""Add resource '{self.resource_type}/{self.resource_name}' to '{self.trg}'"""
        else:
            return f"""Add resource {self.resource_source_file} to '{self.trg}'"""

    def get_run_args(self, run_args) -> None:
        resolved_reshacker_path = os.fspath(utils.ExpandAndResolvePath(self.reshacker_path))
        if not os.path.isfile(resolved_reshacker_path):
            raise FileNotFoundError(resolved_reshacker_path)
        resolved_trg_path = os.fspath(utils.ExpandAndResolvePath(self.trg))
        if not os.path.isfile(resolved_trg_path):
            raise FileNotFoundError(resolved_trg_path)
        resolved_resource_source_file = os.fspath(utils.ExpandAndResolvePath(self.resource_source_file))
        if not os.path.isfile(resolved_resource_source_file):
            raise FileNotFoundError(resolved_resource_source_file)
        run_args.extend([resolved_reshacker_path,
                         "-open",
                         resolved_trg_path,
                         "-save",
                         resolved_trg_path,
                         "-resource",
                         resolved_resource_source_file,
                         "-action",
                         "addoverwrite"])
        if self.resource_type and self.resource_name:
            run_args.extend(["-mask", f"""{self.resource_type},{self.resource_name},0"""])


class FullACLForEveryone(RunProcessBase):
    """ Give group 'Everyone' all possible permissions """
    def __init__(self, path: os.PathLike, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = Path(path)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.path))

    def progress_msg_self(self):
        return f"FullACLForEveryone for {self.path}"

    def get_run_args(self, run_args) -> None:
        self.path = utils.ExpandAndResolvePath(self.path)
        run_args.extend(["icacls",
                         os.fspath(self.path),
                         "remove:d",  # remove all denied rights
                         "*S-1-1-0",  # for group everyone
                         "/grant",
                         "*S-1-1-0:(OI)(CI)F",  # grant all possible rights to group everyone, these right will be inherited
                         "/Q"])
        if self.recursive:
            run_args.append("/T")
