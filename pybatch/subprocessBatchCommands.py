import abc
import collections
import collections.abc
import logging
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread, Event
from typing import List

import psutil

import utils
from configVar import config_vars
from .baseClasses import PythonBatchCommandBase

log = logging.getLogger(__name__)

# Workstream 1 (live ETA): cadence + smoothing for the in-loop `session_state`
# progress ticks emitted during the curl download. curl's per-tick Speed is too
# jittery to drive a stable ETA, so we feed Central an EMA-smoothed throughput
# (alpha weights the newest sample) at most once per interval. Best-effort:
# emitting must never break a download.
_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC = 1.0
_DOWNLOAD_PROGRESS_THROUGHPUT_EMA_ALPHA = 0.2


class RunProcessBase(PythonBatchCommandBase, call__call__=True, is_context_manager=True,
                     kwargs_defaults={"stderr_means_err": True, "capture_stdout": False, "out_file": None,
                                      "detach": False}):
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
            # normalize to a tuple so a repr round-trip (which renders the
            # sequence as a list literal) recreates an equal object
            self.ignore_specific_exit_codes = tuple(ignore_specific_exit_codes)
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
            pid = subprocess.Popen(run_args).pid
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

            completed_process = subprocess.run(run_args, check=False, stdin=in_stream, stdout=out_stream,
                                                   stderr=subprocess.PIPE, shell=self.shell, bufsize=0)

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

    def log_result(self, log_lvl, message, exception_obj):
        if self.stderr:
            message += f'; STDERR: {utils.unicodify(self.stderr)}'
        super().log_result(log_lvl, message, exception_obj)

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
        elif self.output_script and sys.platform == 'darwin':
            return f"""adding to post install script '{self.shell_command}'"""
        else:
            return f"""running {self.shell_command}"""

    def get_run_args(self, run_args) -> None:
        resolved_shell_command = os.path.expandvars(self.shell_command)
        run_args.append(resolved_shell_command)

    def __call__(self, *args, **kwargs):
        if self.output_script and sys.platform == 'darwin':
            PythonBatchCommandBase.__call__(self, *args, **kwargs)
            utils.write_shell_command(f'''{self.shell_command} \n''', self.output_script)
        else:
            RunProcessBase.__call__(self, *args, **kwargs)

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
            assert isinstance(shell_command_list, collections.abc.Sequence)
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


