#!/usr/bin/env python3


import os
import stat
import sys
import shlex
import tarfile
import fnmatch
import time

import utils
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack
from . import connectionBase


class InstlMisc(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.curr_progress = 0
        self.actual_progress = 0
        self.total_progress = 0
        self.progress_staccato_command = False
        self.progress_staccato_period = 1
        self.progress_staccato_count = 0

    def __del__(self):
        if self.curr_progress != self.actual_progress:
            print("curr_progress: {self.curr_progress} != actual_progress: {self.actual_progress}".format(**locals()))

    def do_command(self):
        the_command = var_stack.resolve("$(__MAIN_COMMAND__)", raise_on_fail=True)
        fixed_command = the_command.replace('-', '_')
        self.curr_progress = int(var_stack.resolve("$(__START_DYNAMIC_PROGRESS__)")) + 1
        self.actual_progress = 1
        self.total_progress = int(var_stack.resolve("$(__TOTAL_DYNAMIC_PROGRESS__)"))
        self.progress_staccato_period = int(var_stack.resolve("$(PROGRESS_STACCATO_PERIOD)"))
        self.progress_staccato_count = 0
        do_command_func = getattr(self, "do_" + fixed_command)
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
        self.no_artifacts = "__NO_WTAR_ARTIFACTS__" in var_stack

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
                # find split files and join them, this must be done before looking for the joint .wtar files
                # so if previously the join failed and left a non-complete .wtar file, this .wtar will be overwritten
                for a_file in files:
                    a_file_path = os.path.join(root, a_file)
                    if a_file_path.endswith(".wtar.aa"):
                        joint_file = self.join_split_files(a_file_path)
                        files_to_unwtar.append(joint_file)

                # find unsplit wtar files
                for a_file in files:
                    a_file_path = os.path.join(root, a_file)
                    if a_file_path.endswith(".wtar"):
                        files_to_unwtar.append(a_file_path)

                for wtar_file_path in files_to_unwtar:
                    self.unwtar_a_file(wtar_file_path)
        else:
            print(what_to_work_on, "is not a file or directory")

    def unwtar_a_file(self, wtar_file_path):
        try:
            wtar_folder_path, _ = os.path.split(wtar_file_path)
            with tarfile.open(wtar_file_path, "r") as tar:
                tar.extractall(wtar_folder_path)
            if self.no_artifacts:
                os.remove(wtar_file_path)
            # self.dynamic_progress("Expanding {wtar_file_path}".format(**locals()))
        except tarfile.ReadError as re_er:
            print("tarfile read error while opening file", os.path.abspath(wtar_file_path))
            raise

    def join_split_files(self, first_file):
        joined_file_path = None
        try:
            norm_first_file = os.path.normpath(first_file) # remove trialing . if any
            base_folder, base_name = os.path.split(norm_first_file)
            if not base_folder:
                base_folder = "."
            joined_file_path = norm_first_file[:-3] # without the final '.aa'
            filter_pattern = base_name[:-2] + "??"  # with ?? instead of aa
            matching_files = sorted(fnmatch.filter(os.listdir(base_folder), filter_pattern))
            with open(joined_file_path, "wb") as wfd:
                for a_file in matching_files:
                    with open(os.path.join(base_folder, a_file), "rb") as rfd:
                        wfd.write(rfd.read())
            if self.no_artifacts:
                for a_file in matching_files:
                    os.remove(os.path.join(base_folder, a_file))
                    #self.dynamic_progress("removing {a_file}".format(**locals()))
            # self.dynamic_progress("joined {joined_file_path}".format(**locals()))
            return joined_file_path
        except BaseException as es:
            try: # try to remove the tar file
                os.remove(joined_file_path)
            except: # but no worry if file does not exist
                pass
            print("exception while join_split_files", first_file)
            raise es

    def do_check_checksum(self):
        self.progress_staccato_command = True
        bad_checksum_list = list()
        self.info_map_table.read_from_file(var_stack.resolve("$(__MAIN_INPUT_FILE__)", raise_on_fail=True))
        for file_item in self.info_map_table.get_items(what="file"):
            if os.path.isfile(file_item.path):
                file_checksum = utils.get_file_checksum(file_item.path)
                if not utils.compare_checksums(file_checksum, file_item.checksum):
                    sigs = utils.create_file_signatures(file_item.path)
                    bad_checksum_list.append( " ".join(("Bad checksum:", file_item.path, "expected", file_item.checksum, "found", sigs["sha1_checksum"])) )
            else:
                bad_checksum_list.append(" ".join((file_item.path, "does not exist")))
            self.dynamic_progress("Check checksum {file_item.path}".format(**locals()))
        if bad_checksum_list:
            print("\n".join(bad_checksum_list))
            raise ValueError("Bad checksum for " + str(len(bad_checksum_list)) + " files")

    def do_set_exec(self):
        self.progress_staccato_command = True
        self.info_map_table.read_from_file(var_stack.resolve("$(__MAIN_INPUT_FILE__)", raise_on_fail=True))
        for file_item in self.info_map_table.get_exec_items(what="file"):
            if os.path.isfile(file_item.path):
                file_stat = os.stat(file_item.path)
                os.chmod(file_item.path, file_stat.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            self.dynamic_progress("Set exec {file_item.path}".format(**locals()))

    def do_create_folders(self):
        self.progress_staccato_command = True
        self.info_map_table.read_from_file(var_stack.resolve("$(__MAIN_INPUT_FILE__)", raise_on_fail=True))
        for dir_item in self.info_map_table.get_items(what="dir"):
            utils.safe_makedirs(dir_item.path)
            self.dynamic_progress("Create folder {dir_item.path}".format(**locals()))

    def do_test_import(self):
        import importlib

        bad_modules = list()
        for module in ("yaml", "appdirs", "configVar", "utils", "svnTree", "aYaml"):
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
        target_path = var_stack.resolve("$(__SHORTCUT_TARGET_PATH__)", raise_on_fail=True)
        working_directory, target_name = os.path.split(target_path)
        from win32com.client import Dispatch

        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = target_path
        shortcut.WorkingDirectory = working_directory
        shortcut.save()

    def do_translate_url(self):
        url_to_translate = var_stack.resolve("$(__MAIN_INPUT_FILE__)")
        translated_url = connectionBase.connection_factory().translate_url(url_to_translate)
        print(translated_url)

    def do_mac_dock(self):
        path_to_item = var_stack.resolve("$(__DOCK_ITEM_PATH__)", default="")
        label_for_item = var_stack.resolve("$(__DOCK_ITEM_LABEL__)", default="")
        restart_the_doc = var_stack.resolve("$(__RESTART_THE_DOCK__)", default="")
        remove = "__REMOVE_FROM_DOCK__" in var_stack

        dock_util_command = list()
        if remove:
            dock_util_command.append("--remove")
            if label_for_item:
                dock_util_command.append(label_for_item)
            if not restart_the_doc:
                dock_util_command.append("--no-restart")
        else:
            if not path_to_item:
                if restart_the_doc:
                    dock_util_command.append("--restart")
                else:
                    print("mac-dock confusing options, both --path and --restart were not suppied")
            else:
                dock_util_command.append("--add")
                dock_util_command.append(path_to_item)
                if label_for_item:
                    dock_util_command.append("--label")
                    dock_util_command.append(label_for_item)
                    dock_util_command.append("--replacing")
                    dock_util_command.append(label_for_item)
        if not restart_the_doc:
            dock_util_command.append("--no-restart")
        utils.dock_util(dock_util_command)

    def do_ls(self):
        if "__MAIN_OUT_FILE__" in var_stack:
            out_file = var_stack.resolve("$(__MAIN_OUT_FILE__)")
        else:
            out_file = "stdout"

        main_folder_to_list = var_stack.resolve("$(__MAIN_INPUT_FILE__)")
        folders_to_list = []
        if var_stack.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_stack.resolve_to_list("$(__LIMIT_COMMAND_TO__)")
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                folders_to_list.append(os.path.join(main_folder_to_list, limit))
        else:
            folders_to_list.append(main_folder_to_list)

        the_listing = utils.folder_listing(folders_to_list)
        with utils.write_to_file_or_stdout(out_file) as wfd:
            wfd.write(the_listing)
