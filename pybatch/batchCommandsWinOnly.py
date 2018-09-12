import os
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
    def __init__(self, hkey, key, data_type='REG_SZ', reg_view=64, **kwargs):
        '''
        The base registry key class to be used for reading/creating/deleting keys or values in the registry
        Args:
            hkey (HKEY_CLASSES_ROOT/HKEY_CURRENT_USER/HKEY_LOCAL_MACHINE/HKEY_USERS/HKEY_CURRENT_CONFIG).
            key - path to key's folder
            reg_name - key name in folder
            reg_view - 32/64
            data_type -  REG_SZ (default) | REG_DWORD | REG_EXPAND_SZ | REG_MULTI_SZ'''
        super().__init__(**kwargs)
        self.hkey = hkey
        self._hkey = getattr(winreg, self.hkey)
        self.key = key
        self.data_type = data_type
        self._data_type = getattr(winreg, self.data_type)
        self.reg_view = reg_view
        if reg_view == 64:
            self._reg_view = winreg.KEY_WOW64_64KEY
        else:
            self._reg_view = winreg.KEY_WOW64_32KEY
        self._key = None

    def progress_msg_self(self) -> str:
        return "BaseRegistryKey"

    def _open_key(self, permission_flag=winreg.KEY_READ):
        return winreg.OpenKey(self._hkey, self.key, 0, (self._reg_view + permission_flag))

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
    def __init__(self, hkey, key, name, **kwargs):
        super().__init__(hkey, key, **kwargs)
        self.name = name

    def __repr__(self) -> str:
        return f'''{self.__class__.__name__}({utils.quoteme_double(self.hkey)}, {utils.quoteme_raw_string(self.key)}, {utils.quoteme_double(self.name)}, data_type={utils.quoteme_double(self.data_type)}, reg_view={self.reg_view})'''

    def progress_msg_self(self) -> str:
        return f"Reading key {self.key}\\{self.name}"

    def __call__(self, *args, **kwargs) -> str:
        self._key = self._open_key()
        key_val, key_type = winreg.QueryValueEx(self._key, self.name)
        if key_type == 3:  # reg type 3 is REG_BINARY
            v = key_val
        elif key_type == 7:  # reg type 7 is REG_MULTI_SZ - A list of null-terminated strings
            v = ''.join(map(str, key_val))
        else:
            v = str(key_val)
        return v

    def exit_self(self, exit_return):
        winreg.CloseKey(self.key)


class CreateRegistryKey(BaseRegistryKey):
    def __init__(self, hkey, key, key_to_create, **kwargs):
        super().__init__(hkey, key, **kwargs)
        self.key_to_create = key_to_create

    def _open_key(self, **kwargs):
        return super()._open_key(permission_flag=winreg.KEY_ALL_ACCESS)

    def __repr__(self) -> str:
        return f'''{self.__class__.__name__}({utils.quoteme_double(self.hkey)}, {utils.quoteme_raw_string(self.key)}, {utils.quoteme_double(self.key_to_create)}, data_type={utils.quoteme_double(self.data_type)}, reg_view={self.reg_view})'''

    def __call__(self, *args, **kwargs):
        self._key = self._open_key()
        winreg.CreateKey(self._key, self.key_to_create)

    def exit_self(self, exit_return):
        winreg.CloseKey(self._key)


class CreateRegistryValues(BaseRegistryKey):
    def __init__(self, hkey, key, values_dict: dict, **kwargs):
        super().__init__(hkey, key, **kwargs)
        self.values_dict = values_dict

    def __repr__(self) -> str:
        return f'''{self.__class__.__name__}({utils.quoteme_double(self.hkey)}, {utils.quoteme_raw_string(self.key)}, {self.values_dict}, data_type={utils.quoteme_double(self.data_type)}, reg_view={self.reg_view})'''

    def _open_key(self, **kwargs):
        return super()._open_key(permission_flag=winreg.KEY_ALL_ACCESS)

    def __call__(self, *args, **kwargs):
        try:
            self._key = self._open_key()
        except FileNotFoundError:  # Key doesn't exist
            self._key = winreg.CreateKey(self._hkey, self.key)
        for name, data in self.values_dict.items():
            winreg.SetValueEx(self._key, name, 0, self._data_type, data)

    def exit_self(self, exit_return):
        winreg.CloseKey(self._key)


class DeleteRegistryKey(BaseRegistryKey):
    '''WARNING!! This class can not delete keys with subkeys. Access denied will be raised in such case'''
    def __init__(self, hkey, key, key_to_delete, **kwargs):
        super().__init__(hkey, key, **kwargs)
        self.key_to_delete = key_to_delete

    def _open_key(self, **kwargs):
        return super()._open_key(permission_flag=winreg.KEY_ALL_ACCESS)

    def __repr__(self) -> str:
        return f'''{self.__class__.__name__}({utils.quoteme_double(self.hkey)}, {utils.quoteme_raw_string(self.key)}, {utils.quoteme_raw_string(self.key_to_delete)}, data_type={utils.quoteme_double(self.data_type)}, reg_view={self.reg_view})'''

    def __call__(self, *args, **kwargs):
        self._key = self._open_key()
        winreg.DeleteKey(self._key, self.key_to_delete)
