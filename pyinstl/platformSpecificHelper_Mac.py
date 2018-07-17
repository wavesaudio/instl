#!/usr/bin/env python3


import os
import datetime
from typing import List

import utils
from configVar import config_vars  # √
from .platformSpecificHelper_Base import PlatformSpecificHelperBase
from .platformSpecificHelper_Base import CopyToolRsync
from .platformSpecificHelper_Base import DownloadToolBase


class CopyToolMacRsync(CopyToolRsync):
    def __init__(self, platform_helper) -> None:
        super().__init__(platform_helper)


class PlatformSpecificHelperMac(PlatformSpecificHelperBase):
    def __init__(self, instlObj) -> None:
        super().__init__(instlObj)
        self.var_replacement_pattern = "${\g<var_name>}"
        self.echo_template = 'echo "{}"'
        self.batch_lines_id = 0

    def init_platform_tools(self):
        self.dl_tool = DownloadTool_mac_curl(self)

    def get_install_instructions_prefix(self, exit_on_errors=True):
        """ exec 2>&1 within a batch file will redirect stderr to stdout.
            .sync.sh >& out.txt on the command line will redirect stderr to stdout from without.
        """
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
        return ()

    def get_install_instructions_mkdir_with_owner_func(self):
        # -m will set the perm even if the dir exists
        # ignore error if owner cannot be changed
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
        self.invocations_file_path = config_vars["__INVOCATIONS_FILE_PATH__"].str()
        retVal = f"""
report_invocation_start() {{
    echo "--- {self.random_invocation_id}" >> "{self.invocations_file_path}"
    start_date=`date +%Y/%m/%d-%H:%M:%S`
    echo "start: $start_date" >> "{1}"
    echo "batch file: ${{BASH_SOURCE[0]}}" >> "{self.invocations_file_path}"
}}

report_invocation_end() {{
    echo "run time: $(convertsecs $Time_Measure_Diff)" >> "{self.invocations_file_path}"
    end_date=`date +%Y/%m/%d-%H:%M:%S`
    echo "end: $end_date" >> "{1}"
    echo "exit code: $1" >> "{1}"
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
        time_start_command = "Time_Measure_Start=$(date +%s)"
        return time_start_command

    def end_time_measure(self):
        time_end_commands = ('Time_Measure_End=$(date +%s)',
                             'Time_Measure_Diff=$(echo "$Time_Measure_End - $Time_Measure_Start" | bc)',
                             'convertsecs() { ((h=${1}/3600)) ; ((m=(${1}%3600)/60)) ; ((s=${1}%60)) ; printf "%02dh:%02dm:%02ds" $h $m $s ; }',
                             'echo $(__MAIN_COMMAND__) Time: $(convertsecs $Time_Measure_Diff)')
        return time_end_commands

    def mkdir(self, directory):
        mk_command = " ".join(("mkdir", "-p", "-m a+rwx", utils.quoteme_double(directory) ))
        return mk_command

    def mkdir_with_owner(self, directory, progress_num=0):
        mk_command = " ".join(("mkdir_with_owner", utils.quoteme_double(directory), str(progress_num) ))
        return mk_command

    def cd(self, directory):
        cd_command = " ".join(("cd", utils.quoteme_double(directory) ))
        return cd_command

    def pushd(self, directory):
        pushd_command = " ".join(("pushd", utils.quoteme_double(directory), ">", "/dev/null"))
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

    def rmdir(self, directory, recursive=False, check_exist=False):
        """ If recursive==False, only empty directory will be removed """
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
        rmfile_command_parts = list()
        norm_file = utils.quoteme(a_file, quote_char)
        if check_exist:
            rmfile_command_parts.extend(("[", "!", "-f", norm_file, "]", "||"))
        rmfile_command_parts.extend(("rm", "-f", norm_file))
        rmfile_command = " ".join(rmfile_command_parts)
        return rmfile_command

    def rm_file_or_dir(self, file_or_dir):
        # on mac rmdir -fr will remove a file or a directory without complaint.
        rm_command = self.rmdir(file_or_dir, recursive=True)
        return rm_command

    def get_svn_folder_cleanup_instructions(self):
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'

    def var_assign(self, identifier, value):
        quoter = '"'
        if '"' in value:
            quoter = "'"
            if "'" in value:
                print(value, """has both ' and " quote chars;""", "identifier:", identifier)
                return ()

        retVal = "".join((identifier, '=', quoter, value, quoter))
        return retVal

    def setup_echo(self):
        retVal = []
        echo_template = ['echo', '"{}"']
        if config_vars.defined('ECHO_LOG_FILE'):
            retVal.append(self.touch("$(ECHO_LOG_FILE)"))
            retVal.append(self.chmod("0666", "$(ECHO_LOG_FILE)"))
            echo_template.extend(("|", "tee", "-a", utils.quoteme_double("$(ECHO_LOG_FILE)")))
        self.echo_template = " ".join(echo_template)
        return retVal

    def echo(self, message):
        echo_command = self.echo_template.format(message)
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('#', remark))
        return remark_command

    def use_copy_tool(self, tool_name):
        if tool_name == "rsync":
            self.copy_tool = CopyToolMacRsync(self)
        else:
            raise ValueError(f"{tool_name} is not a valid copy tool for Mac OS")

    def copy_file_to_file(self, src_file, trg_file, hard_link=False, check_exist=False):
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
        resolve_command = " ".join(("resolve_symlinks", utils.quoteme_double(in_dir)))
        return resolve_command

    def check_checksum_for_file(self, file_path, checksum):
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
        if to_tar_name.endswith(".zip"):
            wtar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "-c", "-f", utils.quoteme_double(to_tar_name+'.wtar'), utils.quoteme_double(to_tar_name))
        else:
            wtar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "-c", "--use-compress-program bzip2", "-f", utils.quoteme_double(to_tar_name + '.wtar'), utils.quoteme_double(to_tar_name))
        wtar_command = " ".join(wtar_command_parts)
        return wtar_command

    def tar_with_instl(self, to_tar_name):
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
        split_command = " ".join(("split_file", utils.quoteme_double(file_to_split)))
        return split_command

    def wait_for_child_processes(self):
        return "wait",

    def chmod(self, new_mode, file_path):
        chmod_command = " ".join(("chmod", str(new_mode), utils.quoteme_double(file_path)))
        return chmod_command

    def make_executable(self, file_path):
        return self.chmod("a+x", file_path)

    def make_writable(self, file_path):
        return self.chmod("a+w", file_path)

    def unlock(self, file_path, recursive=False, ignore_errors=True):
        """ Remove the system's read-only flag, this is different from permissions.
            For changing permissions use chmod.
        """
        ignore_errors_flag = recurse_flag = ""
        if ignore_errors:
            ignore_errors_flag = "-f"
        if recursive:
            recurse_flag = "-R"
        nouchg_command = " ".join(("chflags", ignore_errors_flag, recurse_flag, "nouchg", utils.quoteme_double(file_path)))
        if ignore_errors: # -f is not enough in case the file does not exist, chflags will still exit with 1
            nouchg_command = " ".join((nouchg_command, "2>", "/dev/null", "||", "true"))
        return nouchg_command

    def touch(self, file_path):
        touch_command = " ".join(("touch", utils.quoteme_double(file_path)))
        return touch_command

    def append_file_to_file(self, source_file, target_file):
        append_command = " ".join(("cat", utils.quoteme_double(source_file), ">>", utils.quoteme_double(target_file)))
        return append_command

    def chown(self, user_id, group_id, target_path, recursive=False):
        chown_command_parts = list()
        chown_command_parts.append("chown")
        chown_command_parts.append("-f")
        if recursive:
            chown_command_parts.append("-R")
        chown_command_parts.append("".join((user_id, ":", group_id)))
        chown_command_parts.append(utils.quoteme_double(target_path))
        chown_command = " ".join(chown_command_parts)
        return chown_command


class DownloadTool_mac_curl(DownloadToolBase):
    def __init__(self, platform_helper) -> None:
        super().__init__(platform_helper)

    def download_url_to_file(self, src_url, trg_file):
        """ Create command to download a single file.
            src_url is expected to be already escaped (spaces as %20...)
        """
        connect_time_out = str(config_vars.setdefault("CURL_CONNECT_TIMEOUT", "16"))
        max_time = str(config_vars.setdefault("CURL_MAX_TIME", "180"))
        retries = str(config_vars.setdefault("CURL_RETRIES", "2"))
        retry_delay = str(config_vars.setdefault("CURL_RETRY_DELAY", "8"))

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

        with utils.utf8_open(parallel_run_config_file_path, "w") as wfd:
            utils.make_open_file_read_write_for_all(wfd)
            for config_file in config_files:
                wfd.write(config_vars.resolve_str(f'"$(DOWNLOAD_TOOL_PATH)" --config "{config_file}"\n'))

        download_command = " ".join((self.platform_helper.run_instl(),  "parallel-run", "--in", utils.quoteme_double(parallel_run_config_file_path)))
        return download_command
