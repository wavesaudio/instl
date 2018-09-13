import os
from typing import Dict
import winreg
from win32com.client import Dispatch


from .baseClasses import PythonBatchCommandBase
from utils import misc_utils as utils


class WinShortcut(PythonBatchCommandBase):
    def __init__(self, shortcut_path: os.PathLike, target_path: os.PathLike, run_as_admin=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.shortcut_path = shortcut_path
        self.target_path = target_path
        self.run_as_admin = run_as_admin

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.shortcut_path)}, {utils.quoteme_raw_string(self.target_path)}'''
        if self.run_as_admin:
            the_repr += ''', run_as_admin=True'''
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""Create shortcut '{self.shortcut_path}' to '{self.target_path}'"""

    def __call__(self, *args, **kwargs) -> None:
        shell = Dispatch("WScript.Shell")
        resolved_shortcut_path = os.path.expandvars(self.shortcut_path)
        shortcut = shell.CreateShortCut(resolved_shortcut_path)
        resolved_target_path = os.path.expandvars(self.target_path)
        shortcut.Targetpath = resolved_target_path
        working_directory, target_name = os.path.split(resolved_target_path)
        shortcut.WorkingDirectory = working_directory
        shortcut.save()
        if self.run_as_admin:
            import pythoncom
            from win32com.shell import shell, shellcon
            link_data = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLinkDataList)
            file = link_data.QueryInterface(pythoncom.IID_IPersistFile)
            file.Load(resolved_shortcut_path)
            flags = link_data.GetFlags()
            if not flags & shellcon.SLDF_RUNAS_USER:
                link_data.SetFlags(flags | shellcon.SLDF_RUNAS_USER)
                file.Save(resolved_shortcut_path, 0)


class BaseRegistryKey(PythonBatchCommandBase):
    reg_view_num_to_const = {64: winreg.KEY_WOW64_64KEY, 32: winreg.KEY_WOW64_32KEY}
    def __init__(self, top_key: str, sub_key: str, data_type: str='REG_SZ', reg_view: int=64, **kwargs):
        '''
        The base registry sub_key class to be used for reading/creating/deleting keys or values in the registry
        args follow names and meaning of winreg functions such as OpenKey
        Args:
            top_key one of HKEY_CLASSES_ROOT/HKEY_CURRENT_USER/HKEY_LOCAL_MACHINE/HKEY_USERS/HKEY_CURRENT_CONFIG
            sub_key - path to sub_key's folder
            reg_view - 32/64
            data_type -  REG_SZ (default) | REG_DWORD | REG_EXPAND_SZ | REG_MULTI_SZ'''
        super().__init__(**kwargs)
        self.top_key = top_key
        self.sub_key = sub_key
        self.data_type = data_type
        self.reg_view = reg_view
        self.key_handle = None
        self.permission_flag = winreg.KEY_READ
        self.ignore_if_not_exist = kwargs.get('ignore_if_not_exist', False)
        if self.ignore_if_not_exist:
            self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}({utils.quoteme_double(self.top_key)}, {utils.quoteme_raw_string(self.sub_key)}"
        if self.data_type != 'REG_SZ':
            the_repr += f", data_type={utils.quoteme_double(self.data_type)}"
        if self.reg_view != 64:
            the_repr += f", reg_view={self.reg_view}"
        the_repr += ")"
        return the_repr

    def __str__(self):
        return f"{self.__class__.__name__} {self.top_key}, {self.sub_key}, {self.data_type}, {self.reg_view}"

    def progress_msg_self(self) -> str:
        return "BaseRegistryKey"

    def _open_key(self):
        self.key_handle = winreg.OpenKey(getattr(winreg, self.top_key), self.sub_key, 0, (self.reg_view_num_to_const[self.reg_view] | self.permission_flag))

    def _close_key(self):
        if self.key_handle is not None:
            winreg.CloseKey(self.key_handle)
            self.key_handle = None

    def exit_self(self, exit_return):
        self._close_key()

    @property
    def exists(self):
        try:
            _key = self._open_key()
        except FileNotFoundError:
            return False
        else:
            return True

    def __call__(self, *args, **kwargs):
        raise NotImplemented()


class ReadRegistryValue(BaseRegistryKey):
    def __init__(self, top_key: str, sub_key: str, value_name: str, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.value_name = value_name
        self.the_value = None

    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}({utils.quoteme_double(self.top_key)}, {utils.quoteme_raw_string(self.sub_key)}, {utils.quoteme_raw_string(self.value_name)}"
        if self.data_type != 'REG_SZ':
            the_repr += f", data_type={utils.quoteme_double(self.data_type)}"
        if self.reg_view != 64:
            the_repr += f", reg_view={self.reg_view}"
        if self.ignore_if_not_exist != False:
            the_repr += f", ignore_if_not_exist={self.ignore_if_not_exist}"
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f"Reading {self.sub_key}\\{self.value_name} -> {self.the_value}"

    def __call__(self, *args, **kwargs) -> str:
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
        return self.the_value


class CreateRegistryKey(BaseRegistryKey):
    def __init__(self, top_key: str, sub_key: str, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.permission_flag = winreg.KEY_ALL_ACCESS

    def progress_msg_self(self) -> str:
        return f"Creating sub_key {self.top_key}\\{self.sub_key}"

    def __call__(self, *args, **kwargs):
        try:
            self.key_handle = winreg.CreateKey(getattr(winreg, self.top_key), self.sub_key)
        finally:
            self._close_key()


class CreateRegistryValues(BaseRegistryKey):
    '''Creating registry values (and sub_key if needed) based on a supplied dictionary.
       If a value already exists it will overwrite the previous value'''
    def __init__(self, top_key: str, sub_key: str, value_dict: Dict[str, str], **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.value_dict = value_dict
        self.permission_flag = winreg.KEY_ALL_ACCESS

    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}({utils.quoteme_double(self.top_key)}, {utils.quoteme_raw_string(self.sub_key)}"
        the_repr += f", value_dict={self.value_dict}"
        if self.data_type != 'REG_SZ':
            the_repr += f", data_type={utils.quoteme_double(self.data_type)}"
        if self.reg_view != 64:
            the_repr += f", reg_view={self.reg_view}"
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f"Creating values {self.sub_key} -> {self.value_dict}"

    def __call__(self, *args, **kwargs):
        try:
            self.key_handle = winreg.CreateKey(getattr(winreg, self.top_key), self.sub_key)
            for value_name, value_data in self.value_dict.items():
                winreg.SetValueEx(self.key_handle, value_name, 0, getattr(winreg, self.data_type), value_data)
        finally:
            self._close_key()


class DeleteRegistryKey(BaseRegistryKey):
    '''WARNING!! This class can not delete keys with subkeys. Access denied will be raised in such case'''
    def __init__(self, top_key, sub_key, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.permission_flag = winreg.KEY_ALL_ACCESS
        self.exceptions_to_ignore.append(FileNotFoundError)

    def progress_msg_self(self) -> str:
        return f"Deleting sub_key {self.sub_key}\\{self.sub_key}"

    def __call__(self, *args, **kwargs):
        winreg.DeleteKeyEx(getattr(winreg, self.top_key), self.sub_key, (self.reg_view_num_to_const[self.reg_view] | self.permission_flag), 0)


class DeleteRegistryValues(BaseRegistryKey):
    '''Deleting registry values based on a supplied list'''
    def __init__(self, top_key, sub_key, values: (list, tuple), **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.values = list(values)
        self.permission_flag = winreg.KEY_ALL_ACCESS
        self.exceptions_to_ignore.append(FileNotFoundError)

    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}({utils.quoteme_double(self.top_key)}, {utils.quoteme_raw_string(self.sub_key)}"
        the_repr += f", {utils.quoteme_raw_if_list(self.values)}"
        if self.data_type != 'REG_SZ':
            the_repr += f", data_type={utils.quoteme_double(self.data_type)}"
        if self.reg_view != 64:
            the_repr += f", reg_view={self.reg_view}"
        if self.ignore_if_not_exist != False:
            the_repr += f", ignore_if_not_exist={self.ignore_if_not_exist}"
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f"Deleting values {self.sub_key} -> {self.values}"

    def __call__(self, *args, **kwargs):
        try:
            self._open_key()
            for name in self.values:
                try:
                    winreg.DeleteValue(self.key_handle, name)
                except FileNotFoundError:
                    pass  # Value does not exists
        finally:
            self._close_key()
