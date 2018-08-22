#!/usr/bin/env python3.6


import os
import datetime

import utils
from configVar import config_vars  #  √
from .platformSpecificHelper_Base import PlatformSpecificHelperBase
from .platformSpecificHelper_Base import CopyToolRsync
from .platformSpecificHelper_Base import DownloadToolBase

from pybatch import *


class CopyToolMacRsync(CopyToolRsync):
    def __init__(self, platform_helper):
        super().__init__(platform_helper)


class PlatformSpecificHelperPython(PlatformSpecificHelperBase):
    var_name_counter = 0
    def __init__(self, instlObj, in_os):
        super().__init__(instlObj)
        self.var_replacement_pattern = "${\g<var_name>}"
        self.echo_template = 'echo "{}"'
        self.os = in_os

    def init_platform_tools(self):
        raise NotImplementedError
        self.dl_tool = DownloadTool_mac_curl(self)

    def get_install_instructions_prefix(self, exit_on_errors=True):
        """ exec 2>&1 within a batch file will redirect stderr to stdout.
            .sync.sh >& out.txt on the command line will redirect stderr to stdout from without.
        """
        retVal = AnonymousAccum()
        return retVal
        retVal = (
            "#!/usr/bin/env bash",
            self.remark(self.instlObj.get_version_str()),
            self.remark(datetime.datetime.today().isoformat()),
            "set -e" if exit_on_errors else "",
            "umask 0000",
            self.get_install_instructions_invocation_report_funcs(),
            self.get_install_instructions_exit_func(),
            self.get_install_instructions_mkdir_with_owner_func(),
            self.get_resolve_symlinks_func(),
            self.save_dir("TOP_SAVE_DIR"),
            self.start_time_measure(),
            "report_invocation_start")
        return retVal

    def get_install_instructions_exit_func(self):
        raise NotImplementedError
        retVal = (
            "exit_func() {",
            "CATCH_EXIT_VALUE=$?",
            "if [ ${CATCH_EXIT_VALUE} -ne 0 ]; then case $__MAIN_COMMAND__ in sync|copy|synccopy) ps -ax ;; esac; fi",
            self.restore_dir("TOP_SAVE_DIR"),
            self.end_time_measure(),
            'report_invocation_end "${CATCH_EXIT_VALUE}"',
            self.echo("exit code ${CATCH_EXIT_VALUE}"),
            "exit ${CATCH_EXIT_VALUE}",
            "}",
            "trap \"exit_func\" EXIT")
        return retVal

    def get_install_instructions_postfix(self):
        retVal = AnonymousAccum()
        return retVal

    def get_install_instructions_mkdir_with_owner_func(self):
        # -m will set the perm even if the dir exists
        # ignore error if owner cannot be changed
        raise NotImplementedError
        retVal = (
"""
mkdir_with_owner() {
if [[ ! -d "$1" ]]; then
    mkdir -p -m a+rwx "$1"
    if [[ "$2" -gt 0 ]]; then
        echo "Progress: $2 of $(TOTAL_ITEMS_FOR_PROGRESS_REPORT); Create folder $1"
    fi
else
    chmod a+rwx "$1"
fi
chown $(__USER_ID__): "$1" || true   
}
"""
        )
        return retVal

    def get_install_instructions_invocation_report_funcs(self):
        raise NotImplementedError
        self.invocations_file_path = config_vars["__INVOCATIONS_FILE_PATH__"].str()
        retVal = f"""
report_invocation_start() {{
    echo "--- {self.random_invocation_id}" >> "{self.invocations_file_path}"
    start_date=`date +%Y/%m/%d-%H:%M:%S`
    echo "start: $start_date" >> "{self.invocations_file_path}"
    echo "batch file: ${{BASH_SOURCE[0]}}" >> "{self.invocations_file_path}"
}}

report_invocation_end() {{
    echo "run time: $(convertsecs $Time_Measure_Diff)" >> "{self.invocations_file_path}"
    end_date=`date +%Y/%m/%d-%H:%M:%S`
    echo "end: $end_date" >> "{self.invocations_file_path}"
    echo "exit code: $1" >> "{self.invocations_file_path}"
    echo "---  {self.random_invocation_id}" >> "{self.invocations_file_path}"
}}
    """
        return retVal

    def get_resolve_symlinks_func(self):
        """ create instructions to turn .symlink files into real symlinks.
            Main problem was with files that had space in their name, just
            adding \" was no enough, had to separate each step to a single line
            which solved the spaces problem. Also find returns an empty string
            even when there were no files found, and therefor the check
        """
        raise NotImplementedError
        retVal = (
            '''resolve_symlinks() {''',
            '''find -P "$1" -type f -name '*.symlink'  -not -path "$(COPY_SOURCES_ROOT_DIR)*" | while read readlink_file; do''',
            '''     link_target=${readlink_file%%.symlink}''',
            '''     if [ ! -h "${link_target}" ]''',
            '''     then''',
            '''         symlink_contents=`cat "${readlink_file}"`''',
            '''         ln -sfh "${symlink_contents}" "${link_target}"''',
            '''     fi''',
            '''     rm -f "${readlink_file}"''',
            '''done }''')
        return retVal

    def start_time_measure(self):
        raise NotImplementedError
        time_start_command = "Time_Measure_Start=$(date +%s)"
        return time_start_command

    def end_time_measure(self):
        raise NotImplementedError
        time_end_commands = ('Time_Measure_End=$(date +%s)',
                             'Time_Measure_Diff=$(echo "$Time_Measure_End - $Time_Measure_Start" | bc)',
                             'convertsecs() { ((h=${1}/3600)) ; ((m=(${1}%3600)/60)) ; ((s=${1}%60)) ; printf "%02dh:%02dm:%02ds" $h $m $s ; }',
                             'echo $(__MAIN_COMMAND__) Time: $(convertsecs $Time_Measure_Diff)')
        return time_end_commands

    def mkdir(self, directory):
        python_batch_command = MakeDirs(directory)
        return python_batch_command

    def mkdir_with_owner(self, directory, progress_num=0):
        mk_command = " ".join(("mkdir_with_owner", utils.quoteme_double(directory), str(progress_num) ))
        return mk_command

    def cd(self, directory):
        raise NotImplementedError
        cd_command = " ".join(("cd", utils.quoteme_double(directory) ))
        return cd_command

    def pushd(self, directory):
        raise NotImplementedError
        pushd_command = " ".join(("pushd", utils.quoteme_double(directory), ">", "/dev/null"))
        return pushd_command

    def popd(self):
        raise NotImplementedError
        pop_command = " ".join(("popd", ">", "/dev/null"))
        return pop_command

    def save_dir(self, var_name):
        raise NotImplementedError
        save_dir_command = var_name + "=`pwd`"
        return save_dir_command

    def restore_dir(self, var_name):
        raise NotImplementedError
        restore_dir_command = self.cd("$(" + var_name + ")")
        return restore_dir_command

    def rmdir(self, directory, recursive=False, check_exist=False):
        """ If recursive==False, only empty directory will be removed """
        raise NotImplementedError
        rmdir_command_parts = list()
        norm_directory = utils.quoteme_double(directory)
        if check_exist:
            rmdir_command_parts.extend(("[", "!", "-d", norm_directory, "]", "||"))

        if recursive:
            rmdir_command_parts.extend(("rm", "-fr", norm_directory))
        else:
            rmdir_command_parts.extend(("rmdir", norm_directory))

        rmdir_command = " ".join(rmdir_command_parts)
        return rmdir_command

    def rmfile(self, a_file, quote_char='"', check_exist=False):
        python_batch_command = RmFile(a_file)
        return python_batch_command

    def rm_file_or_dir(self, file_or_dir):
        python_batch_command = RmFileOrDir(file_or_dir)
        return python_batch_command

    def get_svn_folder_cleanup_instructions(self):
        raise NotImplementedError
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'

    def var_assign(self, identifier, value):
        retVal = VarAssign(identifier, value)
        return retVal

    def setup_echo(self):
        retVal = AnonymousAccum()
        return retVal

    def echo(self, message):
        echo_command = Echo(message)
        return echo_command

    def remark(self, remark):
        remark_command = Remark(remark)
        return remark_command

    def use_copy_tool(self, tool_name):
        if tool_name == "rsync":
            self.copy_tool = CopyToolMacRsync(self)
        else:
            raise ValueError(f"{tool_name} is not a valid copy tool for Mac OS")

    def copy_file_to_file(self, src_file, trg_file, hard_link=False, check_exist=False):
        raise NotImplementedError
        if hard_link:
            copy_command = f"""ln -f "{src_file}" "{trg_file}" """
        else:
            copy_command = f"""cp -f "{src_file}" "{trg_file}" """
        if check_exist:
            copy_command += " || true"
        return copy_command

    def resolve_symlink_files(self, in_dir="$PWD"):
        """ create instructions to turn .symlinks files into real symlinks.
            Main problem was with files that had space in their name, just
            adding \" was no enough, had to separate each step to a single line
            which solved the spaces problem. Also find returns an empty string
            even when there were no files found, and therefor the check
        """
        raise NotImplementedError
        resolve_command = " ".join(("resolve_symlinks", utils.quoteme_double(in_dir)))
        return resolve_command

    def check_checksum_for_file(self, file_path, checksum):
        raise NotImplementedError
        check_command_parts = (  "CHECKSUM_CHECK=`$(CHECKSUM_TOOL_PATH) sha1",
                                 utils.quoteme_double(file_path),
                                 "` ;",
                                 "if [ ${CHECKSUM_CHECK: -40} !=",
                                 utils.quoteme_double(checksum),
                                 "];",
                                 "then",
                                 "echo bad checksum",
                                 utils.quoteme_double("${PWD}/" + file_path),
                                 "1>&2",
                                 ";",
                                 "exit 1",
                                 ";",
                                 "fi"
        )
        check_command = " ".join(check_command_parts)
        return check_command

    def tar(self, to_tar_name):
        raise NotImplementedError
        if to_tar_name.endswith(".zip"):
            wtar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "-c", "-f", utils.quoteme_double(to_tar_name+'.wtar'), utils.quoteme_double(to_tar_name))
        else:
            wtar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "-c", "--use-compress-program bzip2", "-f", utils.quoteme_double(to_tar_name + '.wtar'), utils.quoteme_double(to_tar_name))
        wtar_command = " ".join(wtar_command_parts)
        return wtar_command

    def tar_with_instl(self, to_tar_name):
        raise NotImplementedError
        if not config_vars.defined('__INSTL_LAUNCH_COMMAND__'):
            return # we cannot do anything without __INSTL_LAUNCH_COMMAND__

        tar_with_instl_command_parts = (config_vars["__INSTL_LAUNCH_COMMAND__"].str(),
                            "wtar",
                            "--in",
                            utils.quoteme_double(to_tar_name))
        return " ".join(tar_with_instl_command_parts)

    def split_func(self):
        the_split_func = ("""
split_file()
{
    if [ -f "$1" ]
    then
        file_size=$(stat -f %z "$1")
        if [ "$(MIN_FILE_SIZE_TO_WTAR)" -lt "$file_size" ]
        then
            let "part_size=($file_size / (($file_size / $(MIN_FILE_SIZE_TO_WTAR)) + ($file_size % $(MIN_FILE_SIZE_TO_WTAR) > 0 ? 1 : 0)))+1"
            split -a 2 -b $part_size "$1" "$1."
            rm -fr "$1"
        else
            mv "$1" "$1.aa"
        fi
    fi
}
""")
        return the_split_func

    def split(self, file_to_split):
        raise NotImplementedError
        split_command = " ".join(("split_file", utils.quoteme_double(file_to_split)))
        return split_command

    def wait_for_child_processes(self):
        raise NotImplementedError
        return "wait",

    def chmod(self, new_mode, file_path):
        python_batch_command = Chmod(file_path, new_mode)
        return python_batch_command

    def make_executable(self, file_path):
        python_batch_command = Chmod(file_path, 'a+x')
        return python_batch_command

    def make_writable(self, file_path):
        python_batch_command = Chmod(file_path, 'a+w')
        return python_batch_command

    def unlock(self, file_path, recursive=False, ignore_errors=True):
        """ Remove the system's read-only flag, this is different from permissions.
            For changing permissions use chmod.
        """
        python_batch_command = Unlock(file_path, recursive=recursive, ignore_errors=ignore_errors)
        return python_batch_command

    def touch(self, file_path):
        python_batch_command = Touch(file_path)
        return python_batch_command

    def append_file_to_file(self, source_file, target_file):
        python_batch_command = AppendFileToFile(source_file, target_file)
        return python_batch_command

    def chown(self, user_id, group_id, target_path, recursive=False):
        chown_command = Chown(user_id, group_id, target_path, recursive)
        return chown_command

    def shell_commands(self, the_lines: List[str]):
        retVal = list()
        # separate true shell commands from those starting with '!' which are
        # repr for one of the PythonBatchCommands

        true_shell_commands = list()
        for line in the_lines:
            if line.startswith('^'):
                if true_shell_commands:  # wrap up the true shell commands up till now
                    PlatformSpecificHelperPython.var_name_counter += 1
                    var_name = f"var_{PlatformSpecificHelperPython.var_name_counter:04}"
                    var = VarAssign(var_name, var_stack.ResolveListToList(true_shell_commands))
                    retVal.append(var)
                    batch = ShellCommands(dir="$(__MAIN_OUT_FILE_DIR__)", shell_commands_var_name=var_name)
                    retVal.append(batch)
                    true_shell_commands[:] = []
                retVal.append(GenericRepr(line[1:]))
            else:
                true_shell_commands.append(line)
        # wrap up the last true shell commands
        if true_shell_commands:
            PlatformSpecificHelperPython.var_name_counter += 1
            var_name = f"var_{PlatformSpecificHelperPython.var_name_counter:04}"
            var = VarAssign(var_name, var_stack.ResolveListToList(true_shell_commands))
            retVal.append(var)
            batch = ShellCommands(dir="$(__MAIN_OUT_FILE_DIR__)", shell_commands_var_name=var_name)
            retVal.append(batch)
        return retVal

    def progress(self, msg, num_items=0):
        """ do we need separate progress command for python-batch?"""
        progress_command = Progress(msg)
        return progress_command



