#!/usr/bin/env python2.7
from __future__ import print_function

import os
import datetime

import utils
from configVar import var_stack
from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolRsync
from platformSpecificHelper_Base import DownloadToolBase


class CopyToolMacRsync(CopyToolRsync):
    def __init__(self, platform_helper):
        super(CopyToolMacRsync, self).__init__(platform_helper)


class PlatformSpecificHelperMac(PlatformSpecificHelperBase):
    def __init__(self, instlObj):
        super(PlatformSpecificHelperMac, self).__init__(instlObj)
        self.var_replacement_pattern = "${\g<var_name>}"
        self.echo_template = 'echo "{}"'

    def init_platform_tools(self):
        self.dl_tool = DownloadTool_mac_curl(self)

    def get_install_instructions_prefix(self):
        """ exec 2>&1 within a batch file will redirect stderr to stdout.
            .sync.sh >& out.txt on the command line will redirect stderr to stdout from without.
        """
        retVal = (
            "#!/usr/bin/env bash",
            self.remark(self.instlObj.get_version_str()),
            self.remark(datetime.datetime.today().isoformat()),
            "set -e",
            # "set -u",
            self.get_install_instructions_exit_func(),
            self.get_install_instructions_mkdir_with_owner_func(),
            self.get_resolve_symlinks_func(),
            self.save_dir("TOP_SAVE_DIR"),
            self.start_time_measure())
        return retVal

    def get_install_instructions_exit_func(self):
        retVal = (
            "exit_func() {",
            "CATCH_EXIT_VALUE=$?",
            "if [ ${CATCH_EXIT_VALUE} -ne 0 ]; then case $__MAIN_COMMAND__ in sync|copy|synccopy) ps -ax ;; esac; fi",
            self.restore_dir("TOP_SAVE_DIR"),
            self.end_time_measure(),
            self.echo("exit code ${CATCH_EXIT_VALUE}"),
            "exit ${CATCH_EXIT_VALUE}",
            "}",
            "trap \"exit_func\" EXIT")
        return retVal

    def get_install_instructions_postfix(self):
        return ()

    def get_install_instructions_mkdir_with_owner_func(self):
        retVal = (
            'mkdir_with_owner() {',
            'mkdir -p -m a+rwx "$1"',
            'chown $(__USER_ID__): "$1"',
            '}')
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
            '''find -P "$1" -type f -name '*.symlink' | while read readlink_file; do''',
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

    def mkdir_with_owner(self, directory):
        mk_command = " ".join(("mkdir_with_owner", utils.quoteme_double(directory) ))
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

    def rmdir(self, directory, recursive=False):
        """ If recursive==False, only empty directory will be removed """
        rmdir_command = ""
        if recursive:
            rmdir_command = " ".join(("rm", "-fr", utils.quoteme_double(directory) ))
        else:
            rmdir_command = " ".join(("rmdir", utils.quoteme_double(directory) ))
        return rmdir_command

    def rmfile(self, a_file):
        rmfile_command = " ".join(("rm", "-f", utils.quoteme_double(a_file) ))
        return rmfile_command

    def rm_file_or_dir(self, file_or_dir):
        # on mac rmdir -fr will remove a file or a directory without complaint.
        rm_command = self.rmdir(file_or_dir, recursive=True)
        return rm_command

    def get_svn_folder_cleanup_instructions(self):
        return 'find . -maxdepth 1 -mindepth 1 -type d -print0 | xargs -0 "$(SVN_CLIENT_PATH)" cleanup --non-interactive'

    def var_assign(self, identifier, value, comment=None):
        retVal = identifier + '="' + value + '"'
        if comment is not None:
            retVal += ' ' + self.remark(str(comment))
        return retVal

    def setup_echo(self):
        retVal = []
        echo_template = ['echo', '"{}"']
        if var_stack.defined('ECHO_LOG_FILE'):
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
            raise ValueError(tool_name, "is not a valid copy tool for Mac OS")

    def copy_file_to_file(self, src_file, trg_file, hard_link=False):
        if hard_link:
            copy_command = """ln -f "{src_file}" "{trg_file}" """.format(**locals())
        else:
            copy_command = """cp -f "{src_file}" "{trg_file}" """.format(**locals())
        return copy_command

    def resolve_symlink_files(self, in_dir="."):
        """ create instructions to turn .readlink files into symlinks.
            Main problem was with files that had space in their name, just
            adding \" was no enough, had to separate each step to a single line
            which solved the spaces problem. Also find returns an empty string
            even when there were no files found, and therefor the check
        """
        resolve_command = " ".join(("resolve_symlinks", utils.quoteme_double(in_dir) ))
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
        wtar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "-c", "--use-compress-program bzip2", "-f", utils.quoteme_double(to_tar_name+'.wtar'), utils.quoteme_double(to_tar_name))
        wtar_command = " ".join(wtar_command_parts)
        return wtar_command

    def unwtar_file(self, file_path):
        unwtar_command = " ".join(("$(WTAR_OPENER_TOOL_PATH)", "-x", "-f", utils.quoteme_double(file_path)))
        done_stamp_file = file_path + ".done"
        return unwtar_command, self.touch(done_stamp_file)

    def split_func(self):
        the_split_func = ("""
split_file()
{
    file_size=$(stat -f %z "$1")
    if [ "$(MIN_FILE_SIZE_TO_WTAR)" -lt "$file_size" ]
    then
        let "part_size=($file_size / (($file_size / $(MIN_FILE_SIZE_TO_WTAR)) + ($file_size % $(MIN_FILE_SIZE_TO_WTAR) > 0 ? 1 : 0)))+1"
        split -a 2 -b $part_size "$1" "$1."
        rm -fr "$1"
    fi
}
""")
        return the_split_func

    def split(self, file_to_split):
        split_command = " ".join(("split_file", utils.quoteme_double(file_to_split)))
        return split_command

    def wait_for_child_processes(self):
        return ("wait",)

    def chmod(self, new_mode, file_path):
        chmod_command = " ".join(("chmod", str(new_mode), utils.quoteme_double(file_path)))
        return chmod_command

    def make_executable(self, file_path):
        return self.chmod("a+x", file_path)

    def unlock(self, file_path, recursive=False):
        """ Remove the system's read-only flag, this is different from permissions.
            For changing permissions use chmod.
        """
        recurse_flag = ""
        if recursive:
            recurse_flag = "-R"
        nouchg_command = " ".join(("chflags", recurse_flag, "nouchg", utils.quoteme_double(file_path)))
        return nouchg_command

    def touch(self, file_path):
        touch_command = " ".join(("touch", utils.quoteme_double(file_path)))
        return touch_command

    def append_file_to_file(self, source_file, target_file):
        append_command = " ".join(("cat", utils.quoteme_double(source_file), ">>", utils.quoteme_double(target_file)))
        return append_command


