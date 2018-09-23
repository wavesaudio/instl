import os
from typing import Dict
import winreg
from win32com.client import Dispatch


from .baseClasses import PythonBatchCommandBase
from utils import misc_utils as utils


class WinShortcut(PythonBatchCommandBase):
    """ create a shortcut (windows only)"""
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

    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}("
        the_repr += ", ".join(self.positional_members_repr()+self.named_members_repr())
        the_repr += ")"
        return the_repr

    def positional_members_repr(self) -> str:
        """ helper function to create repr for BaseRegistryKey common to all subclasses """
        members_repr = list()
        members_repr.append(utils.quoteme_double(self.top_key))
        members_repr.append(utils.quoteme_raw_string(self.sub_key))
        if self.value_name is not None:
            members_repr.append(utils.quoteme_raw_string(self.value_name))
        if self.value_data is not None:
            members_repr.append(utils.quoteme_raw_string(self.value_data))
        return members_repr

    def named_members_repr(self) -> str:
        members_repr = list()
        if self.data_type != 'REG_SZ':
            members_repr.append(f"data_type={utils.quoteme_double(self.data_type)}")
        if self.reg_num_bits != 64:
            members_repr.append(f"reg_num_bits={self.reg_num_bits}")
        if self.ignore_if_not_exist is not False:
            members_repr.append(f"ignore_if_not_exist={self.ignore_if_not_exist}")
        return members_repr

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
    """ create a key in registry (windows only)"""
    def __init__(self, top_key: str, sub_key: str, value_data=None, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.value_data = value_data
        self.permission_flag = winreg.KEY_ALL_ACCESS

    def progress_msg_self(self) -> str:
        return f"Creating sub_key {self.top_key}\\{self.sub_key}"

    def __call__(self, *args, **kwargs):
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

    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}("
        the_repr += ", ".join(self.positional_members_repr()+self.named_members_repr())
        the_repr += f", value_dict={self.value_dict}"
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f"Creating values {self.sub_key} -> {self.value_dict}"

    def __call__(self, *args, **kwargs):
        try:
            self.key_handle = winreg.CreateKeyEx(getattr(winreg, self.top_key), self.sub_key, 0, (self.reg_view_num_to_const[self.reg_num_bits] | self.permission_flag))
            for value_name, value_data in self.value_dict.items():
                winreg.SetValueEx(self.key_handle, value_name, 0, getattr(winreg, self.data_type), value_data)
        finally:
            self._close_key()


class DeleteRegistryKey(BaseRegistryKey):
    """ delete a key from registry (windows only) """
    def __init__(self, top_key, sub_key, **kwargs):
        super().__init__(top_key, sub_key, **kwargs)
        self.permission_flag = winreg.KEY_ALL_ACCESS
        self.exceptions_to_ignore.append(FileNotFoundError)

    def progress_msg_self(self) -> str:
        return f"Deleting sub_key {self.sub_key}\\{self.sub_key}"

    def __call__(self, *args, **kwargs):
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

    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}("
        the_repr += ", ".join(self.positional_members_repr() + utils.quoteme_raw_list(self.values) + self.named_members_repr())
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
