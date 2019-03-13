#!/usr/bin/env python3.6


import subprocess
import sys
import os
import signal
import logging
from itertools import repeat
from concurrent import futures
from threading import Timer

import utils

log = logging.getLogger()

exit_val = 0
process_list = list()


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


def run_processes_in_parallel(commands, shell=False, abort_file=None):
    global exit_val
    try:
        install_signal_handlers()

        lists_of_command_lists = utils.partition_list(commands, lambda c: c[0] == "wait")

        for command_list in lists_of_command_lists:
            with futures.ThreadPoolExecutor(len(command_list)) as executor:
                list(executor.map(run_process, command_list, repeat(shell), repeat(abort_file)))

        exit_val = 0
        killall_and_exit()
    except Exception as e:
        log.error(e)
        killall_and_exit()


def run_process(command, shell, abort_file=None):
    global exit_val
    global process_list
    a_process = launch_process(command, shell)
    process_list.append(a_process)
    if abort_file is not None:
        t = ContinuousTimer(1, check_abort_file, args=[abort_file])
        t.start()

    while True:
        enqueue_output(a_process.stdout)
        status = a_process.poll()
        if status is not None:  # None means it's still alive
            log.debug(f'Process finished - {command}')
            if status == -15:
                exit_val = status
                raise ProcessTerminatedExternally(command)
            elif status != 0:
                exit_val = status
                raise RuntimeError(f'Command failed {command}')
            break
    if hasattr('t'):
        t.cancel()


def launch_process(command, shell):
    global exit_val
    if shell:
        full_command = " ".join(command)
        kwargs = {}
    else:
        full_command = command
        kwargs = {'executable': command[0]}
    if getattr(os, "setsid", None):  # UNIX
        kwargs['preexec_fn'] = os.setsid
    try:
        a_process = subprocess.Popen(full_command, shell=shell, bufsize=1,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    except Exception as e:
        exit_val = 31
        raise RuntimeError(f"failed to start {command}") from e
    return a_process


def enqueue_output(out):
    for line in iter(out.readline, b''):
        if line != '':
            log.info(line.decode('utf-8').strip('\n'))
    out.close()


def check_abort_file(abort_file):
    if not os.path.exists(abort_file):
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
                a_process.kill()  # Windows
    sys.exit(exit_val)


def install_signal_handlers():
    for sig in (signal.SIGABRT, signal.SIGFPE, signal.SIGILL, signal.SIGINT, signal.SIGSEGV, signal.SIGTERM):
        signal.signal(sig, signal_handler)
