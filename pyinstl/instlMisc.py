#!/usr/bin/env python3.6

import shlex
import threading
from collections import namedtuple

from .instlInstanceBase import InstlInstanceBase
from . import connectionBase
from pybatch import *
import utils
import psutil


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
        pass

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

        where_to_put_wtar = config_vars["__MAIN_OUT_FILE__"].Path(resolve=True)

        Wtar(what_to_wtar=what_to_work_on, where_to_put_wtar=where_to_put_wtar)()

    def do_unwtar(self):
        self.no_artifacts =  bool(config_vars["__NO_WTAR_ARTIFACTS__"])
        what_to_work_on = config_vars.get("__MAIN_INPUT_FILE__", os.curdir).Path()
        where_to_unwtar = config_vars.get("__MAIN_OUT_FILE__", None).Path()

        Unwtar(what_to_work_on, where_to_unwtar, self.no_artifacts)()

        self.dynamic_progress(f"unwtar {utils.original_name_from_wtar_name(what_to_work_on.name)}")

    def do_check_checksum(self):
        self.progress_staccato_command = True
        info_map_file = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        CheckDownloadFolderChecksum(info_map_file, print_report=True, raise_on_bad_checksum=True)()

    def do_test_import(self):
        import importlib

        bad_modules = list()
        for module in ("yaml", "appdirs", "configVar", "utils", "svnTree", "aYaml", "xmltodict"):
            try:
                importlib.import_module(module)
            except ImportError:
                bad_modules.append(module)
        if len(bad_modules) > 0:
            log.error(f"""missing modules {bad_modules}""")
            sys.exit(17)

    def do_translate_url(self):
        url_to_translate = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        translated_url = connectionBase.connection_factory(config_vars).translate_url(url_to_translate)
        print(translated_url)

    def do_ls(self):
        main_folder_to_list = config_vars["__MAIN_INPUT_FILE__"].Path()
        folders_to_list = []
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                folders_to_list.append(main_folder_to_list.joinpath(limit))
        else:
            folders_to_list.append(main_folder_to_list)

        ls_format = str(config_vars.get("LS_FORMAT", '*'))
        out_file = config_vars.get("__MAIN_OUT_FILE__", None).Path(resolve=True)

        for fold in folders_to_list:
            Ls(fold, out_file=out_file, ls_format=ls_format, out_file_append=True)()

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
        config_files = config_vars.get("__CONFIG_FILE__", []).list()
        input_file = config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)
        output_file = config_vars.get("__MAIN_OUT_FILE__", None).Path(resolve=True)
        config_vars["PRINT_COMMAND_TIME"] = "no" # do not print time report
        ResolveConfigVarsInFile(input_file, output_file, config_files=config_files)()

    def do_exec(self):
        try:
            py_file_path = config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)
            config_files = None
            if "__CONFIG_FILE__" in config_vars:
                config_files = [Path(config_file) for config_file in config_vars["__CONFIG_FILE__"].list()]

                for conf_file in config_files:
                    self.read_yaml_file(conf_file)
            with Exec(py_file_path, config_files, reuse_db=False, own_progress_count=0, report_own_progress=False) as exec_le:
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

        where_to_put_wzip = config_vars.get("__MAIN_OUT_FILE__", None).Path(resolve=True)

        Wzip(what_to_work_on, where_to_put_wzip)()

    def setup_abort_file_monitoring(self):
        def start_abort_file_thread(abort_file_path, time_to_sleep, exit_code):
            """ Open a thread to wtach the abort file
            """

            def abort_file_thread_func(_abort_file_path, _time_to_sleep, _exit_code):
                _abort_file_path = Path(_abort_file_path)
                while _abort_file_path.is_file():
                    time.sleep(_time_to_sleep)
                log.info(f"aborting because abort file not found {_abort_file_path}")

                current_process = psutil.Process()
                childern = current_process.children(recursive=True)
                for child in childern:
                    child.kill()
                os._exit(_exit_code)  # to kill the main thread see: https://docs.python.org/3.6/library/os.html#os._exit

            thread_name = "abort file monitor"
            x = threading.Thread(target=abort_file_thread_func, args=(abort_file_path, time_to_sleep, exit_code), daemon=True, name=thread_name)
            x.start()

        if 'ABORT_FILE' in config_vars:
            abort_file_path = config_vars["ABORT_FILE"].Path(resolve=True)
            log.info(f"watching abort file {abort_file_path}")
            start_abort_file_thread(abort_file_path=abort_file_path, time_to_sleep=1, exit_code=0)

    def do_run_process(self):
        """ run list of processes as specified in the input file
            input file can have two kinds of processes:
            1. command line, e.g. ls /etc
            2. echo statement, e.g. echo "a message"
            each line can also be followed by ">" or ">>" and path to a file, in which case
            output from the process or echo will go to that file. ">" will open the file in "w" mode, ">>" in "a" mode.
            if --abort-file argument is passed to run-process, the fiel specified will be watch and if and when it does not exist
            current running subprocess will be aborted and next processes will not be launched.
        """
        self.setup_abort_file_monitoring()

        list_of_argv = list()
        if "__MAIN_INPUT_FILE__" in config_vars:  # read commands from a file
            file_with_commands = config_vars["__MAIN_INPUT_FILE__"]
            with utils.utf8_open_for_read(file_with_commands, "r") as rfd:
                for line in rfd.readlines():
                    list_of_argv.append(shlex.split(line))
        else:    # read a command from argv
            list_of_argv.append(config_vars["RUN_PROCESS_ARGUMENTS"].list())

        RunProcessInfo = namedtuple('RunProcessInfo', ['process_name', 'argv', 'redirect_open_mode', 'redirect_path', 'stderr_means_err'])

        list_of_process_to_run_with_redirects = list()
        # find redirects
        for run_process_info in list_of_argv:
            stderr_means_err = True
            if "2>&1" in run_process_info:
                stderr_means_err = False
                run_process_info.remove("2>&1")

            if len(run_process_info) >= 3 and run_process_info[-2] in (">", ">>"):
                list_of_process_to_run_with_redirects.append(RunProcessInfo(process_name=run_process_info[0].strip(),
                                                                            argv=run_process_info[1:-2],
                                                                            redirect_open_mode={">": "w", ">>": "a"}[run_process_info[-2]],
                                                                            redirect_path=run_process_info[-1],
                                                                            stderr_means_err=stderr_means_err))
            else:
                list_of_process_to_run_with_redirects.append(RunProcessInfo(process_name=run_process_info[0].strip(),
                                                                            argv=run_process_info[1:],
                                                                            redirect_open_mode=None,
                                                                            redirect_path=None,
                                                                            stderr_means_err=stderr_means_err))

        for run_process_info in list_of_process_to_run_with_redirects:
            redirect_file = None
            if run_process_info.redirect_path:
                redirect_file = open(run_process_info.redirect_path, run_process_info.redirect_open_mode)

            print(run_process_info)
            if run_process_info.process_name.lower() == "echo":
                str_to_echo = " ".join(run_process_info.argv)
                if redirect_file:
                    redirect_file.write(f"{str_to_echo}\n")
                else:
                    sys.stdout.write(f"{str_to_echo}\n")
            else:
                log.info(f"Start running {run_process_info.process_name} with argv {run_process_info.argv}")
                with Subprocess(run_process_info.process_name,
                                *run_process_info.argv,
                                out_file=redirect_file,
                                stderr_means_err=run_process_info.stderr_means_err,
                                own_progress_count=0) as sub_proc:
                    sub_proc()
                log.info(f"Done running {run_process_info.process_name} with argv {run_process_info.argv}")

            if redirect_file:
                redirect_file.close()
