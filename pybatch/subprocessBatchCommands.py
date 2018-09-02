import os
import stat
import pathlib
import shlex
import collections
from typing import List, Any, Optional, Union

import utils
from .baseClasses import *


class ShellCommand(RunProcessBase, essential=True):
    """ run a single command in a shell """

    def __init__(self, shell_command, message, **kwargs):
        kwargs["shell"] = True
        super().__init__(**kwargs)
        self.shell_command = shell_command
        self.message = message

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(shell_command={utils.quoteme_raw_string(self.shell_command)}, message={utils.quoteme_raw_string(self.message)})"""
        return the_repr

    def progress_msg_self(self):
        return f"""{self.message}"""

    def create_run_args(self):
        resolved_shell_command = os.path.expandvars(self.shell_command)
        the_lines = [resolved_shell_command]
        return the_lines


class ShellCommands(PythonBatchCommandBase, essential=True):
    def __init__(self, shell_commands_list, message, **kwargs):
        kwargs["shell"] = True
        super().__init__(**kwargs)
        if shell_commands_list is None:
            self.shell_commands_list = list()
        else:
            assert isinstance(shell_commands_list, collections.Sequence)
            self.shell_commands_list = shell_commands_list
        self.own_progress_count = len(self.shell_commands_list)
        self.message = message

    def __repr__(self):
        quoted_shell_commands_list = ", ".join(utils.quoteme_raw_list(self.shell_commands_list))

        the_repr = f"""{self.__class__.__name__}(shell_commands_list=[{quoted_shell_commands_list}], message={utils.quoteme_raw_string(self.message)})"""
        return the_repr

    def progress_msg_self(self):
        return f"""{self.__class__.__name__}"""

    def create_run_args(self):
        the_lines = self.shell_commands_list
        if isinstance(the_lines, str):
            the_lines = [the_lines]
        if sys.platform == 'darwin':
            the_lines.insert(0,  "#!/usr/bin/env bash")
            batch_extension = ".command"
        elif sys.platform == "win32":
            batch_extension = ".bat"
        commands_text = "\n".join(the_lines)
        batch_file_path = pathlib.Path(self.dir, self.var_name + batch_extension)
        with open(batch_file_path, "w") as batch_file:
            batch_file.write(commands_text)
        os.chmod(batch_file.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

        run_args = list()
        run_args.append(batch_file.name)
        return run_args

    def __call__(self, *args, **kwargs):
        # TODO: optimize by calling all the commands at once
        for i, shell_command in enumerate(self.shell_commands_list):
            self.doing = f"""running shell command #{i} '{shell_command}'"""
            with ShellCommand(shell_command, f"""{self.message} #{i+1}""", progress_count=0) as shelli:
                shelli()


class ParallelRun(PythonBatchCommandBase, essential=True):
    def __init__(self, config_file,  shell, **kwargs):
        super().__init__(**kwargs)
        self.config_file = config_file
        self.shell = shell

    def __repr__(self):
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(os.fspath(self.config_file))}, shell={self.shell}'''
        if self.own_progress_count > 1:
            the_repr += f''', progress_count={self.own_progress_count}'''
        if not self.report_own_progress:
            the_repr += f''', report_own_progress={self.report_own_progress}'''

        the_repr += ''')'''
        return the_repr

    def progress_msg_self(self):
        return f"""{self.__class__.__name__} '{self.config_file}'"""

    def __call__(self, *args, **kwargs):
        commands = list()
        resolved_config_file = utils.ResolvedPath(self.config_file)
        self.doing = f"""ParallelRun reading config file '{resolved_config_file}'"""
        with utils.utf8_open(resolved_config_file, "r") as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        try:
            self.doing = f"""ParallelRun, config file '{resolved_config_file}', running with {len(commands)} processes in parallel"""
            utils.run_processes_in_parallel(commands, self.shell)
        except SystemExit as sys_exit:
            if sys_exit.code != 0:
                raise
