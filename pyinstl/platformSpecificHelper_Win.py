#!/usr/bin/env python2.7
from __future__ import print_function

import os
import urllib
import datetime

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase
from platformSpecificHelper_Base import quoteme_single
from platformSpecificHelper_Base import quoteme_double

class CopyTool_win_robocopy(CopyToolBase):
    def __init__(self, platformHelper):
        super(CopyTool_win_robocopy, self).__init__(platformHelper)
        self.robocopy_error_threshold = 4 # see ss64.com/nt/robocopy-exit.html

    def create_ignore_spec(self, ignore):
        retVal = ""
        if not isinstance(ignore, basestring):
            ignore = " ".join(map(quoteme_double, ignore))
        retVal = "/XF {ignore} /XD {ignore}".format(**locals())
        return retVal

    def create_log_spec(self):
        """ To do: dedicate a variable to copy logging (COPY_LOG_FILE ???)
        """
        retVal = ""
        #log_file = self.platformHelper.instlObj.cvl.get_str("LOG_FILE")
        #retVal = " /LOG:{log_file}".format(**locals())
        return retVal

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=None, ignore=None):
        retVal = list()
        src_dir, src_file = os.path.split(src_file)
        log_file_spec = self.create_log_spec()
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" \"{src_file}\" /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /LEV:1 {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_file(self, src_file, trg_file, link_dest=None, ignore=None):
        retVal = list()
        copy_command = "copy \"{src_file}\" \"{trg_file}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

class CopyTool_win_xcopy(CopyToolBase):
    def __init__(self, platformHelper):
        super(CopyTool_win_xcopy, self).__init__(platformHelper)

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        mkdir_command  = "mkdir \"{trg_dir}\"".format(**locals())
        retVal.append(mkdir_command)
        retVal.extend(self.copy_dir_contents_to_dir(src_dir, trg_dir))
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=None):
        retVal = list()
        #src_dir, src_file = os.path.split(src_file)
        copy_command = "xcopy  /R /Y \"{src_file}\" \"{trg_dir}\"".format(**locals())
        copy_command.replace("\\", "/")
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None):
        retVal = list()
        copy_command = "xcopy /E /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None):
        retVal = list()
        copy_command = "xcopy  /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

