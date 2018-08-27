import os
from win32com.client import Dispatch


from .baseClasses import PythonBatchCommandBase


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

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""{self.__class__.__name__} '{self.shortcut_path}' shortcut to '{self.target_path}'"""

    def __call__(self, *args, **kwargs) -> None:
        shell = Dispatch("WScript.Shell")
        expanded_shortcut_path = os.path.expandvars(self.shortcut_path)
        shortcut = shell.CreateShortCut(expanded_shortcut_path)
        expanded_target_path = os.path.expandvars(self.target_path)
        shortcut.Targetpath = expanded_target_path
        working_directory, target_name = os.path.split(expanded_target_path)
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
            file.Load(expanded_shortcut_path)
            flags = link_data.GetFlags()
            if not flags & shellcon.SLDF_RUNAS_USER:
                link_data.SetFlags(flags | shellcon.SLDF_RUNAS_USER)
                file.Save(expanded_shortcut_path, 0)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({
            'shortcut_path': self.shortcut_path,
            'target_path': self.target_path,
        })
