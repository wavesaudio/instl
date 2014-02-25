#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import urllib
import datetime
from pyinstl.utils import *

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase

def dos_escape(some_string):
    escaped_string = some_string.replace("&", "^&")
    return escaped_string

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
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" /E {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        norm_src_dir, norm_src_file = os.path.split(os.path.normpath(src_file))
        norm_trg_dir = os.path.normpath(trg_dir)
        log_file_spec = self.create_log_spec()
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" \"{norm_src_file}\" /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" /E {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" /LEV:1 {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_file(self, src_file, trg_file, link_dest=None, ignore=None):
        retVal = list()
        norm_src_file = os.path.normpath(src_file)
        norm_trg_file = os.path.normpath(trg_file)
        copy_command = "copy \"{norm_src_file}\" \"{norm_trg_file}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

class CopyTool_win_xcopy(CopyToolBase):
    def __init__(self, platformHelper):
        super(CopyTool_win_xcopy, self).__init__(platformHelper)

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        _, dir_to_copy = os.path.split(norm_src_dir)
        norm_trg_dir = "/".join( (norm_trg_dir, dir_to_copy) )
        mkdir_command  = "mkdir \"{norm_trg_dir}\"".format(**locals())
        retVal.append(mkdir_command)
        retVal.extend(self.copy_dir_contents_to_dir(norm_src_dir, norm_trg_dir))
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False):
        retVal = list()
        #src_dir, src_file = os.path.split(src_file)
        norm_src_file = os.path.normpath(src_file)
        norm_trg_file = os.path.normpath(trg_file)
        copy_command = "xcopy  /R /Y \"{norm_src_file}\" \"{norm_trg_file}\"".format(**locals())
        copy_command.replace("\\", "/")
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "xcopy /E /R /Y \"{norm_src_dir}\" \"{norm_trg_dir}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

    def copy_dir_files_to_dir(self, src_dir, norm_trg_dir, link_dest=None):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "xcopy  /R /Y \"{norm_src_dir}\" \"{trg_dir}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platformHelper.exit_if_error())
        return retVal

