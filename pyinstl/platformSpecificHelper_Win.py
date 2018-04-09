#!/usr/bin/env python3


import os
import sys
import datetime
import subprocess
import re
import random
import string

import utils
from .platformSpecificHelper_Base import PlatformSpecificHelperBase
from .platformSpecificHelper_Base import CopyToolBase
from .platformSpecificHelper_Base import DownloadToolBase
from configVar import var_stack


def escape_me_dos_callback(match_obj):
    replacement = "^"+match_obj.group(1)
    return replacement

# regex to find some characters that should be escaped in dos, but are not
dos_escape_regex = re.compile("""(?<!\^)([<|&>])""", re.MULTILINE)
def dos_escape(some_string):
    # 1. remove ^><|'s from end of string - they cause CMD to ask for 'More?' or 'The syntax of the command is incorrect.'
    retVal = some_string.rstrip("^><|")
    # 2. replace some chars with ?
    retVal = re.sub("""[\r\n]""", "?", retVal)
    # 3. escape some chars, but only of they are not already escaped
    retVal = dos_escape_regex.sub(escape_me_dos_callback, retVal)
    return retVal


class CopyTool_win_robocopy(CopyToolBase):
    def __init__(self, platform_helper):
        super().__init__(platform_helper)
        self.robocopy_error_threshold = 4  # see ss64.com/nt/robocopy-exit.html
        robocopy_path = self.platform_helper.find_cmd_tool("ROBOCOPY_PATH")
        if robocopy_path is None:
            raise IOError("could not find {} in path".format("robocopy.exe"))

    def finalize(self):
        pass

    def begin_copy_folder(self):
        return ()

    def end_copy_folder(self):
        return ()

    def create_ignore_spec(self, ignore):
        retVal = ""
        if not isinstance(ignore, str):
            ignore = " ".join(map(utils.quoteme_double, ignore))
        retVal = """/XF {ignore} /XD {ignore}""".format(**locals())
        return retVal

    def create_log_spec(self):
        """ To do: dedicate a variable to copy logging (COPY_LOG_FILE ???)
        """
        retVal = ""
        # log_file = var_stack.ResolveVarToStr("LOG_FILE")
        # retVal = " /LOG:{log_file}".format(**locals())
        return retVal

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=False):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join((trg_dir, dir_to_copy))
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        if not preserve_dest_files:
            delete_spec = "/PURGE"
        else:
            delete_spec = ""
        copy_command = """"$(ROBOCOPY_PATH)" "{norm_src_dir}" "{norm_trg_dir}" {ignore_spec} /E /R:9 /W:1 /NS /NC /NFL /NDL /NP /NJS {delete_spec} {log_file_spec}""".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        norm_src_dir, norm_src_file = os.path.split(os.path.normpath(src_file))
        norm_trg_dir = os.path.normpath(trg_dir)
        log_file_spec = self.create_log_spec()
        copy_command = """"$(ROBOCOPY_PATH)" "{norm_src_dir}" "{norm_trg_dir}" "{norm_src_file}" /R:9 /W:1 /NS /NC /NFL /NDL /NP /NJS {log_file_spec}""".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None, preserve_dest_files=True):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        delete_spec = ""
        if not preserve_dest_files:
            delete_spec = "/PURGE"
        else:
            delete_spec = ""
        log_file_spec = self.create_log_spec()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = """"$(ROBOCOPY_PATH)" "{norm_src_dir}" "{norm_trg_dir}" /E {delete_spec} {ignore_spec} /R:9 /W:1 /NS /NC /NFL /NDL /NP /NJS {log_file_spec}""".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        retVal = list()
        ignore_spec = self.create_ignore_spec(ignore)
        log_file_spec = self.create_log_spec()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = """"$(ROBOCOPY_PATH)" "{norm_src_dir}" "{norm_trg_dir}" /LEV:1 {ignore_spec} /R:9 /W:1 /NS /NC /NFL /NDL /NP /NJS {log_file_spec}""".format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def copy_file_to_file(self, src_file, trg_file, link_dest=None, ignore=None):
        retVal = list()
        norm_src_file = os.path.normpath(src_file)
        norm_trg_file = os.path.normpath(trg_file)
        copy_command = """copy "{norm_src_file}" "{norm_trg_file}" """.format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def remove_file(self, file_to_remove):
        print("removing", file_to_remove)

    def remove_dir(self, dir_to_remove):
        print("removing", dir_to_remove)


