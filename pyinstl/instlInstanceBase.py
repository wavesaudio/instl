#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import os
import argparse
import yaml
import re
import abc
from collections import OrderedDict, defaultdict
import appdirs
import logging
import datetime

import pyinstl.log_utils
from pyinstl.log_utils import func_log_wrapper
from configVarList import ConfigVarList, value_ref_re
from aYaml import augmentedYaml
from installItem import read_index_from_yaml
from pyinstl.utils import *
from pyinstl.searchPaths import SearchPaths
from instlException import InstlException
from platformSpecificHelper_Base import PlatformSpecificHelperFactory

current_os_names = current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

INSTL_VERSION=(0, 4, 0)
this_program_name = "instl"

class InstallInstructionsState(object):
    """ holds state for specific creating of install instructions """
    @func_log_wrapper
    def __init__(self):
        self.root_install_items = unique_list()
        self.full_install_items = unique_list()
        self.orphan_install_items = unique_list()
        self.install_items_by_target_folder = defaultdict(unique_list)
        self.no_copy_items_by_sync_folder = defaultdict(unique_list)
        self.variables_assignment_lines = list()
        self.instruction_lines = defaultdict(list)
        self.sync_paths = unique_list()
        self.indent_level = 0

    @func_log_wrapper
    def extend_instructions(self, which, instruction_list):
        #print("extend_instructions indent", self.indent_level)
        self.instruction_lines[which].extend( map(lambda line: " " * 4 * self.indent_level + line, instruction_list))

    @func_log_wrapper
    def append_instructions(self, which, single_instruction):
        #print("append_instructions indent", self.indent_level)
        self.instruction_lines[which].append(" " * 4 * self.indent_level + single_instruction)

    @func_log_wrapper
    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['root_install_items'] = list(self.root_install_items)
        retVal['full_install_items'] = list(self.full_install_items)
        retVal['orphan_install_items'] = list(self.orphan_install_items)
        retVal['install_items_by_target_folder'] = {folder: list(self.install_items_by_target_folder[folder]) for folder in self.install_items_by_target_folder}
        retVal['no_copy_items_by_sync_folder'] = list(self.no_copy_items_by_sync_folder)
        retVal['variables_assignment_lines'] = list(self.variables_assignment_lines)
        retVal['copy_instruction_lines'] = self.instruction_lines['copy']
        retVal['sync_paths'] = list(self.sync_paths)
        retVal['sync_instruction_lines'] = self.instruction_lines['sync']
        return retVal

    @func_log_wrapper
    def calculate_full_install_items_set(self, instlInstance):
        """ calculate the set of iids to install by starting with the root set and adding all dependencies.
            Initial list of iids should already be in self.root_install_items.
            results are accomulated in InstallInstructionsState.
            If an install items was not found for a iid, the iid is added to the orphan set.
        """

        if len(self.root_install_items) > 0:
            logging.info(" ".join(("Main install items:", ", ".join(self.root_install_items))))
        else:
            logging.error("Main install items list is empty")
        # root_install_items might have guid in it, translate them to iids

        root_install_iids_translated = unique_list()
        for IID in self.root_install_items:
            if instlInstance.guid_re.match(IID): # if it's a guid translate to iid's
                iids_from_the_guid = instlInstance.iids_from_guid(IID)
                if len(iids_from_the_guid) > 0:
                    root_install_iids_translated.extend(iids_from_the_guid)
                    logging.info("GUID %s, translated to %d iids: %s", IID, len(iids_from_the_guid), ", ".join(iids_from_the_guid))
                else:
                    self.orphan_install_items.append(IID)
                    logging.warning("%s is a guid but could not be translated to iids", IID)
            else:
                root_install_iids_translated.append(IID)
                logging.info("%s added to root_install_iids_translated", IID)

        for IID in root_install_iids_translated:
            try:
                instlInstance.install_definitions_index[IID].get_recursive_depends(instlInstance.install_definitions_index, self.full_install_items, self.orphan_install_items)
            except KeyError:
                self.orphan_install_items.append(IID)
                logging.warning("%s not found in index", IID)
        self.__sort_install_items_by_target_folder(instlInstance)

    @func_log_wrapper
    def __sort_install_items_by_target_folder(self, instlInstance):
        for IID in self.full_install_items:
            folder_list_for_idd = instlInstance.install_definitions_index[IID].folder_list()
            if folder_list_for_idd:
                for folder in folder_list_for_idd:
                    self.install_items_by_target_folder[folder].append(IID)
            else: # items that need no copy
                source_list_for_idd = instlInstance.install_definitions_index[IID].source_list()
                for source in source_list_for_idd:
                    sync_folder =  "/".join( ("$(LOCAL_SYNC_DIR)", "$(REL_SRC_PATH)", instlInstance.relative_sync_folder_for_source(source)))
                    self.no_copy_items_by_sync_folder[sync_folder].append(IID)

