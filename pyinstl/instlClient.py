#!/usr/bin/env python2.7

from __future__ import print_function
from collections import OrderedDict, defaultdict
import logging

from pyinstl.utils import *
from installItem import read_index_from_yaml, InstallItem, guid_list, iids_from_guid
from aYaml import augmentedYaml

from instlInstanceBase import InstlInstanceBase


class InstallInstructionsState(object):
    """ holds state for specific creating of install instructions """
    def __init__(self):
        self.root_install_items = unique_list()
        self.full_install_items = unique_list()
        self.orphan_install_items = unique_list()
        self.install_items_by_target_folder = defaultdict(unique_list)
        self.no_copy_items_by_sync_folder = defaultdict(unique_list)
        self.sync_paths = unique_list()

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

    def __sort_install_items_by_target_folder(self, instlObj):
        for IID in self.full_install_items:
            folder_list_for_idd = instlObj.install_definitions_index[IID].folder_list()
            if folder_list_for_idd:
                for folder in folder_list_for_idd:
                    norm_folder = os.path.normpath(folder)
                    self.install_items_by_target_folder[norm_folder].append(IID)
            else: # items that need no copy
                source_list_for_idd = instlObj.install_definitions_index[IID].source_list()
                for source in source_list_for_idd:
                    relative_sync_folder = instlObj.relative_sync_folder_for_source(source)
                    sync_folder =  os.path.join( "$(LOCAL_SYNC_DIR)", "$(REL_SRC_PATH)", relative_sync_folder )
                    self.no_copy_items_by_sync_folder[sync_folder].append(IID)

    def calculate_full_install_items_set(self, instlObj):
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
            if guid_re.match(IID): # if it's a guid translate to iid's
                iids_from_the_guid = iids_from_guid(instlObj.install_definitions_index, IID)
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
                instlObj.install_definitions_index[IID].get_recursive_depends(instlObj.install_definitions_index, self.full_install_items, self.orphan_install_items)
            except KeyError:
                self.orphan_install_items.append(IID)
                logging.warning("%s not found in index", IID)
        self.__sort_install_items_by_target_folder(instlObj)

