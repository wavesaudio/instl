#!/usr/bin/env python2.7

from __future__ import print_function

import shlex

from pyinstl.utils import *
from instlInstanceBase import InstlInstanceBase
from pyinstl import svnTree

class InstlMisc(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlMisc, self).__init__(initial_vars)
        self.cvl.set_var("__ALLOWED_COMMANDS__").extend( ('version', 'help') )
        self.svnTree = svnTree.SVNTree()

    def do_command(self):
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        fixed_command = the_command.replace('-', '_')
        do_command_func = getattr(self, "do_"+fixed_command)
        do_command_func()

    def do_version(self):
        print(self.get_version_str())

    def do_help(self):
        import pyinstl.helpHelper
        help_folder_path = os.path.join(self.cvl.resolve_string("$(__INSTL_DATA_FOLDER__)"), "help")
        pyinstl.helpHelper.do_help(self.cvl.get_str("__HELP_SUBJECT__"), help_folder_path)

    def do_parallel_run(self):
        processes_list_file = self.cvl.get_str("__MAIN_INPUT_FILE__")
        commands = list()
        with open(processes_list_file, "r") as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        from parallel_run import run_processes_in_parallel
        run_processes_in_parallel(commands)
