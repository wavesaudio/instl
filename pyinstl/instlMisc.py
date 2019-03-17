#!/usr/bin/env python3.6

from .instlInstanceBase import InstlInstanceBase
from . import connectionBase
from pybatch import *
import utils


# noinspection PyUnresolvedReferences,PyUnresolvedReferences,PyUnresolvedReferences
class InstlMisc(InstlInstanceBase):
    def __init__(self, initial_vars, command) -> None:
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_defaults_file(super().__thisclass__.__name__)
        self.curr_progress = 0
        self.total_progress = 0
        self.progress_staccato_command = False
        self.progress_staccato_period = 1
        self.progress_staccato_count = 0

    def get_default_out_file(self):
        if self.fixed_command in ("ls", "resolve"):
            if "__MAIN_OUT_FILE__" not in config_vars:
                config_vars["__MAIN_OUT_FILE__"] = "stdout"

    def do_command(self):
        self.no_numbers_progress =  bool(config_vars.get("__NO_NUMBERS_PROGRESS__", "False"))
        # if var does not exist default is 0, meaning not to display dynamic progress
        self.curr_progress = int(config_vars.get("__START_DYNAMIC_PROGRESS__", "0"))
        self.total_progress = int(config_vars.get("__TOTAL_DYNAMIC_PROGRESS__", "0"))
        self.progress_staccato_period = int(config_vars["PROGRESS_STACCATO_PERIOD"])
        self.progress_staccato_count = 0
        do_command_func = getattr(self, "do_" + self.fixed_command)
        before_time = time.perf_counter()
        do_command_func()
        after_time = time.perf_counter()
        if bool(config_vars["PRINT_COMMAND_TIME"]):
            log.info(f"""{self.the_command} time: {round(after_time - before_time, 4)} sec.""")

    def dynamic_progress(self, msg):
        if self.total_progress > 0:
            self.progress_staccato_count = (self.progress_staccato_count + 1) % self.progress_staccato_period
            self.curr_progress += 1
            if not self.progress_staccato_command or self.progress_staccato_count == 0:
                log.info(f"Progress: {self.curr_progress} of {self.total_progress}; {msg}")
        elif self.no_numbers_progress:
            log.info(f"Progress: ... of ...; {msg}")

    def do_version(self):
        config_vars["PRINT_COMMAND_TIME"] = "no" # do not print time report
        print(self.get_version_str())

    def do_help(self):
        import help.helpHelper
        config_vars["PRINT_COMMAND_TIME"] = "no" # do not print time report

        help_folder_path = config_vars["__INSTL_DATA_FOLDER__"].Path(resolve=True).joinpath("help")
        help.helpHelper.do_help(config_vars["__HELP_SUBJECT__"].str(), help_folder_path, self)

    def do_parallel_run(self):
        processes_list_file = config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)

        ParallelRun(processes_list_file, shell=False)()

    def do_wtar(self):
        what_to_work_on = config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)
        if not what_to_work_on.exists():
            log.error(f"""{what_to_work_on} does not exists""")
            return

        where_to_put_wtar = None
        if "__MAIN_OUT_FILE__" in config_vars:
            where_to_put_wtar = config_vars["__MAIN_OUT_FILE__"].Path(resolve=True)

        Wtar(what_to_wtar=what_to_work_on, where_to_put_wtar=where_to_put_wtar)()

    def do_unwtar(self):
        self.no_artifacts =  bool(config_vars["__NO_WTAR_ARTIFACTS__"])
        what_to_work_on = str(config_vars.get("__MAIN_INPUT_FILE__", os.curdir))
        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(what_to_work_on)
        where_to_unwtar = None
        if "__MAIN_OUT_FILE__" in config_vars:
            where_to_unwtar = os.fspath(config_vars["__MAIN_OUT_FILE__"])

        Unwtar(what_to_work_on, where_to_unwtar, self.no_artifacts)()

        self.dynamic_progress(f"unwtar {utils.original_name_from_wtar_name(what_to_work_on_leaf)}")

    def do_check_checksum(self):
        self.progress_staccato_command = True
        info_map_file = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        CheckDownloadFolderChecksum(info_map_file, print_report=True, raise_on_bad_checksum=True)()

    def do_set_exec(self):
        self.progress_staccato_command = True
        info_map_file = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        SetExecPermissionsInSyncFolder(info_map_file)

    def do_create_folders(self):
        self.progress_staccato_command = True
        self.info_map_table.read_from_file(os.fspath(config_vars["__MAIN_INPUT_FILE__"]))
        dir_items = self.info_map_table.get_items(what="dir")
        MakeDirs(*dir_items)
        self.dynamic_progress(f"Create folder {dir_item.path}")

    def do_test_import(self):
        import importlib

        bad_modules = list()
        for module in ("yaml", "appdirs", "configVar", "utils", "svnTree", "aYaml"):
            try:
                importlib.import_module(module)
            except ImportError:
                bad_modules.append(module)
        if len(bad_modules) > 0:
            log.error(f"""missing modules {bad_modules}""")
            sys.exit(17)

    def do_remove_empty_folders(self):
        folder_to_remove = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        files_to_ignore = list(config_vars.get("REMOVE_EMPTY_FOLDERS_IGNORE_FILES", []))

        RemoveEmptyFolders(folder_to_remove, files_to_ignore=files_to_ignore)()

    def do_win_shortcut(self):
        shortcut_path = config_vars["__SHORTCUT_PATH__"].str()
        target_path = os.fspath(config_vars["__SHORTCUT_TARGET_PATH__"])
        run_as_admin =  bool(config_vars.get("__RUN_AS_ADMIN__", "False"))
        WinShortcut(shortcut_path, target_path, run_as_admin)()

    def do_translate_url(self):
        url_to_translate = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        translated_url = connectionBase.connection_factory(config_vars).translate_url(url_to_translate)
        print(translated_url)

    def do_mac_dock(self):
        path_to_item = str(config_vars.get("__DOCK_ITEM_PATH__", ""))
        label_for_item = str(config_vars.get("__DOCK_ITEM_LABEL__", ""))
        restart_the_doc = bool(config_vars["__RESTART_THE_DOCK__"])
        remove = bool(config_vars["__REMOVE_FROM_DOCK__"])

        MacDock(path_to_item, label_for_item, restart_the_doc, remove)()

    def do_ls(self):
        main_folder_to_list = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        folders_to_list = []
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                folders_to_list.append(os.path.join(main_folder_to_list, limit))
        else:
            folders_to_list.append(main_folder_to_list)

        ls_format = str(config_vars.get("LS_FORMAT", '*'))
        out_file = os.fspath(config_vars["__MAIN_OUT_FILE__"])

        Ls(*folders_to_list, out_file=out_file, ls_format=ls_format)()

    def do_fail(self):
        sleep_before_fail = int(config_vars.get("__FAIL_SLEEP_TIME__", "0") )
        log.error(f"""Sleeping for {sleep_before_fail} seconds""")
        time.sleep(sleep_before_fail)

        exit_code = int(config_vars.get("__FAIL_EXIT_CODE__", "1") )
        log.error(f"""Failing on purpose with exit code {exit_code}""")
        sys.exit(exit_code)

    def do_checksum(self):
        path_to_checksum = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        ignore_files = list(config_vars.get("WTAR_IGNORE_FILES", []))
        checksums_dict = utils.get_recursive_checksums(path_to_checksum, ignore=ignore_files)
        total_checksum = checksums_dict.pop('total_checksum', "Unknown total checksum")
        path_and_checksum_list = [(path, checksum) for path, checksum in sorted(checksums_dict.items())]
        width_list, align_list = utils.max_widths(path_and_checksum_list)
        col_formats = utils.gen_col_format(width_list, align_list)
        for p_and_c in path_and_checksum_list:
            print(col_formats[len(p_and_c)].format(*p_and_c))
        print()
        print(col_formats[2].format("total checksum", total_checksum))

    def do_resolve(self):
        config_file = config_vars.get("__CONFIG_FILE__", None).str()
        input_file = config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)
        output_file = config_vars["__MAIN_OUT_FILE__"].Path(resolve=True)
        config_vars["PRINT_COMMAND_TIME"] = "no" # do not print time report
        ResolveConfigVarsInFile(input_file, output_file, config_file=config_file)()

    def do_exec(self):
        try:
            py_file_path = config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)
            config_file = None
            if "__CONFIG_FILE__" in config_vars:
                config_file = config_vars.get("__CONFIG_FILE__").Path(resolve=True)

            with Exec(py_file_path, config_file, reuse_db=False, own_progress_count=0, report_own_progress=False) as exec_le:
                exec_le()
        except Exception as ex:
            log.error(f"""Exception while exec {py_file_path}, {ex}""")
            if bool(config_vars.get("EXIT_ON_EXEC_EXCEPTION", False)):
                raise

    def do_wzip(self):
        what_to_work_on = config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)
        if not what_to_work_on.exists():
            log.error(f"""{what_to_work_on} does not exists""")
            return

        where_to_put_wzip = None
        if "__MAIN_OUT_FILE__" in config_vars:
            where_to_put_wzip = config_vars["__MAIN_OUT_FILE__"].Path(resolve=True)

        Wzip(what_to_work_on, where_to_put_wzip)()

    def do_run_process(self):
        abort_file_path = None
        if 'ABORT_FILE' in config_vars:
            abort_file_path = config_vars["ABORT_FILE"].Path()
        print(f"""run-process: {config_vars.get("ABORT_FILE", '')} {config_vars["RUN_PROCESS_ARGUMENTS"].list()}""")
        utils.run_process(config_vars["RUN_PROCESS_ARGUMENTS"].list(), shell=True, abort_file=abort_file_path)
