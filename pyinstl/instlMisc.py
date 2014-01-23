#!/usr/bin/env python2.7

from __future__ import print_function

from pyinstl.log_utils import func_log_wrapper
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
        if the_command in self.cvl.get_list("__ALLOWED_COMMANDS__"):
            do_command_func = getattr(self, "do_"+the_command)
            do_command_func()
        else:
            raise ValueError(the_command+" is not one of the allowed admin commands: "+" ".join(self.cvl.get_list("__ALLOWED_COMMANDS__")))

    def do_version(self):
        print(self.get_version_str())

    def do_help(self):
        import pyinstl.helpHelper
        help_folder_path = os.path.join(self.cvl.resolve_string("$(__INSTL_DATA_FOLDER__)"), "help")
        pyinstl.helpHelper.do_help(self.cvl.get_str("__HELP_SUBJECT__"), help_folder_path)
