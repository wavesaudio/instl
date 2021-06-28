import os
import sys
import stat
import abc
from pathlib import Path
import shlex
import collections
import subprocess
from typing import List
from threading import Thread
import utils
import psutil
import time
from .baseClasses import PythonBatchCommandBase

import logging
log = logging.getLogger(__name__)


class RunProcessBase(PythonBatchCommandBase, call__call__=True, is_context_manager=True,
                     kwargs_defaults={"stderr_means_err": True, "capture_stdout": False, "out_file": None,"detach": False}):
    """ base class for classes pybatch commands that need to spawn a subprocess
        input, output, stderr can read/writen to files according to in_file, out_file, err_file
        Some subprocesses write to stderr but return exit code 0, in which case if stderr_means_err==True and something was written
        to stderr, RunProcessBase will raise with error code 123. If stderr_means_err==False the exit code from the
        subprocess will remain as it was returned from the subprocess. stderr handling will only occur if err_file==None.
    """
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
        self.stderr = ''  # for log_results


    @abc.abstractmethod
    def get_run_args(self, run_args) -> None:
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        """ Normally list of arguments are calculated by calling self.get_run_args,
            unless kwargs["run_args"] exists.
        """
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        run_args = list()
        if "run_args" in kwargs:
            run_args.extend(kwargs["run_args"])
        else:
            self.get_run_args(run_args)
        run_args = list(map(str, run_args))
        self.doing = f"""calling subprocess '{" ".join(run_args)}'"""
        if self.detach:
            pid = os.spawnlp(os.P_NOWAIT, *run_args)
            # in https://docs.python.org/3.6/library/subprocess.html#replacing-the-os-spawn-family
            # the recommended way to replace os.spawnlp(os.P_NOWAIT,.. is by using subprocess.Popen,
            # but it does not work properly
            #pid = subprocess.Popen(run_args).pid
        else:
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

            out_stream = None
            need_to_close_out_file = False
            if self.out_file:
                if isinstance(self.out_file, (str, os.PathLike, bytes)):
                    out_file = Path(self.out_file).resolve()
                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    out_stream = utils.utf8_open_for_write(out_file, "w")
                    log.info(f"output will be written to {out_file}")
                    need_to_close_out_file = True
                elif hasattr(self.out_file, "write"):  # out_file is already an open file
                    out_stream = self.out_file

            elif self.capture_stdout:
                # this will capture stdout in completed_process.stdout instead of writing directly to stdout
                # so objects overriding handle_completed_process will have access to stdout
                out_stream = subprocess.PIPE
            in_stream = None
            err_stream = subprocess.PIPE

            completed_process = subprocess.run(run_args, check=False, stdin=in_stream, stdout=out_stream, stderr=err_stream, shell=self.shell, bufsize=0)

            if need_to_close_out_file:
                out_stream.close()

            if completed_process.stderr:
                self.stderr = utils.unicodify(completed_process.stderr)
                if self.ignore_all_errors:
                    # in case of ignore_all_errors redirect stderr to stdout so we know there was an error
                    # but it will not be interpreted as an error by whoever is running instl
                    log.info(self.stderr)
                else:
                    if self.stderr_means_err:
                        log.error(self.stderr)
                        if completed_process.returncode == 0:
                            completed_process.returncode = 123
                    else:
                        log.info(self.stderr)
            else:
                pass

            if self.ignore_all_errors:
                completed_process.returncode = 0

            completed_process.check_returncode()

            self.handle_completed_process(completed_process)

    def handle_completed_process(self, completed_process):
        pass

    def log_result(self, log_lvl, message, exc_val):
        if self.stderr:
            message += f'; STDERR: {utils.unicodify(self.stderr)}'
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
                 max_time: int=180, retires: int=2, retry_delay: int=8, **kwargs) -> None:
        super().__init__(**kwargs)
        self.src: os.PathLike = src
        self.trg: os.PathLike = trg
        self.curl_path = curl_path
        self.connect_time_out = connect_time_out
        self.max_time = max_time
        self.retires = retires
        self.retry_delay = retry_delay

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("src", self.src))
        all_args.append(self.named__init__param("trg", self.trg))
        all_args.append(self.named__init__param("curl_path", self.curl_path))
        all_args.append(self.named__init__param("connect_time_out", self.connect_time_out))
        all_args.append(self.named__init__param("max_time", self.max_time))
        all_args.append(self.named__init__param("retires", self.retires))
        all_args.append(self.named__init__param("retry_delay", self.retry_delay))

    def progress_msg_self(self):
        return f"""Download '{self.src}' to '{self.trg}'"""

    def get_run_args(self, run_args) -> None:
        resolved_curl_path = os.fspath(utils.ExpandAndResolvePath(self.curl_path))
        resolved_trg_path = os.fspath(utils.ExpandAndResolvePath(self.trg))
        run_args.extend([resolved_curl_path,
                         "--insecure",
                         "--fail",
                         "--raw",
                         "--silent",
                         "--show-error",
                         "--connect-timeout", self.connect_time_out,
                         "--max-time", self.max_time,
                         "--retry", self.retires,
                         "--retry-delay", self.retry_delay,
                         "-o", resolved_trg_path, self.src])
        # TODO
        # download_command_parts.append("write-out")
        # download_command_parts.append(CUrlHelper.curl_write_out_str)


