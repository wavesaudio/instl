#!/usr/bin/env python3


import subprocess
import time
import sys
import os
import signal

exit_val = 0
process_list = list()


def run_processes_in_parallel(commands):
    global exit_val
    try:
        install_signal_handlers()
        run_parallels(commands)
        exit_val = 0
        killall_and_exit()
    except Exception:
        killall_and_exit()


def run_parallels(commands):
    global exit_val
    for command in commands:
        try:
            if getattr(os, "setsid", None):
                a_process = subprocess.Popen(command, executable=command[0], shell=False, preexec_fn=os.setsid)  # Unix
            else:
                a_process = subprocess.Popen(command, executable=command[0], shell=False)  # Windows
            process_list.append(a_process)
        except Exception:
            print("failed to start", command, file=sys.stderr)
            sys.stdout.flush()
            exit_val = 31
            killall_and_exit()

    active_process_list = list()
    while process_list:
        for a_process in process_list:
            status = a_process.poll()
            if status is None:  # None means it's still alive
                active_process_list.append(a_process)
            else:
                if status != 0:
                    exit_val = status
                    killall_and_exit()
        process_list[:] = active_process_list
        active_process_list[:] = []
        sys.stdout.flush()
        time.sleep(.2)


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
