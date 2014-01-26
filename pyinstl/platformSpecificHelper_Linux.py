#!/usr/bin/env python2.7
from __future__ import print_function

import os
import datetime

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolRsync
from platformSpecificHelper_Base import DownloadToolBase
from platformSpecificHelper_Base import quoteme_single
from platformSpecificHelper_Base import quoteme_double

class CopyToolLinuxRsync(CopyToolRsync):
    def __init__(self, platformHelper):
        super(CopyToolLinuxRsync, self).__init__(platformHelper)

class PlatformSpecificHelperLinux(PlatformSpecificHelperBase):
    def __init__(self, instlInstance):
        super(PlatformSpecificHelperLinux, self).__init__(instlInstance)
        self.var_replacement_pattern = "${\g<var_name>}"
        self.dl_tool = DownloadTool_linux_curl(self)

    def get_install_instructions_prefix(self):
        retVal =  (
            "#!/usr/bin/env bash",
            self.remark(self.instlInstance.get_version_str()),
            self.remark(datetime.datetime.today().isoformat()),
            "set -e",
            self.save_dir("TOP_SAVE_DIR"))
        return retVal

    def get_install_instructions_postfix(self):
        return (self.restore_dir("TOP_SAVE_DIR"), "exit 0")

    def mkdir(self, directory):
        mk_command = " ".join( ("mkdir", "-p", quoteme_double(directory) ) )
        return mk_command

    def cd(self, directory):
        cd_command = " ".join( ("cd", quoteme_double(directory) ) )
        return cd_command

    def save_dir(self, var_name):
        save_dir_command = var_name+"=`pwd`"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$("+var_name+")")
        return restore_dir_command

    def rmdir(self, directory, recursive=False):
        rmdir_command = ""
        if recursive:
            rmdir_command = " ".join( ("rm", "-fr", quoteme_double(directory) ) )
        else:
            rmdir_command = " ".join( ("rmdir", quoteme_double(directory) ) )
        return rmdir_command

    def rmfile(self, file):
        rmfile_command = " ".join( ("rm", "-f", quoteme_double(file) ) )
        return rmfile_command

    def get_svn_folder_cleanup_instructions(self):
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'

    def var_assign(self, identifier, value):
        return identifier+'="'+value+'"'

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

    def copy_file_to_file(self, src_file, trg_file):
        sync_command = "cp -f \"{src_file}\" \"{trg_file}\"".format(**locals())
        return sync_command

    def check_checksum(self, file, checksum):
        raise NotImplementedError

    def tar(self, to_tar_name):
        raise NotImplementedError

    def unwtar(self, filepath):
        raise NotImplementedError

class DownloadTool_linux_curl(DownloadToolBase):
    def __init__(self, platformHelper):
        super(DownloadTool_linux_curl, self).__init__(platformHelper)

    def download_url_to_file(self, src_url, trg_file):
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--insecure")
        download_command_parts.append("--fail")
        download_command_parts.append("--raw")
        download_command_parts.append("--silent")
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("60")
        download_command_parts.append("--max-time")
        download_command_parts.append("900")
        #download_command_parts.append(" --write-out")
        #download_command_parts.append(quoteme_double("%{http_code}"))
        download_command_parts.append("-o")
        download_command_parts.append(quoteme_double(trg_file))
        download_command_parts.append(quoteme_double(src_url))
        return " ".join(download_command_parts)

    def create_config_file(self):
        pass
    def download_from_config_file(self):
        pass
