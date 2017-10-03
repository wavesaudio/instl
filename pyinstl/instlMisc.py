#!/usr/bin/env python3

import re
import os
import stat
import sys
import shlex
import tarfile
import time
import utils
from collections import OrderedDict
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack
from . import connectionBase


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
        self.commands_that_need_info_map_table = ("check_checksum", "set_exec", "create_folders")
        self.commands_that_need_items_table = ("exec")

    def get_default_out_file(self):
        retVal = None
        if self.fixed_command in ("ls", "resolve"):
            retVal = "stdout"
        return retVal

    def do_command(self):
        self.no_numbers_progress = "__NO_NUMBERS_PROGRESS__" in var_stack
        # if var does not exist default is 0, meaning not to display dynamic progress
        self.curr_progress = int(var_stack.ResolveVarToStr("__START_DYNAMIC_PROGRESS__", default="0"))
        self.total_progress = int(var_stack.ResolveVarToStr("__TOTAL_DYNAMIC_PROGRESS__", default="0"))
        self.progress_staccato_period = int(var_stack.ResolveVarToStr("PROGRESS_STACCATO_PERIOD"))
        self.progress_staccato_count = 0
        do_command_func = getattr(self, "do_" + self.fixed_command)
        before_time = time.clock()
        if self.fixed_command in self.commands_that_need_info_map_table:
            from svnTree import SVNTable
            self.info_map_table = SVNTable()
        if self.fixed_command in self.commands_that_need_items_table:
            self.init_items_table()
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
        elif self.no_numbers_progress:
            print("Progress: ... of ...; {msg}".format(**locals()))

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
        with utils.utf8_open(processes_list_file, "r") as rfd:
            for line in rfd:
                line = line.strip()
                if line and line[0] != "#":
                    args = shlex.split(line)
                    commands.append(args)
        utils.run_processes_in_parallel(commands)

    def do_wtar(self):
        """ Create a new wtar archive for a file or folder provided in '--in' command line option

            If --out is not supplied on the command line the new wtar file will be created
                next to the input with extension '.wtar'.
                e.g. the command:
                    instl wtar --in /a/b/c
                will create the wtar file at path:
                    /a/b/c.wtar

            If '--out' is supplied and it's an existing file, the new wtar will overwrite
                this existing file, wtar extension will NOT be added.
                e.g. assuming /d/e/f.txt is an existing file, the command:
                    instl wtar --in /a/b/c --out /d/e/f.txt
                will create the wtar file at path:
                    /d/e/f.txt

            if '--out' is supplied and is and existing folder the wtar file will be created
                inside this folder with extension '.wtar'.
                e.g. assuming /g/h/i is an existing folder, the command:
                    instl wtar --in /a/b/c --out /g/h/i
                will create the wtar file at path:
                    /g/h/i/c.wtar

            if '--out' is supplied and does not exists, the folder will be created
                and the wtar file will be created inside the new folder with extension
                 '.wtar'.
                e.g. assuming /j/k/l is a non existing folder, the command:
                    instl wtar --in /a/b/c --out /j/k/l
                will create the wtar file at path:
                    /j/k/l/c.wtar

            "total_checksum" field is added to the pax_headers. This checksum is a checksum of all individual
                file checksums as calculated by utils.get_recursive_checksums. See utils.get_recursive_checksums
                doc string for details on how checksums are calculated. Individual file checksums are not added
                to the pax_headers because during unwtarring tarfile code goes over all the pax_headers for each file
                making the process exponential slow for large archived.

            if wtar file(s) with the same base name as the --in file/folder, the total_checksum of the existing wtar
                will be checked against the total_checksum of the --in file/folder.
                If total_checksums are identical, the wtar
                will not be created. This will protect against new wtar being created when only the modification date of files
                in the --in file/folder has changed.
                If total_checksums are no identical the old wtar files wil be removed and a new war created. Removing the old wtars
                ensures that if the number of new wtar split files is smaller than the number of old split files, not extra files wil remain. E.g. if before [a.wtar.aa, a.wtar.ab, a.wtar.ac] and after  [a.wtar.aa, a.wtar.ab] a.wtar.ac will be removed.
            Format of the tar is PAX_FORMAT.
            Compression is bzip2.

        """
        what_to_work_on = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        if not os.path.exists(what_to_work_on):
            print(what_to_work_on, "does not exists")
            return

        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(what_to_work_on)

        where_to_put_wtar = None
        if "__MAIN_OUT_FILE__" in var_stack:
            where_to_put_wtar = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
        else:
            where_to_put_wtar = what_to_work_on_dir
            if not where_to_put_wtar:
                where_to_put_wtar = "."

        if os.path.isfile(where_to_put_wtar):
            target_wtar_file = where_to_put_wtar
        else:  # assuming it's a folder
            os.makedirs(where_to_put_wtar, exist_ok=True)
            target_wtar_file = os.path.join(where_to_put_wtar, what_to_work_on_leaf+".wtar")

        tar_total_checksum = utils.get_wtar_total_checksum(target_wtar_file)
        ignore_files = var_stack.ResolveVarToList("WTAR_IGNORE_FILES", default=list())
        with utils.ChangeDirIfExists(what_to_work_on_dir):
            pax_headers = {"total_checksum": utils.get_recursive_checksums(what_to_work_on_leaf, ignore=ignore_files)["total_checksum"]}

            def check_tarinfo(tarinfo):
                for ig in ignore_files:
                    if tarinfo.name.endswith(ig):
                        return None
                tarinfo.uid = tarinfo.gid = 0
                tarinfo.uname = tarinfo.gname = "waves"
                if os.path.isfile(tarinfo.path):
                    # wtar should to be idempotent. tarfile code adds "mtime" to
                    # each file's pax_headers. We add "checksum" to pax_headers.
                    # The result is that these two values are written to the tar
                    # file in no particular order and taring the same file twice
                    # might produce different results. By supplying the mtime
                    # ourselves AND passing an OrderedDict as the pax_headers
                    # hopefully the tar files will be the same each time.
                    file_pax_headers = OrderedDict()
                    file_pax_headers["checksum"] = utils.get_file_checksum(tarinfo.path)
                    mode_time = str(float(os.lstat(tarinfo.path)[stat.ST_MTIME]))
                    file_pax_headers["mtime"] = mode_time
                    tarinfo.pax_headers = file_pax_headers
                return tarinfo

            if pax_headers["total_checksum"] != tar_total_checksum:
                existing_wtar_parts = utils.find_split_files_from_base_file(what_to_work_on_leaf)
                [utils.safe_remove_file(f) for f in existing_wtar_parts]
                with tarfile.open(target_wtar_file, "w|bz2", format=tarfile.PAX_FORMAT, pax_headers=pax_headers) as tar:
                    tar.add(what_to_work_on_leaf, filter=check_tarinfo)
            else:
                print("{0} skipped since {0}.wtar already exists and has the same contents".format(what_to_work_on))

    def do_unwtar(self):
        self.no_artifacts = "__NO_WTAR_ARTIFACTS__" in var_stack
        what_to_work_on = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__", default='.')
        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(what_to_work_on)
        where_to_unwtar = None
        if "__MAIN_OUT_FILE__" in var_stack:
            where_to_unwtar = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
        ignore_files = var_stack.ResolveVarToList("WTAR_IGNORE_FILES", default=list())

        if os.path.isfile(what_to_work_on):
            if utils.is_first_wtar_file(what_to_work_on):
                utils.unwtar_a_file(what_to_work_on, where_to_unwtar, no_artifacts=self.no_artifacts, ignore=ignore_files)
        elif os.path.isdir(what_to_work_on):
            where_to_unwtar_the_file = None
            for root, dirs, files in os.walk(what_to_work_on, followlinks=False):
                # a hack to prevent unwtarring of the sync folder. Copy command might copy something
                # to the top level of the sync folder.
                if "bookkeeping" in dirs:
                    dirs[:] = []
                    print("skipping", root, "because bookkeeping folder was found")
                    continue

                tail_folder = root[len(what_to_work_on):].strip("\\/")
                if where_to_unwtar is not None:
                    where_to_unwtar_the_file = os.path.join(where_to_unwtar, tail_folder)
                for a_file in files:
                    a_file_path = os.path.join(root, a_file)
                    if utils.is_first_wtar_file(a_file_path):
                        utils.unwtar_a_file(a_file_path, where_to_unwtar_the_file, no_artifacts=self.no_artifacts, ignore=ignore_files)

        else:
            raise FileNotFoundError(what_to_work_on)
        self.dynamic_progress("Expand {}".format(utils.original_name_from_wtar_name(what_to_work_on_leaf)))

    def do_check_checksum(self):
        self.progress_staccato_command = True
        bad_checksum_list = list()
        missing_files_list = list()
        self.read_info_map_from_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"))
        for file_item in self.info_map_table.get_items(what="file"):
            if os.path.isfile(file_item.download_path):
                file_checksum = utils.get_file_checksum(file_item.download_path)
                if not utils.compare_checksums(file_checksum, file_item.checksum):
                    sigs = utils.create_file_signatures(file_item.download_path)
                    bad_checksum_list.append( " ".join(("Bad checksum:", file_item.download_path, "expected", file_item.checksum, "found", sigs["sha1_checksum"])) )
            else:
                missing_files_list.append(" ".join((file_item.download_path, "was not found")))
            self.dynamic_progress("Check checksum {file_item.path}".format(**locals()))
        if bad_checksum_list or missing_files_list:
            bad_checksum_list_exception_message = ""
            missing_files_exception_message = ""
            if bad_checksum_list:
                print("\n".join(bad_checksum_list))
                bad_checksum_list_exception_message += "Bad checksum for {} files".format(len(bad_checksum_list))
                print(bad_checksum_list_exception_message)
            if missing_files_list:
                print("\n".join(missing_files_list))
                missing_files_exception_message += "Missing {} files".format(len(missing_files_list))
                print(missing_files_exception_message)
            raise ValueError("\n".join((bad_checksum_list_exception_message, missing_files_exception_message)))

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
                        file_to_remove_full_path = os.path.join(root_path, filename)
                        os.remove(file_to_remove_full_path)
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

    def do_ls(self):
        main_folder_to_list = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        folders_to_list = []
        if var_stack.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_stack.ResolveVarToList("__LIMIT_COMMAND_TO__")
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                folders_to_list.append(os.path.join(main_folder_to_list, limit))
        else:
            folders_to_list.append(main_folder_to_list)

        ls_format = var_stack.ResolveVarToStr("LS_FORMAT", default='*')
        the_listing = utils.disk_item_listing(*folders_to_list, ls_format=ls_format)

        try:
            out_file = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
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
        ignore_files = var_stack.ResolveVarToList("WTAR_IGNORE_FILES", default=list())
        checksums_dict = utils.get_recursive_checksums(path_to_checksum, ignore=ignore_files)
        total_checksum = checksums_dict.pop('total_checksum', "Unknown total checksum")
        path_and_checksum_list = [(path, checksum) for path, checksum in sorted(checksums_dict.items())]
        width_list, align_list = utils.max_widths(path_and_checksum_list)
        col_formats = utils.gen_col_format(width_list, align_list)
        for p_and_c in path_and_checksum_list:
            print(col_formats[len(p_and_c)].format(*p_and_c))
        print()
        print(col_formats[len(p_and_c)].format("total checksum", total_checksum))

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
        with utils.utf8_open(input_file, "r") as rfd:
            text_to_resolve = rfd.read()
        resolved_text = var_stack.ResolveStrToStr(text_to_resolve)
        with utils.utf8_open(output_file, "w") as wfd:
            wfd.write(resolved_text)

    def do_exec(self):
        py_file_path = "unknown file"
        try:
            self.read_yaml_file("InstlClient.yaml")  # temp hack, which additional config file to read should come from command line options
            config_file = var_stack.ResolveVarToStr("__CONFIG_FILE__")
            if os.path.isfile(config_file):
                self.read_yaml_file(config_file)
            py_file_path = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
            with utils.utf8_open(py_file_path, 'r') as rfd:
                py_text = rfd.read()
                exec(py_text, globals())
        except Exception as ex:
            print("Exception while exec ", py_file_path, ex)
