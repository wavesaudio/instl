#!/usr/bin/env python3.12

import os
import sys
import re
import abc
from pathlib import Path
import appdirs
import urllib.error
import functools
import datetime
import time
import logging

import aYaml
import utils

from configVar import config_vars
from configVar import ConfigVarYamlReader

from . import connectionBase
from db import DBManager
from pybatch import *

from .curlHelper import CUrlHelper

log = logging.getLogger()


if False:
    # decorator to set the correct "doing" message
    class DoingDecorator:
        def __init__(self, message):
            self.message = message

        def __call__(self, func):
            def decorated_func(*args, **kwargs):
                print(f"going in {self.message}")
                retVal = func(*args, **kwargs)
                print(f"going out {self.message}")
            return decorated_func


def check_version_compatibility():
    retVal = True
    message = ""
    if "INSTL_MINIMAL_VERSION" in config_vars:
        cur_instl_ver = list(map(int, list(config_vars["__INSTL_VERSION__"])))
        required_instl_ver = list(map(int, list(config_vars["INSTL_MINIMAL_VERSION"])))
        retVal = cur_instl_ver >= required_instl_ver
        if not retVal:
            message = f"instl version {cur_instl_ver} < minimal required version {required_instl_ver}"
    return retVal, message


class IndexYamlReaderBase(DBManager, ConfigVarYamlReader):

    def __init__(self, config_vars, **kwargs) -> None:
        ConfigVarYamlReader.__init__(self, config_vars)

    def init_specific_doc_readers(self):
        ConfigVarYamlReader.init_specific_doc_readers(self)
        self.specific_doc_readers["!require"] = self.read_require
        self.specific_doc_readers["!index"] = self.read_index
        if "TARGET_OS" in config_vars:
            self.specific_doc_readers[config_vars.resolve_str("!index_$(TARGET_OS)")] = self.read_index
            if "!index_Mac" in self.specific_doc_readers and "!index_Win" in self.specific_doc_readers:
                raise AssertionError("both !index_Mac and !index_Win cannot be defined simultaneously")

    def read_index(self, a_node, *args, **kwargs):
        self.items_table.read_index_node(a_node, **kwargs)

    def read_require(self, a_node, *args, **kwargs):
        del args
        self.items_table.read_require_node(a_node, **kwargs)


