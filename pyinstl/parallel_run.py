#!/usr/bin/env python2.7
from __future__ import print_function

import subprocess
import time
import sys
import signal
import shlex
from collections import deque

exit_val = 0
proc_que = deque()

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
    retVal = 0
    max_time = 6
    start_time = time.time()
    for command in commands:
        try:
            proc = subprocess.Popen(command, executable=command[0], shell=False)#, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            #print("Started", command, proc.pid)
            #sys.stdout.flush()
            proc_que.append(proc)
        except Exception as es:
            print("failed to start", command, es.strerror, file=sys.stderr)
            sys.stdout.flush()
            exit_val = es.strerror
            raise
            
    while proc_que:
        proc = proc_que.popleft()
        status = proc.poll()
        if status is None: # None means it's still alive
            #print(proc.pid, "still alive")
            proc_que.append(proc)
            #continue
        else:
            #print(proc.pid, "just died", status)
            if status != 0:
                exit_val = status
                killall_and_exit()
        sys.stdout.flush()
        time.sleep(.5)
   
def signal_handler(signum, frame):
    global exit_val
    #print("signal", signum, frame)
    exit_val = signum
    killall_and_exit()

def killall_and_exit():
    for proc in proc_que:
        proc.kill()
    sys.exit(exit_val)
    
def install_signal_handlers():
    for sig in (signal.SIGABRT, signal.SIGFPE, signal.SIGILL, signal.SIGINT, signal.SIGSEGV, signal.SIGTERM):
        signal.signal(sig, signal_handler)
