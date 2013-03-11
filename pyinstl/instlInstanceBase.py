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

import configVar
from configVarList import ConfigVarList, value_ref_re
from aYaml import augmentedYaml
from installItem import InstallItem, read_index_from_yaml
from pyinstl.utils import *

import platform
current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'mac'
elif current_os == 'Windows':
    current_os = 'win'

INSTL_VERSION=(0, 2, 0)
this_program_name = "instl"

class InstallInstructionsState(object):
    """ holds state for specific creating of install instructions """
    def __init__(self):
        self.root_install_items = unique_list()
        self.full_install_items = unique_list()
        self.orphan_install_items = unique_list()
        self.install_items_by_folder = defaultdict(unique_list)
        self.variables_assignment_lines = list()
        self.copy_instruction_lines = list()
        self.sync_paths = unique_list()
        self.sync_instruction_lines = list()

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['root_install_items'] = list(self.root_install_items)
        retVal['full_install_items'] = list(self.full_install_items)
        retVal['orphan_install_items'] = list(self.orphan_install_items)
        retVal['install_items_by_folder'] = {folder: list(self.install_items_by_folder[folder]) for folder in self.install_items_by_folder}
        retVal['variables_assignment_lines'] = list(self.variables_assignment_lines)
        retVal['copy_instruction_lines'] = self.copy_instruction_lines
        retVal['sync_paths'] = list(self.sync_paths)
        retVal['sync_instruction_lines'] = self.sync_instruction_lines
        return retVal

    def calculate_full_install_items_set(self, instlInstance):
        """ calculate the set of idds to install by starting with the root set and adding all dependencies.
            Initial list of idd should already be in self.root_install_items.
            results are accomulated in InstallInstructionsState.
            If an install items was not found for a idd, the idd is added to the orphan set.
        """
        # root_install_items might have guid in it, translate them to idds
        root_install_idds_translated = unique_list()
        for IDD in self.root_install_items:
            if instlInstance.guid_re.match(IDD):
                root_install_idds_translated.extend(instlInstance.idds_from_guid(IDD))
            else:
                root_install_idds_translated.append(IDD)
        for IDD in root_install_idds_translated:
            try:
                instlInstance.install_definitions_index[IDD].get_recursive_depends(instlInstance.install_definitions_index, self.full_install_items, self.orphan_install_items)
            except KeyError:
                self.orphan_install_items.append(IDD)
        self.__sort_install_items_by_folder(instlInstance)

    def __sort_install_items_by_folder(self, instlInstance):
        for IDD in self.full_install_items:
            for folder in instlInstance.install_definitions_index[IDD].folder_list():
                self.install_items_by_folder[folder].append(IDD)