class DownloadTool_mac_curl(DownloadToolBase):
    def __init__(self, platform_helper):
        super(DownloadTool_mac_curl, self).__init__(platform_helper)

    def download_url_to_file(self, src_url, trg_file):
        """ Create command to download a single file.
            src_url is expected to be already escaped (spaces as %20...)
        """
        connect_time_out = var_stack.resolve("$(CURL_CONNECT_TIMEOUT)", raise_on_fail=True)
        max_time = var_stack.resolve("$(CURL_MAX_TIME)", raise_on_fail=True)
        retries = var_stack.resolve("$(CURL_RETRIES)", raise_on_fail=True)
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
        download_command_parts.append(utils.quoteme_double(trg_file))
        download_command_parts.append(utils.quoteme_double(src_url))
        return " ".join(download_command_parts)

    def create_config_files(self, curl_config_file_path, num_files):
        import itertools

        num_urls_to_download = len(self.urls_to_download)
        if num_urls_to_download > 0:
            connect_time_out = var_stack.resolve("$(CURL_CONNECT_TIMEOUT)", raise_on_fail=True)
            max_time = var_stack.resolve("$(CURL_MAX_TIME)", raise_on_fail=True)
            retries = var_stack.resolve("$(CURL_RETRIES)", raise_on_fail=True)

            actual_num_files = max(0, min(num_urls_to_download, num_files))
            list_of_lines_for_files = [list() for i in range(actual_num_files)]
            list_for_file_cycler = itertools.cycle(list_of_lines_for_files)
            url_num = 0
            for url, path in self.urls_to_download:
                line_list = list_for_file_cycler.next()
                line_list.append('''url = "{url}"\noutput = "{path}"\n\n'''.format(**locals()))
                url_num += 1

            num_digits = len(str(actual_num_files))
            file_name_list = ["-".join( (curl_config_file_path, str(file_i).zfill(num_digits)) ) for file_i in xrange(actual_num_files)]

            lise_of_lines_iter = iter(list_of_lines_for_files)
            for file_name in file_name_list:
                with open(file_name, "w") as wfd:
                    utils.make_open_file_read_write_for_all(wfd)
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
                    list_of_lines = lise_of_lines_iter.next()
                    for line in list_of_lines:
                        wfd.write(line)

            return file_name_list
        else:
            return ()

    def download_from_config_files(self, parallel_run_config_file_path, config_files):

        with open(parallel_run_config_file_path, "w") as wfd:
            utils.make_open_file_read_write_for_all(wfd)
            for config_file in config_files:
                wfd.write(var_stack.resolve('"$(DOWNLOAD_TOOL_PATH)" --config "{config_file}"\n'.format(**locals()), raise_on_fail=True))

        download_command = " ".join( (self.platform_helper.run_instl(),  "parallel-run", "--in", utils.quoteme_double(parallel_run_config_file_path)) )
        return download_command