# noinspection PyPep8Naming
class InstlInstanceBase(IndexYamlReaderBase, metaclass=abc.ABCMeta):
    """ Main object of instl. Keeps the state of variables and install index
        and knows how to create a batch file for installation. InstlInstanceBase
        must be inherited by platform specific implementations, such as InstlInstance_mac
        or InstlInstance_win.
    """
    # some commands need a fresh db file, so existing one will be erased,
    # other commands rely on the db file to exist. default is to not refresh
    commands_that_need_to_refresh_db_file = ['copy', 'sync', 'synccopy', 'uninstall', 'remove',
                                             'doit', 'read-yaml', 'translate-guids',
                                             'verify-repo', 'depend', 'fix-props', 'up2s3', 'activate-repo-rev',
                                             'short-index', 'up-short-index', 'report-versions']

    def __init__(self, initial_vars=None) -> None:
        self.total_self_progress = 0   # if > 0 output progress during run (as apposed to batch file progress)

        self.the_command = None
        self.fixed_command = None

        DBManager.__init__(self)
        IndexYamlReaderBase.__init__(self, config_vars)

        self.path_searcher = utils.SearchPaths(config_vars, "__SEARCH_PATHS__")
        self.url_translator = connectionBase.translate_url
        self.init_default_vars(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_defaults_file(super().__thisclass__.__name__)
        # initialize the search paths helper with the current directory and dir where instl is now
        self.path_searcher.add_search_path(Path.cwd())
        self.path_searcher.add_search_path(Path(config_vars["__ARGV__"][0]).resolve())
        self.path_searcher.add_search_path(config_vars["__INSTL_DATA_FOLDER__"].Path())

        self.batch_accum = PythonBatchCommandAccum()
        self.dl_tool = CUrlHelper()

        self.out_file_realpath = None
        self.internal_progress = 0  # progress of preparing installer NOT of the installation
        self.num_digits_repo_rev_hierarchy=None
        self.num_digits_per_folder_repo_rev_hierarchy=None
        self.update_mode = False
        self.python_batch_names = PythonBatchCommandBase.get_derived_class_names()

    def progress(self, *messages):
        if self.total_self_progress:
            self.internal_progress += 1
            if self.internal_progress >= self.total_self_progress:
                self.total_self_progress *= 5
            log.info(f"""Progress: {self.internal_progress} of {self.total_self_progress}; {" ".join(str(mes) for mes in messages)}""")

    def init_specific_doc_readers(self):
        IndexYamlReaderBase.init_specific_doc_readers(self)
        self.specific_doc_readers.pop("__no_tag__", None)
        self.specific_doc_readers.pop("__unknown_tag__", None)

        self.specific_doc_readers["!define"] = self.read_defines
        # !define_const is deprecated and read as non-const
        self.specific_doc_readers["!define_const"] = self.read_defines

        acceptables = list(config_vars.setdefault("ACCEPTABLE_YAML_DOC_TAGS", []))
        if "__INSTL_COMPILED__" in config_vars:
            if config_vars["__INSTL_COMPILED__"].str() == "True":
                acceptables.append("define_Compiled")
            else:
                acceptables.append("define_Uncompiled")
        for acceptibul in acceptables:
            if acceptibul.startswith("define_if_not_exist"):
                self.specific_doc_readers["!" + acceptibul] = self.read_defines_if_not_exist
            elif acceptibul.startswith("define"):
                self.specific_doc_readers["!" + acceptibul] = self.read_defines

    def get_version_str(self, short=False):
        if short:
            to_resolve_var = "__INSTL_VERSION_STR_SHORT__"
        else:
            to_resolve_var = "__INSTL_VERSION_STR_LONG__"
        instl_ver_str = config_vars[to_resolve_var].str()
        return instl_ver_str

    def init_default_vars(self, initial_vars):
        def get_now_date_time(val):
            return str(datetime.datetime.fromtimestamp(time.time()))
        config_vars.set_dynamic_var("__NOW__", get_now_date_time)

        config_vars.update(initial_vars)

        # settings these configVar requires setting global values in files.py as soon as possible
        config_vars["ACTING_UID"].set_callback_when_value_is_set(utils.set_active_user_or_group_config_var_callback),
        config_vars["ACTING_GID"].set_callback_when_value_is_set(utils.set_active_user_or_group_config_var_callback),

        # read defaults/main.yaml
        self.read_defaults_file("main", ignore_if_not_exist=False)

        # read defaults/compile-info.yaml
        self.read_defaults_file("compile-info")
        if "__COMPILATION_TIME__" not in config_vars:
            if bool(config_vars["__INSTL_COMPILED__"]):
                config_vars["__COMPILATION_TIME__"] = "unknown compilation time"
            else:
                config_vars["__COMPILATION_TIME__"] = "(not compiled)"

        self.read_user_config()

    #@DoingDecorator("read_defaults_file")
    def read_defaults_file(self, file_name, allow_reading_of_internal_vars=True, ignore_if_not_exist=True):
        """ read class specific file from defaults/class_name.yaml """
        name_specific_defaults_file_path = config_vars["__INSTL_DEFAULTS_FOLDER__"].Path().joinpath(file_name + ".yaml").resolve()
        self.read_yaml_file(name_specific_defaults_file_path, ignore_if_not_exist=ignore_if_not_exist, allow_reading_of_internal_vars=allow_reading_of_internal_vars)

    #@DoingDecorator("read_user_config")
    def read_user_config(self):
        user_config_path = config_vars["__USER_CONFIG_FILE_PATH__"].str()
        self.read_yaml_file(user_config_path, ignore_if_not_exist=True, allow_reading_of_internal_vars=True)

    def check_prerequisite_var_existence(self, prerequisite_vars):
        missing_vars = [var for var in prerequisite_vars if var not in config_vars]
        if len(missing_vars) > 0:
            msg = "Prerequisite variables were not defined: " + ", ".join(missing_vars)
            raise ValueError(msg)

    def init_from_cmd_line_options(self, cmd_line_options_obj):
        """ turn command line options into variables """

        if "__MAIN_COMMAND__" in config_vars:
            self.the_command = str(config_vars["__MAIN_COMMAND__"])
            self.fixed_command = self.the_command.replace('-', '_')
        # to do: in python3.8 with the new sqlite.backup function, memory database
        # can be writen to disk if needed

        db_need_refresh = cmd_line_options_obj.mode == "interactive" or self.the_command in self.commands_that_need_to_refresh_db_file
        DBManager.set_refresh_db_file(db_need_refresh)

        if hasattr(cmd_line_options_obj, "subject") and cmd_line_options_obj.subject is not None:
            config_vars["__HELP_SUBJECT__"] = cmd_line_options_obj.subject
        else:
            config_vars["__HELP_SUBJECT__"] = ""

        if cmd_line_options_obj.which_revision:
            config_vars["__WHICH_REVISION__"] = cmd_line_options_obj.which_revision[0]

        if cmd_line_options_obj.define:
            individual_definitions = cmd_line_options_obj.define[0].split(",")
            for definition in individual_definitions:
                name, value = definition.split("=")
                config_vars[name] = value

        self.get_default_out_file()

    def close(self):
        del self.info_map_table
        del self.items_table
        del self.db
        config_vars.print_statistics()

    def get_default_out_file(self) -> None:
        if "__MAIN_OUT_FILE__" not in config_vars:
            if "__MAIN_INPUT_FILE__" in config_vars:
                config_vars["__MAIN_OUT_FILE__"] = "$(__MAIN_INPUT_FILE__)-$(__MAIN_COMMAND__).$(BATCH_EXT)"

    def read_require(self, a_node, *args, **kwargs):
        del args
        self.items_table.read_require_node(a_node, **kwargs)

    def write_require_file(self, file_path, require_dict):
        with utils.utf8_open_for_write(file_path, "w") as wfd:

            require_define_dict = {"REQUIRE_REPO_REV": config_vars["MAX_REPO_REV"].str(),
                                   "REQUIRE_REPO_NAME": config_vars.get("REPO_NAME", "N/A").str(),
                                   "REQUIRE_SYNC_BASE_URL": config_vars.get("SYNC_BASE_URL", "N/A").str(),
                                   "REQUIRE_S3_BUCKET_NAME": config_vars.get("S3_BUCKET_NAME", "N/A").str(),
                                   }
            define_dict = aYaml.YamlDumpDocWrap(require_define_dict,
                                                '!define', "definitions",
                                                 explicit_start=True, sort_mappings=True)
            require_dict = aYaml.YamlDumpDocWrap(require_dict, '!require', "requirements",
                                                 explicit_start=True, sort_mappings=True)

            aYaml.writeAsYaml((define_dict, require_dict), wfd)

    internal_identifier_re = re.compile(r"""
                                        __                  # dunder here
                                        (?P<internal_identifier>\w*)
                                        __                  # dunder there
                                        """, re.VERBOSE)

    def resolve_defined_paths(self):
        self.path_searcher.add_search_paths(list(config_vars.setdefault("SEARCH_PATHS", [])))
        for path_var_to_resolve in list(config_vars.get("PATHS_TO_RESOLVE", [])):
            if path_var_to_resolve in config_vars:
                resolved_path = self.path_searcher.find_file(str(config_vars[path_var_to_resolve]),
                                                             return_original_if_not_found=True)
                config_vars[path_var_to_resolve] = resolved_path

    def read_include_node(self, i_node, *args, **kwargs):
        if i_node.isScalar():
            kwargs['original-path-to-file'] = i_node.value
            resolved_file_name = config_vars.resolve_str(i_node.value)
            self.read_yaml_file(resolved_file_name, *args, **kwargs)
        elif i_node.isSequence():
            for sub_i_node in i_node:
                self.read_include_node(sub_i_node, *args, **kwargs)
        elif i_node.isMapping():
            if "url" in i_node:
                file_was_downloaded_and_read = False
                kwargs['original-path-to-file'] = i_node["url"].value
                unresolved_url = i_node["url"].value
                resolved_file_url = config_vars.resolve_str(unresolved_url)
                expected_checksum = None
                if "checksum" in i_node:
                    expected_checksum = config_vars.resolve_str(i_node["checksum"].value)

                try:
                    file_path = utils.download_from_file_or_url(in_url=resolved_file_url,
                                                                config_vars=config_vars,
                                                                in_target_path=None,
                                                                translate_url_callback=connectionBase.translate_url,
                                                                cache_folder=self.get_aux_cache_dir(make_dir=True),
                                                                expected_checksum=expected_checksum)
                    self.read_yaml_file(file_path, *args, **kwargs)
                    file_was_downloaded_and_read = True
                except (FileNotFoundError, urllib.error.URLError):
                    ignore = kwargs.get('ignore_if_not_exist', False)
                    if ignore:
                        self.progress(f"'ignore_if_not_exist' specified, ignoring FileNotFoundError for {resolved_file_url}")
                    else:
                        raise

                if "copy" in i_node and file_was_downloaded_and_read:
                    self.batch_accum.set_current_section('post')
                    for copy_destination in i_node["copy"]:
                        need_to_copy = True
                        destination_file_resolved_path = utils.ExpandAndResolvePath(config_vars.resolve_str(copy_destination.value))
                        if destination_file_resolved_path.is_file() and expected_checksum is not None:
                            checksums_match = utils.check_file_checksum(file_path=destination_file_resolved_path, expected_checksum=expected_checksum)
                            need_to_copy = not checksums_match
                        if need_to_copy:
                            self.batch_accum += MakeDir(destination_file_resolved_path.parent, chowner=True)
                            self.batch_accum += CopyFileToFile(file_path, destination_file_resolved_path, hard_links=False, copy_owner=True)

    def create_variables_assignment(self, in_batch_accum):
        in_batch_accum.set_current_section('assign')
        #do_not_write_vars = [var.lower() for var in config_vars["DONT_WRITE_CONFIG_VARS"].list() + list(os.environ.keys())]
        do_not_write_vars = config_vars["DONT_WRITE_CONFIG_VARS"].list()
        if not bool(config_vars.get("WRITE_CONFIG_VARS_READ_FROM_ENVIRON_TO_BATCH_FILE", "no")):
            do_not_write_vars += [re.escape(a_var) for a_var in os.environ.keys()]

        regex = "|".join(do_not_write_vars)
        do_not_write_vars_regex = re.compile(regex, re.IGNORECASE)
        for identifier in config_vars.keys():
            if not do_not_write_vars_regex.fullmatch(identifier):
                value_list = list(config_vars[identifier])
                in_batch_accum += ConfigVarAssign(identifier, *value_list)

    def init_python_batch(self, in_batch_accum):
        in_batch_accum.set_current_section("begin")

        in_batch_accum += PythonDoSomething('''RsyncClone.add_global_ignore_patterns(config_vars.get("COPY_IGNORE_PATTERNS", []).list())''')
        in_batch_accum += PythonDoSomething('''RsyncClone.add_global_no_hard_link_patterns(config_vars.get("NO_HARD_LINK_PATTERNS", []).list())''')
        in_batch_accum += PythonDoSomething('''RsyncClone.add_global_no_flags_patterns(config_vars.get("NO_FLAGS_PATTERNS", []).list())''')

        if not self.update_mode:
            in_batch_accum += PythonDoSomething('''RsyncClone.add_global_avoid_copy_markers(config_vars.get("AVOID_COPY_MARKERS", []).list())''')

        in_batch_accum += PythonDoSomething(f'''RemoveEmptyFolders.set_a_kwargs_default("files_to_ignore", config_vars.get("REMOVE_EMPTY_FOLDERS_IGNORE_FILES", []).list())''')
        in_batch_accum += PythonDoSomething(f"""log.setLevel({config_vars.get("PYTHON_BATCH_LOG_LEVEL", 20)})""")

    def calc_user_cache_dir_var(self):
        if "USER_CACHE_DIR" not in config_vars:
            os_family_name = config_vars["__CURRENT_OS__"].str()
            match os_family_name:
                case "Mac":
                    user_cache_dir_param = "$(VENDOR_NAME)/$(INSTL_EXEC_DISPLAY_NAME)"
                    user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
                case "Win":
                    user_cache_dir = appdirs.user_cache_dir("$(INSTL_EXEC_DISPLAY_NAME)", "$(VENDOR_NAME)")
                case "Linux":
                    user_cache_dir_param = "$(VENDOR_NAME)/$(INSTL_EXEC_DISPLAY_NAME)"
                    user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
                case _:
                    raise RuntimeError(f"Unknown operating system {os_family_name}")
            config_vars["USER_CACHE_DIR"] = user_cache_dir

    def get_aux_cache_dir(self, make_dir=True):
        """ return a path where to download and cache files (but not installation artifacts)
            return LOCAL_REPO_REV_BOOKKEEPING_DIR if it's fully resolved (meaning we have values for
            S3_BUCKET_NAME, REPO_NAME, REPO_REV)
            otherwise return USER_CACHE_DIR
        """
        local_repo_rev_bookkeeping_dir = config_vars["LOCAL_REPO_REV_BOOKKEEPING_DIR"].str()
        if config_vars.is_str_resolved(local_repo_rev_bookkeeping_dir):
            aux_cache_dir = Path(local_repo_rev_bookkeeping_dir)
        else:
            aux_cache_dir = config_vars["USER_CACHE_DIR"].Path().joinpath("cache")
        if make_dir:
            with MakeDir(aux_cache_dir, report_own_progress=False) as md:
                md()
        return aux_cache_dir

    def get_default_sync_dir(self, continue_dir=None, make_dir=True):
        retVal = config_vars["USER_CACHE_DIR"].Path()
        if continue_dir:
            retVal = retVal.joinpath(continue_dir)
        if make_dir:
            with MakeDir(retVal, report_own_progress=False) as md:
                md()
        return retVal

    def relative_sync_folder_for_source(self, source):
        source_path, source_type = source[0], source[1]
        match source_type:
            case '!dir' | '!file':
                retVal = "/".join(source_path.split("/")[0:-1])
            case '!dir_cont':
                retVal = source_path
            case _:
                raise ValueError(f"unknown tag for source {source_path}: {source_type}")
        return retVal

    def relative_sync_folder_for_source_table(self, adjusted_source, source_type):
        match source_type:
            case '!dir' | '!file':
                retVal = "/".join(adjusted_source.split("/")[0:-1])
            case '!dir_cont':
                retVal = adjusted_source
            case _:
                raise ValueError(f"unknown tag for source {adjusted_source}: {source_type}")
        return retVal

    def write_batch_file(self, in_batch_accum, file_name_post_fix=""):
        assert "__MAIN_OUT_FILE__" in config_vars

        config_vars["TOTAL_ITEMS_FOR_PROGRESS_REPORT"] = in_batch_accum.total_progress_count()

        in_batch_accum.initial_progress = self.internal_progress
        self.create_variables_assignment(in_batch_accum)
        self.init_python_batch(in_batch_accum)

        exit_on_errors = self.the_command != 'uninstall'  # in case of uninstall, go on with batch file even if some operations failed

        final_repr = repr(in_batch_accum)

        out_file: Path = config_vars.get("__MAIN_OUT_FILE__", None).Path()
        if out_file:
            out_file = out_file.parent.joinpath(out_file.name+file_name_post_fix)
            with MakeDir(out_file.parent, report_own_progress=False) as md:
                md()
            self.out_file_realpath = os.fspath(out_file)
        else:
            self.out_file_realpath = "stdout"

        with utils.write_to_file_or_stdout(out_file) as fd:
            fd.write(final_repr)
            fd.write('\n')

        msg = " ".join(
            (self.out_file_realpath, str(in_batch_accum.total_progress_count()), "progress items"))
        log.info(msg)

    def run_batch_file(self):
        if self.out_file_realpath.endswith(".py"):
            with utils.utf8_open_for_read(self.out_file_realpath, 'r') as rfd:
                py_text = rfd.read()
                py_compiled = compile(py_text, os.fspath(self.out_file_realpath), mode='exec', flags=0, dont_inherit=False, optimize=2)
                exec(py_compiled, globals())

        else:
            from subprocess import Popen

            p = Popen([self.out_file_realpath], executable=self.out_file_realpath, shell=False)
            stdout, stderr = p.communicate()
            if stdout:
                print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)
            return_code = p.returncode
            if return_code != 0:
                raise SystemExit(self.out_file_realpath + " returned exit code " + str(return_code))

    def read_index(self, a_node, *args, **kwargs):
        self.progress("reading index.yaml")
        IndexYamlReaderBase.read_index(self, a_node, *args, **kwargs)
        repo_rev = str(config_vars.get("REPO_REV", "unknown"))
        self.progress("repo-rev", repo_rev)

    def find_cycles(self):
        try:
            from . import installItemGraph

            depend_graph = installItemGraph.create_dependencies_graph(self.items_table)
            depend_cycles = installItemGraph.find_cycles(depend_graph)
            if not depend_cycles:
                self.progress("No depend cycles found")
            else:
                self.progress(f"{len(depend_cycles)} depend cycles found")
                for cy in depend_cycles:
                    log.info(f"""depend cycle: {" -> ".join(cy)}""")
            inherit_graph = installItemGraph.create_inheritItem_graph(self.items_table)
            inherit_cycles = installItemGraph.find_cycles(inherit_graph)
            if not inherit_cycles:
                self.progress("No inherit cycles found")
            else:
                self.progress(f"{len(inherit_cycles)} inherit cycles found")
                for cy in inherit_cycles:
                    log.info(f"""inherit cycle: {" -> ".join(cy)}""")
        except ImportError:  # no installItemGraph, no worry
                log.info("Could not load installItemGraph")

    def needs(self, iid, all_iids_set=None, cache=None):
        if cache is None:
            cache = dict()
        if iid in cache:
            return list(sorted(cache[iid]))
        if all_iids_set is None:
            all_iids_set = set(self.items_table.get_all_iids())

        retVal = set()
        depends_from_db = sorted(self.items_table.get_resolved_details_value_for_iid(iid, 'depends',unique_values=True))
        for dep in depends_from_db:
            if dep in all_iids_set:
                retVal.add(dep)
                retVal.update(self.needs(dep, all_iids_set, cache))
            else:
                retVal.append(dep + "(missing)")
        cache[iid] = retVal
        return list(sorted(retVal))

    def needed_by(self, iid, graph=None):
        try:
            from . import installItemGraph
            if not graph:
                graph = installItemGraph.create_dependencies_graph(self.items_table)
            needed_by_list = installItemGraph.find_needed_by(graph, iid)
            return sorted(needed_by_list)
        except ImportError:  # no installItemGraph, no worry
            log.info("Could not load installItemGraph")
            return None

    def handle_yaml_read_error(self, **kwargs):
        try:
            the_node_stack = kwargs.get('node-stack', "unknown")
            position_in_file = getattr(the_node_stack, "start_mark", "unknown")
            original_path_to_file = utils.ExpandAndResolvePath(config_vars.resolve_str(kwargs.get('original-path-to-file', '')))
            yaml_read_errors = list()
            yaml_read_errors.append("yaml_read_error:")
            if os.fspath(original_path_to_file) not in position_in_file:
                yaml_read_errors.append(f"""    path-to-file: {original_path_to_file}""")
            yaml_read_errors.append(f"""    position-in-file: {position_in_file}""")
            yaml_read_errors.append(f"""    permissions: {utils.single_disk_item_listing(original_path_to_file)}""")
            yaml_read_errors.append(f"""    exception: {kwargs.get('exception', '')}""")

            log.error("\n".join(yaml_read_errors))
        except Exception as ex:
            pass

    def verify_actions(self, problem_messages_by_iid=None):
        self.progress("verify actions")
        self.items_table.activate_all_oses()
        actions_list = self.items_table.get_all_actions_from_index()
        all_pybatch_commands = self.python_batch_names
        # Each row has: original_iid, detail_name, detail_value, os_id, _id
        num_bad_actions = 0
        for row in actions_list:
            try:
                if row['detail_value']:  # it's OK for action to have None value, but no need to check them
                    actions = config_vars.resolve_str_to_list(row['detail_value'])
                    if actions:
                        for action in actions:
                            try:
                                EvalShellCommand(action, None, all_pybatch_commands, raise_on_error=True)
                            except ValueError as ve:
                                num_bad_actions += 1
                                logging.warning(f"syntax error for an action in IID '{row['original_iid']}': {row['detail_name']}: {row['detail_value']}")
                                if problem_messages_by_iid is not None:
                                    problem_messages_by_iid[row['original_iid']].append(f"syntax error for an action in IID '{row['original_iid']}': {row['detail_name']}: {row['detail_value']}")
            except Exception as ex:
                log.warning(f"Exception in verify_actions for IID '{row['original_iid']}': {row['detail_name']}")
                if problem_messages_by_iid is not None:
                    problem_messages_by_iid[row['original_iid']].append(f"Exception in verify_actions for IID '{row['original_iid']}': {row['detail_name']}; {ex}")
        self.progress(f"{num_bad_actions} bad actions found")

    def write_config_vars_to_file(self, path_to_config_vars_file):
        if path_to_config_vars_file:
            variables_as_yaml = config_vars.repr_for_yaml()
            yaml_doc = aYaml.YamlDumpDocWrap(variables_as_yaml, '!define', "",
                                             explicit_start=True, sort_mappings=True)
            with open(path_to_config_vars_file, "w") as wfd:
                aYaml.writeAsYaml(yaml_doc, wfd)
            self.progress(f"ConfigVar values written to {path_to_config_vars_file}")