class InstlInstanceBase(object):
    """ Main object of instl. Keeps the state of variables and install index
        and knows how to create a batch file for installation. InstlInstanceBase
        must be inherited by platform specific implementations, such as InstlInstance_mac
        or InstlInstance_win.
    """
    __metaclass__ = abc.ABCMeta
    def __init__(self):
        self.out_file_realpath = None
        self.install_definitions_index = dict()
        self.cvl = ConfigVarList()
        self.var_replacement_pattern = None
        self.init_default_vars()

        self.guid_re = re.compile("""
                        [a-f0-9]{8}
                        (-[a-f0-9]{4}){3}
                        -[a-f0-9]{12}
                        $
                        """, re.VERBOSE)

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

    def init_default_vars(self):
        self.cvl.add_const_config_variable("__INSTL_VERSION__", "from InstlInstanceBase.init_default_vars", *INSTL_VERSION)
        self.cvl.set_variable("LOCAL_SYNC_DIR", "from InstlInstanceBase.init_default_vars").append(appdirs.user_cache_dir(this_program_name, this_program_name))

    def do_command(self):
        self.read_input_files()
        self.resolve_index_inheritance()
        installState = InstallInstructionsState()
        self.calculate_default_install_item_set(installState)
        if self.name_space_obj.command == "sync":
            self.create_sync_instructions(installState)
        if self.name_space_obj.command == "copy":
            self.create_copy_instructions(installState)
        self.write_batch_file(installState)

    def do_something(self):
        try:
            if self.name_space_obj.command == "version":
                print(" ".join( (this_program_name, "version", ".".join(self.cvl.get("__INSTL_VERSION__")))))
            else:
                import do_something
                do_something.do_something(self.something_to_do)
        except Exception as es:
            import traceback
            tb = traceback.format_exc()
            print("do_something", es, tb)

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

    internal_identifier_re = re.compile("""
                                        __                  # dunder here
                                        (?P<internal_identifier>\w*)
                                        __                  # dunder there
                                        """, re.VERBOSE)
    def read_defines(self, a_node):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node:
                if not self.internal_identifier_re.match(identifier): # do not read internal state indentifiers
                    self.cvl.set_variable(identifier, str(contents.start_mark)).extend([item.value for item in contents])
                elif identifier == '__include__':
                    for file_name in contents:
                        resolved_file_name = self.cvl.resolve_string(file_name.value)
                        self.read_file(resolved_file_name)

    def read_index(self, a_node):
        self.install_definitions_index.update(read_index_from_yaml(a_node))

    def read_input_files(self):
        input_files = self.cvl.get_list("__MAIN_INPUT_FILES__")
        if input_files:
            file_actually_opened = list()
            for file_path in input_files:
                try:
                    self.read_file(file_path)
                except Exception as ex:
                    print("failed to read", file_path, ex)
                else:
                    file_actually_opened.append(os.path.abspath(file_path))
            self.cvl.add_const_config_variable("__MAIN_INPUT_FILES_ACTUALLY_OPENED__", "opened by read_input_files", *file_actually_opened)

    def read_file(self, file_path):
        try:
            with open_for_read_file_or_url(file_path) as file_fd:
                for a_node in yaml.compose_all(file_fd):
                    if a_node.tag == '!define':
                        self.read_defines(a_node)
                    elif a_node.tag == '!index':
                        self.read_index(a_node)
                    else:
                        print("Unknown document tag '"+a_node.tag+"'; Tag should be one of: !define, !index'")
        except Exception as ex:
            import traceback
            tb = traceback.format_exc()
            print("read_file", file_path, ex, tb)

    def resolve_index_inheritance(self):
        for install_def in self.install_definitions_index.values():
            install_def.resolve_inheritance(self.install_definitions_index)

    def guid_list(self):
        retVal = unique_list()
        retVal.extend(filter(bool, [install_def.guid for install_def in self.install_definitions_index.values()]))
        return retVal

    def idds_from_guid(self, guid):
        retVal = list()
        for idd, install_def in self.install_definitions_index.iteritems():
            if install_def.guid == guid:
                retVal.append(idd)
        return retVal

    def calculate_default_install_item_set(self, installState):
        """ calculate the set of idd to install from the "__MAIN_INSTALL_TARGETS__" variable.
            Full set of install idds and orphan idds are also writen to variable.
        """
        if "MAIN_INSTALL_TARGETS" not in self.cvl:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        installState.root_install_items.extend(self.cvl.get_list("MAIN_INSTALL_TARGETS"))
        self.cvl.set_variable("__MAIN_INSTALL_TARGETS__").extend(installState.root_install_items)
        installState.calculate_full_install_items_set(self)
        self.cvl.set_variable("__FULL_LIST_OF_INSTALL_TARGETS__").extend(installState.full_install_items)
        self.cvl.set_variable("__ORPHAN_INSTALL_TARGETS__").extend(installState.orphan_install_items)

    def create_variables_assignment(self, installState):
        for identifier in self.cvl:
            if not self.internal_identifier_re.match(identifier): # do not write internal state indentifiers
                installState.variables_assignment_lines.append(self.create_var_assign(identifier,self.cvl.get_str(identifier)))

    def init_sync_vars(self):
        if "SVN_REPO_URL" not in self.cvl:
            raise ValueError("'SVN_REPO_URL' was not defined")
        if "BASE_SRC_URL" not in self.cvl:
            raise ValueError("'BASE_SRC_URL' was not defined")
        if "BOOKKEEPING_DIR_URL" not in self.cvl:
            raise ValueError("'BOOKKEEPING_DIR_URL' was not defined")

        rel_sources = relative_url(self.cvl.get_str("SVN_REPO_URL"), self.cvl.get_str("BASE_SRC_URL"))
        self.cvl.set_variable("REL_SRC_PATH", "from InstlInstanceBase.init_sync_vars").append(rel_sources)
        
        bookkeeping_relative_path = relative_url(self.cvl.get_str("SVN_REPO_URL"), self.cvl.get_str("BOOKKEEPING_DIR_URL"))
        self.cvl.set_variable("REL_BOOKKIPING_PATH", "from InstlInstanceBase.init_sync_vars").append(bookkeeping_relative_path)

        if "REPO_REV" not in self.cvl:
            self.cvl.set_variable("REPO_REV", "from InstlInstanceBase.init_sync_vars").append("HEAD")

        if "REPO_NAME" not in self.cvl:
            repo_name = last_url_item(self.cvl.get_str("SVN_REPO_URL"))
            self.cvl.set_variable("REPO_NAME", "from InstlInstanceBase.init_sync_vars").append(repo_name)
 
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

    def create_sync_instructions(self, installState):
        self.init_sync_vars()
        self.create_variables_assignment(installState)
        installState.sync_instruction_lines.extend(self.make_directory_cmd("$(LOCAL_SYNC_DIR)/$(REPO_NAME)"))
        installState.sync_instruction_lines.extend(self.change_directory_cmd("$(LOCAL_SYNC_DIR)/$(REPO_NAME)"))
        installState.sync_instruction_lines.append(" ".join(('"$(SVN_CLIENT_PATH)"', "co", '"$(BOOKKEEPING_DIR_URL)"', '"$(REL_BOOKKIPING_PATH)"', "--revision", "$(REPO_REV)")))
        for idd  in installState.full_install_items:                   # svn pulling actions
            installi = self.install_definitions_index[idd]
            for source in installi.source_list():                   # svn pulling actions
                installState.sync_instruction_lines.extend(self.create_svn_sync_instructions_for_source(source))
 
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
        retVal.append(" ".join(command_parts))
        return retVal
   
    def create_copy_instructions(self, installState):
        self.init_copy_vars()
        self.create_variables_assignment(installState)
        for folder_name, folder_items in installState.install_items_by_folder.iteritems():
            installState.copy_instruction_lines.extend(self.make_directory_cmd(folder_name))
            installState.copy_instruction_lines.extend(self.change_directory_cmd(folder_name))
            folder_in_actions = unique_list()
            install_item_instructions = list()
            folder_out_actions = unique_list()
            for IDD in folder_items: # folder_in actions
                installi = self.install_definitions_index[IDD]
                folder_in_actions.extend(installi.action_list('folder_in'))
                for source in installi.source_list():
                    install_item_instructions.extend(self.create_copy_instructions_for_source(source))
                folder_out_actions.extend(installi.action_list('folder_out'))
            installState.copy_instruction_lines.extend(folder_in_actions)
            installState.copy_instruction_lines.extend(install_item_instructions)
            installState.copy_instruction_lines.extend(folder_out_actions)

    def create_copy_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """
        retVal = list()
        source_url = "$(LOCAL_SYNC_DIR)/$(REPO_NAME)/$(REL_SRC_PATH)/"+source[0]

        if source[1] == '!file': # get a single file, not recommneded
            retVal.extend(self.create_copy_file_to_dir_command(source_url, "."))
        elif source[1] == '!dir_cont': # get all files and folders from a folder
            retVal.extend(self.create_copy_dir_contents_to_dir_command(source_url, "."))
        elif source[1] == '!files': # get all files from a folder
            retVal.extend(self.create_copy_dir_files_to_dir_command(source_url, "."))
        else:
            retVal.extend(self.create_copy_dir_to_dir_command(source_url, "."))
        return retVal

    def finalize_list_of_lines(self, installState):
        lines = list()
        lines.extend(self.get_install_instructions_prefix())
        lines.extend( ('\n', ) )

        lines.extend(sorted(installState.variables_assignment_lines))
        lines.extend( ('\n', ) )


        lines.extend(installState.sync_instruction_lines)
        lines.extend( ('\n', ) )

        lines.extend(installState.copy_instruction_lines)
        lines.extend( ('\n', ) )

        lines.extend(self.get_install_instructions_postfix())

        return lines

    def write_batch_file(self, installState):
        lines = self.finalize_list_of_lines(installState)
        lines_after_var_replacement = '\n'.join([value_ref_re.sub(self.var_replacement_pattern, line) for line in lines])

        from utils import write_to_file_or_stdout
        out_file = self.cvl.get_str("__MAIN_OUT_FILE__")
        with write_to_file_or_stdout(out_file) as fd:
            fd.write(lines_after_var_replacement)
            fd.write('\n')

        if out_file != "stdout":
            self.out_file_realpath = os.path.realpath(out_file)
            os.chmod(self.out_file_realpath, 0755)

    def write_program_state(self):
        from utils import write_to_file_or_stdout
        state_file = self.cvl.get_str("__MAIN_STATE_FILE__")
        with write_to_file_or_stdout(state_file) as fd:
            augmentedYaml.writeAsYaml(self, fd)

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
                except ImportError as IE: # no installItemGraph, no worry
                    print("Could not load installItemGraph")

    def needs(self, idd, out_list):
        """ return all items that depend on idd """
        if idd not in self.install_definitions_index:
            raise KeyError(idd+" is not in index")
        for dep in self.install_definitions_index[idd].depend_list():
            if dep in self.install_definitions_index:
                out_list.append(dep)
                self.needs(dep, out_list)
            else:
                out_list.append(dep+"(missing)")

    def needed_by(self, idd):
        try:
            from pyinstl import installItemGraph
            graph = installItemGraph.create_dependencies_graph(self.install_definitions_index)
            needed_by_list = installItemGraph.find_needed_by(graph, idd)
            return needed_by_list
        except ImportError as IE: # no installItemGraph, no worry
            print("Could not load installItemGraph")
            return None

    def do_da_interactive(self):
        try:
            from instlInstanceBase_interactive import go_interactive
            go_interactive(self)
        except Exception as es:
            print("go_interactive", es)
            raise

    @abc.abstractmethod
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        """ platform specific """
        pass

    @abc.abstractmethod
    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        """ platform specific """
        pass

    @abc.abstractmethod
    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        """ platform specific """
        pass

    @abc.abstractmethod
    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        """ platform specific """
        pass

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

    def read_command_line_options(self, arglist=None):
        """ parse command line options """
        try:
            if arglist and len(arglist) > 0:
                parser = prepare_args_parser()
                self.name_space_obj = cmd_line_options()
                args = parser.parse_args(arglist, namespace=self.name_space_obj)
                self.mode = self.name_space_obj.mode
                if self.mode == "batch":
                    self.init_from_cmd_line_options(self.name_space_obj)
            else:
                self.mode = "interactive"
        except Exception as ex:
            import traceback
            tb = traceback.format_exc()
            print(ex, tb)
            raise

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
        return "\n".join([n+": "+str(v) for n,v in sorted(vars(self).iteritems())])

        
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

    for subparser in (parser_sync, parser_copy):
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
        
        if current_os == 'mac':
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