class ParallelRun(PythonBatchCommandBase, kwargs_defaults={
    'action_name': None,
    'shell': False,
    'fallback_config_file': None,
    'fallback_exit_codes': (),
}):
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
        resolved_config_file = utils.ExpandAndResolvePath(self.config_file)
        self.doing = f"""{self.get_action_name()} reading config file '{resolved_config_file}'"""
        commands = self._read_parallel_run_config_file(resolved_config_file)
        try:
            self.doing = f"""{self.get_action_name()}, config file '{resolved_config_file}', running with {len(commands)} processes in parallel"""
            self._run_with_pause_and_offline_hold(commands)
        finally:
            self.increment_progress()

    def _control_channel(self):
        """The stdin control channel singleton, or None if unavailable.

        Only used for curl downloads, so a pause/offline-hold can't affect
        unrelated parallel runs (e.g. copy). Imported lazily to avoid a
        utils->pyinstl import at module load.
        """
        try:
            from pyinstl.downloadControlChannel import get_global_channel
            return get_global_channel()
        except Exception:
            return None

    def _run_with_pause_and_offline_hold(self, commands):
        """Run the parallel batch, honoring pause and surviving a brief offline.

        - Pause (Central, or auto-pause while offline): the runner terminates
          curl and returns PAUSED_EXIT_CODE; we wait_if_paused() and re-run,
          which resumes from the .part files (continue-at). Nothing flows while
          paused, so this is a real pause (#1) and an offline hold (#2/#6).
        - Network-class curl exit without a pause: hold if Central has paused us,
          otherwise back off briefly and retry a bounded number of times so a
          short blip recovers instead of failing the session.
        - The curl range-failure fallback (exit 33) and genuine failures keep
          their existing behavior.
        """
        is_curl = self._is_curl_command(commands)
        channel = self._control_channel() if is_curl else None
        pause_check = channel.is_paused if channel is not None else None
        network_retry_budget = 12
        network_attempt = 0
        while True:
            try:
                utils.run_processes_in_parallel(commands, self.shell, pause_check=pause_check)
                return  # run_processes_in_parallel always sys.exits; here for safety
            except SystemExit as sys_exit:
                code = sys_exit.code
                if code == 0:
                    return
                if code == utils.PAUSED_EXIT_CODE:
                    log.info(f"{self.get_action_name()} paused; holding until resume")
                    if channel is not None:
                        channel.wait_if_paused()
                    network_attempt = 0
                    continue
                if self._can_run_fallback(code):
                    self._run_fallback_after_curl_range_failure(code)
                    return
                if is_curl and self._is_network_error(code):
                    # Offline grace: if Central paused us (offline), hold here
                    # until resume; otherwise back off and retry a few times so
                    # a quick disconnect/reconnect recovers without erroring.
                    if channel is not None:
                        channel.wait_if_paused()
                    if network_retry_budget > 0:
                        network_retry_budget -= 1
                        network_attempt += 1
                        backoff = min(2 * network_attempt, 10)
                        log.info(f"{self.get_action_name()} network error (curl {code}); retry in {backoff}s ({network_retry_budget} left)")
                        if channel is not None:
                            channel.sleep_or_wake(backoff)  # try_now/resume cuts this short
                        else:
                            time.sleep(backoff)
                        continue
                    raise Exception(utils.get_curl_err_msg(code))
                if is_curl:
                    raise Exception(utils.get_curl_err_msg(code))
                raise

    def _is_network_error(self, exit_code):
        try:
            return int(exit_code) in utils.NETWORK_ERROR_CURL_EXIT_CODES
        except (TypeError, ValueError):
            return False

    def _read_parallel_run_config_file(self, resolved_config_file):
        commands = list()
        with utils.utf8_open_for_read(resolved_config_file, "r") as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        return commands

    def _can_run_fallback(self, exit_code):
        return (
            self.fallback_config_file
            and int(exit_code) in {int(code) for code in self.fallback_exit_codes}
        )

    def _is_curl_command(self, commands):
        return bool(commands) and Path(commands[0][0]).name.lower().startswith("curl")

    def _run_fallback_after_curl_range_failure(self, exit_code):
        resolved_fallback_config_file = utils.ExpandAndResolvePath(self.fallback_config_file)
        fallback_commands = self._read_parallel_run_config_file(resolved_fallback_config_file)
        self.doing = (
            f"{self.get_action_name()} curl resume failed with exit code {exit_code}; "
            f"retrying from zero with fallback config '{resolved_fallback_config_file}'"
        )
        log.info(self.doing)
        try:
            utils.run_processes_in_parallel(fallback_commands, self.shell)
        except SystemExit as fallback_exit:
            if fallback_exit.code != 0:
                if self._is_curl_command(fallback_commands):
                    err_msg = utils.get_curl_err_msg(fallback_exit.code)
                    raise Exception(err_msg)
                raise


class ExecPython(PythonBatchCommandBase):
    def __init__(self, python_file, config_files=None, reuse_db=True, args=None, **kwargs):
        super().__init__(**kwargs)
        self.python_file = python_file
        self.config_files = config_files
        self.reuse_db = reuse_db
        self.args = args

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.python_file))
        if self.config_files:
            all_args.append(self.unnamed__init__param(self.config_files))
        all_args.append(self.optional_named__init__param("reuse_db", self.reuse_db, True))
        all_args.append(self.optional_named__init__param("args", self.args, []))

    def progress_msg_self(self):
        return f"""Executing '{self.python_file}'"""

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        self.python_file = utils.ExpandAndResolvePath(self.python_file)
        with utils.utf8_open_for_read(self.python_file, 'r') as rfd:
            original_argv = sys.argv
            py_text = rfd.read()
            py_compiled = compile(py_text, os.fspath(self.python_file), mode='exec', flags=0, dont_inherit=False, optimize=2)

            if self.args:
                sys.argv = [os.fspath(self.python_file), *self.args]
            sys.path.append(os.fspath(self.python_file.parent))  # add python_file's parent so python_file can import files located in the same folder as python_file
            exec(py_compiled, globals())
            sys.argv = original_argv


