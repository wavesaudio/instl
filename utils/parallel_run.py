#!/usr/bin/env python
from __future__ import print_function

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
    except Exception as es:
        killall_and_exit()

def run_parallels(commands):
    global exit_val
    for command in commands:
        try:
            if getattr(os, "setsid", None):
                proc = subprocess.Popen(command, executable=command[0], shell=False, preexec_fn=os.setsid) # Unix
            else:
                proc = subprocess.Popen(command, executable=command[0], shell=False) # Windows
            #print("Started", command, proc.pid)
            #sys.stdout.flush()
            process_list.append(proc)
        except Exception as es:
            print("failed to start", command, es.strerror, file=sys.stderr)
            sys.stdout.flush()
            exit_val = es.strerror
            killall_and_exit()

    active_process_list = list()
    while process_list:
        for proc in process_list:
            status = proc.poll()
            if status is None: # None means it's still alive
                #sys.stdout.write(str(proc.pid) + " still alive\n")
                #sys.stdout.flush()
                active_process_list.append(proc)
                #continue
            else:
                #sys.stdout.write(str(proc.pid) + " just died " + str(status) + "\n")
                #sys.stdout.flush()
                if status != 0:
                    exit_val = status
                    killall_and_exit()
        process_list[:] = active_process_list
        active_process_list[:] = []
        sys.stdout.flush()
        time.sleep(.2)
   
def signal_handler(signum, frame):
    global exit_val
    #print("signal", signum, frame)
    exit_val = signum
    killall_and_exit()

def killall_and_exit():
    for proc in process_list:
        status = proc.poll()
        if status is None: # None means it's still alive
            #sys.stdout.write("killall_and_exit: "+str(proc.pid) + " gets killed\n")
            #sys.stdout.flush()
            if getattr(os, "killpg", None):
                os.killpg(proc.pid, signal.SIGTERM) # Unix
            else:
                proc.kill() # Windows
    sys.exit(exit_val)
    
def install_signal_handlers():
    for sig in (signal.SIGABRT, signal.SIGFPE, signal.SIGILL, signal.SIGINT, signal.SIGSEGV, signal.SIGTERM):
        signal.signal(sig, signal_handler)
