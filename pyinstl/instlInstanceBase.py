#!/usr/local/bin/python2.7
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
from installItem import InstallItem, read_index_from_yaml
from pyinstl.utils import *
from pyinstl.searchPaths import SearchPaths
from instlException import InstlException

import platform
current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'Mac'
elif current_os == 'Windows':
    current_os = 'Win'

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
                    sync_folder =  "/".join( ("$(LOCAL_SYNC_DIR)", "$(REPO_NAME)", "$(REL_SRC_PATH)", instlInstance.relative_sync_folder_for_source(source)))
                    self.no_copy_items_by_sync_folder[sync_folder].append(IID)

class InstlInstanceBase(object):
    """ Main object of instl. Keeps the state of variables and install index
        and knows how to create a batch file for installation. InstlInstanceBase
        must be inherited by platform specific implementations, such as InstlInstance_mac
        or InstlInstance_win.
    """
    __metaclass__ = abc.ABCMeta
    @func_log_wrapper
    def __init__(self):
        self.out_file_realpath = None
        self.install_definitions_index = dict()
        self.cvl = ConfigVarList()
        self.var_replacement_pattern = None
        self.init_default_vars()
        # initialize the search paths helper with the current directory and dir where instl is now
        self.search_paths_helper = SearchPaths(self.cvl.get_configVar_obj("__SEARCH_PATHS__"))
        self.search_paths_helper.add_search_path(os.getcwd())
        self.search_paths_helper.add_search_path(os.path.dirname(sys.argv[0]))
        self.progress_file = None
        
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
            is None (the default) creare representation of everything.
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
    def init_default_vars(self):
        var_description = "from InstlInstanceBase.init_default_vars"
        self.cvl.add_const_config_variable("CURRENT_OS", var_description, current_os)
        self.cvl.set_variable("TARGET_OS", var_description).append(current_os)
        self.cvl.add_const_config_variable("__INSTL_VERSION__", var_description, *INSTL_VERSION)
        self.cvl.set_variable("LOCAL_SYNC_DIR", var_description).append(appdirs.user_cache_dir(this_program_name, this_program_name))

        log_file = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=False)
        self.cvl.set_variable("LOG_FILE", var_description).extend( (log_file, logging.getLevelName(pyinstl.log_utils.default_logging_level), pyinstl.log_utils.default_logging_started) )
        debug_log_file = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=True)
        self.cvl.set_variable("LOG_DEBUG_FILE", var_description).extend( (debug_log_file, logging.getLevelName(pyinstl.log_utils.debug_logging_level), pyinstl.log_utils.debug_logging_started) )
        for identifier in self.cvl:
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    @func_log_wrapper
    def do_command(self, the_command, installState):
        self.read_input_files()
        self.resolve_index_inheritance()
        self.calculate_default_install_item_set(installState)
        if the_command in ("sync", 'synccopy'):
            logging.info("Creating sync instructions")
            self.init_sync_vars()
            self.create_sync_instructions(installState)
        if the_command in ("copy", 'synccopy'):
            logging.info("Creating copy instructions")
            self.init_copy_vars()
            self.create_copy_instructions(installState)
        self.create_variables_assignment(installState)

    @func_log_wrapper
    def do_command_batch_mode(self):
        installState = InstallInstructionsState()
        self.do_command(self.name_space_obj.command, installState)
        self.write_batch_file(installState)
        if "__MAIN_RUN_INSTALLATION__" in self.cvl:
            self.run_batch_file()

    @func_log_wrapper
    def do_something(self):
        try:
            logging.debug("... %s", self.name_space_obj.command)
            if self.name_space_obj.command == "version":
                print(" ".join( (this_program_name, "version", ".".join(self.cvl.get_list("__INSTL_VERSION__")))))
            else:
                import do_something
                do_something.do_something(self.name_space_obj.command)
        except Exception as es:
            raise InstlException(" ".join( ("Error while doing command", "'"+self.name_space_obj.command+"':\n") ), es)

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
            if not self.internal_identifier_re.match(identifier): # do not write internal state indentifiers
                installState.variables_assignment_lines.append(self.create_var_assign(identifier,self.cvl.get_str(identifier)))

    @func_log_wrapper
    def init_sync_vars(self):
        if "SVN_REPO_URL" not in self.cvl:
            raise ValueError("'SVN_REPO_URL' was not defined")
        if "SVN_CLIENT_PATH" not in self.cvl:
            raise ValueError("'SVN_CLIENT_PATH' was not defined")
        svn_client_full_path = self.search_paths_helper.find_file_with_search_paths(self.cvl.get_str("SVN_CLIENT_PATH"))
        self.cvl.set_variable("SVN_CLIENT_PATH", "from InstlInstanceBase.init_sync_vars").append(svn_client_full_path)
        
        if "BOOKKEEPING_DIR_URL" not in self.cvl:
            self.cvl.set_variable("BOOKKEEPING_DIR_URL").append("$(SVN_REPO_URL)/instl")
        bookkeeping_relative_path = relative_url(self.cvl.get_str("SVN_REPO_URL"), self.cvl.get_str("BOOKKEEPING_DIR_URL"))
        self.cvl.set_variable("REL_BOOKKIPING_PATH", "from InstlInstanceBase.init_sync_vars").append(bookkeeping_relative_path)
       
        rel_sources = relative_url(self.cvl.get_str("SVN_REPO_URL"), self.cvl.get_str("BASE_SRC_URL"))
        self.cvl.set_variable("REL_SRC_PATH", "from InstlInstanceBase.init_sync_vars").append(rel_sources)


        if "REPO_REV" not in self.cvl:
            self.cvl.set_variable("REPO_REV", "from InstlInstanceBase.init_sync_vars").append("HEAD")
        if "REPO_NAME" not in self.cvl:
            repo_name = last_url_item(self.cvl.get_str("SVN_REPO_URL"))
            self.cvl.set_variable("REPO_NAME", "from InstlInstanceBase.init_sync_vars").append(repo_name)
        if "BASE_SRC_URL" not in self.cvl:
            self.cvl.set_variable("BASE_SRC_URL", "from InstlInstanceBase.init_sync_vars").append("$(SVN_REPO_URL)/$(TARGET_OS)")
        if "BOOKKEEPING_DIR_URL" not in self.cvl:
            self.cvl.set_variable("BOOKKEEPING_DIR_URL", "from InstlInstanceBase.init_sync_vars").append("$(SVN_REPO_URL)/instl")
        for identifier in ("SVN_REPO_URL", "SVN_CLIENT_PATH", "REL_SRC_PATH", "REPO_REV", "REPO_NAME", "BASE_SRC_URL", "BOOKKEEPING_DIR_URL"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))
        self.progress_file = self.cvl.get_str("SYNC_PROGRESS_FILE", default=None)
        if self.progress_file:
            self.progress_file = os.path.realpath(self.progress_file)

    @func_log_wrapper
    def init_copy_vars(self):
        if "REL_SRC_PATH" not in self.cvl:
            if "SVN_REPO_URL" not in self.cvl:
                raise ValueError("'SVN_REPO_URL' was not defined")
            if "BASE_SRC_URL" not in self.cvl:
                raise ValueError("'BASE_SRC_URL' was not defined")
            rel_sources = relative_url(self.cvl.get_str("SVN_REPO_URL"), self.cvl.get_str("BASE_SRC_URL"))
            self.cvl.set_variable("REL_SRC_PATH", "from InstlInstanceBase.init_sync_vars").append(rel_sources)

        if "REPO_NAME" not in self.cvl:
            if "SVN_REPO_URL" not in self.cvl:
                raise ValueError("'SVN_REPO_URL' was not defined")
            repo_name = last_url_item(self.cvl.get_str("SVN_REPO_URL"))
            self.cvl.set_variable("REPO_NAME", "from InstlInstanceBase.init_sync_vars").append(repo_name)
        if "COPY_TOOL" not in self.cvl:
            from copyCommander import DefaultCopyToolName
            self.cvl.set_variable("COPY_TOOL", "from InstlInstanceBase.init_sync_vars").append(DefaultCopyToolName(self.cvl.get_str("TARGET_OS")))
        for identifier in ("REL_SRC_PATH", "REPO_NAME", "COPY_TOOL"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))
        self.progress_file = self.cvl.get_str("COPY_PROGRESS_FILE", default=None)
        if self.progress_file:
            self.progress_file = os.path.realpath(self.progress_file)

    @func_log_wrapper
    def create_sync_instructions(self, installState):
        installState.append_instructions('sync', self.create_echo_command("starting sync from $(BASE_SRC_URL)", self.progress_file))
        installState.indent_level += 1
        installState.extend_instructions('sync', self.make_directory_cmd("$(LOCAL_SYNC_DIR)/$(REPO_NAME)"))
        installState.extend_instructions('sync', self.change_directory_cmd("$(LOCAL_SYNC_DIR)/$(REPO_NAME)"))
        installState.indent_level += 1
        installState.append_instructions('sync', " ".join(('"$(SVN_CLIENT_PATH)"', "co", '"$(BOOKKEEPING_DIR_URL)"', '"$(REL_BOOKKIPING_PATH)"', "--revision", "$(REPO_REV)", "--depth", "infinity")))
        installState.append_instructions('sync', self.create_echo_command("synced index file $(BOOKKEEPING_DIR_URL)", self.progress_file))
        for iid  in installState.full_install_items:                   # svn pulling actions
            installi = self.install_definitions_index[iid]
            if installi.source_list():
                for source in installi.source_list():                   # svn pulling actions
                    installState.extend_instructions('sync', self.create_svn_sync_instructions_for_source(source))
                    #installState.append_instructions('sync', self.create_echo_command("synced source {}".format(source), self.progress_file))
                installState.append_instructions('sync', self.create_echo_command("synced {}".format(installi.name), self.progress_file))
        for iid in installState.orphan_install_items:
            installState.append_instructions('sync', self.create_echo_command("Don't know how to sync "+iid))
        installState.append_instructions('sync', self.create_echo_command("finished sync from $(BASE_SRC_URL)", self.progress_file))
        installState.indent_level -= 1

    @func_log_wrapper
    def create_svn_sync_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        retVal = list()
        source_url =   '/'.join( ("$(BASE_SRC_URL)", source[0]) )
        target_path =  '/'.join( ("$(REL_SRC_PATH)", source[0]) )
        if source[1] == '!file':
            source_url = '/'.join( source_url.split("/")[0:-1]) # skip the file name sync the whole folder
            target_path = '/'.join( target_path.split("/")[0:-1]) # skip the file name sync the whole folder
        command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"'+source_url+'"', '"'+target_path+'"', "--revision", "$(REPO_REV)"]
        if source[1] in ('!file', '!files'):
            command_parts.extend( ( "--depth", "files") )
        else:
            command_parts.extend( ( "--depth", "infinity") )
        retVal.append(" ".join(command_parts))
        logging.info("... %s; (%s)", source[0], source[1])
        return retVal

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
        installState.append_instructions('copy', self.create_echo_command("starting copy", self.progress_file))
        from copyCommander import CopyCommanderFactory
        copy_command_creator = CopyCommanderFactory(self.cvl.get_str("TARGET_OS"), self.cvl.get_str("COPY_TOOL"))
        for folder_name, folder_items in installState.install_items_by_target_folder.iteritems():
            installState.append_instructions('copy', self.create_echo_command("Starting copy to folder "+folder_name, self.progress_file))
            installState.indent_level += 1
            logging.info("... folder %s (%s)", folder_name, self.cvl.resolve_string(folder_name))
            installState.extend_instructions('copy', self.make_directory_cmd(folder_name))
            installState.extend_instructions('copy', self.change_directory_cmd(folder_name))
            folder_in_actions = unique_list()
            install_item_instructions = list()
            folder_out_actions = unique_list()
            for IID in folder_items: # folder_in actions
                installi = self.install_definitions_index[IID]
                folder_in_actions.extend(installi.action_list('folder_in'))
                for source in installi.source_list():
                    install_item_instructions.extend(installi.action_list('before'))
                    install_item_instructions.extend(self.create_copy_instructions_for_source(source, copy_command_creator))
                    install_item_instructions.extend(installi.action_list('after'))
                folder_out_actions.extend(installi.action_list('folder_out'))
            installState.extend_instructions('copy', folder_in_actions)
            installState.indent_level += 1
            installState.extend_instructions('copy', install_item_instructions)
            installState.extend_instructions('copy', folder_out_actions)
            installState.append_instructions('copy', self.create_echo_command("Done copy to folder "+folder_name, self.progress_file))
            installState.indent_level -= 1
            installState.indent_level -= 1

        # actions instructions for sources that do not need copying
        for folder_name, folder_items in installState.no_copy_items_by_sync_folder.iteritems():
            logging.info("... non-copy items folder %s (%s)", folder_name, self.cvl.resolve_string(folder_name))
            installState.extend_instructions('copy', self.change_directory_cmd(folder_name))
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
        # messages about orphan iids
        for iid in installState.orphan_install_items:
            logging.info("Orphan item: %s", iid)
            installState.append_instructions('copy', self.create_echo_command("Don't know how to install "+iid))
        installState.append_instructions('copy', self.create_echo_command("finished copy", self.progress_file))

    @func_log_wrapper
    def create_copy_instructions_for_source(self, source, copy_command_creator):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        retVal = list()
        source_url = "$(LOCAL_SYNC_DIR)/$(REPO_NAME)/$(REL_SRC_PATH)/"+source[0]

        retVal.append(self.create_echo_command("Starting copy of {}".format(source[0]), self.progress_file))
        if source[1] == '!file':       # get a single file, not recommneded
            retVal.extend(copy_command_creator.create_copy_file_to_dir_command(source_url, "."))
        elif source[1] == '!dir_cont': # get all files and folders from a folder
            retVal.extend(copy_command_creator.create_copy_dir_contents_to_dir_command(source_url, "."))
        elif source[1] == '!files':    # get all files from a folder
            retVal.extend(copy_command_creator.create_copy_dir_files_to_dir_command(source_url, "."))
        else:
            retVal.extend(copy_command_creator.create_copy_dir_to_dir_command(source_url, "."))
        logging.info("... %s; (%s - %s)", source_url, self.cvl.resolve_string(source_url), source[1])
        retVal.append(self.create_echo_command("Done copy of {}".format(source[0]), self.progress_file))
        return retVal

    @func_log_wrapper
    def finalize_list_of_lines(self, installState):
        lines = list()
        lines.extend(self.get_install_instructions_prefix())
        lines.append(self.create_remark_command(datetime.datetime.today().isoformat()))

        lines.extend( ('\n', ) )

        lines.extend(sorted(installState.variables_assignment_lines))
        lines.extend( ('\n', ) )

        resolved_sync_intruction_lines = map(self.cvl.resolve_string, installState.instruction_lines['sync'])
        lines.extend(resolved_sync_intruction_lines)
        lines.extend( ('\n', ) )

        resolved_copy_intruction_lines = map(self.cvl.resolve_string, installState.instruction_lines['copy'])
        lines.extend(resolved_copy_intruction_lines)
        lines.extend( ('\n', ) )

        lines.extend(self.get_install_instructions_postfix())

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

    @func_log_wrapper
    def do_da_interactive(self):
        from instlInstanceBase_interactive import go_interactive
        go_interactive(self)

    @abc.abstractmethod
    def get_install_instructions_prefix(self):
        """ platform specific """
        pass

    @abc.abstractmethod
    def get_install_instructions_postfix(self):
        """ platform specific last lines of the install script """
        pass

    @abc.abstractmethod
    def make_directory_cmd(self, directory):
        """ platform specific mkdir for install script """
        pass

    @abc.abstractmethod
    def change_directory_cmd(self, directory):
        """ platform specific cd for install script """
        pass

    @abc.abstractmethod
    def get_svn_folder_cleanup_instructions(self, directory):
        """ platform specific cleanup of svn locks """
        pass

    @abc.abstractmethod
    def create_var_assign(self, identifier, value):
        pass

    @abc.abstractmethod
    def create_echo_command(self, message, file=None):
        pass

    @abc.abstractmethod
    def create_remark_command(self, remark):
        pass

    @func_log_wrapper
    def read_command_line_options(self, arglist=None):
        """ parse command line options """
        args_str = "No options given"
        if arglist is not None:
            logging.info("arglist: %s", " ".join(arglist))
        self.cvl.add_const_config_variable('__COMMAND_LINE_OPTIONS__', "read only value", args_str)
        if not arglist or len(arglist) == 0:
            auto_run_file_path = None
            auto_run_file_name = "auto_run_instl.yaml"
            auto_run_file_path = self.search_paths_helper.find_file_with_search_paths(auto_run_file_name)
            if auto_run_file_path:
                arglist = ("@"+auto_run_file_path,)
                logging.info("found auto run file %s", auto_run_file_name)
        if arglist and len(arglist) > 0:
            parser = prepare_args_parser()
            self.name_space_obj = cmd_line_options()
            parser.parse_args(arglist, namespace=self.name_space_obj)
            self.mode = self.name_space_obj.mode
            if self.mode == "batch":
                self.init_from_cmd_line_options(self.name_space_obj)
        else:
            self.mode = "interactive"

