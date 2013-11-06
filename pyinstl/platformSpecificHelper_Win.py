#!/usr/bin/env python2.7
from __future__ import print_function

from platformSpecificHelper_Base import PlatformSpecificHelperBase

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )


class PlatformSpecificHelperWin(PlatformSpecificHelperBase):
    def __init__(self):
        super(PlatformSpecificHelperWin, self).__init__()
        self.var_replacement_pattern = "%\g<var_name>%"

    def get_install_instructions_prefix(self):
        return ("SET SAVE_DIR=%CD%", )

    def get_install_instructions_postfix(self):
        return ("cd /d %SAVE_DIR%", )

    def make_directory_cmd(self, directory):
        mk_command = " ".join( ("mkdir", '"'+directory+'"'))
        return (mk_command, )
 
    def change_directory_cmd(self, directory):
        cd_command = " ".join( ("cd", '/d', '"'+directory+'"') )
        return (cd_command, )

    def get_svn_folder_cleanup_instructions(self):
        return ()
        
    def create_var_assign(self, identifier, value):
        return "SET "+identifier+'='+value

    def create_echo_command(self, message):
        echo_command = " ".join(('echo', quoteme(message)))
        return echo_command

    def create_remark_command(self, remark):
        remark_command = " ".join(('REM', quoteme(remark)))
        return remark_command