class InstlInstanceBase(object):
    """ Main object of instl. Keeps the state of variables and install index
        and knows how to create a batch file for installation. InstlInstanceBase
        must be inherited by platform specific implementations, such as InstlInstance_mac
        or InstlInstance_win.
    """
    __metaclass__ = abc.ABCMeta
    @func_log_wrapper
    def __init__(self, initial_vars=None):
        self.platform_helper = PlatformSpecificHelperFactory(os_family_name)
        self.out_file_realpath = None
        self.install_definitions_index = dict()
        self.cvl = ConfigVarList()
        self.var_replacement_pattern = None
        self.init_default_vars(initial_vars)
        # initialize the search paths helper with the current directory and dir where instl is now
        self.search_paths_helper = SearchPaths(self.cvl.get_configVar_obj("__SEARCH_PATHS__"))
        self.search_paths_helper.add_search_path(os.getcwd())
        self.search_paths_helper.add_search_path(os.path.dirname(os.path.realpath(sys.argv[0])))
        self.search_paths_helper.add_search_path(self.cvl.get_str("__INSTL_EXE_PATH__"))
        #if os_family_name == "Win":
        #    self.search_paths_helper.add_search_path(os.path.join(self.cvl.get_str("__INSTL_EXE_PATH__"), "wsvn"))

        self.guid_re = re.compile("""
                        [a-f0-9]{8}
                        (-[a-f0-9]{4}){3}
                        -[a-f0-9]{12}
                        $
                        """, re.VERBOSE)

    @func_log_wrapper
    def repr_for_yaml(self, what=None):
        """ Create representation of self suitable for printing as yaml.
            parameter 'what' is a list of identifiers to represent. If 'what'
            is None (the default) create representation of everything.
            InstlInstanceBase object is represented as two yaml documents:
            one for define (tagged !define), one for the index (tagged !index).
        """
        retVal = list()
        if what is None: # None is all
            retVal.append(augmentedYaml.YamlDumpDocWrap(self.cvl, '!define', "Definitions", explicit_start=True, sort_mappings=True))
            retVal.append(augmentedYaml.YamlDumpDocWrap(self.install_definitions_index, '!index', "Installation index", explicit_start=True, sort_mappings=True))
        else:
            for identifier in what:
                if identifier in self.cvl:
                    retVal.append(self.cvl.repr_for_yaml(identifier))
                elif identifier in self.install_definitions_index:
                    retVal.append({identifier: self.install_definitions_index[identifier].repr_for_yaml()})
                else:
                    retVal.append(augmentedYaml.YamlDumpWrap(value="UNKNOWN VARIABLE", comment=identifier+" is not in variable list"))

        return retVal

    @func_log_wrapper
    def init_default_vars(self, initial_vars):
        if initial_vars:
            var_description = "from initial_vars"
            for var, value in initial_vars.iteritems():
                self.cvl.add_const_config_variable(var, var_description, value)

        var_description = "from InstlInstanceBase.init_default_vars"
        self.cvl.add_const_config_variable("CURRENT_OS", var_description, os_family_name)
        self.cvl.add_const_config_variable("CURRENT_OS_SECOND_NAME", var_description, os_second_name)
        self.cvl.add_const_config_variable("CURRENT_OS_NAMES", var_description, *current_os_names)
        self.cvl.set_variable("TARGET_OS", var_description).append(os_family_name)
        self.cvl.set_variable("TARGET_OS_NAMES", var_description).extend(current_os_names)
        self.cvl.add_const_config_variable("__INSTL_VERSION__", var_description, *INSTL_VERSION)

        log_file = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=False)
        self.cvl.set_variable("LOG_FILE", var_description).append(log_file)
        debug_log_file = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=True)
        self.cvl.set_variable("LOG_DEBUG_FILE", var_description).extend( (debug_log_file, logging.getLevelName(pyinstl.log_utils.debug_logging_level), pyinstl.log_utils.debug_logging_started) )
        for identifier in self.cvl:
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    @func_log_wrapper
    def do_command(self, the_command, installState):
        installState = InstallInstructionsState()
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        self.read_input_files()
        self.resolve_index_inheritance()
        self.calculate_default_install_item_set(installState)
        if the_command in ("sync", 'synccopy'):
            logging.info("Creating sync instructions")
            if self.cvl.get_str("REPRO_TYPE") == "URL":
                from instlInstanceSync_url import InstlInstanceSync_url
                syncer = InstlInstanceSync_url(self)
            elif self.cvl.get_str("REPRO_TYPE") == "SVN":
                from instlInstanceSync_svn import InstlInstanceSync_svn
                syncer = InstlInstanceSync_svn(self)
            syncer.init_sync_vars()
            syncer.create_sync_instructions(installState)
        if the_command in ("copy", 'synccopy'):
            logging.info("Creating copy instructions")
            self.init_copy_vars()
            self.create_copy_instructions(installState)
        self.create_variables_assignment(installState)
        if "__MAIN_RUN_INSTALLATION__" in self.cvl:
            self.run_batch_file()


    @func_log_wrapper
    def init_from_cmd_line_options(self, cmd_line_options_obj):
        """ turn command line options into variables """
        if cmd_line_options_obj.input_files:
            self.cvl.add_const_config_variable("__MAIN_INPUT_FILES__", "from command line options", *cmd_line_options_obj.input_files)
        if cmd_line_options_obj.output_file:
            self.cvl.add_const_config_variable("__MAIN_OUT_FILE__", "from command line options", cmd_line_options_obj.output_file[0])
        if cmd_line_options_obj.state_file:
            self.cvl.add_const_config_variable("__MAIN_STATE_FILE__", "from command line options", cmd_line_options_obj.state_file)
        if cmd_line_options_obj.run:
            self.cvl.add_const_config_variable("__MAIN_RUN_INSTALLATION__", "from command line options", "yes")
        if cmd_line_options_obj.command:
            self.cvl.set_variable("__MAIN_COMMAND__", "from command line options").append(cmd_line_options_obj.command)
        for identifier in self.cvl:
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    internal_identifier_re = re.compile("""
                                        __                  # dunder here
                                        (?P<internal_identifier>\w*)
                                        __                  # dunder there
                                        """, re.VERBOSE)
    @func_log_wrapper
    def read_defines(self, a_node):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node:
                logging.debug("... %s: %s", identifier, str(contents))
                if not self.internal_identifier_re.match(identifier): # do not read internal state indentifiers
                    self.cvl.set_variable(identifier, str(contents.start_mark)).extend([item.value for item in contents])
                elif identifier == '__include__':
                    for file_name in contents:
                        resolved_file_name = self.cvl.resolve_string(file_name.value)
                        self.read_file(resolved_file_name)

    @func_log_wrapper
    def read_index(self, a_node):
        self.install_definitions_index.update(read_index_from_yaml(a_node))

    @func_log_wrapper
    def read_input_files(self):
        input_files = self.cvl.get_list("__MAIN_INPUT_FILES__")
        if input_files:
            file_actually_opened = list()
            for file_path in input_files:
                self.read_file(file_path)
                file_actually_opened.append(os.path.abspath(file_path))
            self.cvl.add_const_config_variable("__MAIN_INPUT_FILES_ACTUALLY_OPENED__", "opened by read_input_files", *file_actually_opened)

    @func_log_wrapper
    def read_file(self, file_path):
        try:
            logging.info("... Reading input file %s", file_path)
            with open_for_read_file_or_url(file_path, self.search_paths_helper) as file_fd:
                for a_node in yaml.compose_all(file_fd):
                    if a_node.tag == '!define':
                        self.read_defines(a_node)
                    elif a_node.tag == '!index':
                        self.read_index(a_node)
                    else:
                        logging.error("Unknown document tag '%s' while reading file %s; Tag should be one of: !define, !index'", a_node.tag, file_path)
        except InstlException as ie:
            raise # re-raise in case of recursive call to read_file
        except yaml.YAMLError as ye:
            raise InstlException(" ".join( ("YAML error while reading file", "'"+file_path+"':\n", str(ye)) ), ye)
        except IOError as ioe:
            raise InstlException(" ".join(("Failed to read file", "'"+file_path+"'", ":")), ioe)

    @func_log_wrapper
    def resolve_index_inheritance(self):
        for install_def in self.install_definitions_index.values():
            install_def.resolve_inheritance(self.install_definitions_index)

    @func_log_wrapper
    def guid_list(self):
        retVal = unique_list()
        retVal.extend(filter(bool, [install_def.guid for install_def in self.install_definitions_index.values()]))
        return retVal

    @func_log_wrapper
    def iids_from_guid(self, guid):
        retVal = list()
        for iid, install_def in self.install_definitions_index.iteritems():
            if install_def.guid == guid:
                retVal.append(iid)
        return retVal

    @func_log_wrapper
    def calculate_default_install_item_set(self, installState):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_INSTALL_TARGETS" not in self.cvl:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        installState.root_install_items.extend(self.cvl.get_list("MAIN_INSTALL_TARGETS"))
        installState.root_install_items = filter(bool, installState.root_install_items)
        installState.calculate_full_install_items_set(self)
        self.cvl.set_variable("__FULL_LIST_OF_INSTALL_TARGETS__").extend(installState.full_install_items)
        self.cvl.set_variable("__ORPHAN_INSTALL_TARGETS__").extend(installState.orphan_install_items)
        for identifier in ("MAIN_INSTALL_TARGETS", "__FULL_LIST_OF_INSTALL_TARGETS__", "__ORPHAN_INSTALL_TARGETS__"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    @func_log_wrapper
    def create_variables_assignment(self, installState):
        for identifier in self.cvl:
            if not self.internal_identifier_re.match(identifier) or pyinstl.log_utils.debug_logging_started: # do not write internal state identifiers, unless in debug mode
                installState.variables_assignment_lines.append(self.platform_helper.create_var_assign(identifier,self.cvl.get_str(identifier)))

    @func_log_wrapper
    def get_default_sync_dir(self):
        retVal = None
        if os_family_name == "Mac":
            user_cache_dir_param = self.cvl.get_str("COMPANY_NAME")+"/"+this_program_name
            user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
        elif os_family_name == "Win":
            user_cache_dir = appdirs.user_cache_dir(this_program_name, self.cvl.get_str("COMPANY_NAME"))
        from_url = main_url_item(self.cvl.get_str("SVN_REPO_URL"))
        if from_url:
            if 'Win' in current_os_names:
                from_url = from_url.lstrip("/\\")
            retVal = os.path.join(user_cache_dir, from_url)
        else:
            retVal = user_cache_dir
        #print("------------------", user_cache_dir, "-", from_url, "-", retVal)
        return retVal

    @func_log_wrapper
    def init_copy_vars(self):
        var_description = "from InstlInstanceBase.init_copy_vars"
        if "SET_ICON_PATH" in self.cvl:
            setIcon_full_path = self.search_paths_helper.find_file_with_search_paths(self.cvl.get_str("SET_ICON_PATH"))
            self.cvl.set_variable("SET_ICON_PATH", var_description).append(setIcon_full_path)
# check which variabls are needed for for offline install....
        if "REL_SRC_PATH" not in self.cvl:
            if "SVN_REPO_URL" not in self.cvl:
                raise ValueError("'SVN_REPO_URL' was not defined")
            if "BASE_SRC_URL" not in self.cvl:
                self.cvl.set_variable("BASE_SRC_URL", var_description).append("$(SVN_REPO_URL)/$(TARGET_OS)")
            rel_sources = relative_url(self.cvl.get_str("SVN_REPO_URL"), self.cvl.get_str("BASE_SRC_URL"))
            self.cvl.set_variable("REL_SRC_PATH", var_description).append(rel_sources)

        if "LOCAL_SYNC_DIR" not in self.cvl:
            self.cvl.set_variable("LOCAL_SYNC_DIR", var_description).append(self.get_default_sync_dir())

        if "COPY_TOOL" not in self.cvl:
            from copyCommander import DefaultCopyToolName
            self.cvl.set_variable("COPY_TOOL", var_description).append(DefaultCopyToolName(self.cvl.get_str("TARGET_OS")))
        for identifier in ("REL_SRC_PATH", "COPY_TOOL"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    @func_log_wrapper
    def relative_sync_folder_for_source(self, source):
        retVal = None
        if source[1] in ('!dir', '!file'):
            retVal = "/".join(source[0].split("/")[0:-1])
        elif source[1] in ('!dir_cont', '!files'):
            retVal = source[0]
        else:
            raise ValueError("unknown tag for source "+source[0]+": "+source[1])
        return retVal

    @func_log_wrapper
    def create_copy_instructions(self, installState):
        # copy and actions instructions for sources
        installState.append_instructions('copy', self.platform_helper.create_echo_command("starting copy"))
        self.platform_helper.use_copy_tool(self.cvl.get_str("COPY_TOOL"))
        num_items_for_progress_report = 1 # one for a dummy last item
        for folder_items in installState.install_items_by_target_folder.values():
            for IID in folder_items:
                for source in self.install_definitions_index[IID].source_list():
                    num_items_for_progress_report += 1
        num_items_for_progress_report += len(installState.no_copy_items_by_sync_folder)

        current_item_for_progress_report = 0
        installState.append_instructions('copy', self.platform_helper.create_echo_command("Progress: copied {current_item_for_progress_report} of {num_items_for_progress_report}; from $(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)".format(**locals())))
        current_item_for_progress_report += 1
        for folder_name, folder_items in installState.install_items_by_target_folder.iteritems():
            installState.append_instructions('copy', self.platform_helper.create_echo_command("Starting copy to folder "+folder_name))
            installState.indent_level += 1
            logging.info("... folder %s (%s)", folder_name, self.cvl.resolve_string(folder_name))
            installState.extend_instructions('copy', self.platform_helper.make_directory_cmd(folder_name))
            installState.extend_instructions('copy', self.platform_helper.change_directory_cmd(folder_name))
            folder_in_actions = unique_list()
            install_item_instructions = list()
            folder_out_actions = unique_list()
            for IID in folder_items: # folder_in actions
                installi = self.install_definitions_index[IID]
                folder_in_actions.extend(installi.action_list('folder_in'))
                for source in installi.source_list():
                    install_item_instructions.extend(installi.action_list('before'))
                    install_item_instructions.extend(self.create_copy_instructions_for_source(source))
                    install_item_instructions.extend(installi.action_list('after'))
                    install_item_instructions.append(self.platform_helper.create_echo_command("Progress: copied {current_item_for_progress_report} of {num_items_for_progress_report}; {installi.iid}: {installi.name}".format(**locals())))
                    current_item_for_progress_report += 1
                folder_out_actions.extend(installi.action_list('folder_out'))
            installState.extend_instructions('copy', folder_in_actions)
            installState.indent_level += 1
            installState.extend_instructions('copy', install_item_instructions)
            installState.extend_instructions('copy', folder_out_actions)
            installState.indent_level -= 1
            installState.indent_level -= 1

        # actions instructions for sources that do not need copying
        for folder_name, folder_items in installState.no_copy_items_by_sync_folder.iteritems():
            logging.info("... non-copy items folder %s (%s)", folder_name, self.cvl.resolve_string(folder_name))
            installState.extend_instructions('copy', self.platform_helper.change_directory_cmd(folder_name))
            folder_in_actions = unique_list()
            install_actions = list()
            folder_out_actions = unique_list()
            for IID in folder_items: # folder_in actions
                installi = self.install_definitions_index[IID]
                folder_in_actions.extend(installi.action_list('folder_in'))
                install_actions.extend(installi.action_list('before'))
                install_actions.extend(installi.action_list('after'))
                folder_out_actions.extend(installi.action_list('folder_out'))
            installState.extend_instructions('copy', folder_in_actions)
            installState.extend_instructions('copy', install_actions)
            installState.extend_instructions('copy', folder_out_actions)
            installState.append_instructions('copy', self.platform_helper.create_echo_command("Progress: copied {current_item_for_progress_report} of {num_items_for_progress_report}".format(**locals())))
            current_item_for_progress_report += 1
        # messages about orphan iids
        for iid in installState.orphan_install_items:
            logging.info("Orphan item: %s", iid)
            installState.append_instructions('copy', self.platform_helper.create_echo_command("Don't know how to install "+iid))
        installState.append_instructions('copy', self.platform_helper.create_echo_command("Progress: copied {current_item_for_progress_report} of {num_items_for_progress_report}".format(**locals())))

    @func_log_wrapper
    def create_copy_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        retVal = list()
        source_url = "$(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)/"+source[0]

        if source[1] == '!file':       # get a single file, not recommneded
            retVal.extend(self.platform_helper.copy_tool.create_copy_file_to_dir_command(source_url, "."))
        elif source[1] == '!dir_cont': # get all files and folders from a folder
            retVal.extend(self.platform_helper.copy_tool.create_copy_dir_contents_to_dir_command(source_url, "."))
        elif source[1] == '!files':    # get all files from a folder
            retVal.extend(self.platform_helper.copy_tool.create_copy_dir_files_to_dir_command(source_url, "."))
        else:
            retVal.extend(self.platform_helper.copy_tool.create_copy_dir_to_dir_command(source_url, "."))
        logging.info("... %s; (%s - %s)", source_url, self.cvl.resolve_string(source_url), source[1])
        return retVal

    @func_log_wrapper
    def finalize_list_of_lines(self, installState):
        lines = list()
        lines.extend(self.platform_helper.get_install_instructions_prefix())
        lines.append(self.platform_helper.create_remark_command(datetime.datetime.today().isoformat()))

        lines.extend( ('\n', ) )

        lines.extend(sorted(installState.variables_assignment_lines))
        lines.extend( ('\n', ) )

        resolved_sync_intruction_lines = map(self.cvl.resolve_string, installState.instruction_lines['sync'])
        lines.extend(resolved_sync_intruction_lines)
        lines.extend( ('\n', ) )

        resolved_copy_intruction_lines = map(self.cvl.resolve_string, installState.instruction_lines['copy'])
        lines.extend(resolved_copy_intruction_lines)
        lines.extend( ('\n', ) )

        lines.extend(self.platform_helper.get_install_instructions_postfix())

        return lines

    @func_log_wrapper
    def write_batch_file(self, installState):
        lines = self.finalize_list_of_lines(installState)
        lines_after_var_replacement = '\n'.join([value_ref_re.sub(self.var_replacement_pattern, line) for line in lines])

        from utils import write_to_file_or_stdout
        out_file = self.cvl.get_str("__MAIN_OUT_FILE__")
        logging.info("... %s", out_file)
        with write_to_file_or_stdout(out_file) as fd:
            fd.write(lines_after_var_replacement)
            fd.write('\n')

        if out_file != "stdout":
            self.out_file_realpath = os.path.realpath(out_file)
            os.chmod(self.out_file_realpath, 0755)

    @func_log_wrapper
    def run_batch_file(self):
        logging.info("running batch file %s", self.out_file_realpath)
        from subprocess import Popen
        p = Popen(self.out_file_realpath)
        stdout, stderr = p.communicate()

    @func_log_wrapper
    def write_program_state(self):
        from utils import write_to_file_or_stdout
        state_file = self.cvl.get_str("__MAIN_STATE_FILE__")
        with write_to_file_or_stdout(state_file) as fd:
            augmentedYaml.writeAsYaml(self, fd)

    @func_log_wrapper
    def find_cycles(self):
            if not self.install_definitions_index:
                print ("index empty - nothing to check")
            else:
                try:
                    from pyinstl import installItemGraph
                    depend_graph = installItemGraph.create_dependencies_graph(self.install_definitions_index)
                    depend_cycles = installItemGraph.find_cycles(depend_graph)
                    if not depend_cycles:
                        print ("No depend cycles found")
                    else:
                        for cy in depend_cycles:
                            print("depend cycle:", " -> ".join(cy))
                    inherit_graph = installItemGraph.create_inheritItem_graph(self.install_definitions_index)
                    inherit_cycles = installItemGraph.find_cycles(inherit_graph)
                    if not inherit_cycles:
                        print ("No inherit cycles found")
                    else:
                        for cy in inherit_cycles:
                            print("inherit cycle:", " -> ".join(cy))
                except ImportError: # no installItemGraph, no worry
                    print("Could not load installItemGraph")

    @func_log_wrapper
    def needs(self, iid, out_list):
        """ return all items that depend on iid """
        if iid not in self.install_definitions_index:
            raise KeyError(iid+" is not in index")
        for dep in self.install_definitions_index[iid].depend_list():
            if dep in self.install_definitions_index:
                out_list.append(dep)
                self.needs(dep, out_list)
            else:
                out_list.append(dep+"(missing)")

    @func_log_wrapper
    def needed_by(self, iid):
        try:
            from pyinstl import installItemGraph
            graph = installItemGraph.create_dependencies_graph(self.install_definitions_index)
            needed_by_list = installItemGraph.find_needed_by(graph, iid)
            return needed_by_list
        except ImportError: # no installItemGraph, no worry
            print("Could not load installItemGraph")
            return None