class InstlClient(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlClient, self).__init__(initial_vars)

    def do_command(self):
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        #print("client_commands", the_command)
        self.installState = InstallInstructionsState()
        self.read_yaml_file(self.cvl.get_str("__MAIN_INPUT_FILE__"))
        self.init_default_client_vars()
        self.resolve_defined_paths()
        self.resolve_index_inheritance()
        self.add_deafult_items()
        self.calculate_default_install_item_set()
        self.platform_helper.num_items_for_progress_report = int(self.cvl.get_str("LAST_PROGRESS"))

        fixed_command_name = the_command.replace('-', '_')
        do_command_func = getattr(self, "do_"+fixed_command_name)
        do_command_func()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in self.cvl:
            self.run_batch_file()

    def init_default_client_vars(self):
        if "LOCAL_SYNC_DIR" not in self.cvl:
            if "SYNC_BASE_URL" not in self.cvl:
                raise ValueError("'SYNC_BASE_URL' was not defined")
            resolved_sync_base_url = self.cvl.get_str("SYNC_BASE_URL")
            url_main_item = main_url_item(resolved_sync_base_url)
            default_sync_dir = self.get_default_sync_dir(continue_dir=url_main_item, mkdir=True)
            self.cvl.set_var("LOCAL_SYNC_DIR", description="from init_default_client_vars").append(default_sync_dir)

    def do_sync(self):
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
        syncer.create_sync_instructions(self.installState)
        self.batch_accum += self.platform_helper.progress("done sync")

    def do_copy(self):
        logging.info("Creating copy instructions")
        self.init_copy_vars()
        self.create_copy_instructions()

    def do_synccopy(self):
        self.do_sync()
        self.do_copy()
        self.batch_accum += self.platform_helper.progress("done synccopy")

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

    def resolve_index_inheritance(self):
        for install_def in self.install_definitions_index.values():
            install_def.resolve_inheritance(self.install_definitions_index)

    def add_deafult_items(self):
        all_items_item = InstallItem()
        all_items_item.iid = "__ALL_ITEMS_IID__"
        all_items_item.name = "All IIDs"
        for item_name in self.install_definitions_index:
            all_items_item.add_depend(item_name)
        self.install_definitions_index["__ALL_ITEMS_IID__"] = all_items_item

        all_guids_item = InstallItem()
        all_guids_item.iid = "__ALL_GUIDS_IID__"
        all_guids_item.name = "All GUIDs"
        for guid in guid_list(self.install_definitions_index):
            all_guids_item.add_depend(guid)
        self.install_definitions_index["__ALL_GUIDS_IID__"] = all_guids_item

    def calculate_default_install_item_set(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_INSTALL_TARGETS" not in self.cvl:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        for os_name in self.cvl.get_list("TARGET_OS_NAMES"):
            InstallItem.begin_get_for_specific_os(os_name)
        self.installState.root_install_items.extend(self.cvl.get_list("MAIN_INSTALL_TARGETS"))
        self.installState.root_install_items = filter(bool, self.installState.root_install_items)
        self.installState.calculate_full_install_items_set(self)
        self.cvl.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(self.installState.full_install_items)
        self.cvl.set_var("__ORPHAN_INSTALL_TARGETS__").extend(self.installState.orphan_install_items)
        for identifier in ("MAIN_INSTALL_TARGETS", "__FULL_LIST_OF_INSTALL_TARGETS__", "__ORPHAN_INSTALL_TARGETS__"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    def init_copy_vars(self):
        var_description = "from InstlInstanceBase.init_copy_vars"
        # check which variables are needed for for offline install....
        if "REL_SRC_PATH" not in self.cvl: #?
            if "SYNC_BASE_URL" not in self.cvl:
                raise ValueError("'SYNC_BASE_URL' was not defined")
            rel_sources = relative_url(self.cvl.get_str("SYNC_BASE_URL"), self.cvl.get_str("SYNC_TRAGET_OS_URL"))
            self.cvl.set_var("REL_SRC_PATH", var_description).append(rel_sources)

        for identifier in ("REL_SRC_PATH", "COPY_TOOL"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    def create_copy_instructions(self):
        # copy and actions instructions for sources
        self.batch_accum.set_current_section('copy')
        self.batch_accum += self.platform_helper.progress("starting copy")

        self.batch_accum += self.platform_helper.progress("from $(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)")

        if 'Mac' in self.cvl.get_list("__CURRENT_OS_NAMES__") and 'Mac' in self.cvl.get_list("TARGET_OS"):
            self.batch_accum += self.platform_helper.resolve_symlink_files(in_dir="$(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)")
            self.batch_accum += self.platform_helper.progress("resolve .symlink files")

        for folder_name, items_in_folder in self.installState.install_items_by_target_folder.iteritems():
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

        # actions instructions for sources that do not need copying
        for folder_name, items_in_folder in self.installState.no_copy_items_by_sync_folder.iteritems():
            logging.info("... non-copy items folder %s (%s)", folder_name, self.cvl.resolve_string(folder_name))
            self.batch_accum += self.platform_helper.cd(folder_name)
            self.batch_accum.indent_level += 1

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
            self.batch_accum.indent_level -= 1

        # messages about orphan iids
        for iid in self.installState.orphan_install_items:
            logging.info("Orphan item: %s", iid)
            self.batch_accum += self.platform_helper.echo("Don't know how to install "+iid)
        self.batch_accum += self.platform_helper.progress("done copy")

    def create_copy_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """

        source_path = os.path.normpath("$(LOCAL_SYNC_DIR)/$(REL_SRC_PATH)/"+source[0])

        if source[1] == '!file':       # get a single file, not recommended
            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".", link_dest=True, ignore=(".svn", "*.symlink", "*.wtar", "*.done"))
        elif source[1] == '!dir_cont': # get all files and folders from a folder
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(source_path, ".", link_dest=True, ignore=(".svn", "*.symlink", "*.wtar", "*.done"))
        elif source[1] == '!files':    # get all files from a folder
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_files_to_dir(source_path, ".", link_dest=True, ignore=(".svn", "*.symlink", "*.wtar", "*.done"))
        else: # !dir
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path, ".", link_dest=True, ignore=(".svn", "*.symlink", "*.wtar", "*.done"))
        logging.info("... %s; (%s - %s)", source_path, self.cvl.resolve_string(source_path), source[1])

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
