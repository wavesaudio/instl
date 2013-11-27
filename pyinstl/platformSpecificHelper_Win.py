#!/usr/bin/env python2.7
from __future__ import print_function

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase

def quoteme(to_qoute):
    return "".join( ('"', to_qoute, '"') )

class CopyTool_win_robocopy(CopyToolBase):
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E /XD .svn /R:3 /W:3".format(**locals())
        retVal.append(copy_command)
        return retVal

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        src_dir, src_file = os.path.split(src_file)
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" \"{src_file}\" /R:3 /W:3".format(**locals())
        return (copy_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E /XD .svn /R:3 /W:3".format(**locals())
        return (copy_command, )
    
    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /LEV:1 /XD .svn /R:3 /W:3".format(**locals())
        return (copy_command, )

    def create_copy_file_to_file_command(self, src_file, trg_file):
        sync_command = "copy \"{src_file}\" \"{trg_file}\"".format(**locals())
        return (sync_command, )

class CopyTool_win_xcopy(CopyToolBase):
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        mkdir_command  = "mkdir \"{trg_dir}\"".format(**locals())
        retVal.append(mkdir_command)
        retVal.extend(self.create_copy_dir_contents_to_dir_command(src_dir, trg_dir))
        return retVal

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        #src_dir, src_file = os.path.split(src_file)
        copy_command = "xcopy  /R /Y \"{src_file}\" \"{trg_dir}\"".format(**locals())
        copy_command.replace("\\", "/")
        return (copy_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        copy_command = "xcopy /E /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (copy_command, )
    
    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        copy_command = "xcopy  /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (copy_command, )

class PlatformSpecificHelperWin(PlatformSpecificHelperBase):
    def __init__(self):
        super(PlatformSpecificHelperWin, self).__init__()
        self.var_replacement_pattern = "%\g<var_name>%"
        self.dl_tool = DownloadTool_win_wget()

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

    def use_copy_tool(self, tool):
        if tool == "robocopy":
            self.copy_tool = CopyTool_win_robocopy()
        elif tool == "xcopy":
            self.copy_tool = CopyTool_win_xcopy()
        else:
            raise ValueError(tool, "is not a valid copy tool for", target_os)

    def create_copy_file_to_file_command(self, src_file, trg_file):
        sync_command = "copy \"{src_file}\" \"{trg_file}\"".format(**locals())
        return (sync_command, )


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