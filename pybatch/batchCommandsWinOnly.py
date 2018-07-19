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
        the_repr = f'''WinShortcut(r"{self.shortcut_path}, r"{self.target_path}"'''
        if self.run_as_admin:
            the_repr += '''run_as_admin=True'''
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

    def __call__(self, *args, **kwargs) -> None:
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(self.shortcut_path)
        shortcut.Targetpath = self.target_path
        working_directory, target_name = os.path.split(self.target_path)
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
            file.Load(self.shortcut_path)
            flags = link_data.GetFlags()
            if not flags & shellcon.SLDF_RUNAS_USER:
                link_data.SetFlags(flags | shellcon.SLDF_RUNAS_USER)
                file.Save(self.shortcut_path, 0)
