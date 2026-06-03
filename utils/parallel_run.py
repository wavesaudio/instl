#!/usr/bin/env python3.12


import subprocess
import sys
import os
import time
import signal
import logging
import psutil
from itertools import repeat
from concurrent import futures
from threading import Timer

import utils

log = logging.getLogger()

exit_val = 0
aborted = False
paused = False
process_list = list()

# Sentinel exit code meaning the parallel batch stopped because Central paused
# the engine (or it was auto-paused while offline) — NOT a failure. The caller
# (ParallelRun) holds until resume and then re-runs, resuming via continue-at.
PAUSED_EXIT_CODE = 9990

# curl exit codes that indicate a transient network problem (resolve/connect/
# timeout/recv-send/SSL-connect). On these the caller can hold-and-retry rather
# than failing the session, so a brief disconnect doesn't kill the install.
NETWORK_ERROR_CURL_EXIT_CODES = frozenset({6, 7, 18, 28, 35, 52, 55, 56})


class ProcessTerminatedExternally(RuntimeError):
    pass


class ContinuousTimer(Timer):
    """
    See: https://hg.python.org/cpython/file/2.7/Lib/threading.py#l1079
    """

    def run(self):
        while not self.finished.is_set():
            self.finished.wait(self.interval)
            self.function(*self.args, **self.kwargs)

        self.finished.set()


def run_processes_in_parallel(commands, shell=False, do_enqueue_output=True, abort_file=None, pause_check=None):
    global exit_val, aborted, paused, process_list
    # Reset per-run state so a retry (e.g. resume after an offline hold) starts
    # clean and doesn't inherit a stale process list / aborted / paused flag.
    exit_val = 0
    aborted = False
    paused = False
    process_list = list()
    try:
        install_signal_handlers()

        lists_of_command_lists = utils.partition_list(commands, lambda c: c[0] == "wait")

        for command_list in lists_of_command_lists:
            with futures.ThreadPoolExecutor(len(command_list)) as executor:
                list(executor.map(run_process, command_list, repeat(shell), repeat(do_enqueue_output), repeat(abort_file), repeat(pause_check)))
        log.debug('Finished all processes')
        # A clean pause is not a failure: signal it so the caller can hold and
        # then resume, rather than treating the stopped transfer as an error.
        exit_val = PAUSED_EXIT_CODE if paused else 0
        killall_and_exit()
    except Exception as e:
        log.error(e)
        killall_and_exit()


def run_process(command, shell, do_enqueue_output=True, abort_file=None, pause_check=None):
    """
    Running a sub-process externally
    Args:
        command: The command to run as sub-process. list/string (when using shell=True)
        shell: Running the command in a shell
        do_enqueue_output: Printing sub-process output to the log file.
                           Should be used only when calling processes that are not instl.
                           The option blocks the main process and can't be used when using abort_file.
        abort_file: Using an abort file to monitor and killing the process in case the file was deleted.
                    This option overrides do_enqueue_output to be able to monitor the abort file.
        pause_check: Optional callable returning True while the engine is paused
                     (Central pause, or auto-pause while offline). When it goes
                     True the running process is terminated and treated as paused
                     (not failed); the caller holds and re-runs on resume.
    """
    global exit_val
    global process_list
    global paused
    if abort_file is not None:  # Disabling enqueue_output if abort file is used.
        do_enqueue_output = False
    a_process = launch_process(command, shell, do_enqueue_output)
    process_list.append(a_process)
    t = None
    if abort_file is not None:
        t = ContinuousTimer(1, check_abort_file, args=[abort_file])
        t.start()

    try:
        while True:
            if pause_check is not None and pause_check():
                # Stop this transfer cleanly so no bytes flow while paused. The
                # .part temp file is preserved for resume on the next run.
                paused = True
                terminate_process(a_process)
                log.info(f'Process paused - terminated {command}')
                break
            if do_enqueue_output:  # Calling enqueue_output only if abort file is not used.
                enqueue_output(a_process, pause_check)
            status = a_process.poll()
            if status is not None:  # None means it's still alive
                log.debug(f'Process finished - {command}')
                if aborted:
                    exit_val = status
                    raise ProcessTerminatedExternally(command)
                elif status != 0:
                    exit_val = status
                    raise RuntimeError(f'Command failed {command}')
                break
            # status is None and not paused: enqueue_output returned early
            # (e.g. it observed a pause); loop back to re-check pause_check.
    finally:
        if t is not None:
            t.cancel()


