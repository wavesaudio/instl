import os
import sys
import stat
import abc
from pathlib import Path
import shlex
import collections
import subprocess
from typing import List

import utils
from .baseClasses import PythonBatchCommandBase


class RunProcessBase(PythonBatchCommandBase, essential=True, call__call__=True, is_context_manager=True, kwargs_defaults={"in_file": None, "out_file": None, "err_file": None}):
    def __init__(self, ignore_specific_exit_codes=(),  **kwargs):
        super().__init__(**kwargs)
        if self.ignore_all_errors:
            self.exceptions_to_ignore.append(subprocess.CalledProcessError)
        if isinstance(ignore_specific_exit_codes, int):
            self.ignore_specific_exit_codes = (ignore_specific_exit_codes,)
        else:
            self.ignore_specific_exit_codes = ignore_specific_exit_codes
        self.shell = kwargs.get('shell', False)
        self.script = kwargs.get('script', False)
        self.stdout = ''
        self.stderr = ''

    @abc.abstractmethod
    def get_run_args(self, run_args) -> None:
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        run_args = list()
        self.get_run_args(run_args)
        run_args = list(map(str, run_args))
        self.doing = f"""calling subprocess '{" ".join(run_args)}'"""
        if self.script:
            self.shell = True
            assert len(run_args) == 1
        elif self.shell and len(run_args) == 1:
            if sys.platform == 'darwin':  # MacOS needs help with spaces in paths
                #run_args = shlex.split(run_args[0])
                #run_args = [p.replace(" ", r"\ ") for p in run_args]
                #run_args = " ".join(run_args)
                run_args = run_args[0]
            elif sys.platform == 'win32':
                run_args = run_args[0]
        if self.out_file:
            out_stream = open(self.out_file, "w")
        else:
            out_stream = subprocess.PIPE
        if self.in_file:
            in_stream = open(self.in_file, "r")
        else:
            in_stream = None
        if self.err_file:
            err_stream = open(self.err_file, "w")
        else:
            err_stream = subprocess.PIPE
        completed_process = subprocess.run(run_args, check=False, stdin=in_stream, stdout=out_stream, stderr=err_stream, shell=self.shell)

        if self.in_file:
            in_stream.close()

        if self.out_file is None:
            local_stdout = self.stdout = utils.unicodify(completed_process.stdout)
        else:
            out_stream.close()

        if self.err_file is None:
            local_stderr = self.stderr = utils.unicodify(completed_process.stderr)
        else:
            err_stream.close()

        completed_process.check_returncode()
        self.handle_completed_process(completed_process)

    def handle_completed_process(self, completed_process):
        pass

    def log_result(self, log_lvl, message, exc_val):
        if self.stderr:
            message += f'; STDERR: {self.stderr.decode()}'
        super().log_result(log_lvl, message, exc_val)

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def should_ignore__exit__exception(self, exc_type, exc_val, exc_tb):
        retVal = super().should_ignore__exit__exception(exc_type, exc_val, exc_tb)
        if not retVal:
            if exc_type is subprocess.CalledProcessError:
                retVal = exc_val.returncode in self.ignore_specific_exit_codes
        return retVal


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

    def get_run_args(self, run_args) -> None:
        resolved_curl_path = os.fspath(utils.ResolvedPath(self.curl_path))
        resolved_trg_path = utils.ResolvedPath(self.trg)
        run_args.extend([resolved_curl_path, "--insecure", "--fail", "--raw", "--silent", "--show-error", "--compressed",
                    "--connect-timeout", self.connect_time_out, "--max-time", self.max_time,
                    "--retry", self.retires, "--retry-delay", self.retry_delay,
                    "-o", resolved_trg_path, self.src])
        # TODO
        # download_command_parts.append("write-out")
        # download_command_parts.append(CUrlHelper.curl_write_out_str)


class ShellCommand(RunProcessBase, essential=True):
    """ run a single command in a shell """

    def __init__(self, shell_command, message=None, ignore_specific_exit_codes=(), **kwargs):
        kwargs["shell"] = True
        super().__init__(ignore_specific_exit_codes=ignore_specific_exit_codes, **kwargs)
        self.shell_command = shell_command
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(self.shell_command))
        if self.message:
            all_args.append(f"""message={utils.quoteme_raw_string(self.message)}""")
        if self.ignore_specific_exit_codes:
            if len(self.ignore_specific_exit_codes,) == 1:
                all_args.append(f"""ignore_specific_exit_codes={self.ignore_specific_exit_codes[0]}""")
            else:
                all_args.append(f"""ignore_specific_exit_codes={self.ignore_specific_exit_codes}""")

    def progress_msg_self(self):
        if self.message:
            return f"""{self.message}"""
        else:
            return f"""running {self.shell_command}"""

    def get_run_args(self, run_args) -> None:
        resolved_shell_command = os.path.expandvars(self.shell_command)
        run_args.append(resolved_shell_command)


class ScriptCommand(ShellCommand):
    """ run a shell script (not a specific binary)"""
    def __init__(self, shell_command, message=None, ignore_specific_exit_codes=(), **kwargs):
        kwargs["script"] = True
        super().__init__(shell_command, message, ignore_specific_exit_codes=ignore_specific_exit_codes, **kwargs)


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

    def get_run_args(self, run_args) -> None:
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

        run_args.append(batch_file.name)

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


class Exec(PythonBatchCommandBase, essential=True):
    def __init__(self, python_file, config_file=None, reuse_db=True, **kwargs):
        super().__init__(**kwargs)
        self.python_file = python_file
        self.config_file = config_file
        self.reuse_db = reuse_db

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(os.fspath(self.python_file)))
        if self.config_file is not None:
            all_args.append(utils.quoteme_raw_string(os.fspath(self.config_file)))
        if not self.reuse_db:
            all_args.append(f"reuse_db={self.reuse_db}")

    def progress_msg_self(self):
        return f"""Executing '{self.python_file}'"""

    def __call__(self, *args, **kwargs):
        if self.config_file is not None:
            self.read_yaml_file(self.config_file)
        with utils.utf8_open(self.python_file, 'r') as rfd:
            py_text = rfd.read()
            py_compiled = compile(py_text, self.python_file, mode='exec', flags=0, dont_inherit=False, optimize=2)
            exec(py_compiled, globals())