class cmd_line_options(object):
    """ namespace object to give to parse_args
        holds command line options
    """
    def __init__(self):
        self.command = None
        self.input_files = None
        self.output_file = None
        self.run = False
        self.state_file = None
        self.todo_args = None

    def __str__(self):
        return "\n".join([''.join((n, ": ", str(v))) for n,v in sorted(vars(self).iteritems())])


def prepare_args_parser():
    def decent_convert_arg_line_to_args(self, arg_line):
        """ parse a file with options so that we do not have to write one sub-option
            per line.  Remove empty lines, comment lines, and end of line comments.
            ToDo: handle quotes
        """
        line_no_whitespce = arg_line.strip()
        if line_no_whitespce and line_no_whitespce[0] != '#':
            for arg in line_no_whitespce.split():
                if not arg:
                    continue
                elif  arg[0] == '#':
                    break
                yield arg

    parser = argparse.ArgumentParser(description='instl: cross platform svn based installer',
                    prefix_chars='-+',
                    fromfile_prefix_chars='@',
                    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    argparse.ArgumentParser.convert_arg_line_to_args = decent_convert_arg_line_to_args

    subparsers = parser.add_subparsers(dest='command', help='sub-command help')
    parser_sync = subparsers.add_parser('sync',
                                        help='sync files to be installed from server to temp folder')
    parser_copy = subparsers.add_parser('copy',
                                        help='copy files from temp folder to target paths')
    parser_synccopy = subparsers.add_parser('synccopy',
                                        help='sync files to be installed from server to temp folder and copy files from temp folder to target paths')

    for subparser in (parser_sync, parser_copy, parser_synccopy):
        subparser.set_defaults(mode='batch')
        standard_options = subparser.add_argument_group(description='standard arguments:')
        standard_options.add_argument('--in','-i',
                                    required=True,
                                    nargs='+',
                                    metavar='list-of-input-files',
                                    dest='input_files',
                                    help="file(s) to read index and defintions from")
        standard_options.add_argument('--out','-o',
                                    required=True,
                                    nargs=1,
                                    metavar='path-to-output-file',
                                    dest='output_file',
                                    help="a file to write sync/copy instructions")
        standard_options.add_argument('--run','-r',
                                    required=False,
                                    default=False,
                                    action='store_true',
                                    dest='run',
                                    help="run the installation instructions script")
        standard_options.add_argument('--state','-s',
                                    required=False,
                                    nargs='?',
                                    const="stdout",
                                    metavar='path-to-state-file',
                                    dest='state_file',
                                    help="a file to write program state - good for debugging")

        parser_version = subparsers.add_parser('version', help='display instl version')
        parser_version.set_defaults(mode='do_something')

        if current_os == 'Mac':
            parser_alias = subparsers.add_parser('alias',
                                                help='create Mac OS alias')
            parser_alias.set_defaults(mode='do_something')
            parser_alias.add_argument('todo_args',
                                    action='append',
                                    metavar='path_to_original',
                                    help="paths to original file")
            parser_alias.add_argument('todo_args',
                                    action='append',
                                    metavar='path_to_alias',
                                    help="paths to original file and to alias file")
    return parser;
