#!/usr/bin/env python3.6


import os
import sys
import re
import abc
from pathlib import Path
import platform
import appdirs
import urllib.error
import io
import datetime
import time

import aYaml
import utils

from configVar import config_vars
from configVar import ConfigVarYamlReader

from . import connectionBase
from db import DBManager
from pybatch import *

from .curlHelper import CUrlHelper

log = logging.getLogger()


value_ref_re = re.compile("""
                            (?P<varref_pattern>
                                (?P<varref_marker>[$])      # $
                                \(                          # (
                                    (?P<var_name>[\w\s]+?|[\w\s(]+[\w\s)]+?)           # value
                                    (?P<varref_array>\[
                                        (?P<array_index>\d+)
                                    \])?
                                \)
                            )                         # )
                            """, re.X)


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


# noinspection PyPep8Naming
class InstlInstanceBase(DBManager, ConfigVarYamlReader, metaclass=abc.ABCMeta):
    """ Main object of instl. Keeps the state of variables and install index
        and knows how to create a batch file for installation. InstlInstanceBase
        must be inherited by platform specific implementations, such as InstlInstance_mac
        or InstlInstance_win.
    """
    # some commands need a fresh db file, so existing one will be erased,
    # other commands rely on the db file to exist. default is to not refresh
    commands_that_need_to_refresh_db_file = ['copy', 'sync', 'synccopy', 'uninstall', 'remove','doit', 'report-versions', 'exec', 'read-yaml']

    def __init__(self, initial_vars=None) -> None:
        self.total_self_progress = 0   # if > 0 output progress during run (as apposed to batch file progress)

        self.the_command = None
        self.fixed_command = None

        DBManager.__init__(self)
        ConfigVarYamlReader.__init__(self, config_vars)

        self.path_searcher = utils.SearchPaths(config_vars, "__SEARCH_PATHS__")
        self.url_translator = connectionBase.translate_url
        self.init_default_vars(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_defaults_file(super().__thisclass__.__name__)
        # initialize the search paths helper with the current directory and dir where instl is now
        self.path_searcher.add_search_path(os.getcwd())
        self.path_searcher.add_search_path(os.path.dirname(os.path.realpath(sys.argv[0])))
        self.path_searcher.add_search_path(config_vars["__INSTL_DATA_FOLDER__"].str())

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
                self.total_self_progress += 1000
            log.info(f"""Progress: {self.internal_progress} of {self.total_self_progress}; {" ".join(str(mes) for mes in messages)}""")

    def init_specific_doc_readers(self):
        ConfigVarYamlReader.init_specific_doc_readers(self)
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

        self.specific_doc_readers["!index"] = self.read_index
        self.specific_doc_readers["!require"] = self.read_require

    def get_version_str(self, short=False):
        instl_ver_str = ".".join(list(config_vars["__INSTL_VERSION__"]))
        if not short:
            if "__PLATFORM_NODE__" not in config_vars:
                config_vars.update({"__PLATFORM_NODE__": platform.node()})
            instl_ver_str = config_vars.resolve_str(
                "$(INSTL_EXEC_DISPLAY_NAME) version "+instl_ver_str+" $(__COMPILATION_TIME__) $(__PLATFORM_NODE__)")
        return instl_ver_str

    def init_default_vars(self, initial_vars):
        config_vars.update(initial_vars)

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

    def read_defaults_file(self, file_name, allow_reading_of_internal_vars=True, ignore_if_not_exist=True):
        """ read class specific file from defaults/class_name.yaml """
        name_specific_defaults_file_path = config_vars["__INSTL_DEFAULTS_FOLDER__"].Path().joinpath(file_name + ".yaml").resolve()
        self.read_yaml_file(name_specific_defaults_file_path, ignore_if_not_exist=ignore_if_not_exist, allow_reading_of_internal_vars=allow_reading_of_internal_vars)

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
        self.get_default_db_file()

    def close(self):
        del self.info_map_table
        del self.items_table
        del self.db
        config_vars.print_statistics()

    def get_default_out_file(self) -> None:
        if "__MAIN_OUT_FILE__" not in config_vars:
            if "__MAIN_INPUT_FILE__" in config_vars:
                config_vars["__MAIN_OUT_FILE__"] = "$(__MAIN_INPUT_FILE__)-$(__MAIN_COMMAND__).$(BATCH_EXT)"

    def get_default_db_file(self):
        if "__MAIN_DB_FILE__" not in config_vars:
            db_base_path = None
            if "__MAIN_OUT_FILE__" in config_vars:
                # try to set the db file next to the output file
                db_base_path = os.fspath(config_vars["__MAIN_OUT_FILE__"])
            elif "__MAIN_INPUT_FILE__" in config_vars:
                # if no output file try next to the input file
                db_base_path = config_vars.resolve_str("$(__MAIN_INPUT_FILE__)-$(__MAIN_COMMAND__)")
            else:
                # as last resort try the Logs folder on desktop if one exists
                logs_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Logs")
                if os.path.isdir(logs_dir):
                    db_base_path = config_vars.resolve_str(f"{logs_dir}/instl-$(__MAIN_COMMAND__)")

            if db_base_path:
                # set the proper extension
                db_base_path, ext = os.path.splitext(db_base_path)
                db_base_path = config_vars.resolve_str(f"{db_base_path}.$(DB_FILE_EXT)")
                config_vars["__MAIN_DB_FILE__"] = db_base_path
                if self.the_command in self.commands_that_need_to_refresh_db_file:
                    if os.path.isfile(db_base_path):
                        utils.safe_remove_file(db_base_path)
                        self.progress(f"removed previous db file {db_base_path}")

    def read_require(self, a_node, *args, **kwargs):
        del args
        self.items_table.read_require_node(a_node, **kwargs)

    def write_require_file(self, file_path, require_dict):
        with utils.utf8_open(file_path, "w") as wfd:
            utils.make_open_file_read_write_for_all(wfd, int(config_vars["__USER_ID__"]), int(config_vars["__GROUP_ID__"]))

            define_dict = aYaml.YamlDumpDocWrap({"REQUIRE_REPO_REV": config_vars["MAX_REPO_REV"].str()},
                                                '!define', "definitions",
                                                 explicit_start=True, sort_mappings=True)
            require_dict = aYaml.YamlDumpDocWrap(require_dict, '!require', "requirements",
                                                 explicit_start=True, sort_mappings=True)

            aYaml.writeAsYaml((define_dict, require_dict), wfd)

    internal_identifier_re = re.compile("""
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
                kwargs['original-path-to-file'] = i_node["url"].value
                resolved_file_url = config_vars.resolve_str(i_node["url"].value)
                expected_checksum = None
                if "checksum" in i_node:
                    expected_checksum = config_vars.resolve_str(i_node["checksum"].value)

                try:
                    file_path = utils.download_from_file_or_url(in_url=resolved_file_url,
                                                                config_vars=config_vars,
                                                                in_target_path=None,
                                                                translate_url_callback=connectionBase.translate_url,
                                                                cache_folder=self.get_default_sync_dir(continue_dir="cache", make_dir=True),
                                                                expected_checksum=expected_checksum)
                    self.read_yaml_file(file_path, *args, **kwargs)
                except (FileNotFoundError, urllib.error.URLError):
                    ignore = kwargs.get('ignore_if_not_exist', False)
                    if ignore:
                        self.progress(f"'ignore_if_not_exist' specified, ignoring FileNotFoundError for {resolved_file_url}")
                    else:
                        raise

                if "copy" in i_node:
                    self.batch_accum.set_current_section('post')
                    for copy_destination in i_node["copy"]:
                        need_to_copy = True
                        destination_file_resolved_path = utils.ResolvedPath(config_vars.resolve_str(copy_destination.value))
                        if destination_file_resolved_path.is_file() and expected_checksum is not None:
                            checksums_match = utils.check_file_checksum(file_path=destination_file_resolved_path, expected_checksum=expected_checksum)
                            need_to_copy = not checksums_match
                        if need_to_copy:
                            self.batch_accum += MakeDirs(destination_file_resolved_path.parent)
                            self.batch_accum += CopyFileToFile(file_path, destination_file_resolved_path, hard_links=False, copy_owner=True)

    def create_variables_assignment(self, in_batch_accum):
        in_batch_accum.set_current_section("assign")
        #do_not_write_vars = [var.lower() for var in config_vars["DONT_WRITE_CONFIG_VARS"].list() + list(os.environ.keys())]
        do_not_write_vars = config_vars["DONT_WRITE_CONFIG_VARS"].list()
        if not bool(config_vars.get("WRITE_CONFIG_VARS_READ_FROM_ENVIRON_TO_BATCH_FILE", "no")):
            do_not_write_vars += list(os.environ.keys())

        regex = "|".join(do_not_write_vars)
        do_not_write_vars_regex = re.compile(regex, re.IGNORECASE)
        for identifier in config_vars.keys():
            if not do_not_write_vars_regex.match(identifier):
                in_batch_accum += ConfigVarAssign(identifier, *list(config_vars[identifier]))

    def init_python_batch(self, in_batch_accum):
        in_batch_accum.set_current_section("begin")

        in_batch_accum += PythonDoSomething('''RsyncClone.add_global_ignore_patterns(config_vars.get("COPY_IGNORE_PATTERNS", []).list())''')
        in_batch_accum += PythonDoSomething('''RsyncClone.add_global_no_hard_link_patterns(config_vars.get("NO_HARD_LINK_PATTERNS", []).list())''')
        in_batch_accum += PythonDoSomething('''RsyncClone.add_global_no_flags_patterns(config_vars.get("NO_FLAGS_PATTERNS", []).list())''')

        if not self.update_mode:
            in_batch_accum += PythonDoSomething('''RsyncClone.add_global_avoid_copy_markers(config_vars.get("AVOID_COPY_MARKERS", []).list())''')

        in_batch_accum += PythonDoSomething(f'''RemoveEmptyFolders.set_a_kwargs_default("files_to_ignore", config_vars.get("REMOVE_EMPTY_FOLDERS_IGNORE_FILES", []).list())''')

    def calc_user_cache_dir_var(self, make_dir=True):
        if "USER_CACHE_DIR" not in config_vars:
            os_family_name = config_vars["__CURRENT_OS__"].str()
            if os_family_name == "Mac":
                user_cache_dir_param = "$(VENDOR_NAME)/$(INSTL_EXEC_DISPLAY_NAME)"
                user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
            elif os_family_name == "Win":
                user_cache_dir = appdirs.user_cache_dir("$(INSTL_EXEC_DISPLAY_NAME)", "$(VENDOR_NAME)")
            elif os_family_name == "Linux":
                user_cache_dir_param = "$(VENDOR_NAME)/$(INSTL_EXEC_DISPLAY_NAME)"
                user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
            else:
                raise RuntimeError(f"Unknown operating system {os_family_name}")
            config_vars["USER_CACHE_DIR"] = user_cache_dir
            #var_stack.get_configVar_obj("USER_CACHE_DIR").freeze_values_on_first_resolve = True
        if make_dir:
            user_cache_dir_resolved = os.fspath(config_vars["USER_CACHE_DIR"])
            os.makedirs(user_cache_dir_resolved, exist_ok=True)

    def get_default_sync_dir(self, continue_dir=None, make_dir=True):
        self.calc_user_cache_dir_var(make_dir)
        retVal = Path(os.fspath(config_vars["USER_CACHE_DIR"]))
        if continue_dir:
            retVal = retVal.joinpath(continue_dir)
        return retVal

    def relative_sync_folder_for_source(self, source):
        source_path, source_type = source[0], source[1]
        if source_type in ('!dir', '!file'):
            retVal = "/".join(source_path.split("/")[0:-1])
        elif source_type in ('!dir_cont', ):
            retVal = source_path
        else:
            raise ValueError(f"unknown tag for source {source_path}: {source_type}")
        return retVal

    def relative_sync_folder_for_source_table(self, adjusted_source, source_type):
        if source_type in ('!dir', '!file'):
            retVal = "/".join(adjusted_source.split("/")[0:-1])
        elif source_type in ('!dir_cont', ):
            retVal = adjusted_source
        else:
            raise ValueError(f"unknown tag for source {adjusted_source}: {source_type}")
        return retVal

    def write_batch_file(self, in_batch_accum, file_name_post_fix=""):
        assert "__MAIN_OUT_FILE__" in config_vars

        config_vars["TOTAL_ITEMS_FOR_PROGRESS_REPORT"] = in_batch_accum.total_progress_count()

        self.create_variables_assignment(in_batch_accum)
        self.init_python_batch(in_batch_accum)

        exit_on_errors = self.the_command != 'uninstall'  # in case of uninstall, go on with batch file even if some operations failed

        final_repr = repr(in_batch_accum)

        out_file = os.fspath(config_vars["__MAIN_OUT_FILE__"])
        out_file += file_name_post_fix
        out_file = os.path.abspath(out_file)
        d_path, f_name = os.path.split(out_file)
        os.makedirs(d_path, exist_ok=True)
        with utils.write_to_file_or_stdout(out_file) as fd:
            fd.write(final_repr)
            fd.write('\n')

        if out_file != "stdout":
            self.out_file_realpath = os.path.realpath(out_file)
            # chmod to 0777 so that file created under sudo, can be re-written under regular user.
            # However regular user cannot chmod for file created under sudo, hence the try/except
            try:
                os.chmod(self.out_file_realpath, 0o777)
            except Exception:
                pass
        else:
            self.out_file_realpath = "stdout"
        msg = " ".join(
            (self.out_file_realpath, str(in_batch_accum.total_progress_count()), "progress items"))
        log.info(msg)

    def run_batch_file(self):
        if self.out_file_realpath.endswith(".py"):
            with utils.utf8_open(self.out_file_realpath, 'r') as rfd:
                py_text = rfd.read()
                exec(py_text, globals())

        else:
            from subprocess import Popen

            p = Popen([self.out_file_realpath], executable=self.out_file_realpath, shell=False)
            unused_stdout, unused_stderr = p.communicate()
            return_code = p.returncode
            if return_code != 0:
                raise SystemExit(self.out_file_realpath + " returned exit code " + str(return_code))

    def read_index(self, a_node, *args, **kwargs):
        self.progress("reading index.yaml")
        self.items_table.read_index_node(a_node, **kwargs)
        #self.items_table.read_index_node_one_by_one(a_node, **kwargs)  # for debugging reading index.yaml
        repo_rev = str(config_vars.get("REPO_REV", "unknown"))
        self.progress("repo-rev", repo_rev)

    def find_cycles(self):
        try:
            from . import installItemGraph

            depend_graph = installItemGraph.create_dependencies_graph(self.items_table)
            depend_cycles = installItemGraph.find_cycles(depend_graph)
            if not depend_cycles:
                log.info("No depend cycles found")
            else:
                for cy in depend_cycles:
                    log.info(f"""depend cycle: {" -> ".join(cy)}""")
            inherit_graph = installItemGraph.create_inheritItem_graph(self.items_table)
            inherit_cycles = installItemGraph.find_cycles(inherit_graph)
            if not inherit_cycles:
                log.info("No inherit cycles found")
            else:
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

    def repo_rev_to_folder_hierarchy(self, repo_rev):
        retVal = str(repo_rev)
        try:
            if self.num_digits_repo_rev_hierarchy is None:
                self.num_digits_repo_rev_hierarchy=int(config_vars["NUM_DIGITS_REPO_REV_HIERARCHY"])
            if self.num_digits_per_folder_repo_rev_hierarchy is None:
                self.num_digits_per_folder_repo_rev_hierarchy=int(config_vars["NUM_DIGITS_PER_FOLDER_REPO_REV_HIERARCHY"])
            if self.num_digits_repo_rev_hierarchy > 0 and self.num_digits_per_folder_repo_rev_hierarchy > 0:
                zero_pad_repo_rev = str(repo_rev).zfill(self.num_digits_repo_rev_hierarchy)
                by_groups = [zero_pad_repo_rev[i:i+self.num_digits_per_folder_repo_rev_hierarchy] for i in range(0, len(zero_pad_repo_rev), self.num_digits_per_folder_repo_rev_hierarchy)]
                retVal = "/".join(by_groups)
        except Exception as ex:
            pass
        return retVal

    def handle_yaml_read_error(self, **kwargs):
        try:
            the_node_stack = kwargs.get('node-stack', "unknown")
            position_in_file = getattr(the_node_stack, "start_mark", "unknown")
            yaml_read_error = f"""
yaml_read_error:
    position-in-file: {position_in_file}
    exception: {kwargs.get('exception', '')}
"""
            original_path_to_file = kwargs.get('original-path-to-file', '')
            if original_path_to_file not in yaml_read_error:
                yaml_read_error = f"{yaml_read_error}\n    original-path-to-file: {original_path_to_file}"
            log.error(yaml_read_error)
        except Exception as ex:
            pass
