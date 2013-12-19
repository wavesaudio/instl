#!/usr/bin/env python2.7
from __future__ import print_function

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )

class CopyTool_win_robocopy(CopyToolBase):
    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=None):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E /XD .svn /R:3 /W:3".format(**locals())
        retVal.append(copy_command)
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=None):
        src_dir, src_file = os.path.split(src_file)
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" \"{src_file}\" /R:3 /W:3".format(**locals())
        return copy_command

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None):
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E /XD .svn /R:3 /W:3".format(**locals())
        return copy_command
    
    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None):
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /LEV:1 /XD .svn /R:3 /W:3".format(**locals())
        return copy_command

    def copy_file_to_file(self, src_file, trg_file, link_dest=None):
        sync_command = "copy \"{src_file}\" \"{trg_file}\"".format(**locals())
        return sync_command

class CopyTool_win_xcopy(CopyToolBase):
    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=None):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        mkdir_command  = "mkdir \"{trg_dir}\"".format(**locals())
        retVal.append(mkdir_command)
        retVal.extend(self.copy_dir_contents_to_dir(src_dir, trg_dir))
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=None):
        #src_dir, src_file = os.path.split(src_file)
        copy_command = "xcopy  /R /Y \"{src_file}\" \"{trg_dir}\"".format(**locals())
        copy_command.replace("\\", "/")
        return copy_command

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None):
        copy_command = "xcopy /E /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return copy_command
    
    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None):
        copy_command = "xcopy  /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return copy_command

class PlatformSpecificHelperWin(PlatformSpecificHelperBase):
    def __init__(self):
        super(PlatformSpecificHelperWin, self).__init__()
        self.var_replacement_pattern = "%\g<var_name>%"
        self.dl_tool = DownloadTool_win_wget()

    def get_install_instructions_prefix(self):
        prefix_list = []
        prefix_list.append(self.save_dir("TOP_SAVE_DIR"))
        prefix_list.append("\n")
        return prefix_list

    def get_install_instructions_postfix(self):
        postfix_list = []
        postfix_list.append("\n")
        postfix_list.append(self.restore_dir("TOP_SAVE_DIR"))
        return postfix_list

    def mkdir(self, directory):
        mk_command = " ".join( ("mkdir", '"'+directory+'"'))
        return mk_command
 
    def cd(self, directory):
        cd_command = " ".join( ("cd", '/d', '"'+directory+'"') )
        return cd_command

    def save_dir(self, var_name):
        save_dir_command = "SET "+ var_name +" %CD%"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$("+var_name+")")
        return restore_dir_command

    def get_svn_folder_cleanup_instructions(self):
        return ()
        
    def var_assign(self, identifier, value):
        return "SET "+identifier+'='+value

    def echo(self, message):
        echo_command = " ".join(('echo', quoteme(message)))
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('REM', quoteme(remark)))
        return remark_command

    def use_copy_tool(self, tool):
        if tool == "robocopy":
            self.copy_tool = CopyTool_win_robocopy()
        elif tool == "xcopy":
            self.copy_tool = CopyTool_win_xcopy()
        else:
            raise ValueError(tool, "is not a valid copy tool for", target_os)

    def copy_file_to_file(self, src_file, trg_file):
        sync_command = "copy \"{src_file}\" \"{trg_file}\"".format(**locals())
        return (sync_command, )

    def resolve_readlink_files(self, in_dir="."):
        return ()

class DownloadTool_win_wget(DownloadToolBase):

    def create_download_file_to_file_command(self, src_url, trg_file):
        download_command_parts = list()
        download_command_parts.append("wget")
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("60")
        download_command_parts.append("--read-timeout")
        download_command_parts.append("900")
        download_command_parts.append("-O")
        download_command_parts.append(quoteme(trg_file))
        download_command_parts.append(quoteme(src_url))
        return (" ".join(download_command_parts), )
