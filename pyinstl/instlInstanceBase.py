#!/usr/bin/env python3


import os
import sys
import re
import abc

import yaml
import io
import appdirs

import aYaml
import utils
from .batchAccumulator import BatchAccumulator
from .installItem import read_index_from_yaml
from .platformSpecificHelper_Base import PlatformSpecificHelperFactory
from svnTree import SVNTable

from configVar import value_ref_re
from configVar import var_stack
from .installItem import InstallItem
from . import connectionBase

# The plan:
# when online copy & sync and offline sync, get info_map.txt url in INFO_MAP_FILE_URL*
# into LOCAL_REPO_REV_BOOKKEEPING_DIR/remote_info_map.txt. When sync is done
# when when sync is done it will write $(LOCAL_REPO_BOOKKEEPING_DIR)/have_info_map.txt.
# Offline copy will look for $(LOCAL_REPO_BOOKKEEPING_DIR)/have_info_map.txt
# All copy will end with writing $(LOCAL_REPO_BOOKKEEPING_DIR)/installed_info_map.txt
# * which usually takes from INFO_MAP_FILE_URL_SECURE


# noinspection PyPep8Naming
class InstlInstanceBase(object, metaclass=abc.ABCMeta):
    """ Main object of instl. Keeps the state of variables and install index
        and knows how to create a batch file for installation. InstlInstanceBase
        must be inherited by platform specific implementations, such as InstlInstance_mac
        or InstlInstance_win.
    """

    def __init__(self, initial_vars=None):
        self.info_map_table = SVNTable()

        # only when allow_reading_of_internal_vars is true, variables who's name begins and ends with "__"
        # can be read from file
        self.allow_reading_of_internal_vars = False
        self.path_searcher = utils.SearchPaths(var_stack.get_configVar_obj("__SEARCH_PATHS__"))
        self.init_default_vars(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        # initialize the search paths helper with the current directory and dir where instl is now
        self.path_searcher.add_search_path(os.getcwd())
        self.path_searcher.add_search_path(os.path.dirname(os.path.realpath(sys.argv[0])))
        self.path_searcher.add_search_path(var_stack.resolve("$(__INSTL_DATA_FOLDER__)"))

        self.platform_helper = PlatformSpecificHelperFactory(var_stack.resolve("$(__CURRENT_OS__)"), self)
        # init initial copy tool, tool might be later overridden after reading variable COPY_TOOL from yaml.
        self.platform_helper.init_copy_tool()

        self.install_definitions_index = dict()
        self.batch_accum = BatchAccumulator()
        self.do_not_write_vars = ("INFO_MAP_SIG", "INDEX_SIG", "PUBLIC_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "__CREDENTIALS__")
        self.out_file_realpath = None

    def get_version_str(self):
        retVal = var_stack.resolve(
            "$(INSTL_EXEC_DISPLAY_NAME) version $(__INSTL_VERSION__) $(__COMPILATION_TIME__) $(__PLATFORM_NODE__)",
            list_sep=".", default="")
        return retVal

    def init_default_vars(self, initial_vars):
        if initial_vars:
            var_description = "from initial_vars"
            for var, value in initial_vars.items():
                if isinstance(value, str):
                    var_stack.add_const_config_variable(var, var_description, value)
                else:
                    var_stack.add_const_config_variable(var, var_description, *value)

        var_description = "from InstlInstanceBase.init_default_vars"

        # read defaults/main.yaml
        main_defaults_file_path = os.path.join(var_stack.resolve("$(__INSTL_DATA_FOLDER__)"), "defaults", "main.yaml")
        self.read_yaml_file(main_defaults_file_path)

        # read defaults/compile-info.yaml
        compile_info_file_path = os.path.join(var_stack.resolve("$(__INSTL_DATA_FOLDER__)"), "defaults",
                                              "compile-info.yaml")
        if os.path.isfile(compile_info_file_path):
            self.read_yaml_file(compile_info_file_path)
        if "__COMPILATION_TIME__" not in var_stack:
            if var_stack.resolve("$(__INSTL_COMPILED__)") == "True":
                var_stack.add_const_config_variable("__COMPILATION_TIME__", var_description, "unknown compilation time")
            else:
                var_stack.add_const_config_variable("__COMPILATION_TIME__", var_description, "(not compiled)")

        self.read_user_config()

    def read_name_specific_defaults_file(self, file_name):
        """ read class specific file from defaults/class_name.yaml """
        name_specific_defaults_file_path = os.path.join(var_stack.resolve("$(__INSTL_DATA_FOLDER__)"), "defaults",
                                                        file_name + ".yaml")
        if os.path.isfile(name_specific_defaults_file_path):
            self.read_yaml_file(name_specific_defaults_file_path)

    def read_user_config(self):
        user_config_path = var_stack.resolve("$(__USER_CONFIG_FILE_PATH__)")
        if os.path.isfile(user_config_path):
            previous_allow_reading_of_internal_vars = self.allow_reading_of_internal_vars
            self.allow_reading_of_internal_vars = True
            self.read_yaml_file(user_config_path)
            self.allow_reading_of_internal_vars = previous_allow_reading_of_internal_vars

    def check_prerequisite_var_existence(self, prerequisite_vars):
        missing_vars = [var for var in prerequisite_vars if var not in var_stack]
        if len(missing_vars) > 0:
            msg = "Prerequisite variables were not defined: " + ", ".join(missing_vars)
            raise ValueError(msg)

    def init_from_cmd_line_options(self, cmd_line_options_obj):
        """ turn command line options into variables """
        const_attrib_to_var = {
            "input_file": ("__MAIN_INPUT_FILE__", None),
            "output_file": ("__MAIN_OUT_FILE__", None),
            "props_file": ("__PROPS_FILE__", None),
            "config_file": ("__CONFIG_FILE__", None),
            "sh1_checksum": ("__SHA1_CHECKSUM__", None),
            "rsa_signature": ("__RSA_SIGNATURE__", None),
            "start_progress": ("__START_DYNAMIC_PROGRESS__", "0"),
            "total_progress": ("__TOTAL_DYNAMIC_PROGRESS__", "0"),
            "just_with_number": ("__JUST_WITH_NUMBER__", "0"),
            "limit_command_to": ("__LIMIT_COMMAND_TO__", None),
            "shortcut_path": ("__SHORTCUT_PATH__", None),
            "target_path": ("__SHORTCUT_TARGET_PATH__", None),
            "credentials": ("__CREDENTIALS__", None),
            "base_url": ("__BASE_URL__", None),
            "file_sizes_file": ("__FILE_SIZES_FILE__", None)
        }

        for attrib, var in const_attrib_to_var.items():
            attrib_value = getattr(cmd_line_options_obj, attrib)
            if attrib_value:
                var_stack.add_const_config_variable(var[0], "from command line options", *attrib_value)
            elif var[1] is not None:  # there's a default
                var_stack.add_const_config_variable(var[0], "from default", var[1])

        non_const_attrib_to_var = {
            "target_repo_rev": "TARGET_REPO_REV",
            "base_repo_rev": "BASE_REPO_REV",
        }

        for attrib, var in non_const_attrib_to_var.items():
            attrib_value = getattr(cmd_line_options_obj, attrib)
            if attrib_value:
                var_stack.set_var(var, "from command line options").append(attrib_value[0])

        if cmd_line_options_obj.command:
            var_stack.set_var("__MAIN_COMMAND__", "from command line options").append(cmd_line_options_obj.command)

        if hasattr(cmd_line_options_obj, "subject") and cmd_line_options_obj.subject is not None:
            var_stack.add_const_config_variable("__HELP_SUBJECT__", "from command line options",
                                                cmd_line_options_obj.subject)
        else:
            var_stack.add_const_config_variable("__HELP_SUBJECT__", "from command line options", "")

        if cmd_line_options_obj.state_file:
            var_stack.add_const_config_variable("__MAIN_STATE_FILE__", "from command line options",
                                                cmd_line_options_obj.state_file)

        if cmd_line_options_obj.run:
            var_stack.add_const_config_variable("__RUN_BATCH__", "from command line options", "yes")

        if cmd_line_options_obj.no_wtar_artifacts:
            var_stack.add_const_config_variable("__NO_WTAR_ARTIFACTS__", "from command line options", "yes")

        if cmd_line_options_obj.all_revisions:
            var_stack.add_const_config_variable("__ALL_REVISIONS__", "from command line options", "yes")

        if cmd_line_options_obj.dock_item_path:
            var_stack.add_const_config_variable("__DOCK_ITEM_PATH__", "from command line options", *cmd_line_options_obj.dock_item_path)
        if cmd_line_options_obj.dock_item_label:
            var_stack.add_const_config_variable("__DOCK_ITEM_LABEL__", "from command line options", *cmd_line_options_obj.dock_item_label)
        if cmd_line_options_obj.remove_from_dock:
            var_stack.add_const_config_variable("__REMOVE_FROM_DOCK__", "from command line options", "yes")
        if cmd_line_options_obj.restart_the_dock:
            var_stack.add_const_config_variable("__RESTART_THE_DOCK__", "from command line options", "yes")

        if cmd_line_options_obj.define:
            individual_definitions = cmd_line_options_obj.define[0].split(",")
            for definition in individual_definitions:
                name, value = definition.split("=")
                var_stack.set_var(name, "from command line define option").append(value)

        if "__MAIN_OUT_FILE__" not in var_stack and "__MAIN_INPUT_FILE__" in var_stack:
            var_stack.add_const_config_variable("__MAIN_OUT_FILE__", "from command line options",
                                                "$(__MAIN_INPUT_FILE__)-$(__MAIN_COMMAND__).$(BATCH_EXT)")

    def is_acceptable_yaml_doc(self, doc_node):
        acceptables = var_stack.resolve_to_list("$(ACCEPTABLE_YAML_DOC_TAGS)") + ["define", "define_const", "index", 'require']
        if "__INSTL_COMPILED__" in var_stack:
            if var_stack.resolve("$(__INSTL_COMPILED__)") == "True":
                acceptables.append("define_Compiled")
            else:
                acceptables.append("define_Uncompiled")
        acceptables = ["!" + acceptibul for acceptibul in acceptables]
        retVal = doc_node.tag in acceptables
        return retVal

    def read_yaml_from_stream(self, the_stream):
        for a_node in yaml.compose_all(the_stream):
            if self.is_acceptable_yaml_doc(a_node):
                if a_node.tag.startswith('!define_const'):
                    self.read_const_defines(a_node)
                elif a_node.tag.startswith('!define'):
                    self.read_defines(a_node)
                elif a_node.tag.startswith('!index'):
                    self.read_index(a_node)
                elif a_node.tag.startswith('!require'):
                    self.read_require(a_node)
        if not self.check_version_compatibility():
            raise ValueError(var_stack.resolve("Minimal instl version $(INSTL_MINIMAL_VERSION) > current version $(__INSTL_VERSION__); ")+var_stack.get_configVar_obj("INSTL_MINIMAL_VERSION").description)

    def read_yaml_file(self, file_path):
        try:
            with utils.open_for_read_file_or_url(file_path, connectionBase.translate_url, self.path_searcher) as file_fd:
                buffer = file_fd.read()
                if type(buffer) is bytes:
                    buffer = buffer.decode("utf-8")
                buffer = io.StringIO(buffer)
                self.read_yaml_from_stream(buffer)
            var_stack.get_configVar_obj("__READ_YAML_FILES__").append(file_path)
        except:
            print("Exception reading file:", file_path)
            raise

    def read_require(self, a_node):
        # dependencies_file_path = var_stack.resolve("$(SITE_REQUIRE_FILE_PATH)")
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier in self.install_definitions_index:
                    self.install_definitions_index[identifier].required_by.extend([required_iid.value for required_iid in contents])
                else:
                    # require file might contain IIDs form previous installations that are no longer in the index
                    item_not_in_index = InstallItem()
                    item_not_in_index.iid = identifier
                    item_not_in_index.required_by.extend([required_iid.value for required_iid in contents])
                    self.install_definitions_index[identifier] = item_not_in_index

    def write_require_file(self, file_path):
        require_dict = dict()
        for IID in sorted(self.install_definitions_index.keys()):
            if len(self.install_definitions_index[IID].required_by) > 0:
                require_dict[IID] = sorted(self.install_definitions_index[IID].required_by)
        with open(file_path, "w") as wfd:
            utils.make_open_file_read_write_for_all(wfd)
            require_dict = aYaml.YamlDumpDocWrap(require_dict, '!require', "requirements",
                                                 explicit_start=True, sort_mappings=True)
            aYaml.writeAsYaml(require_dict, wfd)

    internal_identifier_re = re.compile("""
                                        __                  # dunder here
                                        (?P<internal_identifier>\w*)
                                        __                  # dunder there
                                        """, re.VERBOSE)

    def resolve_defined_paths(self):
        self.path_searcher.add_search_paths(var_stack.resolve_to_list("$(SEARCH_PATHS)"))
        for path_var_to_resolve in var_stack.resolve_to_list("$(PATHS_TO_RESOLVE)"):
            if path_var_to_resolve in var_stack:
                resolved_path = self.path_searcher.find_file(var_stack.resolve_var(path_var_to_resolve),
                                                             return_original_if_not_found=True)
                var_stack.set_var(path_var_to_resolve, "resolve_defined_paths").append(resolved_path)

    def read_defines(self, a_node):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if self.allow_reading_of_internal_vars or not self.internal_identifier_re.match(identifier):  # do not read internal state identifiers
                    var_stack.set_var(identifier, str(contents.start_mark)).extend([item.value for item in contents])
                elif identifier == '__include__':
                    self.read_include_node(contents)

    def read_const_defines(self, a_node):
        """ Read a !define_const sub-doc. All variables will be made const.
            Reading of internal state identifiers is allowed.
            __include__ is not allowed.
        """
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier == "__include__":
                    raise ValueError("!define_const doc cannot except __include__")
                var_stack.add_const_config_variable(identifier, "from !define_const section",
                                                    *[item.value for item in contents])

    def provision_public_key_text(self):
        if "PUBLIC_KEY" not in var_stack:
            if "PUBLIC_KEY_FILE" in var_stack:
                public_key_file = var_stack.resolve("$(PUBLIC_KEY_FILE)")
                with utils.open_for_read_file_or_url(public_key_file, connectionBase.translate_url, self.path_searcher) as file_fd:
                    public_key_text = file_fd.read()
                    var_stack.set_var("PUBLIC_KEY", "from " + public_key_file).append(public_key_text)
            else:
                raise ValueError("No public key, variables PUBLIC_KEY & PUBLIC_KEY_FILE are not defined")
        resolved_public_key = var_stack.resolve("$(PUBLIC_KEY)")
        return resolved_public_key

    def read_include_node(self, i_node):
        if i_node.isScalar():
            resolved_file_name = var_stack.resolve(i_node.value)
            self.read_yaml_file(resolved_file_name)
        elif i_node.isSequence():
            for sub_i_node in i_node:
                self.read_include_node(sub_i_node)
        elif i_node.isMapping():
            if "url" in i_node:
                cached_files_dir = self.get_default_sync_dir(continue_dir="cache", make_dir=True)
                resolved_file_url = var_stack.resolve(i_node["url"].value)
                cached_file_path = None
                expected_checksum = None
                if "checksum" in i_node:
                    expected_checksum = var_stack.resolve(i_node["checksum"].value)
                    cached_file_path = os.path.join(cached_files_dir, expected_checksum)

                expected_signature = None
                public_key_text = None
                if "sig" in i_node:
                    expected_signature = var_stack.resolve(i_node["sig"].value)
                    public_key_text = self.provision_public_key_text()

                if expected_checksum is None:
                    self.read_yaml_file(resolved_file_url)
                    cached_file_path = resolved_file_url
                else:
                    utils.download_from_file_or_url(resolved_file_url,cached_file_path,
                                              connectionBase.translate_url, cache=True,
                                              public_key=public_key_text,
                                              textual_sig=expected_signature,
                                              expected_checksum=expected_checksum)
                    self.read_yaml_file(cached_file_path)

                if "copy" in i_node:
                    self.batch_accum.set_current_section('post')
                    for copy_destination in i_node["copy"]:
                        need_to_copy = True
                        destination_file_resolved_path = var_stack.resolve(copy_destination.value)
                        if os.path.isfile(destination_file_resolved_path):
                            checksums_match = utils.check_file_checksum(file_path=destination_file_resolved_path, expected_checksum=expected_checksum)
                            need_to_copy = not checksums_match
                        if need_to_copy:
                            destination_folder, destination_file_name = os.path.split(copy_destination.value)
                            self.batch_accum += self.platform_helper.mkdir(destination_folder)
                            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_file(cached_file_path,
                                                                                                 var_stack.resolve(copy_destination.value),
                                                                                                 link_dest=True)

    def create_variables_assignment(self):
        self.batch_accum.set_current_section("assign")
        for identifier in var_stack:
            if identifier not in self.do_not_write_vars:
                self.batch_accum += self.platform_helper.var_assign(identifier, var_stack.resolve_var(identifier),
                                                                    None)  # var_stack[identifier].resolved_num

    def calc_user_cache_dir_var(self, make_dir=True):
        if "USER_CACHE_DIR" not in var_stack:
            os_family_name = var_stack.resolve("$(__CURRENT_OS__)")
            if os_family_name == "Mac":
                user_cache_dir_param = "$(COMPANY_NAME)/$(INSTL_EXEC_DISPLAY_NAME)"
                user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
            elif os_family_name == "Win":
                user_cache_dir = appdirs.user_cache_dir("$(INSTL_EXEC_DISPLAY_NAME)", "$(COMPANY_NAME)")
            elif os_family_name == "Linux":
                user_cache_dir_param = "$(COMPANY_NAME)/$(INSTL_EXEC_DISPLAY_NAME)"
                user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
            var_description = "from InstlInstanceBase.get_user_cache_dir"
            var_stack.set_var("USER_CACHE_DIR", var_description).append(user_cache_dir)
        if make_dir:
            user_cache_dir_resolved = var_stack.resolve("$(USER_CACHE_DIR)", raise_on_fail=True)
            utils.safe_makedirs(user_cache_dir_resolved)

    def get_default_sync_dir(self, continue_dir=None, make_dir=True):
        self.calc_user_cache_dir_var()
        if continue_dir:
            retVal = os.path.join("$(USER_CACHE_DIR)", continue_dir)
        else:
            retVal = "$(USER_CACHE_DIR)"
        # print("1------------------", user_cache_dir, "-", from_url, "-", retVal)
        if make_dir and retVal:
            retVal = var_stack.resolve(retVal, raise_on_fail=True)
            utils.safe_makedirs(retVal)
        return retVal

    def relative_sync_folder_for_source(self, source):
        source_path, source_type = source[0], source[1]
        if source_type in ('!dir', '!file'):
            retVal = "/".join(source_path.split("/")[0:-1])
        elif source_type in ('!dir_cont', '!files'):
            retVal = source_path
        else:
            raise ValueError("unknown tag for source " + source_path + ": " + source_type)
        return retVal

    def write_batch_file(self):
        self.batch_accum.set_current_section('pre')
        self.batch_accum += self.platform_helper.get_install_instructions_prefix()
        self.batch_accum.set_current_section('post')
        var_stack.set_var("TOTAL_ITEMS_FOR_PROGRESS_REPORT").append(
            str(self.platform_helper.num_items_for_progress_report))
        self.batch_accum += self.platform_helper.get_install_instructions_postfix()
        lines = self.batch_accum.finalize_list_of_lines()
        lines_after_var_replacement = '\n'.join(
            [value_ref_re.sub(self.platform_helper.var_replacement_pattern, line) for line in lines])

        out_file = var_stack.resolve("$(__MAIN_OUT_FILE__)", raise_on_fail=True)
        with utils.write_to_file_or_stdout(out_file) as fd:
            fd.write(lines_after_var_replacement)
            fd.write('\n')

        if out_file != "stdout":
            self.out_file_realpath = os.path.realpath(out_file)
            # chmod to 0777 so that file created under sudo, can be re-written under regular user.
            # However regular user cannot chmod for file created under sudo, hence the try/except
            try:
                os.chmod(self.out_file_realpath, 0o777)
            except:
                pass
        else:
            self.out_file_realpath = "stdout"
        msg = " ".join(
            (self.out_file_realpath, str(self.platform_helper.num_items_for_progress_report), "progress items"))
        print(msg)

    def run_batch_file(self):
        from subprocess import Popen

        p = Popen([self.out_file_realpath], executable=self.out_file_realpath, shell=False)
        unused_stdout, unused_stderr = p.communicate()
        retcode = p.returncode
        if retcode != 0:
            raise SystemExit(self.out_file_realpath + " returned exit code " + str(retcode))

    def write_program_state(self):

        state_file = var_stack.resolve("$(__MAIN_STATE_FILE__)", raise_on_fail=True)
        with utils.write_to_file_or_stdout(state_file) as fd:
            aYaml.writeAsYaml(self, fd)

    def read_index(self, a_node):
        self.install_definitions_index.update(read_index_from_yaml(a_node))

    def find_cycles(self):
        if not self.install_definitions_index:
            print("index empty - nothing to check")
        else:
            try:
                from .pyinstl import installItemGraph

                depend_graph = installItemGraph.create_dependencies_graph(self.install_definitions_index)
                depend_cycles = installItemGraph.find_cycles(depend_graph)
                if not depend_cycles:
                    print("No depend cycles found")
                else:
                    for cy in depend_cycles:
                        print("depend cycle:", " -> ".join(cy))
                inherit_graph = installItemGraph.create_inheritItem_graph(self.install_definitions_index)
                inherit_cycles = installItemGraph.find_cycles(inherit_graph)
                if not inherit_cycles:
                    print("No inherit cycles found")
                else:
                    for cy in inherit_cycles:
                        print("inherit cycle:", " -> ".join(cy))
            except ImportError:  # no installItemGraph, no worry
                print("Could not load installItemGraph")

    def check_version_compatibility(self):
        retVal = True
        if "INSTL_MINIMAL_VERSION" in var_stack:
            inst_ver = list(map(int, var_stack.resolve_to_list("$(__INSTL_VERSION__)")))
            required_ver = list(map(int, var_stack.resolve_to_list("$(INSTL_MINIMAL_VERSION)")))
            retVal = inst_ver >= required_ver
        return retVal

    wtar_file_re = re.compile("""(?P<base_name>.+?)(\.wtar(\.[a-z]{2})?)?$""")

    # Given a name remove the trailing wtar or wtar.?? if any
    # E.g. "a" => "a", "a.wtar" => "a", "a.wtar.aa" => "a"
    def original_name_from_wtar_name(self, wtar_name):
        original_name = self.wtar_file_re.match(wtar_name).group('base_name')
        return original_name

    # Given a list of file/folder names, replace those which are wtarred with the original file name.
    # E.g. ['a', 'b.wtar', 'c.wtar.aa', 'c.wtar.ab'] => ['a', 'b', 'c']
    # We must work on the whole list since several wtar file names might merge to a single original file name.
    def original_names_from_wtars_names(self, original_list):
        replaced_list = utils.unique_list()
        replaced_list.extend([self.original_name_from_wtar_name(file_name) for file_name in original_list])
        return replaced_list

    def needs(self, iid, out_list):
        """ return iids of all items that a specific iid depends on"""
        if iid not in self.install_definitions_index:
            raise KeyError(iid + " is not in index")
        InstallItem.begin_get_for_all_oses()
        with self.install_definitions_index[iid]:
            for dep in var_stack.resolve_var_to_list("iid_depend_list"):
                if dep in self.install_definitions_index:
                    out_list.append(dep)
                    self.needs(dep, out_list)
                else:
                    out_list.append(dep + "(missing)")
        InstallItem.reset_get_for_all_oses()

    def needed_by(self, iid):
        try:
            from .pyinstl import installItemGraph

            InstallItem.begin_get_for_all_oses()
            graph = installItemGraph.create_dependencies_graph(self.install_definitions_index)
            needed_by_list = installItemGraph.find_needed_by(graph, iid)
            InstallItem.reset_get_for_all_oses()
            return needed_by_list
        except ImportError:  # no installItemGraph, no worry
            print("Could not load installItemGraph")
            return None

    def resolve_index_inheritance(self):
        for install_def in list(self.install_definitions_index.values()):
            install_def.resolve_inheritance(self.install_definitions_index)