class PlatformSpecificHelperWin(PlatformSpecificHelperBase):
    def __init__(self, instlObj):
        super(PlatformSpecificHelperWin, self).__init__(instlObj)
        self.var_replacement_pattern = "%\g<var_name>%"
        self.dl_tool = DownloadTool_win_wget(self)

    def get_install_instructions_prefix(self):
        retVal = (
            "@echo off",
            "setlocal enableextensions enabledelayedexpansion",
            self.remark(self.instlObj.get_version_str()),
            self.remark(datetime.datetime.today().isoformat()),
            self.save_dir("TOP_SAVE_DIR"),
            )
        return retVal

    def get_install_instructions_postfix(self):
        retVal = (
                self.restore_dir("TOP_SAVE_DIR"),
                "endlocal",
                "exit /b 0",
                "",
                ":EXIT_ON_ERROR",
                self.restore_dir("TOP_SAVE_DIR"),
                "set defERRORLEVEL=%ERRORLEVEL%",
                "if %defERRORLEVEL% == 0 (set defERRORLEVEL=1)",
                'echo "Exit on error" 1>&2',
                "endlocal",
                "exit /b %defERRORLEVEL%"
                )
        return retVal

    def exit_if_error(self, error_threshold=1):
        retVal = ("IF", "ERRORLEVEL", str(error_threshold), "(", "echo", '"Error %ERRORLEVEL% at step ' + str(self.num_items_for_progress_report+1)+'"', "1>&2", "&", "GOTO", "EXIT_ON_ERROR", ")")
        return " ".join(retVal)

    def mkdir(self, directory):
        mk_command = " ".join( ("if not exist", '"'+directory+'"', "mkdir", '"'+directory+'"'))
        return mk_command

    def cd(self, directory):
        cd_command = " ".join( ("cd", '/d', '"'+directory+'"') )
        return cd_command

    def save_dir(self, var_name):
        save_dir_command = "SET "+ var_name +"=%CD%"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$("+var_name+")")
        return restore_dir_command

    def rmdir(self, directory, recursive=False):
        recurse_switch = '/S' if recursive else ''
        rmdir_command = " ".join( ("rmdir", recurse_switch, quoteme_double(directory) ) )
        return rmdir_command

    def rmfile(self, file_to_del):
        rmfile_command = " ".join( ("del", "/F", quoteme_double(file_to_del) ) )
        return rmfile_command

    def get_svn_folder_cleanup_instructions(self):
        return ()

    def var_assign(self, identifier, value, comment=None):
        return "SET "+identifier+'='+value

    def echo(self, message):
        echo_command = " ".join(('echo', quoteme_double(message)))
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('REM', remark))
        return remark_command

    def use_copy_tool(self, tool_name):
        if tool_name == "robocopy":
            self.copy_tool = CopyTool_win_robocopy(self)
        elif tool_name == "xcopy":
            self.copy_tool = CopyTool_win_xcopy(self)
        else:
            raise ValueError(tool_name, "is not a valid copy tool for", target_os)

    def copy_file_to_file(self, src_file, trg_file):
        sync_command = "copy \"{src_file}\" \"{trg_file}\"".format(**locals())
        return sync_command

    def resolve_readlink_files(self, in_dir="."):
        return ()

    def check_checksum(self, filepath, checksum):
        check_command_parts = (  'for /f "delims=" %%i in',
                                "('$(CHECKSUM_TOOL_PATH) -s",
                                quoteme_double(filepath),
                                "')",
                                "do (set CHECKSUM_CHECK=%%i",
                                "&",
                                "if not \"!CHECKSUM_CHECK:~0,40!\"==",
                                quoteme_double(checksum),
                                '(echo bad checksum',
                                "%CD%/"+filepath,
                                "1>&2",
                                "&",
                                "GOTO EXIT_ON_ERROR)",
                                ")"
                            )
        check_command = " ".join( check_command_parts )
        return check_command

    def tar(self, to_tar_name):
        raise NotImplementedError

    def unwtar(self, filepath):
        tar_file = filepath+".tar"
        unzip_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "x", "-y",
                               quoteme_double(filepath), "-so", ">", quoteme_double(tar_file))
        untar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "x", "-y",
                               quoteme_double(tar_file))
        rm_tar_command = self.rmfile(tar_file)
        untar_commands = " ".join( unzip_command_parts ), " ".join( untar_command_parts), rm_tar_command
        return untar_commands

class DownloadTool_win_wget(DownloadToolBase):
    def __init__(self, platformHelper):
        super(DownloadTool_win_wget, self).__init__(platformHelper)

    def download_url_to_file(self, src_url, trg_file):
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--quiet")
        download_command_parts.append('--header "Accept-Encoding: gzip"'),
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("60")
        download_command_parts.append("--read-timeout")
        download_command_parts.append("900")
        download_command_parts.append("-O")
        download_command_parts.append(quoteme_double(trg_file))
        # urls need to escape spaces as %20, but windows batch files already escape % characters
        # so use urllib.quote to escape spaces and then change %20 to %%20.
        download_command_parts.append(quoteme_double(urllib.quote(src_url, "$()/:").replace("%", "%%")))
        return (" ".join(download_command_parts), self.platformHelper.exit_if_error())

    def create_config_file(self, curl_config_file_path):
        with open(curl_config_file_path, "w") as wfd:
            wfd.write("dirstruct = on\n")
            wfd.write("timeout = 60\n")
            wfd.write("\n")
            for url, path in self.urls_to_download:
                wfd.write('''url = "{url}"\noutput = "{path}"\n\n'''.format(**locals()))

    def download_from_config_file(self, config_file):
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--read-timeout")
        download_command_parts.append("900")
        return (" ".join(download_command_parts), self.platformHelper.exit_if_error())