class ShellCommand(RunProcessBase):
    """ run a single command in a shell """

    def __init__(self, shell_command, message=None, ignore_specific_exit_codes=(), **kwargs):
        kwargs["shell"] = True
        super().__init__(ignore_specific_exit_codes=ignore_specific_exit_codes, **kwargs)
        self.shell_command = shell_command
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.shell_command))
        all_args.append(self.optional_named__init__param("message", self.message))
        if self.ignore_specific_exit_codes:
            if len(self.ignore_specific_exit_codes,) == 1:
                all_args.append(self.named__init__param("ignore_specific_exit_codes", self.ignore_specific_exit_codes[0]))
            else:
                all_args.append(self.named__init__param("ignore_specific_exit_codes", self.ignore_specific_exit_codes))

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


class ShellCommands(PythonBatchCommandBase):
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
        all_args.append(self.named__init__param("message", self.message))

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
        with utils.utf8_open_for_write(batch_file_path, "w") as batch_file:
            batch_file.write(commands_text)
        os.chmod(batch_file.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

        run_args.append(batch_file.name)

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        # TODO: optimize by calling all the commands at once
        for i, shell_command in enumerate(self.shell_command_list):
            self.doing = f"""running shell command #{i} '{shell_command}'"""
            with ShellCommand(shell_command, f"""{self.message} #{i+1}""", own_progress_count=0) as shelli:
                shelli()


class ParallelRun(PythonBatchCommandBase, kwargs_defaults={'action_name': None, 'shell': False}):
    """ run some shell commands in parallel """
    def __init__(self, config_file, **kwargs):
        super().__init__(**kwargs)
        self.config_file = config_file

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.config_file))

    def get_action_name(self):
        return self.action_name if self.action_name else self.__class__.__name__

    def progress_msg_self(self):
        return f"""{self.get_action_name()} '{self.config_file}'"""

    def increment_and_output_progress(self, increment_by=None, prog_counter_msg=None, prog_msg=None):
        pass

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        commands = list()
        resolved_config_file = utils.ExpandAndResolvePath(self.config_file)
        self.doing = f"""{self.get_action_name()} reading config file '{resolved_config_file}'"""
        with utils.utf8_open_for_read(resolved_config_file, "r") as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        try:

            self.doing = f"""{self.get_action_name()}, config file '{resolved_config_file}', running with {len(commands)} processes in parallel"""
            utils.run_processes_in_parallel(commands, self.shell)
        except SystemExit as sys_exit:
            if sys_exit.code != 0:
                if "curl" in commands[0]:
                    err_msg = utils.get_curl_err_msg(sys_exit.code)
                    raise Exception(err_msg)
                else:
                    raise
        finally:
            self.increment_progress()


