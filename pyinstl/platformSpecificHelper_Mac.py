#!/usr/bin/env python2.7
from __future__ import print_function

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )

class CopyTool_mac_rsync(CopyToolBase):
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        #link_dest = "".join( ("'", src_dir, '/..', "'") )
        #src_dir = "".join( ("'", src_dir, "'") )
        #trg_dir = "".join( ("'", trg_dir, "'") )
        link_dest = src_dir+'/..'
        sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{link_dest}\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (sync_command, )

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        assert not src_file.endswith("/")
        sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{src_file}\" \"{src_file}\" \"{trg_dir}\"".format(**locals())
        return (sync_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{src_dir}..\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (sync_command, )

    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        # in order for * to correctly expand, it must be outside the quotes, e.g. to copy all files in folder a: A=a ; "${A}"/* and not "${A}/*" 
        sync_command = "rsync -l -E -d --exclude=\'.svn/\' --link-dest=\"{src_dir}..\" \"{src_dir}\"/* \"{trg_dir}\"".format(**locals())
        return (sync_command, )

class PlatformSpecificHelperMac(PlatformSpecificHelperBase):
    def __init__(self):
        super(PlatformSpecificHelperMac, self).__init__()
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
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'
    
    def create_var_assign(self, identifier, value):
        return identifier+'="'+value+'"'

    def create_echo_command(self, message):
        echo_command = " ".join(('echo', quoteme(message)))
        return echo_command

    def create_remark_command(self, remark):
        remark_command = " ".join(('#', quoteme(remark)))
        return remark_command

    def use_copy_tool(self, tool):
        if tool == "rsync":
            self.copy_tool = CopyTool_mac_rsync()
        else:
            raise ValueError(tool, "is not a valid copy tool for Mac OS")