class CopyTool_win_xcopy(CopyToolBase):
    def __init__(self, platform_helper):
        super().__init__(platform_helper)
        self.excludes_set = set()
        xcopy_path = self.platform_helper.find_cmd_tool("XCOPY_PATH")
        if xcopy_path is None:
            raise IOError("could not find {} in path".format("xcopy.exe"))

    def finalize(self):
        self.create_excludes_file()

    def create_ignore_spec(self, ignore):
        retVal = ""
        if ignore:
            if isinstance(ignore, str):
                ignore = (ignore,)
            self.excludes_set.update([ignoree.lstrip("*") for ignoree in ignore])
            retVal = var_stack.ResolveStrToStr("/EXCLUDE:$(XCOPY_EXCLUDE_FILE_NAME)")
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

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=False):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        _, dir_to_copy = os.path.split(norm_src_dir)
        norm_trg_dir = "/".join((norm_trg_dir, dir_to_copy))
        retVal.append(self.platform_helper.mkdir(norm_trg_dir))
        retVal.extend(self.copy_dir_contents_to_dir(norm_src_dir, norm_trg_dir, ignore=ignore, preserve_dest_files=preserve_dest_files))
        return retVal

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        # src_dir, src_file = os.path.split(src_file)
        norm_src_file = os.path.normpath(src_file)
        norm_trg_dir = os.path.normpath(trg_dir)
        copy_command = """"$(XCOPY_PATH)"  /R /Y "{norm_src_file}" "{norm_trg_dir}" """.format(**locals())
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
        copy_command = """"$(XCOPY_PATH)" /E /R /Y /I {ignore_spec} "{norm_src_dir}" "{norm_trg_dir}" """.format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None):
        retVal = list()
        norm_src_dir = os.path.normpath(src_dir)
        norm_trg_dir = os.path.normpath(trg_dir)
        ignore_spec = self.create_ignore_spec(ignore)
        copy_command = """"$(XCOPY_PATH)"  /R /Y {ignore_spec} "{norm_src_dir}" "{trg_dir}" """.format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def copy_file_to_file(self, src_file, trg_file, link_dest=None, ignore=None):
        retVal = list()
        norm_src_file = os.path.normpath(src_file)
        norm_trg_file = os.path.normpath(trg_file)
        ignore_spec = self.create_ignore_spec(ignore)
        copy_command = """"$(XCOPY_PATH)"  /R /Y {ignore_spec} "{norm_src_file}" "{norm_trg_file}" """.format(**locals())
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def create_excludes_file(self):
        if self.excludes_set:
            with utils.utf8_open(var_stack.ResolveVarToStr("XCOPY_EXCLUDE_FILE_PATH"), "w") as wfd:
                utils.make_open_file_read_write_for_all(wfd)
                wfd.write("\n".join(self.excludes_set))

    def remove_file(self, file_to_remove):
        remove_command = """removing "{file_to_remove}" """.format(**locals())
        return remove_command

    def remove_dir(self, dir_to_remove):
        remove_command = """removing "{dir_to_remove}" """.format(**locals())
        return remove_command


