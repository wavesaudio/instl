#!/usr/bin/env python3

import re
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
from utils.multi_file import MultiFileReader


# noinspection PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences
class InstlMisc(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.curr_progress = 0
        self.total_progress = 0
        self.progress_staccato_command = False
        self.progress_staccato_period = 1
        self.progress_staccato_count = 0

    def do_command(self):
        self.curr_progress = int(var_stack.ResolveVarToStr("__START_DYNAMIC_PROGRESS__"))
        self.total_progress = int(var_stack.ResolveVarToStr("__TOTAL_DYNAMIC_PROGRESS__")) # if var does not exist default is 0, meaning not to display dynamic progress
        self.progress_staccato_period = int(var_stack.ResolveVarToStr("PROGRESS_STACCATO_PERIOD"))
        self.progress_staccato_count = 0
        do_command_func = getattr(self, "do_" + self.fixed_command)
        before_time = time.clock()
        do_command_func()
        after_time = time.clock()
        if utils.str_to_bool_int(var_stack.unresolved_var("PRINT_COMMAND_TIME")):
            print(self.the_command, "time:", round(after_time - before_time, 2), "sec.")

    def dynamic_progress(self, msg):
        if self.total_progress > 0:
            self.progress_staccato_count = (self.progress_staccato_count + 1) % self.progress_staccato_period
            self.curr_progress += 1
            if not self.progress_staccato_command or self.progress_staccato_count == 0:
                print("Progress: {self.curr_progress} of {self.total_progress}; {msg}".format(**locals()))

    def do_version(self):
        var_stack.set_var("PRINT_COMMAND_TIME").append("no") # do not print time report
        print(self.get_version_str())

    def do_help(self):
        import pyinstl.helpHelper
        var_stack.set_var("PRINT_COMMAND_TIME").append("no") # do not print time report

        help_folder_path = os.path.join(var_stack.ResolveVarToStr("__INSTL_DATA_FOLDER__"), "help")
        pyinstl.helpHelper.do_help(var_stack.ResolveVarToStr("__HELP_SUBJECT__"), help_folder_path, self)

    def do_parallel_run(self):
        processes_list_file = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        commands = list()
        with open(processes_list_file, "r", encoding='utf-8') as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        utils.run_processes_in_parallel(commands)

    def do_unwtar(self):
        self.no_artifacts = "__NO_WTAR_ARTIFACTS__" in var_stack
        what_to_work_on = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__", default='.')
        where_to_unwtar = None
        if "__MAIN_OUT_FILE__" in var_stack:
            where_to_unwtar = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")

        if os.path.isfile(what_to_work_on):
            if what_to_work_on.endswith(".wtar.aa"): # this case apparently is no longer relevant
                what_to_work_on = self.find_split_files(what_to_work_on)
                self.unwtar_a_file(what_to_work_on, where_to_unwtar)
            elif what_to_work_on.endswith(".wtar"):
                self.unwtar_a_file([what_to_work_on], where_to_unwtar)
        elif os.path.isdir(what_to_work_on):
            where_to_unwtar_the_file = None
            for root, dirs, files in os.walk(what_to_work_on, followlinks=False):
                # a hack to prevent unwtarring of the sync folder. Copy command might copy something
                # to the top level of the sync folder.
                if "bookkeeping" in dirs:
                    dirs[:] = []
                    continue

                tail_folder = root[len(what_to_work_on):].strip("\\/")
                if where_to_unwtar is not None:
                    where_to_unwtar_the_file = os.path.join(where_to_unwtar, tail_folder)
                for a_file in files:
                    a_file_path = os.path.join(root, a_file)
                    if a_file_path.endswith(".wtar.aa"):
                        split_files = self.find_split_files(a_file_path)
                        self.unwtar_a_file(split_files, where_to_unwtar_the_file)
                    elif a_file_path.endswith(".wtar"):
                        self.unwtar_a_file([a_file_path], where_to_unwtar_the_file)
                    
        else:
            raise FileNotFoundError(what_to_work_on)

    def unwtar_a_file(self, wtar_file_paths, destination_folder=None):
        manifest_file_name = var_stack.ResolveVarToStr("TAR_MANIFEST_FILE_NAME")

        if destination_folder is None:
            destination_folder, full_file_name_to_unwtar = os.path.split(wtar_file_paths[0])
        else:
            _, full_file_name_to_unwtar = destination_folder

        # we need the root folder name within the .wtar file to map the exact location of the manifest
        fname, _ = os.path.splitext(full_file_name_to_unwtar)

        try:
            with MultiFileReader("br", wtar_file_paths) as fd:
                with tarfile.open(fileobj=fd) as tar:
                    # first, let's try to read the manifest
                    try:
                        # per doc, extractall() is safer than extract().
                        # nevertheless, since we just read the manifest from memory, we don't care.
                        # we will care later with actual extract.
                        manifest_raw_content = tar.extractfile(os.path.join(fname, manifest_file_name))

                        # yeah, a manifest!
                        tar_content_per_manifest= {}
                        for line in manifest_raw_content.readlines():
                            line = line.decode('ascii').strip() # we know its ascii

                            # no remarks and no folders are needed
                            # because we always extract folders
                            if line.startswith('#') or line.endswith(os.sep):
                                continue

                            # that's what we want to have: Checksum, Path
                            # we didn't need size because we have member.size, brought to us for free
                            # this regex doesn't handle folders! (folders don't have checksum)
                            # but since we have excluded them up stairs, it's ok
                            m = re.search('(.*) ({}.*)'.format(fname), line)
                            if m:
                                tar_content_per_manifest[m.group(2)] = {
                                    'checksum': m.group(1)  # but we need checksum
                                }

                        # this will hold members that are different and thus need to be extracted
                        member_collection = []
                        for member in tar:
                            if member.name == os.path.join(fname, manifest_file_name):
                                # we don't want to extract the manifest again
                                continue

                            if member.isdir():
                                # folders are always welcome, especially empty ones
                                member_collection.append(member)
                                continue

                            existing_file_full_path = os.path.join(destination_folder, member.name)
                            if not os.path.isfile(existing_file_full_path):
                                # file doesn't exist. manifest or not, just extract.
                                member_collection.append(member)
                                continue

                            # at this point we have a file in the tar that exist on the file-system
                            if member.size == os.stat(existing_file_full_path).st_size:
                                # damn! same size. we must compare checksum
                                if tar_content_per_manifest[member.name]: # just to be on the safe side
                                    cs_ratsui = tar_content_per_manifest[member.name]['checksum']
                                    cs_matsui = utils.get_file_checksum(existing_file_full_path)
                                    if not cs_ratsui == cs_matsui:
                                        # not same cs? pile it up for extraction
                                        member_collection.append(member)

                                else:
                                    # did someone manually add a file to the tar?
                                    # this is strange! a file exists in tar but it's not in the manifest!
                                    member_collection.append(member)

                            else:
                                # different size? we want you
                                member_collection.append(member)
                                continue

                        # extracting only what we need
                        tar.extractall(destination_folder, members=member_collection)

                    except KeyError:
                        # that's ok, a manifest is optional. we'll extract everything
                        tar.extractall(destination_folder)

                        # oops, we have extracted the manifest as well
                        os.remove(os.path.join(destination_folder, fname, manifest_file_name))

            if self.no_artifacts:
                for wtar_file in wtar_file_paths:
                    os.remove(wtar_file)
            # self.dynamic_progress("Expanding {wtar_file_paths}".format(**locals()))

        except OSError as e:
            print("Invalid stream on split file with {}".format(wtar_file_paths[0]))
            raise e

        except tarfile.TarError:
            print("tarfile error while opening file", os.path.abspath(wtar_file_paths[0]))
            raise

    def find_split_files(self, first_file):
        try:
            norm_first_file = os.path.normpath(first_file) # remove trialing . if any
            base_folder, base_name = os.path.split(norm_first_file)
            if not base_folder: base_folder = "."
            filter_pattern = base_name[:-2] + "??"  # with ?? instead of aa
            matching_files = sorted(fnmatch.filter((f.name for f in os.scandir(base_folder)), filter_pattern))
            files_to_read = []
            for a_file in matching_files:
                files_to_read.append(os.path.join(base_folder, a_file))

            return files_to_read

        except Exception as es:
            print("exception while find_split_files", first_file)
            raise es

    def do_check_checksum(self):
        self.progress_staccato_command = True
        bad_checksum_list = list()
        self.read_info_map_from_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"))
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
        self.read_info_map_from_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"))
        for file_item in self.info_map_table.get_exec_items(what="file"):
            if os.path.isfile(file_item.path):
                file_stat = os.stat(file_item.path)
                os.chmod(file_item.path, file_stat.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            self.dynamic_progress("Set exec {file_item.path}".format(**locals()))

    def do_create_folders(self):
        self.progress_staccato_command = True
        self.read_info_map_from_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"))
        for dir_item in self.info_map_table.get_items(what="dir"):
            os.makedirs(dir_item.path, exist_ok=True)
            self.dynamic_progress("Create folder {dir_item.path}".format(**locals()))

    def do_test_import(self):
        import importlib

        bad_modules = list()
        for module in ("yaml", "appdirs", "configVar", "utils", "svnTree", "aYaml"):
            try:
                importlib.import_module(module)
            except ImportError:
                bad_modules.append(module)
        if len(bad_modules) > 0:
            print("missing modules:", bad_modules)
            sys.exit(17)

    def do_remove_empty_folders(self):
        folder_to_remove = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        files_to_ignore = var_stack.ResolveVarToList("REMOVE_EMPTY_FOLDERS_IGNORE_FILES")
        for root_path, dir_names, file_names in os.walk(folder_to_remove, topdown=False, onerror=None, followlinks=False):
            # when topdown=False os.walk creates dir_names for each root_path at the beginning and has
            # no knowledge if a directory has already been deleted.
            existing_dirs = [dir_name for dir_name in dir_names if os.path.isdir(os.path.join(root_path, dir_name))]
            if len(existing_dirs) == 0:
                ignored_files = list()
                for filename in file_names:
                    if filename in files_to_ignore:
                        ignored_files.append(filename)
                    else:
                        break
                if len(file_names) == len(ignored_files):
                    # only remove the ignored files if the folder is to be removed
                    for filename in ignored_files:
                        os.remove(os.path.join(root_path, filename))
                    os.rmdir(root_path)

    def do_win_shortcut(self):
        shortcut_path = var_stack.ResolveVarToStr("__SHORTCUT_PATH__")
        target_path = var_stack.ResolveVarToStr("__SHORTCUT_TARGET_PATH__")
        working_directory, target_name = os.path.split(target_path)
        run_as_admin = "__RUN_AS_ADMIN__" in var_stack
        from win32com.client import Dispatch

        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = target_path
        shortcut.WorkingDirectory = working_directory
        shortcut.save()
        if run_as_admin:
            import pythoncom
            from win32com.shell import shell, shellcon
            link_data = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLinkDataList)
            file = link_data.QueryInterface(pythoncom.IID_IPersistFile)
            file.Load(shortcut_path)
            flags = link_data.GetFlags()
            if not flags & shellcon.SLDF_RUNAS_USER:
                link_data.SetFlags(flags | shellcon.SLDF_RUNAS_USER)
                file.Save(shortcut_path, 0)

    def do_translate_url(self):
        url_to_translate = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        translated_url = connectionBase.connection_factory().translate_url(url_to_translate)
        print(translated_url)

    def do_mac_dock(self):
        path_to_item = var_stack.ResolveVarToStr("__DOCK_ITEM_PATH__", default="")
        label_for_item = var_stack.ResolveVarToStr("__DOCK_ITEM_LABEL__", default="")
        restart_the_doc = var_stack.ResolveVarToStr("__RESTART_THE_DOCK__", default="")
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
                    print("mac-dock confusing options, both --path and --restart were not supplied")
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

    def do_ls(self, collect='*'):
        if "__MAIN_OUT_FILE__" in var_stack:
            out_file = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
        else:
            out_file = "stdout"

        main_folder_to_list = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        folders_to_list = []
        if var_stack.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_stack.ResolveVarToList("__LIMIT_COMMAND_TO__")
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                folders_to_list.append(os.path.join(main_folder_to_list, limit))
        else:
            folders_to_list.append(main_folder_to_list)

        collect = var_stack.ResolveVarToStr("__OUTPUT_FORMAT__", default=collect)
        the_listing = utils.folder_listing(*folders_to_list, collect=collect)

        try:
            with utils.write_to_file_or_stdout(out_file) as wfd:
                wfd.write(the_listing)

        except NotADirectoryError:
            print("Cannot output to {}".format(out_file))

    def do_fail(self):
        exit_code = int(var_stack.ResolveVarToStr("__FAIL_EXIT_CODE__", default="1") )
        print("Failing on purpose with exit code", exit_code)
        sys.exit(exit_code)

    def do_checksum(self):
        path_to_checksum = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        if os.path.isfile(path_to_checksum):
            the_checksum = utils.get_file_checksum(path_to_checksum)
            print(": ".join((path_to_checksum, the_checksum)))
        elif os.path.isdir(path_to_checksum):
            for root, dirs, files in os.walk(path_to_checksum):
                for a_file in files:
                    a_file_path = os.path.join(root, a_file)
                    the_checksum = utils.get_file_checksum(a_file_path)
                    print(": ".join((a_file_path, the_checksum)))

    def do_resolve(self):
        var_stack.set_var("PRINT_COMMAND_TIME").append("no") # do not print time report
        config_file = var_stack.ResolveVarToStr("__CONFIG_FILE__")
        if not os.path.isfile(config_file):
            raise FileNotFoundError(config_file, var_stack.unresolved_var("__CONFIG_FILE__"))
        input_file = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        if not os.path.isfile(input_file):
            raise FileNotFoundError(input_file, var_stack.unresolved_var("__MAIN_INPUT_FILE__"))
        output_file = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
        self.read_yaml_file(config_file)
        with open(input_file, "r") as rfd:
            text_to_resolve = rfd.read()
        resolved_text = var_stack.ResolveStrToStr(text_to_resolve)
        with open(output_file, "w") as wfd:
            wfd.write(resolved_text)
