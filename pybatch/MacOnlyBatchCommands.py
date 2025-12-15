from pathlib import Path
from typing import List
from configVar import config_vars
import logging

from .subprocessBatchCommands import ShellCommand

log = logging.getLogger(__name__)

from .baseClasses import PythonBatchCommandBase


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