class PlatformSpecificHelperWin(PlatformSpecificHelperBase):
    def __init__(self, instlObj):
        super().__init__(instlObj)
        self.var_replacement_pattern = "%\g<var_name>%"

    def find_cmd_tool(self, tool_to_find_var_name):
        """ locate the path to a cmd.exe tool on windows, if found put the full path in variable
        :param tool_to_find_var_name: variable name of tool or full path to tool
        :return: the path to the tool
        """
        tool_path = None
        if tool_to_find_var_name in var_stack:
            original_tool_value = var_stack.ResolveVarToStr(tool_to_find_var_name)
            # first try the variable, could be that the tool was already found
            if os.path.isfile(original_tool_value):
                tool_path = original_tool_value

            if tool_path is None:
                # next try to ask the system using the where command
                try:
                    where_tool_path = subprocess.check_output("where " + original_tool_value).strip()
                    where_tool_path = utils.unicodify(where_tool_path)
                    if os.path.isfile(where_tool_path):
                        tool_path = where_tool_path
                        var_stack.set_var(tool_to_find_var_name, "find_cmd_tool").append(tool_path)
                except Exception:
                    pass # never mind, we'll try on our own

            if tool_path is None:
                win_paths = utils.unique_list()
                # try to find the tool in the PATH variable
                if "PATH" in os.environ:
                    # remove newline characters that might lurk in the path (see tech support case 143589)
                    adjusted_path = re.sub('[\r\n]',"?",utils.unicodify(os.environ["PATH"]))
                    win_paths.extend(adjusted_path.split(";"))
                else:
                    print("PATH was not found in environment variables")
                # also add some known location in case user's PATH variable was altered
                if "SystemRoot" in os.environ:
                    system_root = utils.unicodify(os.environ["SystemRoot"])
                    know_locations = (os.path.join(system_root, "System32"),
                                      os.path.join(system_root, "SysWOW64"))
                    win_paths.extend(know_locations)
                for win_path in win_paths:
                    tool_path = os.path.join(win_path, original_tool_value)
                    if os.path.isfile(tool_path):
                        var_stack.set_var(tool_to_find_var_name, "find_cmd_tool ").append(tool_path)
                        break
                else: # break was not called, tool was not found
                    tool_path = None
        return tool_path

    def init_platform_tools(self):
        download_tool_name = var_stack.ResolveVarToStr("DOWNLOAD_TOOL_PATH")
        if download_tool_name.endswith("wget.exe"):
            self.dl_tool = DownloadTool_win_wget(self)
        elif download_tool_name.endswith("curl.exe"):
            self.dl_tool = DownloadTool_win_curl(self)
        for find_tool_var in \
                list(var_stack.ResolveVarToList("CMD_TOOLS_TO_FIND", default=[])) +\
                list(var_stack.ResolveVarToList("CMD_TOOLS_TO_FIND_INTERNAL", default=[])):
            self.find_cmd_tool(find_tool_var)

    def get_install_instructions_prefix(self):
        self.random_invocation_id = ''.join(random.choice(string.ascii_lowercase) for i in range(16))
        self.invocations_file_path = var_stack.ResolveVarToStr("__INVOCATIONS_FILE_PATH__")
        retVal = (
            "@echo off",
            "chcp 65001",
            "setlocal enableextensions enabledelayedexpansion",
            # write to instl_invocations.txt
                'echo --- {0} >> "{1}"'.format(self.random_invocation_id, self.invocations_file_path),
                'echo start: %date%-%time% >> "{0}"'.format(self.invocations_file_path),
                'echo batch file: %0 >> "{0}"'.format(self.invocations_file_path),
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
            # write to instl_invocations.txt
                'echo run time: %Time_Measure_Diff% seconds >> "{0}"'.format(self.invocations_file_path),
                'echo end: %date%-%time% >> "{0}"'.format(self.invocations_file_path),
                'echo exit code: 0 >> "{0}"'.format(self.invocations_file_path),
                'echo --- {0} >> "{1}"'.format(self.random_invocation_id, self.invocations_file_path),
            "exit /b 0",
            "",
            ":EXIT_ON_ERROR",
            "set CATCH_EXIT_VALUE=%ERRORLEVEL%",
            "if %CATCH_EXIT_VALUE% == 0 (set CATCH_EXIT_VALUE=1)",
            "$(TASKLIST_PATH)",
            self.restore_dir("TOP_SAVE_DIR"),
            self.end_time_measure(),
            # write to instl_invocations.txt
                'echo run time: %Time_Measure_Diff% seconds >> "{0}"'.format(self.invocations_file_path),
                'echo end: %date%-%time% >> "{0}"'.format(self.invocations_file_path),
                'echo exit code: %CATCH_EXIT_VALUE% >> "{0}"'.format(self.invocations_file_path),
                'echo --- {0} >> "{1}"'.format(self.random_invocation_id, self.invocations_file_path),
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

    def exit_if_any_error(self):
        retVal = ("IF", "%ERRORLEVEL%", "NEQ", "0", "(", "echo", 'Error %ERRORLEVEL% at step ' + str(self.num_items_for_progress_report+1), "1>&2", "&", "GOTO", "EXIT_ON_ERROR", ")")
        return " ".join(retVal)

    def mkdir_with_owner(self, directory, progress_num=0):
        norm_directory = os.path.normpath(directory)
        quoted_norm_directory = utils.quoteme_double(norm_directory)
        quoted_norm_directory_slash = utils.quoteme_double(norm_directory+"\\")
        mk_command = " ".join(("if not exist", quoted_norm_directory, "(",
                               "mkdir", quoted_norm_directory,
                               "&", "echo" "Progress: ", str(progress_num), " of $(TOTAL_ITEMS_FOR_PROGRESS_REPORT); Create folder ", quoted_norm_directory, ")"))
        check_mk_command = " ".join(("if not exist", quoted_norm_directory_slash, "(", "echo Error: failed to create ", quoted_norm_directory, "1>&2",
                                    "&", "GOTO", "EXIT_ON_ERROR", ")"))
        return mk_command, check_mk_command


    def mkdir(self, directory):
        norm_directory = os.path.normpath(directory)
        quoted_norm_directory = utils.quoteme_double(norm_directory)
        quoted_norm_directory_slash = utils.quoteme_double(norm_directory+"\\")
        mk_command = " ".join(("if not exist", quoted_norm_directory, "mkdir", quoted_norm_directory))
        check_mk_command = " ".join(("if not exist", quoted_norm_directory_slash, "(", "echo Error: failed to create ", quoted_norm_directory, "1>&2",
                                    "&", "GOTO", "EXIT_ON_ERROR", ")"))
        return mk_command, check_mk_command

    def cd(self, directory):
        norm_directory = utils.quoteme_double(os.path.normpath(directory))
        is_exists_command = " ".join(("if not exist", norm_directory,
                                    "(", "echo directory does not exists", norm_directory, "1>&2",
                                    "&", "GOTO", "EXIT_ON_ERROR", ")"))
        cd_command = " ".join(("cd", '/d', norm_directory))
        check_cd_command = " ".join(("if /I not", norm_directory, "==", utils.quoteme_double("%CD%"),
                                    "(", "echo Error: failed to cd to", norm_directory, "1>&2",
                                    "&", "GOTO", "EXIT_ON_ERROR", ")"))
        return is_exists_command, cd_command, check_cd_command

    def pushd(self, directory):
        norm_directory = utils.quoteme_double(os.path.normpath(directory))
        pushd_command = " ".join(("pushd", norm_directory))
        return pushd_command

    def popd(self):
        return "popd"

    def save_dir(self, var_name):
        save_dir_command = "SET " + var_name + "=%CD%"
        return save_dir_command

    def restore_dir(self, var_name):
        restore_dir_command = self.cd("$(" + var_name + ")")
        return restore_dir_command

    def rmdir(self, directory, recursive=False, check_exist=False):
        rmdir_command_parts = list()
        norm_directory = utils.quoteme_double(os.path.normpath(directory))
        if check_exist:
            rmdir_command_parts.extend(("if", "exist", norm_directory))
        rmdir_command_parts.append("rmdir")
        if recursive:
            rmdir_command_parts.extend(("/S", "/Q"))
        rmdir_command_parts.append(norm_directory)
        rmdir_command = " ".join(rmdir_command_parts)
        return rmdir_command

    def rmfile(self, a_file, quote_char='"', check_exist=False):
        rmfile_command_parts = list()
        norm_file = utils.quoteme(os.path.normpath(a_file), quote_char)
        if check_exist:
            rmfile_command_parts.extend(("if", "exist", norm_file))
        rmfile_command_parts.extend(("del", "/F", "/Q", norm_file))
        rmfile_command = " ".join(rmfile_command_parts)
        return rmfile_command

    def rm_file_or_dir(self, file_or_dir):
        norm_path = utils.quoteme_double(os.path.normpath(file_or_dir))
        rmdir_command = " ".join(("rmdir", '/S', '/Q', norm_path, '>nul', '2>&1'))
        rmfile_command = " ".join(("del", '/F', '/Q', norm_path, '>nul', '2>&1'))
        return rmdir_command, rmfile_command

    def get_svn_folder_cleanup_instructions(self):
        return ()

    def var_assign(self, identifier, value):
        var_assignment = "SET " + identifier + '=' + dos_escape(value)
        return var_assignment

    def echo(self, message):
        echo_command = " ".join(('echo', dos_escape(message)))
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('REM', dos_escape(remark)))
        return remark_command

    def use_copy_tool(self, tool_name):
        if tool_name == "robocopy":
            self.copy_tool = CopyTool_win_robocopy(self)
        elif tool_name == "xcopy":
            self.copy_tool = CopyTool_win_xcopy(self)
        else:
            raise ValueError(tool_name, "is not a valid copy tool for", var_stack.ResolveVarToStr("TARGET_OS"))

    def copy_file_to_file(self, src_file, trg_file, hard_link=False):
        norm_src_file = utils.quoteme_double(os.path.normpath(src_file))
        norm_trg_file = utils.quoteme_double(os.path.normpath(trg_file))
        copy_command = " ".join(("copy", norm_src_file, norm_trg_file))
        return copy_command

    def check_checksum_for_file(self, file_path, checksum):
        norm_file = os.path.normpath(file_path)
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
        check_checksum_for_folder_command = super().check_checksum_for_folder(info_map_file)
        return check_checksum_for_folder_command, self.exit_if_error()

    def ls(self, format='*', folder='.'):
        raise NotImplementedError

    def tar(self, to_tar_name):
        raise NotImplementedError

    def unwtar_something(self, what_to_unwtar, no_artifacts=False, where_to_unwtar=None):
        unwtar_command = super().unwtar_something(what_to_unwtar, no_artifacts, where_to_unwtar)
        check_error_level_command = self.exit_if_error(error_threshold=1)
        return unwtar_command, check_error_level_command

    def wait_for_child_processes(self):
        return ("echo wait_for_child_processes not implemented yet for windows",)

    def chmod(self, new_mode, file_path):
        raise NotImplementedError

    def make_executable(self, file_path):
        raise NotImplementedError

    def unlock(self, file_path, recursive=False, ignore_errors=True):
        recurse_flag = ""
        if recursive:
            recurse_flag = "/S /D"
        writable_command = " ".join(("$(ATTRIB_PATH)", "-R", recurse_flag, utils.quoteme_double(file_path)))
        return writable_command

    def touch(self, file_path):
        touch_command = " ".join(("type", "NUL", ">", utils.quoteme_double(file_path)))
        return touch_command

    def run_instl(self):
        command_prefix = ""
        if not getattr(sys, 'frozen', False):
            command_prefix = "python3 "
        instl_command = command_prefix + '"$(__INSTL_EXE_PATH__)"'
        return instl_command

    def create_folders(self, info_map_file):
        create_folders_command = super().create_folders(info_map_file)
        return create_folders_command, self.exit_if_error()

    def append_file_to_file(self, source_file, target_file):
        append_command = " ".join(("type", utils.quoteme_double(source_file), ">>", utils.quoteme_double(target_file)))
        return append_command

    def chown(self, user_id, group_id, target_path, recursive=False):
        chown_command_parts = list()
        # icacls is actually somewhat between chmod and chown
        #chown_command_parts.append("icacls")
        #chown_command_parts.append(utils.quoteme_double(target_path))
        #chown_command_parts.append("/grant")
        #chown_command_parts.append("Users: (OI)(CI)F")
        #chown_command_parts.append("/T")
        chown_command_parts.append(self.echo("chown not implemented yet for Windows, "+target_path))
        chown_command = " ".join(chown_command_parts)
        return chown_command


