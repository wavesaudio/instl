#!/usr/local/bin/python2.7
from __future__ import print_function

import os
from subprocess import Popen, PIPE
import threading

def create_mac_alias(args):
    original = os.path.realpath(args[0])
    if os.path.exists(original):
        target = os.path.realpath(args[1])
        if os.path.isfile(target):
            os.remove(target)
        target_folder, target_name = os.path.split(target)
        applescript_text = """
        set dest_folder to POSIX file "{original}" as alias
        set alias_folder to POSIX file "{target_folder}" as alias
        set alias_name to "{target_name}"

        tell application "Finder"
            make new alias file at alias_folder to dest_folder
            set name of result to alias_name
        end tell
        """.format(**vars())
        aso = AppleScript()
        ret = aso.run_applescript(applescript_text)
    else:
        print(args[0], "is not an existing file or folder")

def create_win_shortcut(args):
    print ("create_win_shortcut, original:", args[0], "target", args[1])

def fix_mac_icon(bundle_path):
    pass

name_to_action = {'alias': create_mac_alias,
                'shortcut': create_win_shortcut,
                'fix_mac_icon': fix_mac_icon}

def do_something(args):
    if args[0] in name_to_action:
        name_to_action[args[0]](args[1])
    else:
        raise KeyError(args[0]+" unknewn action")

class AppleScript(object):
    """A class for AppleScript procedures"""

    def __init__(self, timeout=60):
        super(AppleScript, self).__init__()
        self.timeout = timeout
        self.err = ''

    def run_applescript(self, script, *args):
        '''Runs an applescript code (a single command or a function from run_appfunc)
    Receives a command (or several lines of command) and returns whatever the applescript command returns.
    Raises an RuntimeError on failure.
    Example: run_applescript('tell application \\"Safari\\" to get the URL of every tab of every window')'''

        p = Popen(['arch', '-i386', 'osascript', '-e', script] +
            [unicode(arg).encode('utf8') for arg in args],
            stdout=PIPE, stderr=PIPE)
        t = threading.Timer(self.timeout, self.f_timeout, [p])
        t.start()
        err = p.wait()
        t.cancel()
        if err:
            self.err = p.stderr.read()[:-1].decode('utf8')
            raise RuntimeError(err, p.stderr.read()[:-1].decode('utf8'))
        return p.stdout.read()[:-1].decode('utf8')

    def f_timeout(self, p):
        '''f_timeout - Timeout function for running applescript process'''
        if p.poll() == None:
            try:
                p.kill()
                print ('Error: process taking too long to complete - terminating.')
            except:
                pass
