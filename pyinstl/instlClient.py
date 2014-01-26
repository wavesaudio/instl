#!/usr/bin/env python2.7

from __future__ import print_function
from collections import OrderedDict, defaultdict
import logging

from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *
from installItem import read_index_from_yaml, InstallItem
from aYaml import augmentedYaml

from instlInstanceBase import InstlInstanceBase


class InstallInstructionsState(object):
    """ holds state for specific creating of install instructions """
    @func_log_wrapper
    def __init__(self):
        self.root_install_items = unique_list()
        self.full_install_items = unique_list()
        self.orphan_install_items = unique_list()
        self.install_items_by_target_folder = defaultdict(unique_list)
        self.no_copy_items_by_sync_folder = defaultdict(unique_list)
        self.sync_paths = unique_list()

    @func_log_wrapper
    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['root_install_items'] = list(self.root_install_items)
        retVal['full_install_items'] = list(self.full_install_items)
        retVal['orphan_install_items'] = list(self.orphan_install_items)
        retVal['install_items_by_target_folder'] = {folder: list(self.install_items_by_target_folder[folder]) for folder in self.install_items_by_target_folder}
        retVal['no_copy_items_by_sync_folder'] = list(self.no_copy_items_by_sync_folder)
        #retVal['variables_assignment_lines'] = list(self.variables_assignment_lines)
        #retVal['copy_instruction_lines'] = self.instruction_lines['copy']
        retVal['sync_paths'] = list(self.sync_paths)
        #retVal['sync_instruction_lines'] = self.instruction_lines['sync']
        return retVal

    @func_log_wrapper
    def __sort_install_items_by_target_folder(self, instlInstance):
        for IID in self.full_install_items:
            folder_list_for_idd = instlInstance.install_definitions_index[IID].folder_list()
            if folder_list_for_idd:
                for folder in folder_list_for_idd:
                    norm_folder = os.path.normpath(folder)
                    self.install_items_by_target_folder[norm_folder].append(IID)
            else: # items that need no copy
                source_list_for_idd = instlInstance.install_definitions_index[IID].source_list()
                for source in source_list_for_idd:
                    sync_folder =  os.path.join( ("$(LOCAL_SYNC_DIR)", "$(REL_SRC_PATH)", instlInstance.relative_sync_folder_for_source(source)))
                    self.no_copy_items_by_sync_folder[sync_folder].append(IID)

    @func_log_wrapper
    def calculate_full_install_items_set(self, instlInstance):
        """ calculate the set of iids to install by starting with the root set and adding all dependencies.
            Initial list of iids should already be in self.root_install_items.
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

class InstlClient(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlClient, self).__init__(initial_vars)
        self.install_definitions_index = dict()
        self.cvl.set_var("__ALLOWED_COMMANDS__").extend( ('sync', 'copy', 'synccopy') )

    @func_log_wrapper
    def do_command(self):
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        if the_command in self.cvl.get_list("__ALLOWED_COMMANDS__"):
            #print("client_commands", the_command)
            installState = InstallInstructionsState()
            self.read_yaml_file(self.cvl.get_str("__MAIN_INPUT_FILE__"))
            self.resolve_defined_paths()
            self.resolve_index_inheritance()
            self.calculate_default_install_item_set(installState)
            if the_command in ("sync", "synccopy"):
                logging.info("Creating sync instructions")
                if self.cvl.get_str("REPO_TYPE") == "URL":
                    from instlInstanceSync_url import InstlInstanceSync_url
                    syncer = InstlInstanceSync_url(self)
                elif self.cvl.get_str("REPO_TYPE") == "SVN":
                    from instlInstanceSync_svn import InstlInstanceSync_svn
                    syncer = InstlInstanceSync_svn(self)
                else:
                    raise ValueError('REPO_TYPE is not defined in input file')
                syncer.init_sync_vars()
                syncer.create_sync_instructions(installState)
            if the_command in ("copy", 'synccopy'):
                logging.info("Creating copy instructions")
                self.init_copy_vars()
                self.create_copy_instructions(installState)
            self.create_variables_assignment()
            self.write_batch_file()
            if "__RUN_BATCH_FILE__" in self.cvl:
                self.run_batch_file()

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
            defines = list()
            indexes = list()
            unknowns = list()
            for identifier in what:
                if identifier in self.cvl:
                    defines.append(self.cvl.repr_for_yaml(identifier))
                elif identifier in self.install_definitions_index:
                    indexes.append({identifier: self.install_definitions_index[identifier].repr_for_yaml()})
                else:
                    unknowns.append(augmentedYaml.YamlDumpWrap(value="UNKNOWN VARIABLE", comment=identifier+" is not in variable list"))
            if defines:
                retVal.append(augmentedYaml.YamlDumpDocWrap(defines, '!define', "Definitions", explicit_start=True, sort_mappings=True))
            if indexes:
                retVal.append(augmentedYaml.YamlDumpDocWrap(indexes, '!index', "Installation index", explicit_start=True, sort_mappings=True))
            if unknowns:
                retVal.append(augmentedYaml.YamlDumpDocWrap(unknowns, '!unknowns', "Installation index", explicit_start=True, sort_mappings=True))

        return retVal

    @func_log_wrapper
    def read_index(self, a_node):
        self.install_definitions_index.update(read_index_from_yaml(a_node))

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
        for os_name in self.cvl.get_list("TARGET_OS_NAMES"):
            InstallItem.begin_get_for_specific_os(os_name)
        installState.root_install_items.extend(self.cvl.get_list("MAIN_INSTALL_TARGETS"))
        installState.root_install_items = filter(bool, installState.root_install_items)
        installState.calculate_full_install_items_set(self)
        self.cvl.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(installState.full_install_items)
        self.cvl.set_var("__ORPHAN_INSTALL_TARGETS__").extend(installState.orphan_install_items)
        for identifier in ("MAIN_INSTALL_TARGETS", "__FULL_LIST_OF_INSTALL_TARGETS__", "__ORPHAN_INSTALL_TARGETS__"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    @func_log_wrapper
    def create_copy_instructions(self, installState):
        # copy and actions instructions for sources
        self.batch_accum.set_current_section('copy')
        self.batch_accum += self.platform_helper.progress("starting copy")
        self.platform_helper.use_copy_tool(self.cvl.get_str("COPY_TOOL"))

        self.batch_accum += self.platform_helper.progress("from $(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)")

        if 'Mac' in self.cvl.get_list("__CURRENT_OS_NAMES__") and 'Mac' in self.cvl.get_list("TARGET_OS"):
            self.batch_accum += self.platform_helper.resolve_symlink_files(in_dir="$(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)")
            self.batch_accum += self.platform_helper.progress("resolve .symlink files")

        for folder_name, items_in_folder in installState.install_items_by_target_folder.iteritems():
            self.batch_accum.indent_level += 1
            logging.info("... folder %s (%s)", folder_name, self.cvl.resolve_string(folder_name))
            self.batch_accum += self.platform_helper.mkdir(folder_name)
            self.batch_accum += self.platform_helper.cd(folder_name)

            # accumulate folder_in actions from all items, eliminating duplicates
            self.batch_accum.indent_level += 1
            folder_in_actions = unique_list() # unique_list to eliminate identical actions while keeping the order
            for IID in items_in_folder: # folder_in actions
                installi = self.install_definitions_index[IID]
                item_actions = installi.action_list('folder_in')
                for an_action in item_actions:
                    len_before = len(folder_in_actions)
                    folder_in_actions.append(an_action)
                    if len_before < len(folder_in_actions): # add progress only for the first same action
                        folder_in_actions.append(self.platform_helper.progress("folder in action"))
            self.batch_accum += folder_in_actions

            for IID in items_in_folder:
                installi = self.install_definitions_index[IID]
                for source in installi.source_list():
                    self.batch_accum += installi.action_list('before')
                    self.create_copy_instructions_for_source(source)
                    self.batch_accum += installi.action_list('after')
                    self.batch_accum += self.platform_helper.progress("{installi.iid}: {installi.name}".format(**locals()))

            # accumulate folder_out actions from all items, eliminating duplicates
            folder_out_actions = unique_list() # unique_list will eliminate identical actions while keeping the order
            for IID in items_in_folder:
                installi = self.install_definitions_index[IID]
                item_actions = installi.action_list('folder_out')
                for an_action in item_actions:
                    len_before = len(folder_out_actions)
                    folder_out_actions.append(an_action)
                    if len_before < len(folder_out_actions): # add progress only for the first same action
                        folder_out_actions.append(self.platform_helper.progress("folder out action"))
            self.batch_accum += folder_out_actions

            self.batch_accum.indent_level -= 1
            self.batch_accum.indent_level -= 1

        # actions instructions for sources that do not need copying
        for folder_name, items_in_folder in installState.no_copy_items_by_sync_folder.iteritems():
            logging.info("... non-copy items folder %s (%s)", folder_name, self.cvl.resolve_string(folder_name))
            self.batch_accum += self.platform_helper.cd(folder_name)

            # accumulate folder_in actions from all items, eliminating duplicates
            folder_in_actions = unique_list() # unique_list will eliminate identical actions while keeping the order
            for IID in items_in_folder: # folder_in actions
                installi = self.install_definitions_index[IID]
                item_actions = installi.action_list('folder_in')
                for an_action in item_actions:
                    len_before = len(folder_in_actions)
                    folder_in_actions.append(an_action)
                    if len_before < len(folder_in_actions): # add progress only for the first same action
                        folder_in_actions.append(self.platform_helper.progress("no copy folder in action"))
            self.batch_accum += folder_in_actions

            for IID in items_in_folder:
                installi = self.install_definitions_index[IID]
                self.batch_accum += installi.action_list('before')
                self.batch_accum += installi.action_list('after')

            # accumulate folder_out actions from all items, eliminating duplicates
            folder_out_actions = unique_list() # unique_list will eliminate identical actions while keeping the order
            for IID in items_in_folder:
                installi = self.install_definitions_index[IID]
                item_actions = installi.action_list('folder_out')
                for an_action in item_actions:
                    len_before = len(folder_out_actions)
                    folder_out_actions.append(an_action)
                    if len_before < len(folder_out_actions): # add progress only for the first same action
                        folder_out_actions.append(self.platform_helper.progress("folder out action"))
            self.batch_accum += folder_out_actions

            self.batch_accum += self.platform_helper.progress("{folder_name}".format(**locals()))
        # messages about orphan iids
        for iid in installState.orphan_install_items:
            logging.info("Orphan item: %s", iid)
            self.batch_accum += self.platform_helper.echo("Don't know how to install "+iid)
        self.batch_accum += self.platform_helper.progress("done copy")

    @func_log_wrapper
    def create_copy_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """

        source_path = os.path.normpath("$(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)/"+source[0])

        if source[1] == '!file':       # get a single file, not recommended
            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".", source_path, ignore=(".svn", "*.symlink", "*.wtar"))
        elif source[1] == '!dir_cont': # get all files and folders from a folder
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(source_path, ".", source_path, ignore=(".svn", "*.symlink", "*.wtar"))
        elif source[1] == '!files':    # get all files from a folder
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_files_to_dir(source_path, ".", source_path, ignore=(".svn", "*.symlink", "*.wtar"))
        else:
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path, ".", source_path, ignore=(".svn", "*.symlink", "*.wtar"))
        logging.info("... %s; (%s - %s)", source_path, self.cvl.resolve_string(source_path), source[1])

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
        InstallItem.begin_get_for_all_oses()
        for dep in self.install_definitions_index[iid].depend_list():
            if dep in self.install_definitions_index:
                out_list.append(dep)
                self.needs(dep, out_list)
            else:
                out_list.append(dep+"(missing)")
        InstallItem.reset_get_for_all_oses()

    @func_log_wrapper
    def needed_by(self, iid):
        try:
            from pyinstl import installItemGraph
            InstallItem.begin_get_for_all_oses()
            graph = installItemGraph.create_dependencies_graph(self.install_definitions_index)
            needed_by_list = installItemGraph.find_needed_by(graph, iid)
            InstallItem.reset_get_for_all_oses()
            return needed_by_list
        except ImportError: # no installItemGraph, no worry
            print("Could not load installItemGraph")
            return None