class PlatformSpecificHelperWin(PlatformSpecificHelperBase):
    def __init__(self, instlObj):
        super(PlatformSpecificHelperWin, self).__init__(instlObj)
        self.var_replacement_pattern = "%\g<var_name>%"

    def init_download_tool(self):
        download_tool_name = self.instlObj.cvl.get_str("DOWNLOAD_TOOL_PATH")
        if download_tool_name.endswith("wget.exe"):
            self.dl_tool = DownloadTool_win_wget(self)
        elif download_tool_name.endswith("curl.exe"):
            self.dl_tool = DownloadTool_win_curl(self)

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
                "exit /b 0",
                "",
                ":EXIT_ON_ERROR",
                self.restore_dir("TOP_SAVE_DIR"),
                "set CATCH_EXIT_VALUE=%ERRORLEVEL%",
                "if %CATCH_EXIT_VALUE% == 0 (set CATCH_EXIT_VALUE=1)",
                self.end_time_measure(),
                'echo Exit on error %CATCH_EXIT_VALUE% 1>&2',
                "exit /b %CATCH_EXIT_VALUE%"
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
        norm_directory = quoteme_double(os.path.normpath(directory))
        mk_command = " ".join( ("if not exist", norm_directory, "mkdir", norm_directory))
        return mk_command

    def cd(self, directory):
        norm_directory = quoteme_double(os.path.normpath(directory))
        cd_command = " ".join( ("cd", '/d', norm_directory) )
        return cd_command

    def pushd(self, directory):
        norm_directory = quoteme_double(os.path.normpath(directory))
        pushd_command = " ".join( ("pushd", norm_directory ) )
        return pushd_command

    def popd(self):
        return "popd"

    def save_dir(self, var_name):
        save_dir_command = "SET "+ var_name +"=%CD%"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$("+var_name+")")
        return restore_dir_command

    def rmdir(self, directory, recursive=False):
        recurse_switch = '/S' if recursive else ''
        norm_directory = quoteme_double(os.path.normpath(directory))
        rmdir_command = " ".join( ("rmdir", recurse_switch, norm_directory ) )
        return rmdir_command

    def rmfile(self, file_to_del):
        norm_file = quoteme_double(os.path.normpath(file_to_del))
        rmfile_command = " ".join( ("del", "/F", norm_file ) )
        return rmfile_command

    def get_svn_folder_cleanup_instructions(self):
        return ()

    def var_assign(self, identifier, value, comment=None):
        return "SET "+identifier+'='+value

    def echo(self, message):
        echo_command = " ".join(('echo', dos_escape(message)))
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

    def copy_file_to_file(self, src_file, trg_file, hard_link=False):
        norm_src_file = quoteme_double(os.path.normpath(src_file))
        norm_trg_file = quoteme_double(os.path.normpath(trg_file))
        copy_command = " ".join( ("copy", norm_src_file,  norm_trg_file) )
        return copy_command

    def check_checksum(self, filepath, checksum):
        norm_file = os.path.normpath(filepath)
        check_commands = (
            """for /f "delims=\" %%i in ('$(CHECKSUM_TOOL_PATH) -s \"{norm_file}\"') do (@set sha1deep_ret=%%i)""".format(**locals()),
            """@set CHECKSUM_CHECK=\"%sha1deep_ret:~0,40%\"""",
            """if not %CHECKSUM_CHECK% == \"{checksum}\" (""".format(**locals()),
            self.echo("""echo bad checksum \"{norm_file}\"""".format(**locals())),
            self.echo("""@echo Expected: {checksum}, Got: %CHECKSUM_CHECK%""".format(**locals())),
            """GOTO EXIT_ON_ERROR""",
            ")"
            )

        return check_commands


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
        done_stamp_file = wtar_file + ".done"
        untar_commands = " ".join( unzip_command_parts ), self.exit_if_error(),\
                         " ".join( untar_command_parts), self.exit_if_error(), \
                         rm_tar_command, self.touch(done_stamp_file)
        return untar_commands

    def wait_for_child_processes(self):
        return ("echo wait_for_child_processes not implemented yet for windows",)

    def make_executable(self, filepath):
        pass

    def touch(self, filepath):
        touch_command = " ".join( ("type", "NUL", ">", quoteme_double(filepath)) )
        return touch_command

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
        connect_time_out = self.platformHelper.instlObj.cvl.get_str("CURL_CONNECT_TIMEOUT")
        max_time         = self.platformHelper.instlObj.cvl.get_str("CURL_MAX_TIME")
        retries          = self.platformHelper.instlObj.cvl.get_str("CURL_RETRIES")
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--insecure")
        download_command_parts.append("--fail")
        download_command_parts.append("--raw")
        download_command_parts.append("--silent")
        download_command_parts.append("--show-error")
        download_command_parts.append("--compressed")
        download_command_parts.append("--connect-timeout")
        download_command_parts.append(connect_time_out)
        download_command_parts.append("--max-time")
        download_command_parts.append(max_time)
        download_command_parts.append("--retry")
        download_command_parts.append(retries)
        download_command_parts.append("write-out")
        download_command_parts.append(DownloadToolBase.curl_write_out_str)
        download_command_parts.append("-o")
        download_command_parts.append(quoteme_double(trg_file))
        download_command_parts.append(quoteme_double(urllib.quote(src_url, "$()/:")))
        return " ".join(download_command_parts)

    def create_config_files(self, curl_config_file_path, num_files):
        import itertools
        num_urls_to_download = len(self.urls_to_download)
        if num_urls_to_download > 0:
            connect_time_out = self.platformHelper.instlObj.cvl.get_str("CURL_CONNECT_TIMEOUT")
            max_time         = self.platformHelper.instlObj.cvl.get_str("CURL_MAX_TIME")
            retries          = self.platformHelper.instlObj.cvl.get_str("CURL_RETRIES")
            actual_num_files = max(1, min(num_urls_to_download / 8, num_files))
            curl_config_file_path_parts = curl_config_file_path.split(".")
            file_name_list = [".".join( curl_config_file_path_parts[:-1]+[str(file_i)]+curl_config_file_path_parts[-1:]  ) for file_i in xrange(actual_num_files)]
            wfd_list = list()
            for file_name in file_name_list:
                wfd_list.append(open(file_name, "w"))

            for wfd in wfd_list:
                wfd.write("insecure\n")
                wfd.write("raw\n")
                wfd.write("fail\n")
                wfd.write("silent\n")
                wfd.write("show-error\n")
                wfd.write("compressed\n")
                wfd.write("create-dirs\n")
                wfd.write("connect-timeout = {connect_time_out}\n".format(**locals()))
                wfd.write("max-time = {max_time}\n".format(**locals()))
                wfd.write("retry = {retries}\n".format(**locals()))
                wfd.write("write-out = \"Progress: ... of ...; " + os.path.basename(wfd.name) + ": " + DownloadToolBase.curl_write_out_str + "\"\n")
                wfd.write("\n")
                wfd.write("\n")

            wfd_cycler = itertools.cycle(wfd_list)
            url_num = 0
            for url, path in self.urls_to_download:
                wfd = wfd_cycler.next()
                wfd.write('''url = "{url}"\noutput = "{path}"\n\n'''.format(**locals()))
                url_num += 1

            for wfd in wfd_list:
                wfd.close()
            return file_name_list
        else:
            return ()

    def download_from_config_files(self, parallel_run_config_file_path, config_files):
        with open(parallel_run_config_file_path, "w") as wfd:
            for config_file in config_files:
                wfd.write(self.platformHelper.instlObj.cvl.resolve_string("\"$(DOWNLOAD_TOOL_PATH)\" --config \""+config_file+"\"\n"))

        command_prefix = ""
        if not getattr(sys, 'frozen', False):
            command_prefix = "python "

        download_command = command_prefix+"\"$(__INSTL_EXE_PATH__)\" parallel-run --in \""+parallel_run_config_file_path+"\""
        return (download_command, self.platformHelper.exit_if_error())
