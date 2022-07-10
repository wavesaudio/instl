from .baseClasses import PythonBatchCommandBase
from typing import List

from .subprocessBatchCommands import ShellCommands
from configVar import config_vars
from os.path import expanduser


import os
import sys
from pathlib import Path

import re
import utils
import platform
SHUTDOWN_VERSION = "1.0.0"  # First release

current_os = platform.system()


class Shutdown(PythonBatchCommandBase):

    def __init__(self, servers_to_kill=['waves_local_server'], tasks_to_kill=['COSMOS'], **kwargs):
        super().__init__(**kwargs)
        self.tasks_to_kill = tasks_to_kill
        self.servers_to_kill = servers_to_kill
        self.commands = []

    # def progress_msg_self(self):
    #
    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param('servers_to_kill', self.servers_to_kill))
        all_args.append(self.named__init__param('tasks_to_kill', self.tasks_to_kill))

    def progress_msg_self(self) -> str:
        return f'shutting down process {str(self.servers_to_kill).strip("[]")}'


    def __call__(self, *args, **kwargs):
        for server in self.servers_to_kill:
            if server == 'waves_local_server':
                self.kill_waves_local_servers()
        for task in self.tasks_to_kill:
            if current_os == "Darwin":
                home = config_vars.get('HOME', expanduser("~"))
                self.commands.append(f"killall {task} 2>/dev/null ")
                plist_file_name = f"{home}/Library/LaunchAgents/com.WavesAudio.{task}.plist"
                if Path(plist_file_name).is_file():
                    self.commands.append(f"launchctl unload {plist_file_name}")
            else:
                self.commands.append(f"taskkill   /im {task}.exe /t /f")
        self.execute_commands()

    @staticmethod
    def find_resources(folder_path, pattern):
        """Return Path object for the relevant path according to the resource"""
        return [Path(file_path) for file_path in Path(folder_path).rglob(pattern)]

    def kill_waves_local_servers(self):
        all_relevant_paths = []
        if current_os == 'Darwin':
            all_relevant_paths = Shutdown.find_resources(config_vars.get('WAVES_PROGRAMDATA_DIR'),
                                                     '*/*/Contents/MacOS/Waves*Client')
        else:
            all_relevant_paths.extend(Shutdown.find_resources(config_vars.get('WAVES_PROGRAMDATA_DIR'),
                                                              '*\*\Contents\Win64\Waves*Client.exe'))
        for path in all_relevant_paths:
            version = re.search("V.*\d", str(path), flags=0)
            if version:
                arg1 = "wps.shutdown"
            else:
                arg1 = 'wpivot.shutdown'

            self.commands.append(f" '{str(path)}' {arg1}")

    def execute_commands(self):
        cmds_str = str(self.commands).strip('[]')
        self.doing = f"running shell commands {cmds_str}"
        with ShellCommands(self.commands, ignore_all_errors=True, message=f"executing {cmds_str} ",
                           report_own_progress=False) as shellCommandsExecution:
            shellCommandsExecution()