class DownloadTool_win_wget(DownloadToolBase):
    def __init__(self, platform_helper):
        super().__init__(platform_helper)

    def download_url_to_file(self, src_url, trg_file):
        """ Create command to download a single file.
            src_url is expected to be already escaped (spaces as %20...)
        """
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--quiet")
        download_command_parts.append('--header "Accept-Encoding: gzip"'),
        download_command_parts.append("--connect-timeout")
        download_command_parts.append("3")
        download_command_parts.append("--read-timeout")
        download_command_parts.append("900")
        download_command_parts.append("-O")
        download_command_parts.append(utils.quoteme_double(trg_file))
        # urls need to escape spaces as %20, but windows batch files already escape % characters
        # so use urllib.quote to escape spaces and then change %20 to %%20.
        download_command_parts.append(utils.quoteme_double(src_url.replace("%", "%%")))
        return " ".join(download_command_parts), self.platform_helper.exit_if_error()

    def download_from_config_file(self, config_file):
        download_command_parts = list()
        download_command_parts.append("$(DOWNLOAD_TOOL_PATH)")
        download_command_parts.append("--read-timeout")
        download_command_parts.append("900")
        return " ".join(download_command_parts), self.platform_helper.exit_if_error()


class DownloadTool_win_curl(DownloadToolBase):
    def __init__(self, platform_helper):
        super().__init__(platform_helper)

    def download_url_to_file(self, src_url, trg_file):
        """ Create command to download a single file.
            src_url is expected to be already escaped (spaces as %20...)
        """
        connect_time_out = var_stack.ResolveVarToStr("CURL_CONNECT_TIMEOUT", "16")
        max_time = var_stack.ResolveVarToStr("CURL_MAX_TIME", "180")
        retries = var_stack.ResolveVarToStr("CURL_RETRIES", "2")
        retry_delay = var_stack.ResolveVarToStr("CURL_RETRY_DELAY", "8")

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
        download_command_parts.append("--retry-delay")
        download_command_parts.append(retry_delay)
        download_command_parts.append("write-out")
        download_command_parts.append(DownloadToolBase.curl_write_out_str)
        download_command_parts.append("-o")
        download_command_parts.append(utils.quoteme_double(trg_file))
        download_command_parts.append(utils.quoteme_double(src_url))
        return " ".join(download_command_parts)

    def download_from_config_files(self, parallel_run_config_file_path, config_files):
        import win32api
        with utils.utf8_open(parallel_run_config_file_path, "w") as wfd:
            utils.make_open_file_read_write_for_all(wfd)
            for config_file in config_files:
                # curl on windows has problem with path to config files that have unicode characters
                normalized_path = win32api.GetShortPathName(config_file)
                wfd.write(var_stack.ResolveStrToStr('''"$(DOWNLOAD_TOOL_PATH)" --config "{}"\n'''.format(normalized_path)))

        download_command = " ".join((self.platform_helper.run_instl(),  "parallel-run", "--in", utils.quoteme_double(parallel_run_config_file_path)))
        return download_command, self.platform_helper.exit_if_error()
