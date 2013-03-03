import os

import instlInstanceBase
import configVar

class InstlInstance_mac(instlInstanceBase.InstlInstanceBase):
    def __init__(self):
        super(InstlInstance_mac, self).__init__()
        self.var_replacement_pattern = "${\g<var_name>}"

    def get_install_instructions_prefix(self):
        return ("#!/bin/sh", "SAVE_DIR=`pwd`")

    def get_install_instructions_postfix(self):
        return (self.change_directory_cmd("$(SAVE_DIR)"), "exit 0")

    def make_directory_cmd(self, directory):
        return " ".join(("mkdir", "-p", '"'+directory+'"'))

    def change_directory_cmd(self, directory):
        return " ".join(("cd", '"'+directory+'"'))

    def get_svn_folder_cleanup_instructions(self):
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'