class Exec(PythonBatchCommandBase):
    def __init__(self, python_file, config_files=None, reuse_db=True, **kwargs):
        super().__init__(**kwargs)
        self.python_file = python_file
        self.config_files = config_files
        self.reuse_db = reuse_db

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.python_file))
        if self.config_files:
            all_args.append(self.unnamed__init__param(self.config_files))
        all_args.append(self.optional_named__init__param("reuse_db", self.reuse_db, True))

    def progress_msg_self(self):
        return f"""Executing '{self.python_file}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.python_file = utils.ExpandAndResolvePath(self.python_file)
        with utils.utf8_open_for_read(self.python_file, 'r') as rfd:
            py_text = rfd.read()
            py_compiled = compile(py_text, os.fspath(self.python_file), mode='exec', flags=0, dont_inherit=False, optimize=2)
            exec(py_compiled, globals())


class RunInThread(PythonBatchCommandBase):
    """
        run another python-batch command in a thread
    """
    def __init__(self, what_to_run, thread_name=None, daemon=None, **kwargs) -> None:
        PythonBatchCommandBase.__init__(self, **kwargs)
        self.what_to_run = what_to_run
        self.thread_name = thread_name
        self.daemon = daemon  # remember: 1 the thread is not daemonize only if self.daemon is None, if self.daemon has any value, including False the thread will be daemonize
                              #           2 daemon means the thread will be terminated when the process is terminated, it has nothing to do with daemon process
        self.own_progress_count = self.what_to_run.total_progress_count()

    def repr_own_args(self, all_args: List[str]) -> None:
        # what_to_run should not increment or report progress because there is no way to know when it will happen
        # so RunInThread takes over what_to_run's progress and reports it as if it is already done.
        all_args.append(repr(self.what_to_run))
        all_args.append(self.optional_named__init__param('thread_name', self.thread_name))
        all_args.append(self.optional_named__init__param('daemon', self.daemon))

    def progress_msg_self(self) -> str:
        return f''''''

    def run_with(self):
        self.what_to_run.own_progress_count = 0
        self.what_to_run.report_own_progress = False
        with self.what_to_run as rit:
            rit()

    def run_without(self):
        self.what_to_run.own_progress_count = 0
        self.what_to_run.report_own_progress = False
        self.what_to_run()

    def __call__(self, *args, **kwargs) -> None:
        thread_thingy = None
        if self.what_to_run.call__call__ is False and self.what_to_run.is_context_manager is False:
            thread_thingy = None  # wtf?
        elif self.what_to_run.call__call__ is False and self.what_to_run.is_context_manager is True:
            thread_thingy = None # wtf?
        elif self.what_to_run.call__call__ is True and self.what_to_run.is_context_manager is False:
            thread_thingy = Thread(target=self.run_without, name=self.thread_name, daemon=self.daemon)
        elif self.what_to_run.call__call__ is True and self.what_to_run.is_context_manager is True:
            thread_thingy = Thread(target=self.run_with, name=self.thread_name, daemon=self.daemon)

        if thread_thingy:
            thread_thingy.start()


class Subprocess(RunProcessBase):
    """ run a single command NOT in a shell """

    def __init__(self, subprocess_exe, *subprocess_args, message=None, ignore_specific_exit_codes=(), **kwargs):
        assert "shell" not in kwargs, "'shell' cannot appear in kwargs for Subprocess"
        super().__init__(ignore_specific_exit_codes=ignore_specific_exit_codes, **kwargs)
        self.subprocess_exe = subprocess_exe
        self.subprocess_args = subprocess_args
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        try:
            all_args.append(self.unnamed__init__param(self.subprocess_exe))
            for arg in self.subprocess_args:
                all_args.append(self.unnamed__init__param(arg))
            all_args.append(self.optional_named__init__param("message", self.message))
            if self.ignore_specific_exit_codes:
                if len(self.ignore_specific_exit_codes,) == 1:
                    all_args.append(self.named__init__param("ignore_specific_exit_codes", self.ignore_specific_exit_codes[0]))
                else:
                    all_args.append(self.named__init__param("ignore_specific_exit_codes", self.ignore_specific_exit_codes))
        except TypeError as te:
            pass

    def progress_msg_self(self):
        if self.message:
            return f"""{self.message}"""
        else:
            return f"""running {self.subprocess_exe} {self.subprocess_args}"""

    def get_run_args(self, run_args) -> None:
        subprocess_exe = os.path.expandvars(self.subprocess_exe)
        run_args.append(subprocess_exe)
        for arg in self.subprocess_args:
            expanded_var = os.path.expandvars(arg)
            run_args.append(expanded_var)


class ExternalPythonExec(Subprocess):
    """ A class that enables running python processes under the native python installed on the machine"""
    def __init__(self, *subprocess_args, **kwargs):
        '''Setting subprocess_exe to an empty string to exclude it from the repr'''
        super().__init__('', *subprocess_args, **kwargs)

    def repr_own_args(self, all_args: List[str]):
        """ Removing subprocess_exe from the repr"""
        super().repr_own_args(all_args)
        all_args.pop(0)  # Removing empty string

    def get_run_args(self, run_args) -> None:
        """ Injecting the relevant OS python process into the run args instead of the empty string"""
        super().get_run_args(run_args)
        python_executables = {'win32': ['py',  '-3.9'], 'darwin': ['python3.9']}
        run_args.pop(0)  # Removing empty string
        for arg in reversed(python_executables[sys.platform]):
            run_args.insert(0, arg)


class SysExit(PythonBatchCommandBase):
    def __init__(self, exit_code=17, **kwargs):
        super().__init__(**kwargs)
        self.exit_code = exit_code

    def progress_msg_self(self) -> str:
        return f'''sys.exit({self.exit_code})'''

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.exit_code))

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.doing = f"calling sys.exit({self.exit_code})"
        sys.exit(self.exit_code)


class Raise(PythonBatchCommandBase):
    def __init__(self, message=None, **kwargs):
        super().__init__(**kwargs)
        self.message = message

    def progress_msg_self(self) -> str:
        return f'''raising BogusException({self.message})'''

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.optional_named__init__param("message", self.message))

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.doing = f"raising bogus exception: {self.message}"

        class BogusException(RuntimeError):
            pass
        raise BogusException(f'bogus exception: {self.message}')


class KillProcess(PythonBatchCommandBase):
    def __init__(self, process_name, retries=2, sleep_sec=1, **kwargs):
        super().__init__(**kwargs)
        self.process_name = process_name
        self.retries = retries
        self.sleep_sec = sleep_sec

    def progress_msg_self(self) -> str:
        return f'''killing process {self.process_name}'''

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.process_name))
        all_args.append(self.optional_named__init__param("retries", self.retries, 2))
        all_args.append(self.optional_named__init__param("sleep_sec", self.sleep_sec, 1))

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        found_process = False
        for i in range(self.retries):
            print(f"looking for process named {self.process_name}")
            for proc in psutil.process_iter():
                if proc.name() == self.process_name:
                    print(f"found process named {self.process_name}")
                    found_process = True
                    proc.kill()
                    break
            else:  # no process by that name was found
                print(f"no process named {self.process_name}")
                break
            time.sleep(self.sleep_sec)

        if found_process:  # make sure it's down
            for i in range(self.retries):
                for proc in psutil.process_iter():
                    if proc.name() == self.process_name:
                        raise TimeoutError(f"failed to kill process {self.process_name}")

