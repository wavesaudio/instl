#!/usr/bin/env python2.7

from __future__ import print_function

import shlex
import tarfile
import fnmatch
import time

import svnTree
import utils
from instlInstanceBase import InstlInstanceBase
from configVar import var_stack


class InstlMisc(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlMisc, self).__init__(initial_vars)
        self.svnTree = svnTree.SVNTree()

    def __del__(self):
        if self.curr_progress != self.actual_progress:
            print("curr_progress: {self.curr_progress} != actual_progress: {self.actual_progress}".format(**locals()))

    def do_command(self):
        the_command = var_stack.resolve("$(__MAIN_COMMAND__)", raise_on_fail=True)
        fixed_command = the_command.replace('-', '_')
        self.curr_progress =  int(var_stack.resolve("$(__START_DYNAMIC_PROGRESS__)")) + 1
        self.total_progress = int(var_stack.resolve("$(__TOTAL_DYNAMIC_PROGRESS__)"))
        self.progress_staccato_period = int(var_stack.resolve("$(PROGRESS_STACCATO_PERIOD)"))
        self.progress_staccato_count = 0
        self.actual_progress = 1
        self.progress_staccato_command = False
        do_command_func = getattr(self, "do_"+fixed_command)
        before_time = time.clock()
        do_command_func()
        after_time = time.clock()
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
        help_folder_path = os.path.join(var_stack.resolve("$(__INSTL_DATA_FOLDER__)", raise_on_fail=True), "help")
        pyinstl.helpHelper.do_help(var_stack.resolve("$(__HELP_SUBJECT__)", raise_on_fail=True), help_folder_path, self)

    def do_parallel_run(self):
        processes_list_file = var_stack.resolve("$(__MAIN_INPUT_FILE__)", raise_on_fail=True)
        commands = list()
        with open(processes_list_file, "r") as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        utils.run_processes_in_parallel(commands)

    def do_unwtar(self):
        self.no_artifacts = False
        if "__NO_WTAR_ARTIFACTS__" in var_stack:
            self.no_artifacts = True

        what_to_work_on = "."
        if "__MAIN_INPUT_FILE__" in var_stack:
            what_to_work_on = var_stack.resolve("$(__MAIN_INPUT_FILE__)")

        if os.path.isfile(what_to_work_on):
            if what_to_work_on.endswith(".wtar.aa"):
                what_to_work_on = self.join_split_files(what_to_work_on)
            if what_to_work_on.endswith(".wtar"):
                self.unwtar_a_file(what_to_work_on)
        elif os.path.isdir(what_to_work_on):
            for root, dirs, files in os.walk(what_to_work_on, followlinks=False):
                # a hack to prevent unwtarring of the sync folder. Copy command might copy something
                # to the top level of the sync folder.
                if "bookkeeping" in dirs:
                    dirs[:] = []
                    continue
                # unique_list so if both .wtar and .wtar.aa exists the list after joining will not have double entries
                files_to_unwtar = utils.unique_list()
                # find split files and join them
                for afile in files:
                    afile_path = os.path.join(root, afile)
                    if afile_path.endswith(".wtar.aa"):
                        joint_file = self.join_split_files(afile_path)
                        files_to_unwtar.append(joint_file)

                # find unsplit wtar files
                for afile in files:
                    afile_path = os.path.join(root, afile)
                    if afile_path.endswith(".wtar"):
                        files_to_unwtar.append(afile_path)

                for wtar_file_path in files_to_unwtar:
                    self.unwtar_a_file(wtar_file_path)
        else:
            print(what_to_work_on, "is not a file or directory")

    def unwtar_a_file(self, wtar_file_path):
        done_file = wtar_file_path+".done"
        if not os.path.isfile(done_file) or os.path.getmtime(done_file) < os.path.getmtime(wtar_file_path):
            try:
                wtar_folder_path, _ = os.path.split(wtar_file_path)
                with tarfile.open(wtar_file_path, "r") as tar:
                    tar.extractall(wtar_folder_path)
                if self.no_artifacts:
                    os.remove(wtar_file_path)
                self.dynamic_progress("Expanding {wtar_file_path}".format(**locals()))
            except tarfile.ReadError as re_er:
                print("tarfile read error while opening file", os.path.abspath(wtar_file_path))
                raise
            if not self.no_artifacts:
                with open(done_file, "a"): os.utime(done_file, None)

    def join_split_files(self, first_file):
        base_folder, base_name = os.path.split(first_file)
        joined_file_path = first_file[:-3] # without the final '.aa'
        done_file = first_file+".done"
        if not os.path.isfile(done_file) or os.path.getmtime(done_file) < os.path.getmtime(first_file):
            filter_pattern = base_name[:-2]+"??" # with ?? instead of aa
            matching_files = sorted(fnmatch.filter(os.listdir(base_folder), filter_pattern))
            with open(joined_file_path, "wb") as wfd:
                for afile in matching_files:
                    with open(os.path.join(base_folder, afile), "rb") as rfd:
                        wfd.write(rfd.read())
            if self.no_artifacts:
                for afile in matching_files:
                    os.remove(os.path.join(base_folder, afile))
            # create done file for the .wtar.aa file
            if not self.no_artifacts:
                with open(done_file, "a"): os.utime(done_file, None)
            # now remove the done file for the newly created .wtar file
            joined_file_done_path = joined_file_path+".done"
            if os.path.isfile(joined_file_done_path):
                os.remove(joined_file_done_path)
            self.dynamic_progress("Expanding {first_file}".format(**locals()))
        return joined_file_path

    def do_check_checksum(self):
        self.progress_staccato_command = True
        bad_checksum_list = list()
        self.read_info_map_file(var_stack.resolve("$(__MAIN_INPUT_FILE__)", raise_on_fail=True))
        for file_item in self.svnTree.walk_items(what="file"):
            file_path = file_item.full_path()
            if os.path.isfile(file_path):
                checkOK = check_file_checksum(file_path, file_item.checksum)
                if not checkOK:
                    sigs = create_file_signatures(file_path)
                    bad_checksum_list.append( " ".join(("Bad checksum:", file_path, "expected", file_item.checksum, "found", sigs["sha1_checksum"])) )
            else:
                bad_checksum_list.append( " ".join((file_path, "does not exist")) )
            self.dynamic_progress("Check checksum {file_path}".format(**locals()))
        if bad_checksum_list:
            print("\n".join(bad_checksum_list))
            raise ValueError("Bad checksum for "+str(len(bad_checksum_list))+" files")

    def do_set_exec(self):
        self.progress_staccato_command = True
        self.read_info_map_file(var_stack.resolve("$(__MAIN_INPUT_FILE__)", raise_on_fail=True))
        for file_item in self.svnTree.walk_items(what="file"):
            if file_item.isExecutable():
                file_path = file_item.full_path()
                if os.path.isfile(file_path):
                    file_stat = os.stat(file_path)
                    os.chmod(file_path, file_stat.st_mode | stat.S_IEXEC)
                self.dynamic_progress("Set exec {file_path}".format(**locals()))

    def do_create_folders(self):
        self.progress_staccato_command = True
        self.read_info_map_file(var_stack.resolve("$(__MAIN_INPUT_FILE__)", raise_on_fail=True))
        for dir_item in self.svnTree.walk_items(what="dir"):
            dir_path = dir_item.full_path()
            safe_makedirs(dir_path)
            self.dynamic_progress("Create folder {dir_path}".format(**locals()))

    def do_test_import(self):
        import importlib
        bad_modules = list()
        for module in ("yaml", "appdirs", "readline", "colorama", "rsa", "boto"):
            try:
                importlib.import_module(module)
            except ImportError as im_err:
                bad_modules.append(module)
        if len(bad_modules) > 0:
            print("missing modules:", bad_modules)
            sys.exit(17)

    def do_remove_empty_folders(self):
        folder_to_remove = var_stack.resolve("$(__MAIN_INPUT_FILE__)")
        files_to_ignore = var_stack.resolve_to_list("$(REMOVE_EMPTY_FOLDERS_IGNORE_FILES)")
        for rootpath, dirnames, filenames in os.walk(folder_to_remove, topdown=False, onerror=None, followlinks=False):
            # when topdown=False os.walk creates dirnames for each rootpath at the beginning and has
            # no knowledge if a directory has already been deleted.
            existing_dirs = [dirname for dirname in dirnames if os.path.isdir(os.path.join(rootpath, dirname))]
            if len(existing_dirs) == 0:
                ignored_files = list()
                for filename in filenames:
                    if filename in files_to_ignore:
                        ignored_files.append(filename)
                    else:
                        break
                if len(filenames) == len(ignored_files):
                    # only remove the ignored files if the folder is to be removed
                    for filename in ignored_files:
                        os.remove(os.path.join(rootpath, filename))
                    os.rmdir(rootpath)

    def do_win_shortcut(self):
        shortcut_path = var_stack.resolve("$(__SHORTCUT_PATH__)", raise_on_fail=True)
        target_path   = var_stack.resolve("$(__SHORTCUT_TARGET_PATH__)", raise_on_fail=True)
        working_directory, target_name = os.path.split(target_path)
        from win32com.client import Dispatch
        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = target_path
        shortcut.WorkingDirectory = working_directory
        shortcut.save()

    def do_translate_url(self):
        url_to_translate = var_stack.resolve("$(__MAIN_INPUT_FILE__)")
        translated_url = ConnectionBase.repo_connection.translate_url(url_to_translate)
        print(translated_url)