def terminate_process(a_process):
    """Terminate a still-running process (and its group/tree), best-effort.

    Uses SIGTERM (not SIGKILL) so curl can flush its partial .part file for a
    later resume. Reuses the same group/tree kill as killall_and_exit.
    """
    try:
        if a_process.poll() is None:
            if getattr(os, "killpg", None):
                os.killpg(a_process.pid, signal.SIGTERM)  # Unix
            else:
                kill_proc_tree(a_process.pid)  # Windows
    except Exception as ex:
        log.debug(f"could not terminate process {getattr(a_process, 'pid', '?')}: {ex}")
    try:
        a_process.wait(timeout=5)
    except Exception:
        pass


def launch_process(command, shell, do_enqueue_output):
    global exit_val
    if shell:
        full_command = " ".join(command)
        kwargs = {}
    else:
        full_command = command
        kwargs = {'executable': command[0]}
    if getattr(os, "setsid", None):  # UNIX
        kwargs['preexec_fn'] = os.setsid
    if do_enqueue_output:
        kwargs.update({'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'bufsize': 128})
    try:
        a_process = subprocess.Popen(full_command, shell=shell, env=os.environ, **kwargs)
    except Exception as e:
        exit_val = 31
        raise RuntimeError(f"failed to start {command}") from e
    return a_process


def enqueue_output(a_process, pause_check=None):
    out = a_process.stdout
    try:
        buffer = ''
        while True:
            time.sleep(0)  # Releasing thread to yield other threads to do work
            if a_process.poll() is not None:
                break
            if pause_check is not None and pause_check():
                # Return so run_process can terminate the process while paused;
                # detection latency is bounded by curl's progress cadence.
                break
            b = out.read(128).decode('utf-8', errors='backslashreplace')  # Reading stream to buffer
            if b:
                buffer += b
                if '\n' in buffer:
                    to_print = buffer.split('\n')
                    for line in to_print[:-1]:  # Logging every line except the last one in the buffer
                        log.info(line.strip('\r\n'))
                    if to_print[-1].endswith('\n'):  # In case the last line in the buffer ends with a newline
                        log.info(to_print[-1].strip('\r\n'))
                    else:
                        buffer = to_print[-1]  # Store the rest for the next round of read

    except ValueError as e:
        pass  # on mac the stdout is closed when the process is terminated. In this case we ignore
    finally:
        if not out.closed:
            out.close()


def check_abort_file(abort_file):
    global aborted
    if not os.path.exists(abort_file):
        aborted = True
        log.debug(f'Process aborted - Abort file not found {abort_file}')
        killall_and_exit()


def signal_handler(signum, frame):
    global exit_val
    exit_val = signum
    killall_and_exit()


def killall_and_exit():
    for a_process in process_list:
        status = a_process.poll()
        if status is None:  # None means it's still alive
            if getattr(os, "killpg", None):
                os.killpg(a_process.pid, signal.SIGTERM)  # Unix
            else:
                kill_proc_tree(a_process.pid)  # Windows
    sys.exit(exit_val)


def kill_proc_tree(pid, including_parent=True):
    parent = psutil.Process(pid)
    children = parent.children(recursive=True)
    for child in children:
        child.kill()
    gone, still_alive = psutil.wait_procs(children, timeout=5)
    if including_parent:
        parent.kill()
        parent.wait(5)


def install_signal_handlers():
    for sig in (signal.SIGABRT, signal.SIGFPE, signal.SIGILL, signal.SIGINT, signal.SIGSEGV, signal.SIGTERM):
        signal.signal(sig, signal_handler)
