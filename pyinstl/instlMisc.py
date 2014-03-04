#!/usr/bin/env python2.7

from __future__ import print_function

import shlex
import tarfile
import fnmatch

from pyinstl.utils import *
from instlInstanceBase import InstlInstanceBase
from pyinstl import svnTree
from configVarList import var_list

class InstlMisc(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlMisc, self).__init__(initial_vars)
        self.svnTree = svnTree.SVNTree()

    def do_command(self):
        the_command = var_list.get_str("__MAIN_COMMAND__")
        fixed_command = the_command.replace('-', '_')
        do_command_func = getattr(self, "do_"+fixed_command)
        do_command_func()

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
            for afile in files:
                afile_path = os.path.join(root, afile)
                wtar_file_path = None
                if afile_path.endswith(".wtar.aa"):
                    wtar_file_path = join_split_files(afile_path)
                elif afile_path.endswith(".wtar"):
                    wtar_file_path = afile_path
                if wtar_file_path:
                    done_file = wtar_file_path+".done"
                    if not os.path.isfile(done_file):
                        try:
                            with tarfile.open(wtar_file_path, "r") as tar:
                                tar.extractall(root)
                        except tarfile.ReadError as re_er:
                            print("tarfile read error while opening file", os.path.abspath(wtar_file_path))
                            raise
                        with open(done_file, "a"): os.utime(done_file, None)


def join_split_files(first_file):
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
        with open(done_file, "a"): os.utime(done_file, None)
        joined_file_done_path = joined_file_path+".done"
        if os.path.isfile(joined_file_done_path):
            os.remove(joined_file_done_path)
    return joined_file_path