class Exec(ExecPython):
    """ deprecated use ExecPython instead"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


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
        match self.what_to_run.call__call__, self.what_to_run.is_context_manager:
            case False, False:
                thread_thingy = None  # wtf?
            case False, True:
                thread_thingy = None # wtf?
            case True, False:
                thread_thingy = Thread(target=self.run_without, name=self.thread_name, daemon=self.daemon)
            case True, True:
                thread_thingy = Thread(target=self.run_with, name=self.thread_name, daemon=self.daemon)

        if thread_thingy:
            thread_thingy.start()


class Subprocess(RunProcessBase):
    """ run a single command NOT in a shell, possibly with arguments """

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
            log.debug(f"Subprocess.repr_own_args failed: {te}")

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
        """Setting subprocess_exe to an empty string to exclude it from the repr"""
        super().__init__('', *subprocess_args, **kwargs)

    def repr_own_args(self, all_args: List[str]):
        """ Removing subprocess_exe from the repr"""
        super().repr_own_args(all_args)
        all_args.pop(0)  # Removing empty string

    def get_run_args(self, run_args) -> None:
        """ Injecting the relevant OS python process into the run args instead of the empty string"""
        super().get_run_args(run_args)
        python_executables = {'win32': ['py',  '-3.12'], 'darwin': ['python3.12']}
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
        look_for = [self.process_name]
        if sys.platform == 'win32':
            if not self.process_name.endswith(".exe"):
                look_for.append(self.process_name+".exe")
        for i in range(self.retries):
            #print(f"looking for process named {self.process_name}")
            for proc in psutil.process_iter():
                proc_name = proc.name()
                if proc_name in look_for:
                    #print(f"found process named {proc_name}")
                    found_process = True
                    proc.kill()
                    break
            else:  # no process by that name was found
                #print(f"no process named {self.process_name}")
                break
            time.sleep(self.sleep_sec)

        if found_process:  # make sure it's down
            for i in range(self.retries):
                for proc in psutil.process_iter():
                    proc_name = proc.name()
                    if proc_name in look_for:
                        raise TimeoutError(f"failed to kill process {self.process_name}")


class CurlWithInternalParallel(PythonBatchCommandBase, kwargs_defaults={
    'fallback_config_file_path': None,
    'fallback_exit_codes': (),
}):
    def __init__(self, curl_path: Path,
                 config_file_path: Path,
                 total_files_to_download: int,
                 previously_downloaded_files: int,
                 total_bytes_to_download: int,
                 *argv, **kwargs):
        super().__init__(*argv, **kwargs)
        self.curl_path = curl_path
        self.config_file_path = config_file_path
        self.total_files_to_download = total_files_to_download
        self.previously_downloaded_files = previously_downloaded_files
        self.total_bytes_to_download = total_bytes_to_download

    # converts a number of bytes to human-readable string
    # 0 => 0
    # 1024 => 1K
    #
    def bytes_to_string(self, number):
        suffixes = ['B', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']
        magnitude = 0

        if number == 0:
            return "0"

        while number >= 1024 and magnitude < len(suffixes) - 1:
            number /= 1024
            magnitude += 1

        decimal_places = 2 if magnitude > 0 else 0
        formatted_number = "{:.{}f}".format(number, decimal_places)

        return f"{formatted_number}{suffixes[magnitude]}"

    # inverse of bytes_to_string: converts curl's "Dled"/"Speed"-style size
    # string back to a number of bytes. Tolerant: returns 0 on any parse
    # failure and never raises (progress accounting must never break curl).
    #   "0"     => 0
    #   "1305k" => 1305 * 1024
    #   "70.2M" => 70.2 * 1024**2
    #   "5.98G" => 5.98 * 1024**3
    def string_to_bytes(self, size_str):
        try:
            s = str(size_str).strip()
            if not s:
                return 0
            suffixes = {'B': 0, 'K': 1, 'M': 2, 'G': 3, 'T': 4, 'P': 5, 'E': 6, 'Z': 7, 'Y': 8}
            last = s[-1].upper()
            if last in suffixes:
                magnitude = suffixes[last]
                number_part = s[:-1]
            else:
                magnitude = 0
                number_part = s
            number = float(number_part)
            return int(number * (1024 ** magnitude))
        except Exception:
            return 0  # never raise: keep progress accounting fail-safe

    def progress_msg_self(self) -> str:
        return f'''CurlInternalParallel {self.config_file_path}'''

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("curl_path", self.curl_path))
        all_args.append(self.named__init__param("config_file_path", self.config_file_path))
        all_args.append(self.named__init__param("total_files_to_download", self.total_files_to_download))
        all_args.append(self.named__init__param("previously_downloaded_files", self.previously_downloaded_files))
        all_args.append(self.named__init__param("total_bytes_to_download", self.total_bytes_to_download))

    def _control_channel(self):
        """The stdin control channel singleton, or None if unavailable.

        Mirrors ParallelRun._control_channel. Imported lazily to avoid a
        utils->pyinstl import at module load.
        """
        try:
            from pyinstl.downloadControlChannel import get_global_channel
            return get_global_channel()
        except Exception:
            return None

    def __call__(self, *args, **kwargs):
        PythonBatchCommandBase.__call__(self, *args, **kwargs)

        config_file_path_fixed = os.fspath(self.config_file_path)
        if 'Win' in utils.get_current_os_names():
            # on windows curl fail to read long paths or paths with unicode chars
            # so convert the path to short path (DOS style 8.3 chars)
            import win32api
            config_file_path_fixed = win32api.GetShortPathName(config_file_path_fixed)

        # Honor the Central pause/resume control channel during the curl
        # download. This class is the path that actually runs the bulk
        # download (a single `curl --config` using curl's internal --parallel),
        # so pause must be enforced HERE -- not only in ParallelRun. On pause
        # we SIGTERM curl (so the partial .part files flush), wait for resume,
        # then re-run `curl --config`, which resumes from the partial files via
        # the `continue-at` entries curlHelper wrote. Without a channel (e.g.
        # non-sync invocations) pause_check is None and behavior is unchanged.
        channel = self._control_channel()
        pause_check = channel.is_paused if channel is not None else None

        # Re-run loop honoring pause/resume and surviving brief network drops
        # (mirrors ParallelRun._run_with_pause_and_offline_hold -- the bulk
        # download actually runs here, not there). On pause we hold then re-run;
        # on a network-class curl exit we hold if Central paused us (offline),
        # otherwise back off and retry a bounded number of times so a quick
        # disconnect/reconnect recovers instead of failing the session. Terminal
        # behavior is intentionally unchanged: once retries are exhausted (or for
        # a non-network error) we fall through to the existing fallback /
        # increment_progress and let the downstream checksum pass redownload
        # whatever is still missing -- this class never raised on curl failure.
        network_retry_budget = 12
        network_attempt = 0
        return_code = 0

        # Cumulative & monotonic progress state carried ACROSS re-runs (each
        # _run_curl_once is one curl pass; on pause/network-resume curl is
        # re-launched and its Xfers/Dled restart at 0). Without this, the
        # logged counts would reset on every resume and the UI would appear to
        # "start from the beginning". See _run_curl_once for the accounting.
        #
        # FILES: a re-run re-walks the WHOLE config -- already-finished files
        #   are still counted in Xfers (processed/skipped fast) so
        #   previously_downloaded_files + (Xfers - Live) trends back up to the
        #   true total on its own; we add NO per-run baseline (that would
        #   double-count). We only clamp it monotonic via this high-water mark.
        # BYTES: with curl resume (`continue-at = -`) a re-run's Dled counts
        #   only the NEW bytes this run. So cumulative = bytes_baseline (sum of
        #   each prior run's final Dled) + this run's current Dled. We fold the
        #   run's last Dled into the baseline when each run ends/pauses, and
        #   clamp monotonic via its own high-water mark.
        self._files_high_water = 0
        self._bytes_baseline = 0
        self._bytes_high_water = 0

        # Workstream 1 (live ETA): EMA-smoothed throughput and the last-emit
        # sample baseline. The EMA value persists ACROSS re-runs so the ETA
        # stays stable through pause/resume; the per-run sample baseline is
        # re-seeded in _run_curl_once so the paused/offline gap is never divided
        # into a bogus "slow" speed. session_id is resolved once (not per tick).
        self._ema_throughput_bps = 0.0
        self._last_emit_monotonic = None
        self._last_emit_bytes = 0
        try:
            self._session_id = str(config_vars["__INVOCATION_RANDOM_ID__"]) \
                if config_vars.defined("__INVOCATION_RANDOM_ID__") else "unknown"
        except Exception:
            self._session_id = "unknown"

        while True:
            return_code, paused = self._run_curl_once(config_file_path_fixed, pause_check)
            if paused:
                log.info(f"{self.progress_msg_self()} paused; holding until resume")
                if channel is not None:
                    channel.wait_if_paused()
                network_attempt = 0
                continue  # resume: re-run curl --config (continue-at resumes partial files)
            if return_code != 0 and self._is_network_error(return_code):
                # Offline grace: hold if Central paused us (offline), otherwise
                # back off briefly and retry so a short blip recovers.
                if channel is not None:
                    channel.wait_if_paused()
                if network_retry_budget > 0:
                    network_retry_budget -= 1
                    network_attempt += 1
                    backoff = min(2 * network_attempt, 10)
                    log.info(f"{self.progress_msg_self()} network error (curl {return_code}); retry in {backoff}s ({network_retry_budget} left)")
                    if channel is not None:
                        channel.sleep_or_wake(backoff)  # resume/try_now cuts this short
                    else:
                        time.sleep(backoff)
                    continue
                log.info(f"{self.progress_msg_self()} network error (curl {return_code}); retries exhausted, continuing")
            break

        print(f"Curl ended {return_code}")
        if self._can_run_fallback(return_code):
            self._run_fallback_after_curl_range_failure(return_code)
        self.increment_progress()

    def _maybe_emit_progress_tick(self, cumulative_bytes, downloaded_files):
        """Emit a throttled, EMA-smoothed ``session_state`` progress tick.

        Workstream 1 (live ETA): curl's per-tick Speed is too jittery to drive
        a stable ETA, and the structured ``session_state`` events otherwise
        carry no in-flight bytes/throughput -- so Central could only compute an
        ETA from the end-of-session summary (i.e. never, during the download).
        This feeds Central cumulative received bytes plus a smoothed throughput
        roughly once per second, so its ETA is populated and stable from the
        first tick.

        The EMA persists across re-runs (smoothing survives pause/resume); the
        first sample of each curl pass only re-establishes the baseline (see the
        ``_last_emit_monotonic = None`` reset in ``_run_curl_once``) so a paused
        gap is never divided into a bogus low speed. Best-effort: any failure is
        swallowed -- instrumentation must never break a download.
        """
        try:
            now = time.monotonic()
            last = getattr(self, "_last_emit_monotonic", None)
            if last is None:
                # First sample of this curl pass: establish the baseline only.
                # The carried-over EMA (if any) still rides along on the tick.
                self._last_emit_monotonic = now
                self._last_emit_bytes = cumulative_bytes
            else:
                dt = now - last
                if dt < _DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC:
                    return  # throttle: at most one tick per interval
                inst_bps = max(0.0, (cumulative_bytes - self._last_emit_bytes) / dt)
                if self._ema_throughput_bps <= 0.0:
                    self._ema_throughput_bps = inst_bps
                else:
                    a = _DOWNLOAD_PROGRESS_THROUGHPUT_EMA_ALPHA
                    self._ema_throughput_bps = a * inst_bps + (1.0 - a) * self._ema_throughput_bps
                self._last_emit_monotonic = now
                self._last_emit_bytes = cumulative_bytes

            try:
                from pyinstl.downloadEvents import emit_session_state
            except Exception:
                return  # structured channel unavailable; legacy text line still flows
            emit_session_state(
                session_id=getattr(self, "_session_id", "unknown"),
                state="downloading",
                bytes_received=int(cumulative_bytes),
                files_completed=int(downloaded_files),
                observed_throughput_bytes_per_second=int(self._ema_throughput_bps),
                # phase_bytes_* mirror the verify phase's tick so Central's
                # phaseDisplayPercent drives a determinate download bar (received
                # / planned), not just the meta line's byte/throughput counters.
                phase_bytes_done=int(cumulative_bytes),
                phase_bytes_planned=int(self.total_bytes_to_download),
                reason="download_progress",
            )
        except Exception as ex:  # pragma: no cover - instrumentation must never break sync
            log.debug(f"could not emit download progress tick: {ex}")

    def _download_part_output_paths(self):
        """Parse the curl ``--config`` file once for its ``output = "..."`` entries.

        curlHelper writes every download as ``output = "<final>.instl-<id>.part"``
        with a ``continue-at`` directive for resume, so these ``.part`` files are
        exactly what curl grows on disk. Summing their sizes gives true cumulative
        received bytes -- independent of curl's console meter, the fragile,
        platform-variable source that yields no in-flight rows on Windows. Parsed
        once and cached; best-effort (any failure -> empty list, so the poller
        simply emits nothing rather than breaking the download)."""
        cached = getattr(self, "_part_output_paths_cache", None)
        if cached is not None:
            return cached
        paths = []
        try:
            with open(os.fspath(self.config_file_path), "r", encoding="utf-8", errors="replace") as cfg:
                for line in cfg:
                    s = line.strip()
                    # form: output = "C:\...\file.ext.instl-<id>.part"
                    if s.startswith("output"):
                        _, sep, rhs = s.partition("=")
                        if not sep:
                            continue
                        rhs = rhs.strip().strip('"')
                        if rhs:
                            paths.append(rhs)
        except OSError as ex:
            log.debug(f"download poller: could not read curl config for part paths: {ex}")
            paths = []
        self._part_output_paths_cache = paths
        return paths

    def _sum_downloaded_part_bytes(self):
        """Sum on-disk sizes of the ``.part`` outputs (cumulative received bytes).

        Best-effort per file: a not-yet-created, locked, or vanished part is
        skipped, never raised. Returns ``(cumulative_bytes, files_estimate)``.
        curl writes all parts in place and instl renames only after the batch, so
        a true per-file completion count is not observable here -- files_estimate
        is a monotonic, byte-proportional approximation (bytes drive the bar/ETA;
        the file count is informational)."""
        total = 0
        for p in self._download_part_output_paths():
            try:
                total += os.path.getsize(p)
            except OSError:
                pass  # not created yet / locked / vanished -- skip this sample
        planned_bytes = self.total_bytes_to_download or 0
        if planned_bytes > 0:
            files_est = int(self.total_files_to_download * min(1.0, total / planned_bytes))
        else:
            files_est = 0
        prev_high = getattr(self, "_poll_files_high_water", 0)
        if files_est < prev_high:
            files_est = prev_high
        else:
            self._poll_files_high_water = files_est
        files_est = min(files_est, self.total_files_to_download)
        return total, files_est

    def _run_download_progress_poller(self, stop_event):
        """Daemon poller: ~once/second, emit a ``download_progress`` tick derived
        from on-disk ``.part`` sizes -- mirroring the verify phase's in-process
        Python cadence, the one progress mechanism that works cross-platform.

        Never raises (instrumentation must never break a download) and is bounded
        by ``stop_event`` so it always joins promptly -- this must never wedge the
        sync or elevated-copy process (see P7-010)."""
        while not stop_event.is_set():
            try:
                cumulative_bytes, files_est = self._sum_downloaded_part_bytes()
                self._maybe_emit_progress_tick(cumulative_bytes, files_est)
            except Exception as ex:  # pragma: no cover - defensive; poller must never raise
                log.debug(f"download progress poller tick failed: {ex}")
            stop_event.wait(_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC)

    def _run_curl_once(self, config_file_path_fixed, pause_check):
        """Run one `curl --config` pass, logging progress.

        Returns (returncode, paused). If pause_check() becomes true while curl
        is running we terminate it (SIGTERM, so partial .part files flush for a
        later resume) and return paused=True. Pause-detection latency is bounded
        by curl's progress cadence (~1s), same as utils.parallel_run.run_process.
        """
        # start_new_session so curl becomes its own process-group leader, which
        # is what terminate_process()'s os.killpg() targets on pause (mirrors
        # launch_process's preexec_fn=os.setsid in parallel_run). Without it the
        # killpg has no group to signal and curl would keep downloading.
        process = subprocess.Popen([os.fspath(self.curl_path), "--config", config_file_path_fixed],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                   universal_newlines=True,
                                   start_new_session=True,
                                   bufsize=1)
        reg = re.compile(r"""^\s*
           (?P<DL_percent>[\d.-]+)\s+
           (?P<UL_percent>[\d.-]+)\s+
           (?P<Dled>[\d.a-z]+)\s+
           (?P<Uled>[\d.a-z]+)\s+
           (?P<Xfers>[\d]+)\s+
           (?P<Live>[\d]+)\s+
           (?P<Queue>[\d]+)?\s*?
           (?P<Total>[\d:-]+)\s+
           (?P<Current>[\d:-]+)\s+
           (?P<Left>[\d:-]+)\s+
           (?P<Speed>[\d.a-z]+)
           (?P<the_rest>.*)?$""",
           re.IGNORECASE | re.VERBOSE)

        bytes_to_download_str = self.bytes_to_string(self.total_bytes_to_download)

        # Last Dled (in bytes) parsed this run; folded into the cumulative
        # bytes baseline when the run ends/pauses (so the next run's Dled, which
        # restarts at 0 yet only fetches the remaining bytes, adds on top).
        last_run_dled_bytes = 0

        # Workstream 1: re-seed the throughput sample baseline for THIS curl
        # pass. The EMA value itself carries over (smoothing survives resume),
        # but the first sample of each pass only re-establishes the baseline so
        # the paused/offline wall-time gap is never counted as transfer time.
        self._last_emit_monotonic = None

        # Workstream 1 root-cause fix (Windows parity with Mac): drive the
        # structured download_progress ticks from on-disk .part sizes via a
        # Python-cadence poller -- exactly like the verify phase -- instead of
        # scraping curl's --parallel console meter. That meter yields no usable
        # in-flight rows on Windows (so the download bar/ETA never move), while
        # verify, an in-process Python loop, ticks fine in the very same run.
        # Cross-platform, no sys.platform branch: Mac keeps working and gains a
        # deterministic cadence. Hang-safe (P7-010): daemon thread + stop Event
        # + bounded join in the finally below; the poller only reads file sizes.
        _poll_stop = Event()
        _poll_thread = Thread(target=self._run_download_progress_poller,
                              args=(_poll_stop,),
                              name="download-progress-poller",
                              daemon=True)
        _poll_thread.start()

        paused = False
        try:
            while process.poll() is None:
                # Check pause before blocking on the next progress line so a pause
                # stops the transfer within roughly one progress tick.
                if pause_check is not None and pause_check():
                    from utils.parallel_run import terminate_process
                    terminate_process(process)
                    paused = True
                    log.info(f"{self.progress_msg_self()} paused - terminated curl")
                    break
                stdout_line = process.stdout.readline().strip()
                stdout_lines = stdout_line.split('\r')
                for stdout_line in stdout_lines:
                    match = reg.match(stdout_line)
                    if match:
                        downloaded_files = self.previously_downloaded_files
                        try:
                            # Add the total Xfers, Reduce by the live count
                            downloaded_files += int(match.group('Xfers')) - int(match.group('Live'))
                        except:
                            pass  # in case 'Xfers' could not be converted to int

                        # FILES: monotonic only (no per-run baseline -- a re-run
                        # re-counts finished files in Xfers, so the value already
                        # trends back to the true total). Never report below the
                        # high-water mark, cap at the total.
                        if downloaded_files > self._files_high_water:
                            self._files_high_water = downloaded_files
                        downloaded_files = min(self._files_high_water, self.total_files_to_download)

                        # BYTES: cumulative across re-runs. This run's Dled only
                        # counts new bytes (curl resumes via continue-at), so add
                        # the baseline of bytes finished in prior runs. Clamp
                        # monotonic and cap at the total.
                        current_dled_bytes = self.string_to_bytes(match.group('Dled'))
                        last_run_dled_bytes = current_dled_bytes
                        cumulative_bytes = self._bytes_baseline + current_dled_bytes
                        if cumulative_bytes > self._bytes_high_water:
                            self._bytes_high_water = cumulative_bytes
                        cumulative_bytes = min(self._bytes_high_water, self.total_bytes_to_download)
                        downloaded_bytes_str = self.bytes_to_string(cumulative_bytes)

                        # Legacy human-readable line (also feeds Central's older
                        # text-based liveDownload parser where curl's meter is
                        # available, e.g. Mac). The structured download_progress
                        # tick is now emitted by the .part poller, not here, so
                        # the UI advances even when this meter line never appears.
                        message = f"Progress ... of ...; " \
                                  f"Downloaded {downloaded_files} of {self.total_files_to_download} files, " \
                                  f"Downloaded {downloaded_bytes_str} of {bytes_to_download_str}, " \
                                  f"Speed {match.group('Speed')}"
                        log.info(message)
        finally:
            # Stop the poller deterministically before returning. Bounded join so
            # a stuck size-read can never wedge the sync/elevated-copy process.
            _poll_stop.set()
            _poll_thread.join(timeout=2.0)

        try:
            process.stdout.close()
        except Exception:
            pass
        process.wait()
        # Fold this run's final Dled into the cumulative byte baseline so the
        # next re-run (whose Dled restarts at 0 but fetches only the remaining
        # bytes) is reported on top of what this run actually transferred.
        self._bytes_baseline += last_run_dled_bytes
        return process.returncode, paused

    def _is_network_error(self, exit_code):
        try:
            return int(exit_code) in utils.NETWORK_ERROR_CURL_EXIT_CODES
        except (TypeError, ValueError):
            return False

    def _can_run_fallback(self, exit_code):
        return (
            self.fallback_config_file_path
            and int(exit_code) in {int(code) for code in self.fallback_exit_codes}
        )

    def _run_fallback_after_curl_range_failure(self, exit_code):
        config_file_path_fixed = os.fspath(self.fallback_config_file_path)
        if 'Win' in utils.get_current_os_names():
            import win32api
            config_file_path_fixed = win32api.GetShortPathName(config_file_path_fixed)
        log.info(
            f"CurlInternalParallel curl resume failed with exit code {exit_code}; "
            f"retrying from zero with fallback config '{self.fallback_config_file_path}'"
        )
        fallback_process = subprocess.run(
            [os.fspath(self.curl_path), "--config", config_file_path_fixed],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if fallback_process.stdout:
            log.info(fallback_process.stdout)
        if fallback_process.stderr:
            log.info(fallback_process.stderr)
        fallback_process.check_returncode()
