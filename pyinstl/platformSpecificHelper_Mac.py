#!/usr/bin/env python2.7
from __future__ import print_function

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )

class CopyTool_mac_rsync(CopyToolBase):
    def copy_dir_to_dir(self, src_dir, trg_dir):
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        #link_dest = "".join( ("'", src_dir, '/..', "'") )
        #src_dir = "".join( ("'", src_dir, "'") )
        #trg_dir = "".join( ("'", trg_dir, "'") )
        link_dest = src_dir+'/..'
        sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{link_dest}\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return sync_command

    def copy_file_to_dir(self, src_file, trg_dir):
        assert not src_file.endswith("/")
        sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{src_file}\" \"{src_file}\" \"{trg_dir}\"".format(**locals())
        return sync_command

    def copy_dir_contents_to_dir(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{src_dir}..\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return sync_command

    def copy_dir_files_to_dir(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        # in order for * to correctly expand, it must be outside the quotes, e.g. to copy all files in folder a: A=a ; "${A}"/* and not "${A}/*" 
        sync_command = "rsync -l -E -d --exclude=\'.svn/\' --link-dest=\"{src_dir}..\" \"{src_dir}\"/* \"{trg_dir}\"".format(**locals())
        return sync_command

class PlatformSpecificHelperMac(PlatformSpecificHelperBase):
    def __init__(self):
        super(PlatformSpecificHelperMac, self).__init__()
        self.var_replacement_pattern = "${\g<var_name>}"
        self.dl_tool = DownloadTool_mac_curl()

    def get_install_instructions_prefix(self):
        return ("#!/bin/sh", "SAVE_DIR=`pwd`")

    def get_install_instructions_postfix(self):
        retVal = (self.cd("$(SAVE_DIR)"), "exit 0")
        return retVal

    def mkdir(self, directory):
        mk_command = " ".join( ("mkdir", "-p", quoteme(directory) ) )
        return mk_command

    def cd(self, directory):
        cd_command = " ".join( ("cd", quoteme(directory) ) )
        return cd_command

    def get_svn_folder_cleanup_instructions(self):
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'
    
    def var_assign(self, identifier, value):
        return identifier+'="'+value+'"'

    def echo(self, message):
        echo_command = " ".join(('echo', quoteme(message)))
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('#', quoteme(remark)))
        return remark_command

    def use_copy_tool(self, tool):
        if tool == "rsync":
            self.copy_tool = CopyTool_mac_rsync()
        else:
            raise ValueError(tool, "is not a valid copy tool for Mac OS")

    def copy_file_to_file(self, src_file, trg_file):
        sync_command = "cp -f \"{src_file}\" \"{trg_file}\"".format(**locals())
        return sync_command

class DownloadTool_mac_curl(DownloadToolBase):

    def create_download_file_to_file_command(self, src_url, trg_file):
        download_command_parts = list()
        download_command_parts.append("curl")
        download_command_parts.append("--insecure")
        download_command_parts.append("--fail")
        download_command_parts.append("--raw")
        download_command_parts.append("--silent")
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("60")
        download_command_parts.append("--max-time")
        download_command_parts.append("900")
        #download_command_parts.append(" --write-out")
        #download_command_parts.append(quoteme("%{http_code}"))
        download_command_parts.append("-o")
        download_command_parts.append(quoteme(trg_file))
        download_command_parts.append(quoteme(src_url))
        return (" ".join(download_command_parts), )
