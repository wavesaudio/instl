#!/usr/bin/env python2.7
from __future__ import print_function

import datetime
from pyinstl.utils import *

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolRsync
from platformSpecificHelper_Base import DownloadToolBase

class CopyToolLinuxRsync(CopyToolRsync):
    def __init__(self, platform_helper):
        super(CopyToolLinuxRsync, self).__init__(platform_helper)

class PlatformSpecificHelperLinux(PlatformSpecificHelperBase):
    def __init__(self, instlObj):
        super(PlatformSpecificHelperLinux, self).__init__(instlObj)
        self.var_replacement_pattern = "${\g<var_name>}"
        self.dl_tool = DownloadTool_linux_curl(self)


    def init_download_tool(self):
        self.dl_tool = DownloadTool_linux_curl(self)

    def get_install_instructions_prefix(self):
        retVal =  (
            "#!/usr/bin/env bash",
            self.remark(self.instlObj.get_version_str()),
            self.remark(datetime.datetime.today().isoformat()),
            "set -e",
            self.save_dir("TOP_SAVE_DIR"))
        return retVal

    def get_install_instructions_postfix(self):
        return self.restore_dir("TOP_SAVE_DIR"), "exit 0"

    def mkdir(self, directory):
        mk_command = " ".join( ("mkdir", "-p", quoteme_double(directory) ) )
        return mk_command

    def cd(self, directory):
        cd_command = " ".join( ("cd", quoteme_double(directory) ) )
        return cd_command

    def pushd(self, directory):
        pushd_command = " ".join( ("pushd", quoteme_double(directory), ">", "/dev/null") )
        return pushd_command

    def popd(self):
        pop_command = " ".join( ("popd", ">", "/dev/null") )
        return pop_command

    def save_dir(self, var_name):
        save_dir_command = var_name+"=`pwd`"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$("+var_name+")")
        return restore_dir_command

    def rmdir(self, directory, recursive=False):
        if recursive:
            rmdir_command = " ".join( ("rm", "-fr", quoteme_double(directory) ) )
        else:
            rmdir_command = " ".join( ("rmdir", quoteme_double(directory) ) )
        return rmdir_command

    def rmfile(self, a_file):
        rmfile_command = " ".join( ("rm", "-f", quoteme_double(a_file) ) )
        return rmfile_command

    def get_svn_folder_cleanup_instructions(self):
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'

    def var_assign(self, identifier, value, comment=None):
        retVal = identifier+'="'+value+'"'
        if comment is not None:
            retVal += ' '+self.remark(str(comment))
        return retVal

    def echo(self, message):
        echo_command = " ".join(('echo', quoteme_double(message)))
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('#', remark))
        return remark_command

    def use_copy_tool(self, tool):
        if tool == "rsync":
            self.copy_tool = CopyToolLinuxRsync(self)
        else:
            raise ValueError(tool, "is not a valid copy tool for Linux")

    def copy_file_to_file(self, src_file, trg_file, hard_link=False):
        if hard_link:
            copy_command = "ln -f \"{src_file}\" \"{trg_file}\"".format(**locals())
        else:
            copy_command = "cp -f \"{src_file}\" \"{trg_file}\"".format(**locals())
        return copy_command

    def check_checksum_for_file(self, a_file, checksum):
        raise NotImplementedError

    def tar(self, to_tar_name):
        raise NotImplementedError

    def unwtar_file(self, filepath):
        raise NotImplementedError

    def wait_for_child_processes(self):
        return ("wait",)

    def chmod(self, new_mode, filepath):
        chmod_command = " ".join( ("chmod", new_mode, quoteme_double(filepath)) )
        return chmod_command

    def make_executable(self, filepath):
        return self.chmod("a+x", filepath)

    def unlock(self, filepath, recursive=False):
        """ Remove the system's read-only flag, this is different from permissions.
            Not relevant for Linux.
        """
        return ""

    def touch(self, filepath):
        touch_command = " ".join( ("touch", quoteme_double(filepath) ) )
        return touch_command

    def append_file_to_file(self, source_file, target_file):
        append_command = " ".join( ("cat", quoteme_double(source_file), ">>", quoteme_double(target_file)) )
        return append_command

class DownloadTool_linux_curl(DownloadToolBase):
    def __init__(self, platform_helper):
        super(DownloadTool_linux_curl, self).__init__(platform_helper)

    def download_url_to_file(self, src_url, trg_file):
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--insecure")
        download_command_parts.append("--fail")
        download_command_parts.append("--raw")
        download_command_parts.append("--silent")
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("3")
        download_command_parts.append("--max-time")
        download_command_parts.append("60")
        #download_command_parts.append(" --write-out")
        #download_command_parts.append(quoteme_double("%{http_code}"))
        download_command_parts.append("-o")
        download_command_parts.append(quoteme_double(trg_file))
        download_command_parts.append(quoteme_double(src_url))
        return " ".join(download_command_parts)

    def download_from_config_files(self, parallel_run_config_file_path, config_files):
        pass
