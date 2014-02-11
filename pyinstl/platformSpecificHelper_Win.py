#!/usr/bin/env python2.7
from __future__ import print_function

import os
import urllib
import datetime
from pyinstl.utils import *

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase

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

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
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

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False):
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
        download_tool_name = instlObj.cvl.get_str("DOWNLOAD_TOOL_PATH")
        if download_tool_name.endswith("wget.exe"):
            self.dl_tool = DownloadTool_win_wget(self)
        elif download_tool_name.endswith("curl.exe"):
            self.dl_tool = DownloadTool_win_curl(self)
        else:
            self.dl_tool = None

    def get_install_instructions_prefix(self):
        retVal = (
            "@echo off",
            "setlocal enableextensions enabledelayedexpansion",
            self.remark(self.instlObj.get_version_str()),
            self.remark(datetime.datetime.today().isoformat()),
            self.start_time_measure(),
            self.save_dir("TOP_SAVE_DIR"),
            )
        return retVal

    def get_install_instructions_postfix(self):
        retVal = (
                self.restore_dir("TOP_SAVE_DIR"),
                self.end_time_measure(),
                "endlocal",
                "exit /b 0",
                "",
                ":EXIT_ON_ERROR",
                self.restore_dir("TOP_SAVE_DIR"),
                "set defERRORLEVEL=%ERRORLEVEL%",
                "if %defERRORLEVEL% == 0 (set defERRORLEVEL=1)",
                'echo Exit on error 1>&2',
                self.end_time_measure(),
                "endlocal",
                "exit /b %defERRORLEVEL%"
                )
        return retVal

    def start_time_measure(self):
        time_start_command = "set Time_Measure_Start=%time%"
        return time_start_command

    def end_time_measure(self):
        time_end_commands = (
            'set Time_Measure_End=%time%',
            'set options="tokens=1-4 delims=:."',
            'for /f %options% %%a in ("%Time_Measure_Start%") do set start_h=%%a & set /a start_m=100%%b %% 100 & set /a start_s=100%%c %% 100 & set /a start_ms=100%%d %% 100',
            'set /a Time_Measure_Start=%start_h%*3600 + %start_m%*60 + %start_s%',
            'for /f %options% %%a in ("%Time_Measure_End%") do set end_h=%%a & set /a end_m=100%%b %% 100 & set /a end_s=100%%c %% 100 & set /a end_ms=100%%d %% 100',
            'set /a Time_Measure_End=%end_h%*3600 + %end_m%*60 + %end_s%',
            'set /a Time_Measure_Diff=%Time_Measure_End% - %Time_Measure_Start%',
            'echo %__MAIN_COMMAND__% Time: %Time_Measure_Diff% seconds'
)
        return time_end_commands

    def exit_if_error(self, error_threshold=1):
        retVal = ("IF", "ERRORLEVEL", str(error_threshold), "(", "echo", 'Error %ERRORLEVEL% at step ' + str(self.num_items_for_progress_report+1), "1>&2", "&", "GOTO", "EXIT_ON_ERROR", ")")
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
        echo_command = " ".join(('echo', message))
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

    def unwtar(self, wtar_file):
        tar_file = wtar_file+".tar"
        unzip_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "x", "-y", "-bd",
                               quoteme_double(wtar_file), "-so", ">", quoteme_double(tar_file),
                                "2>NUL")
        untar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "x", "-y", "-bd",
                               quoteme_double(tar_file), "2>NUL")
        rm_tar_command = self.rmfile(tar_file)
        untar_commands = " ".join( unzip_command_parts ), self.exit_if_error(),\
                         " ".join( untar_command_parts), self.exit_if_error(), \
                         rm_tar_command
        return untar_commands

    def wait_for_child_processes(self):
        return ("echo wait_for_child_processes not implemented yet for windows",)

    def make_executable(self, filepath):
        pass

class DownloadTool_win_wget(DownloadToolBase):
    def __init__(self, platformHelper):
        super(DownloadTool_win_wget, self).__init__(platformHelper)

    def download_url_to_file(self, src_url, trg_file):
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--quiet")
        download_command_parts.append('--header "Accept-Encoding: gzip"'),
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("3")
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


class DownloadTool_win_curl(DownloadToolBase):
    def __init__(self, platformHelper):
        super(DownloadTool_win_curl, self).__init__(platformHelper)

    def download_url_to_file(self, src_url, trg_file):
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--insecure")
        download_command_parts.append("--fail")
        download_command_parts.append("--raw")
        download_command_parts.append("--silent")
        download_command_parts.append("--show-error")
        download_command_parts.append("--compressed")
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("3")
        download_command_parts.append("--max-time")
        download_command_parts.append("60")
        download_command_parts.append("--retry")
        download_command_parts.append("3")
        download_command_parts.append("write-out")
        download_command_parts.append(DownloadToolBase.curl_write_out_str)
        download_command_parts.append("-o")
        download_command_parts.append(quoteme_double(trg_file))
        download_command_parts.append(quoteme_double(urllib.quote(src_url, "$()/:")))
        return " ".join(download_command_parts)

    def create_config_file(self, curl_config_file_path):
        if len(self.urls_to_download) > 0:
            with open(curl_config_file_path, "wb") as wfd:
                wfd.write("insecure\n")
                wfd.write("raw\n")
                wfd.write("fail\n")
                wfd.write("silent\n")
                wfd.write("show-error\n")
                wfd.write("compressed\n")
                wfd.write("create-dirs\n")
                wfd.write("connect-timeout = 3\n")
                wfd.write("max-time = 60\n")
                wfd.write("retry = 3\n")
                wfd.write("write-out = " + quoteme_double(os.path.basename(wfd.name)+": "+DownloadToolBase.curl_write_out_str))
                wfd.write("\n")
                wfd.write("\n")
                for url, path in self.urls_to_download:
                    win_style_path = os.path.normpath(path)
                    win_style_path = win_style_path.replace("\\", "\\\\")
                    dl_lines = '''url = "%s"\noutput = "%s"\n\n''' % (url, win_style_path)
                    wfd.write(dl_lines)
            return curl_config_file_path
        else:
            return None

    def create_config_files(self, curl_config_file_path, num_files):
        curl_config_file_path=  self.create_config_file(curl_config_file_path)
        if curl_config_file_path is not None:
            return (curl_config_file_path,)
        else:
            return ()

    def download_from_config_file(self, config_file):
        #http://stackoverflow.com/questions/649634/how-do-i-run-a-bat-file-in-the-background-from-another-bat-file/649937#649937
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--config")
        download_command_parts.append(quoteme_double(config_file))

        return " ".join(download_command_parts)
