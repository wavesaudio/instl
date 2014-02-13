#!/usr/bin/env python2.7
from __future__ import print_function

import os
import urllib
import datetime
from pyinstl.utils import *

from platformSpecificHelper_Base import PlatformSpecificHelperBase
from platformSpecificHelper_Base import CopyToolRsync
from platformSpecificHelper_Base import DownloadToolBase

class CopyToolMacRsync(CopyToolRsync):
    def __init__(self, platformHelper):
        super(CopyToolMacRsync, self).__init__(platformHelper)

class PlatformSpecificHelperMac(PlatformSpecificHelperBase):
    def __init__(self, instlObj):
        super(PlatformSpecificHelperMac, self).__init__(instlObj)
        self.var_replacement_pattern = "${\g<var_name>}"
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
            self.start_time_measure(),
            self.save_dir("TOP_SAVE_DIR"))
        return retVal

    def get_install_instructions_postfix(self):
        postfix_command = [self.restore_dir("TOP_SAVE_DIR")]
        postfix_command += self.end_time_measure()
        postfix_command += ("exit 0",)
        return postfix_command

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
        """ If recursive==False, only empty directory will be removed """
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

    def var_assign(self, identifier, value, comment=None):
        retVal = identifier+'="'+value+'"'
        if comment is not None:
            retVal += ' '+self.remark(str(comment))
        return retVal

    def echo(self, message):
        echo_command = " ".join(('echo', quoteme_double(message)))
        return echo_command

    def remark(self, remark):
        remark_command = " ".join(('#', remark))
        return remark_command

    def use_copy_tool(self, tool):
        if tool == "rsync":
            self.copy_tool = CopyToolMacRsync(self)
        else:
            raise ValueError(tool, "is not a valid copy tool for Mac OS")

    def copy_file_to_file(self, src_file, trg_file):
        sync_command = "cp -f \"{src_file}\" \"{trg_file}\"".format(**locals())
        return sync_command

    def resolve_symlink_files(self, in_dir="."):
        """ create instructions to turn .readlink files into symlinks.
            Main problem was with files that had space in their name, just
            adding \" was no enough, had to separate each step to a single line
            which solved the spaces problem. Also find returns an empty string
            even when there were no files found, and therefor the check
        """
        resolve_commands = ("""
find -P "%s" -type f -name '*.symlink' | while read readlink_file; do
    link_target=${readlink_file%%.*}
    if [ ! -h "${link_target}" ]
    then
        symlink_contents=`cat "${readlink_file}"`
        ln -sfh "${symlink_contents}" "${link_target}"
    fi
done""" % in_dir)
        return resolve_commands

    def check_checksum(self, filepath, checksum):
        check_command_parts = (  "CHECKSUM_CHECK=`$(CHECKSUM_TOOL_PATH) sha1",
                                quoteme_double(filepath),
                                "` ;",
                                "if [ ${CHECKSUM_CHECK: -40} !=",
                                quoteme_double(checksum),
                                "];",
                                "then",
                                "echo bad checksum",
                                quoteme_double("${PWD}/"+filepath),
                                "1>&2",
                                ";",
                                "exit 1",
                                ";",
                                "fi"
                            )
        check_command = " ".join( check_command_parts )
        return check_command

    def tar(self, to_tar_name):
        wtar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "-c", "-z", "-f", quoteme_double(to_tar_name+'.wtar'), quoteme_double(to_tar_name))
        wtar_command = " ".join( wtar_command_parts )
        return wtar_command

    def unwtar(self, filepath):
        unwtar_command_parts = ("$(WTAR_OPENER_TOOL_PATH)", "-x", "-f", quoteme_double(filepath))
        unwtar_command = " ".join( unwtar_command_parts )
        return unwtar_command

    def wait_for_child_processes(self):
        return ("wait",)

    def make_executable(self, filepath):
        make_exec_command = " ".join( ("chmod a+x", filepath) )
        return make_exec_command

class DownloadTool_mac_curl(DownloadToolBase):
    def __init__(self, platformHelper):
        super(DownloadTool_mac_curl, self).__init__(platformHelper)

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

    def create_config_files(self, curl_config_file_path, num_files):
        import itertools
        num_urls_to_download = len(self.urls_to_download)
        if num_urls_to_download > 0:
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
                wfd.write("connect-timeout = 3\n")
                wfd.write("max-time = 60\n")
                wfd.write("retry = 3\n")
                wfd.write("write-out = " + quoteme_double(os.path.basename(wfd.name)+": "+DownloadToolBase.curl_write_out_str))
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

        download_command = "\"$(__INSTL_EXE_PATH__)\" parallel-run --in \""+parallel_run_config_file_path+"\""
        return download_command
