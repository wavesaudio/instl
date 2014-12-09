#!/usr/bin/env python2.7
from __future__ import print_function

import urllib
import stat
import datetime
from pyinstl.utils import *

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolBase
from platformSpecificHelper_Base import DownloadToolBase
from configVarStack import var_stack as var_list

def dos_escape(some_string):
    escaped_string = some_string.replace("&", "^&")
    return escaped_string

class CopyTool_win_robocopy(CopyToolBase):
    def __init__(self, platform_helper):
        super(CopyTool_win_robocopy, self).__init__(platform_helper)
        self.robocopy_error_threshold = 4 # see ss64.com/nt/robocopy-exit.html

    def finalize(self):
        pass

    def begin_copy_folder(self):
        return ()

    def end_copy_folder(self):
        return ()

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
        #log_file = var_list.resolve("$(LOG_FILE)")
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
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" {ignore_spec} /E /R:3 /W:3 /PURGE {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        norm_src_dir, norm_src_file = os.path.split(os.path.normpath(src_file))
        norm_trg_dir = os.path.normpath(trg_dir)
        log_file_spec = self.create_log_spec()
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" \"{norm_src_file}\" /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None, preserve_dest_files=True):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        delete_spec = ""
        if not preserve_dest_files:
            delete_spec = "/PURGE"
        log_file_spec = self.create_log_spec()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" /E {delete_spec} {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "robocopy \"{norm_src_dir}\" \"{norm_trg_dir}\" /LEV:1 {ignore_spec} /R:3 /W:3 {log_file_spec}".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_file(self, src_file, trg_file, link_dest=None, ignore=None):
        retVal = list()
        norm_src_file = os.path.normpath(src_file)
        norm_trg_file = os.path.normpath(trg_file)
        copy_command = "copy \"{norm_src_file}\" \"{norm_trg_file}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def remove_file(self, file_to_remove):
        print("removing", file_to_remove)

    def remove_dir(self, dir_to_remove):
        print("removing", dir_to_remove)

class CopyTool_win_xcopy(CopyToolBase):
    def __init__(self, platform_helper):
        super(CopyTool_win_xcopy, self).__init__(platform_helper)
        self.excludes_set = set()

    def finalize(self):
        self.create_excludes_file()

    def create_ignore_spec(self, ignore):
        retVal = ""
        if ignore:
            if isinstance(ignore, basestring):
                ignore = (ignore,)
            self.excludes_set.update([ignoree.lstrip("*") for ignoree in ignore])
            retVal = var_list.resolve("/EXCLUDE:$(XCOPY_EXCLUDE_FILE_NAME)")
        return retVal

    def begin_copy_folder(self):
        """ xcopy's /EXCLUDE option cannot except a file with spaces in it's path or quoted path.
            So here we are coping the excludes file for each directory...
        """
        return self.copy_file_to_dir("$(XCOPY_EXCLUDE_FILE_PATH)", ".")

    def end_copy_folder(self):
        """ .... And here we dispose of it.
        """
        return self.platform_helper.rmfile("$(XCOPY_EXCLUDE_FILE_NAME)")

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        _, dir_to_copy = os.path.split(norm_src_dir)
        norm_trg_dir = "/".join( (norm_trg_dir, dir_to_copy) )
        retVal.append(self.platform_helper.mkdir(norm_trg_dir))
        retVal.extend(self.copy_dir_contents_to_dir(norm_src_dir, norm_trg_dir, ignore=ignore))
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        #src_dir, src_file = os.path.split(src_file)
        norm_src_file = os.path.normpath(src_file)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = "xcopy  /R /Y \"{norm_src_file}\" \"{norm_trg_dir}\"".format(**locals())
        copy_command.replace("\\", "/")
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=True):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        ignore_spec = self.create_ignore_spec(ignore)
        # preserve_dest_files is ignored - xcopy has no support for removing target file that are not in source
        copy_command = "xcopy /E /R /Y /I {ignore_spec} \"{norm_src_dir}\" \"{norm_trg_dir}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def copy_dir_files_to_dir(self, src_dir, norm_trg_dir, link_dest=False, ignore=None):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        ignore_spec = self.create_ignore_spec(ignore)
        copy_command = "xcopy  /R /Y {ignore_spec} \"{norm_src_dir}\" \"{trg_dir}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def copy_file_to_file(self, src_file, trg_file, link_dest=None, ignore=None):
        retVal = list()
        norm_src_file = os.path.normpath(src_file)
        norm_trg_file = os.path.normpath(trg_file)
        ignore_spec = self.create_ignore_spec(ignore)
        copy_command = "xcopy  /R /Y {ignore_spec} \"{norm_src_file}\" \"{norm_trg_file}\"".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def create_excludes_file(self):
        if self.excludes_set:
            with open(var_list.resolve("$(XCOPY_EXCLUDE_FILE_PATH)", raise_on_fail=True), "w") as wfd:
                make_open_file_read_write_for_all(wfd)
                wfd.write("\n".join(self.excludes_set))

    def remove_file(self, file_to_remove):
        remove_command = "removing \"{file_to_remove}\"".format(**locals())
        return remove_command

    def remove_dir(self, dir_to_remove):
        remove_command = "removing \"{dir_to_remove}\"".format(**locals())
        return remove_command

