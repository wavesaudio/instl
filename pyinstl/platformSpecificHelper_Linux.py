#!/usr/bin/env python3


import datetime

import utils
from .platformSpecificHelper_Base import PlatformSpecificHelperBase
from .platformSpecificHelper_Base import CopyToolRsync
from .platformSpecificHelper_Base import DownloadToolBase


class CopyToolLinuxRsync(CopyToolRsync):
    def __init__(self, platform_helper) -> None:
        super().__init__(platform_helper)


class PlatformSpecificHelperLinux(PlatformSpecificHelperBase):
    def __init__(self, instlObj) -> None:
        super().__init__(instlObj)
        self.var_replacement_pattern = "${\g<var_name>}"
        self.dl_tool = DownloadTool_linux_curl(self)


    def init_platform_tools(self):
        self.dl_tool = DownloadTool_linux_curl(self)

    def get_install_instructions_prefix(self, exit_on_errors=True):
        retVal = (
            "#!/usr/bin/env bash",
            self.remark(self.instlObj.get_version_str()),
            self.remark(datetime.datetime.today().isoformat()),
            "set -e" if exit_on_errors else "",
            self.save_dir("TOP_SAVE_DIR"))
        return retVal

    def get_install_instructions_postfix(self):
        return self.restore_dir("TOP_SAVE_DIR"), "exit 0"

    def mkdir(self, directory):
        quoted_dir = utils.quoteme_double(directory)
        mk_command = " ".join(("mkdir", "-p", quoted_dir))
        return mk_command

    def cd(self, directory):
        quoted_dir = utils.quoteme_double(directory)
        cd_command = " ".join(("cd", quoted_dir))
        return cd_command

    def pushd(self, directory):
        quoted_dir = utils.quoteme_double(directory)
        pushd_command = " ".join(("pushd", quoted_dir, ">", "/dev/null"))
        return pushd_command

    def popd(self):
        pop_command = " ".join(("popd", ">", "/dev/null"))
        return pop_command

    def save_dir(self, var_name):
        save_dir_command = var_name + "=`pwd`"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$(" + var_name + ")")
        return restore_dir_command

    def rmdir(self, a_dir, recursive=False, check_exist=False):
        quoted_a_dir = utils.quote_path_properly(a_dir)
        if recursive:
            rmdir_command = " ".join(("rm", "-fr", quoted_a_dir))
        else:
            rmdir_command = " ".join(("rmdir", quoted_a_dir))
        return rmdir_command

    def rmfile(self, a_file, quote_char='"', check_exist=False):
        quoted_a_file = utils.quote_path_properly(a_file)
        rmfile_command = " ".join(("rm", "-f", quoted_a_file))
        return rmfile_command

    def rm_file_or_dir(self, file_or_dir):
        # on linux -fr will remove a file or a directory without complaint.
        rm_command = self.rmdir(file_or_dir, recursive=True)
        return rm_command

    def get_svn_folder_cleanup_instructions(self):
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'

    def var_assign(self, identifier, value):
        retVal = identifier + '="' + value + '"'
        return retVal

    def echo(self, message):
        echo_command = " ".join(('echo', utils.quoteme_double(message)))
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('#', remark))
        return remark_command

    def use_copy_tool(self, tool):
        if tool == "rsync":
            self.copy_tool = CopyToolLinuxRsync(self)
        else:
            raise ValueError(f"{tool} is not a valid copy tool for Linux")

    def copy_file_to_file(self, src_file, trg_file, hard_link=False, check_exist=False):
        if hard_link:
            copy_command = f"ln -f \"{src_file}\" \"{trg_file}\""
        else:
            copy_command = f"cp -f \"{src_file}\" \"{trg_file}\""
        if check_exist:
            copy_command += " || true"
        return copy_command

    def check_checksum_for_file(self, a_file, checksum):
        raise NotImplementedError

    def tar(self, to_tar_name):
        raise NotImplementedError

    def wait_for_child_processes(self):
        return ("wait",)

    def chmod(self, new_mode, file_path):
        chmod_command = " ".join(("chmod", new_mode, utils.quoteme_double(file_path)))
        return chmod_command

    def make_executable(self, file_path):
        return self.chmod("a+x", file_path)

    def unlock(self, file_path, recursive=False, ignore_errors=True):
        """ Remove the system's read-only flag, this is different from permissions.
            Not relevant for Linux.
        """
        return ""

    def touch(self, file_path):
        touch_command = " ".join(("touch", utils.quoteme_double(file_path) ))
        return touch_command

    def append_file_to_file(self, source_file, target_file):
        append_command = " ".join(("cat", utils.quoteme_double(source_file), ">>", utils.quoteme_double(target_file)))
        return append_command


