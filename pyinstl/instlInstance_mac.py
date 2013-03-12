import os

import instlInstanceBase
import configVar

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )

class InstlInstance_mac(instlInstanceBase.InstlInstanceBase):
    def __init__(self):
        super(InstlInstance_mac, self).__init__()
        self.var_replacement_pattern = "${\g<var_name>}"

    def get_install_instructions_prefix(self):
        return ("#!/bin/sh", "SAVE_DIR=`pwd`")

    def get_install_instructions_postfix(self):
        retVal = list()
        retVal.extend( self.change_directory_cmd("$(SAVE_DIR)") )
        retVal.append("exit 0")
        return retVal

    def make_directory_cmd(self, directory):
        mk_command = " ".join( ("mkdir", "-p", quoteme(directory) ) )
        return (mk_command, )

    def change_directory_cmd(self, directory):
        cd_command = " ".join( ("cd", quoteme(directory) ) )
        return (cd_command, )

    def get_svn_folder_cleanup_instructions(self):
        print("Barbara")
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'

    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        sync_command = " ".join( ("rsync", "-r", "-E", "--exclude=\'.svn/\'", "--link-dest="+quoteme(src_dir+"/.."), quoteme(src_dir), quoteme(trg_dir) ) )
        return (sync_command, )

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        assert not src_file.endswith("/")
        sync_command = " ".join( ("rsync", "-r", "-E", "--exclude=\'.svn/\'", "--link-dest="+quoteme(src_file), quoteme(src_file), quoteme(trg_dir)) )
        return (sync_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        sync_command = " ".join( ("rsync", "-r", "-E", "--exclude=\'.svn/\'", "--link-dest="+quoteme(src_dir+".."), quoteme(src_dir), quoteme(trg_dir)) )
        return (sync_command, )

    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        sync_command = " ".join( ("rsync", "-E", "--exclude=\'.svn/\'", "--link-dest="+quoteme(src_dir+".."), quoteme(src_dir+"*"), quoteme(trg_dir)) )
        return (sync_command, )
    
    def create_var_assign(self, identifier, value):
        return identifier+'="'+value+'"'

    def create_echo_command(self, message):
        echo_command = " ".join(('echo', quoteme(message)))
        return echo_command

