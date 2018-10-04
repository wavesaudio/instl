import os
import stat
import abc
from pathlib import Path
import shlex
import collections
import subprocess
from typing import List

import utils
from .baseClasses import PythonBatchCommandBase


class RunProcessBase(PythonBatchCommandBase, essential=True, call__call__=True, is_context_manager=True):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.ignore_all_errors:
            self.exceptions_to_ignore.append(subprocess.CalledProcessError)
        self.shell = kwargs.get('shell', False)
        self.stdout = ''
        self.stderr = ''

    @abc.abstractmethod
    def create_run_args(self):
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        run_args = self.create_run_args()
        run_args = list(map(str, run_args))
        self.doing = f"""calling subprocess '{" ".join(run_args)}'"""
        if self.shell:
            run_args = " ".join(run_args)
        completed_process = subprocess.run(run_args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=self.shell)
        self.stdout = utils.unicodify(completed_process.stdout)
        self.stderr = utils.unicodify(completed_process.stderr)
        #log.debug(completed_process.stdout)
        completed_process.check_returncode()

    def log_result(self, log_lvl, message, exc_val):
        if self.stderr:
            message += f'; STDERR: {self.stderr.decode()}'
        super().log_result(log_lvl, message, exc_val)

    def repr_own_args(self, all_args: List[str]) -> None:
        pass


class CUrl(RunProcessBase):
    """ download a file using curl """
    def __init__(self, src, trg: os.PathLike, curl_path: os.PathLike, connect_time_out: int=16,
                 max_time: int=180, retires: int=2, retry_delay: int=8) -> None:
        super().__init__()
        self.src: os.PathLike = src
        self.trg: os.PathLike = trg
        self.curl_path = curl_path
        self.connect_time_out = connect_time_out
        self.max_time = max_time
        self.retires = retires
        self.retry_delay = retry_delay

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f"""src={utils.quoteme_raw_string(self.src)}""")
        all_args.append(f"""trg={utils.quoteme_raw_string(self.trg)}""")
        all_args.append(f"""curl_path={utils.quoteme_raw_string(self.curl_path)}""")
        all_args.append( f"""connect_time_out={self.connect_time_out}""")
        all_args.append( f"""max_time={self.max_time}""")
        all_args.append( f"""retires={self.retires}""")
        all_args.append( f"""retry_delay={self.retry_delay}""")

    def progress_msg_self(self):
        return f"""Download '{src}' to '{self.trg}'"""

    def create_run_args(self):
        resolved_curl_path = os.fspath(utils.ResolvedPath(self.curl_path))
        resolved_trg_path = utils.ResolvedPath(self.trg)
        run_args = [resolved_curl_path, "--insecure", "--fail", "--raw", "--silent", "--show-error", "--compressed",
                    "--connect-timeout", self.connect_time_out, "--max-time", self.max_time,
                    "--retry", self.retires, "--retry-delay", self.retry_delay,
                    "-o", resolved_trg_path, self.src]
        # TODO
        # download_command_parts.append("write-out")
        # download_command_parts.append(CUrlHelper.curl_write_out_str)
        return run_args


class ShellCommand(RunProcessBase, essential=True):
    """ run a single command in a shell """

    def __init__(self, shell_command, message=None, **kwargs):
        kwargs["shell"] = True
        super().__init__(**kwargs)
        self.shell_command = shell_command
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(self.shell_command))
        if self.message:
            all_args.append(f"""message={utils.quoteme_raw_string(self.message)}""")

    def progress_msg_self(self):
        if self.message:
            return f"""{self.message}"""
        else:
            return f"""running {self.shell_command}"""

    def create_run_args(self):
        resolved_shell_command = os.path.expandvars(self.shell_command)
        the_lines = [resolved_shell_command]
        return the_lines


class ShellCommands(PythonBatchCommandBase, essential=True):
    """ run some shells commands in a shell """

    def __init__(self, shell_command_list, message, **kwargs):
        kwargs["shell"] = True
        super().__init__(**kwargs)
        if shell_command_list is None:
            self.shell_command_list = list()
        else:
            assert isinstance(shell_command_list, collections.Sequence)
            self.shell_command_list = shell_command_list
        self.own_progress_count = len(self.shell_command_list)
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        quoted_shell_commands_list = utils.quoteme_raw_if_list(self.shell_command_list)
        all_args.append(f"""shell_command_list={quoted_shell_commands_list}""")
        all_args.append(f"""message={utils.quoteme_raw_string(self.message)}""")

    def progress_msg_self(self):
        return f"""{self.__class__.__name__}"""

    def create_run_args(self):
        the_lines = self.shell_command_list
        if isinstance(the_lines, str):
            the_lines = [the_lines]
        if sys.platform == 'darwin':
            the_lines.insert(0,  "#!/usr/bin/env bash")
            batch_extension = ".command"
        elif sys.platform == "win32":
            batch_extension = ".bat"
        commands_text = "\n".join(the_lines)
        batch_file_path = Path(self.dir, self.var_name + batch_extension)
        with open(batch_file_path, "w") as batch_file:
            batch_file.write(commands_text)
        os.chmod(batch_file.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

        run_args = list()
        run_args.append(batch_file.name)
        return run_args

    def __call__(self, *args, **kwargs):
        # TODO: optimize by calling all the commands at once
        for i, shell_command in enumerate(self.shell_command_list):
            self.doing = f"""running shell command #{i} '{shell_command}'"""
            with ShellCommand(shell_command, f"""{self.message} #{i+1}""", own_progress_count=0) as shelli:
                shelli()


class ParallelRun(PythonBatchCommandBase, essential=True):
    """ run some shell commands in parallel """
    def __init__(self, config_file,  shell, **kwargs):
        super().__init__(**kwargs)
        self.config_file = config_file
        self.shell = shell

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(os.fspath(self.config_file)))
        all_args.append(f'''shell={self.shell}''')

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
