#!/usr/bin/env python2.7
from __future__ import print_function

import os

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )

class CopyToolMacRsync(CopyToolBase):
    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=None):
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        if link_dest is None:
            sync_command = "rsync -l -r -E --exclude=\'.svn/\' \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{relative_link_dest}\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())

        return sync_command

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=None):
        assert not src_file.endswith("/")
        if link_dest is None:
            sync_command = "rsync -l -r -E --exclude=\'.svn/\' \"{src_file}\" \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{relative_link_dest}\" \"{src_file}\" \"{trg_dir}\"".format(**locals())
        return sync_command

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None):
        if not src_dir.endswith("/"):
            src_dir += "/"
        if link_dest is None:
            sync_command = "rsync -l -r -E --exclude=\'.svn/\' \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -r -E --exclude=\'.svn/\' --link-dest=\"{relative_link_dest}\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return sync_command

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None):
        if not src_dir.endswith("/"):
            src_dir += "/"
        # in order for * to correctly expand, it must be outside the quotes, e.g. to copy all files in folder a: A=a ; "${A}"/* and not "${A}/*"
        if link_dest is None:
            sync_command = "rsync -l -E -d --exclude=\'.svn/\' \"{src_dir}\"/* \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -E -d --exclude=\'.svn/\' --link-dest=\"{relative_link_dest}..\" \"{src_dir}\"/* \"{trg_dir}\"".format(**locals())

        return sync_command

class PlatformSpecificHelperMac(PlatformSpecificHelperBase):
    def __init__(self):
        super(PlatformSpecificHelperMac, self).__init__()
        self.var_replacement_pattern = "${\g<var_name>}"
        self.dl_tool = DownloadTool_mac_curl()

    def get_install_instructions_prefix(self):
        prefix_list = []
        prefix_list.append("#!/bin/sh")
        prefix_list.append(self.save_dir("TOP_SAVE_DIR"))
        return prefix_list

    def get_install_instructions_postfix(self):
        postfix_list = []
        postfix_list.append(self.restore_dir("TOP_SAVE_DIR"))
        postfix_list.append("exit 0")
        return postfix_list

    def mkdir(self, directory):
        mk_command = " ".join( ("mkdir", "-p", quoteme(directory) ) )
        return mk_command

    def cd(self, directory):
        cd_command = " ".join( ("cd", quoteme(directory) ) )
        return cd_command

    def save_dir(self, var_name):
        save_dir_command = var_name+"=`pwd`"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$("+var_name+")")
        return restore_dir_command

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
            self.copy_tool = CopyToolMacRsync()
        else:
            raise ValueError(tool, "is not a valid copy tool for Mac OS")

    def copy_file_to_file(self, src_file, trg_file):
        sync_command = "cp -f \"{src_file}\" \"{trg_file}\"".format(**locals())
        return sync_command

    def resolve_readlink_files(self, in_dir="."):
        """ create instructions to turn .readlink files into symlinks.
            Main problem was with files that had space in their name, just
            adding \" was no enough, had to separate each step to a single line
            which solved the spaces problem. Also find returns an empty string
            even when there were no files found, and therefor the check
        """
        resolve_commands = (
            "for readlink_file in \"$(find . -name '*.readlink')\" ; do",
            "   if [ \"$readlink_file\" ] ; then",             # avoid empty results
            "       file_contents=`cat \"$readlink_file\"`",    # avoid spaces in path
            "       link_file=\"${readlink_file%.*}\"",         # avoid spaces in path
            "       ln -s \"$file_contents\" \"$link_file\"",
            "       rm \"$readlink_file\"",
            "   fi",
            "done"
            )
        return resolve_commands

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