class PlatformSpecificHelperWin(PlatformSpecificHelperBase):
    def __init__(self, instlObj):
        super(PlatformSpecificHelperWin, self).__init__(instlObj)
        self.var_replacement_pattern = "%\g<var_name>%"

    def init_download_tool(self):
        download_tool_name = var_list.resolve("$(DOWNLOAD_TOOL_PATH)")
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
        recurse_switch = '/S /Q' if recursive else ''
        norm_directory = quoteme_double(os.path.normpath(directory))
        rmdir_command = " ".join( ("rmdir", recurse_switch, norm_directory ) )
        return rmdir_command

    def rmfile(self, file_to_del):
        norm_file = quoteme_double(os.path.normpath(file_to_del))
        rmfile_command = " ".join( ("del", "/F", "/Q", norm_file ) )
        return rmfile_command

    def rm_file_or_dir(self, file_or_dir):
        norm_path = quoteme_double(os.path.normpath(file_or_dir))
        rmdir_command  = " ".join( ("rmdir", '/S', '/Q', norm_path, '>nul', '2>&1'))
        rmfile_command = " ".join( ("del",   '/F', '/Q', norm_path, '>nul', '2>&1'))
        return (rmdir_command, rmfile_command)

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
            raise ValueError(tool_name, "is not a valid copy tool for", var_list.resolve("$(TARGET_OS)"))

    def copy_file_to_file(self, src_file, trg_file, hard_link=False):
        norm_src_file = quoteme_double(os.path.normpath(src_file))
        norm_trg_file = quoteme_double(os.path.normpath(trg_file))
        copy_command = " ".join( ("copy", norm_src_file,  norm_trg_file) )
        return copy_command

    def check_checksum_for_file(self, filepath, checksum):
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

    def check_checksum_for_folder(self, info_map_file):
        check_checksum_for_folder_command = super(PlatformSpecificHelperWin, self).check_checksum_for_folder(info_map_file)
        return check_checksum_for_folder_command, self.exit_if_error()

    def tar(self, to_tar_name):
        raise NotImplementedError

    def unwtar_file(self, wtar_file):
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

    def unwtar_current_folder(self):
        unwtar_command = super(PlatformSpecificHelperWin, self).unwtar_current_folder()
        return unwtar_command, self.exit_if_error()

    def wait_for_child_processes(self):
        return ("echo wait_for_child_processes not implemented yet for windows",)

    def chmod(self, new_mode, filepath):
        raise NotImplementedError

    def make_executable(self, filepath):
        raise NotImplementedError

    def unlock(self, filepath, recursive=False):
        """ Remove the system's read-only flag, this is different from permissions.
            Not relevant for Linux.
        """
        raise NotImplementedError

    def touch(self, filepath):
        touch_command = " ".join( ("type", "NUL", ">", quoteme_double(filepath)) )
        return touch_command

    def run_instl(self):
        command_prefix = ""
        if not getattr(sys, 'frozen', False):
            command_prefix = "python "
        instl_command = command_prefix+'\"$(__INSTL_EXE_PATH__)\"'
        return instl_command

    def create_folders(self, info_map_file):
        create_folders_command = super(PlatformSpecificHelperWin, self).create_folders(info_map_file)
        return create_folders_command, self.exit_if_error()

    def append_file_to_file(self, source_file, target_file):
        append_command = " ".join( ("type", quoteme_double(source_file), ">>", quoteme_double(target_file)) )
        return append_command

class DownloadTool_win_wget(DownloadToolBase):
    def __init__(self, platform_helper):
        super(DownloadTool_win_wget, self).__init__(platform_helper)

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
        return (" ".join(download_command_parts), self.platform_helper.exit_if_error())

    def create_config_file(self, curl_config_file_path):
        with open(curl_config_file_path, "w") as wfd:
            make_open_file_read_write_for_all(wfd)
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
        return " ".join(download_command_parts), self.platform_helper.exit_if_error()


class DownloadTool_win_curl(DownloadToolBase):
    def __init__(self, platform_helper):
        super(DownloadTool_win_curl, self).__init__(platform_helper)

    def download_url_to_file(self, src_url, trg_file):
        connect_time_out = var_list.resolve("$(CURL_CONNECT_TIMEOUT)", raise_on_fail=True)
        max_time         = var_list.resolve("$(CURL_MAX_TIME)", raise_on_fail=True)
        retries          = var_list.resolve("$(CURL_RETRIES)", raise_on_fail=True)
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
            connect_time_out = var_list.resolve("$(CURL_CONNECT_TIMEOUT)", raise_on_fail=True)
            max_time         = var_list.resolve("$(CURL_MAX_TIME)", raise_on_fail=True)
            retries          = var_list.resolve("$(CURL_RETRIES)", raise_on_fail=True)
            actual_num_files = max(1, min(num_urls_to_download / 8, num_files))

            num_digits = len(str(actual_num_files))
            file_name_list = ["-".join( (curl_config_file_path, str(file_i).zfill(num_digits))  ) for file_i in xrange(actual_num_files)]
            wfd_list = list()
            for file_name in file_name_list:
                wfd = open(file_name, "w")
                make_open_file_read_write_for_all(wfd)
                wfd_list.append(wfd)

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
            make_open_file_read_write_for_all(wfd)
            for config_file in config_files:
                normalized_path = config_file.replace("\\", "/")
                wfd.write(var_list.resolve("\"$(DOWNLOAD_TOOL_PATH)\" --config \""+normalized_path+"\"\n", raise_on_fail=True))

        download_command = " ".join( (self.platform_helper.run_instl(),  "parallel-run", "--in", quoteme_double(parallel_run_config_file_path)) )
        return (download_command, self.platform_helper.exit_if_error())
