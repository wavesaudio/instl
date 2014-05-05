#!/usr/bin/env python2.7

from __future__ import print_function

import shlex
import tarfile
import fnmatch
import time
import stat

from pyinstl.utils import *
from instlInstanceBase import InstlInstanceBase
from pyinstl import svnTree
from configVarList import var_list

class InstlMisc(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlMisc, self).__init__(initial_vars)
        self.svnTree = svnTree.SVNTree()

    def __del__(self):
        if self.curr_progress != self.actual_progress:
            print("curr_progress: {self.curr_progress} != actual_progress: {self.actual_progress}".format(**locals()))

    def do_command(self):
        the_command = var_list.get_str("__MAIN_COMMAND__")
        fixed_command = the_command.replace('-', '_')
        self.curr_progress =  int(var_list.get_str("__START_DYNAMIC_PROGRESS__")) + 1
        self.total_progress = int(var_list.get_str("__TOTAL_DYNAMIC_PROGRESS__"))
        self.progress_staccato_period = int(var_list.get_str("PROGRESS_STACCATO_PERIOD"))
        self.progress_staccato_count = 0
        self.actual_progress = 1
        self.progress_staccato_command = False
        do_command_func = getattr(self, "do_"+fixed_command)
        before_time = time.time()
        do_command_func()
        after_time = time.time()
        if the_command not in ("help", "version"):
            print(the_command, "time:", round(after_time - before_time, 2), "sec.")

    def dynamic_progress(self, msg):
        if self.total_progress > 0:
            self.progress_staccato_count = (self.progress_staccato_count + 1) % self.progress_staccato_period
            self.curr_progress += 1
            self.actual_progress += 1
            if not self.progress_staccato_command or self.progress_staccato_count == 0:
                print("Progress: {self.curr_progress} of {self.total_progress}; {msg}".format(**locals()))

    def do_version(self):
        print(self.get_version_str())

    def do_help(self):
        import pyinstl.helpHelper
        help_folder_path = os.path.join(var_list.resolve_string("$(__INSTL_DATA_FOLDER__)"), "help")
        pyinstl.helpHelper.do_help(var_list.get_str("__HELP_SUBJECT__"), help_folder_path)

    def do_parallel_run(self):
        processes_list_file = var_list.get_str("__MAIN_INPUT_FILE__")
        commands = list()
        with open(processes_list_file, "r") as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        from parallel_run import run_processes_in_parallel
        run_processes_in_parallel(commands)

    def do_unwtar(self):
        for root, dirs, files in os.walk(".", followlinks=False):
            files_to_unwtar = list()
            # find split files and join them
            for afile in files:
                afile_path = os.path.join(root, afile)
                if afile_path.endswith(".wtar.aa"):
                    files_to_unwtar.append(self.join_split_files(afile_path))

            # find unsplit wtar files
            for afile in files:
                afile_path = os.path.join(root, afile)
                if afile_path.endswith(".wtar"):
                    files_to_unwtar.append(afile_path)

            for wtar_file_path in files_to_unwtar:
                done_file = wtar_file_path+".done"
                if not os.path.isfile(done_file):
                    try:
                        with tarfile.open(wtar_file_path, "r") as tar:
                            tar.extractall(root)
                        self.dynamic_progress("unwtar {wtar_file_path}".format(**locals()))
                    except tarfile.ReadError as re_er:
                        print("tarfile read error while opening file", os.path.abspath(wtar_file_path))
                        raise
                    with open(done_file, "a"): os.utime(done_file, None)

    def join_split_files(self, first_file):
        base_folder, base_name = os.path.split(first_file)
        joined_file_path = first_file[:-3] # without the final '.aa'
        done_file = first_file+".done"
        if not os.path.isfile(done_file):
            filter_pattern = base_name[:-2]+"??" # with ?? instead of aa
            matching_files = sorted(fnmatch.filter(os.listdir(base_folder), filter_pattern))
            with open(joined_file_path, "wb") as wfd:
                for afile in matching_files:
                    with open(os.path.join(base_folder, afile), "rb") as rfd:
                        wfd.write(rfd.read())
            # create done file for the .wtar.aa file
            with open(done_file, "a"): os.utime(done_file, None)
            # now remove the done file for the newly created .wtar file
            joined_file_done_path = joined_file_path+".done"
            if os.path.isfile(joined_file_done_path):
                os.remove(joined_file_done_path)
            self.dynamic_progress("Merge wtar parts {first_file}".format(**locals()))
        return joined_file_path

    def do_check_checksum(self):
        self.progress_staccato_command = True
        bad_checksum_list = list()
        self.read_info_map_file(var_list.get_str("__MAIN_INPUT_FILE__"))
        for file_item in self.svnTree.walk_items(what="file"):
            file_path = file_item.full_path()
            if os.path.isfile(file_path):
                checkOK = check_file_checksum(file_path, file_item.checksum())
                if not checkOK:
                    sigs = create_file_signatures(file_path)
                    bad_checksum_list.append( " ".join(("Bad checksum:", file_path, "expected", file_item.checksum(), "found", sigs["sha1_checksum"])) )
            else:
                bad_checksum_list.append( " ".join((file_path, "does not exist")) )
            self.dynamic_progress("Check checksum {file_path}".format(**locals()))
        if bad_checksum_list:
            print("\n".join(bad_checksum_list))
            raise ValueError("Bad checksum for "+str(len(bad_checksum_list))+" files")

    def do_set_exec(self):
        self.progress_staccato_command = True
        self.read_info_map_file(var_list.get_str("__MAIN_INPUT_FILE__"))
        for file_item in self.svnTree.walk_items(what="file"):
            if file_item.isExecutable():
                file_path = file_item.full_path()
                if os.path.isfile(file_path):
                    file_stat = os.stat(file_path)
                    os.chmod(file_path, file_stat.st_mode | stat.S_IEXEC)
                self.dynamic_progress("Set exec {file_path}".format(**locals()))

    def do_create_folders(self):
        self.progress_staccato_command = True
        self.read_info_map_file(var_list.get_str("__MAIN_INPUT_FILE__"))
        for dir_item in self.svnTree.walk_items(what="dir"):
            dir_path = dir_item.full_path()
            safe_makedirs(dir_path)
            self.dynamic_progress("Create folder {dir_path}".format(**locals()))
