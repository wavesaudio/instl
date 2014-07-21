#!/usr/bin/env python2.7

from __future__ import print_function
import time
from collections import OrderedDict, defaultdict
import logging

from pyinstl.utils import *
from installItem import read_index_from_yaml, InstallItem, guid_list, iids_from_guid
from aYaml import augmentedYaml

from instlInstanceBase import InstlInstanceBase
from configVarStack import var_stack as var_list
import svnTree

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
            with instlObj.install_definitions_index[IID] as installi:
                folder_list_for_idd = [folder for folder in var_list["iid_folder_list"]]
                if folder_list_for_idd:
                    for folder in folder_list_for_idd:
                        norm_folder = os.path.normpath(folder)
                        self.install_items_by_target_folder[norm_folder].append(IID)
                else: # items that need no copy
                    for source_var in var_list.get_configVar_obj("iid_source_var_list"):
                        source = var_list.resolve_var_to_list(source_var)
                        relative_sync_folder = instlObj.relative_sync_folder_for_source(source)
                        sync_folder =  os.path.join( "$(LOCAL_REPO_SOURCES_DIR)", relative_sync_folder )
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
                    logging.debug("GUID %s, translated to %d iids: %s", IID, len(iids_from_the_guid), ", ".join(iids_from_the_guid))
                else:
                    self.orphan_install_items.append(IID)
                    logging.warning("%s is a guid but could not be translated to iids", IID)
            else:
                root_install_iids_translated.append(IID)
                logging.debug("%s added to root_install_iids_translated", IID)

        logging.info(" ".join(("Main install items translated:", ", ".join(root_install_iids_translated))))

        for IID in root_install_iids_translated:
            try:
                instlObj.install_definitions_index[IID].get_recursive_depends(instlObj.install_definitions_index, self.full_install_items, self.orphan_install_items)
            except KeyError:
                self.orphan_install_items.append(IID)
                logging.warning("%s not found in index", IID)
        logging.info(" ".join(("Full install items:", ", ".join(self.full_install_items))))
        self.__sort_install_items_by_target_folder(instlObj)

class InstlClient(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlClient, self).__init__(initial_vars)

    def do_command(self):
        the_command = var_list.resolve("$(__MAIN_COMMAND__)")
        #print("client_commands", the_command)
        self.installState = InstallInstructionsState()
        self.read_yaml_file(var_list.resolve("$(__MAIN_INPUT_FILE__)"))
        self.init_default_client_vars()
        self.resolve_defined_paths()
        self.platform_helper.init_download_tool()
        self.platform_helper.init_copy_tool() # after reading variable COPY_TOOL from yaml, we might need to re-init the copy tool.
        self.resolve_index_inheritance()
        self.add_deafult_items()
        self.calculate_default_install_item_set()
        self.platform_helper.num_items_for_progress_report = int(var_list.resolve("$(LAST_PROGRESS)"))

        fixed_command_name = the_command.replace('-', '_')
        do_command_func = getattr(self, "do_"+fixed_command_name)
        do_command_func()
        self.create_instl_history_file()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def create_instl_history_file(self):
        var_list.set_var("__BATCH_CREATE_TIME__").append(time.strftime("%Y/%m/%d %H:%M:%S"))
        yaml_of_defines = augmentedYaml.YamlDumpDocWrap(var_list, '!define', "Definitions", explicit_start=True, sort_mappings=True)
        with open(var_list.resolve("$(INSTL_HISTORY_TEMP_PATH)"), "w") as wfd:
            augmentedYaml.writeAsYaml(yaml_of_defines, wfd)
        self.batch_accum += self.platform_helper.append_file_to_file("$(INSTL_HISTORY_TEMP_PATH)", "$(INSTL_HISTORY_PATH)")

    def read_repo_type_defaults(self):
        repo_type_defaults_file_path = os.path.join(var_list.resolve("$(__INSTL_DATA_FOLDER__)"), "defaults", var_list.resolve("$(REPO_TYPE).yaml"))
        if os.path.isfile(repo_type_defaults_file_path):
            self.read_yaml_file(repo_type_defaults_file_path)

    def init_default_client_vars(self):
        if "LOCAL_SYNC_DIR" not in var_list:
            if "SYNC_BASE_URL" not in var_list:
                raise ValueError("'SYNC_BASE_URL' was not defined")
            resolved_sync_base_url = var_list.resolve("$(SYNC_BASE_URL)")
            url_main_item = main_url_item(resolved_sync_base_url)
            default_sync_dir = self.get_default_sync_dir(continue_dir=url_main_item, mkdir=True)
            var_list.set_var("LOCAL_SYNC_DIR", description="from init_default_client_vars").append(default_sync_dir)
        # TARGET_OS_NAMES defaults to __CURRENT_OS_NAMES__, which is not what we want if syncing to
        # an OS which is not the current
        if var_list.resolve("$(TARGET_OS)") != var_list.resolve("$(__CURRENT_OS__)"):
            target_os_names = var_list.resolve_var_to_list(var_list.resolve("$(TARGET_OS)_ALL_OS_NAMES"))
            var_list.set_var("TARGET_OS_NAMES").extend(target_os_names)
            second_name = var_list.resolve("$(TARGET_OS)")
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            var_list.set_var("TARGET_OS_SECOND_NAME").append(second_name)

        self.read_repo_type_defaults()
        if var_list.resolve("$(REPO_TYPE)") == "P4":
            if "P4_SYNC_DIR" not in var_list:
                if "SYNC_BASE_URL" in var_list:
                    p4_sync_dir = P4GetPathFromDepotPath(var_list.resolve("$(SYNC_BASE_URL)"))
                    var_list.set_var("P4_SYNC_DIR", "from SYNC_BASE_URL").append(p4_sync_dir)

    def do_sync(self):
        logging.info("Creating sync instructions")
        if var_list.resolve("$(REPO_TYPE)") == "URL":
            from instlInstanceSync_url import InstlInstanceSync_url
            syncer = InstlInstanceSync_url(self)
        elif var_list.resolve("$(REPO_TYPE)") == "SVN":
            from instlInstanceSync_svn import InstlInstanceSync_svn
            syncer = InstlInstanceSync_svn(self)
        elif var_list.resolve("$(REPO_TYPE)") == "P4":
            from instlInstanceSync_p4 import InstlInstanceSync_p4
            syncer = InstlInstanceSync_p4(self)
        else:
            raise ValueError('REPO_TYPE is not defined in input file')
        syncer.init_sync_vars()
        syncer.create_sync_instructions(self.installState)
        self.batch_accum += self.platform_helper.progress("Done sync")

    def do_copy(self):
        logging.info("Creating copy instructions")
        self.init_copy_vars()
        self.create_copy_instructions()

    def do_remove(self):
        logging.info("Creating copy instructions")
        self.init_remove_vars()
        self.create_remove_instructions()

    def do_synccopy(self):
        self.do_sync()
        self.do_copy()
        self.batch_accum += self.platform_helper.progress("Done synccopy")

    def repr_for_yaml(self, what=None):
        """ Create representation of self suitable for printing as yaml.
            parameter 'what' is a list of identifiers to represent. If 'what'
            is None (the default) create representation of everything.
            InstlInstanceBase object is represented as two yaml documents:
            one for define (tagged !define), one for the index (tagged !index).
        """
        retVal = list()
        if what is None: # None is all
            retVal.append(augmentedYaml.YamlDumpDocWrap(var_list, '!define', "Definitions", explicit_start=True, sort_mappings=True))
            retVal.append(augmentedYaml.YamlDumpDocWrap(self.install_definitions_index, '!index', "Installation index", explicit_start=True, sort_mappings=True))
        else:
            defines = list()
            indexes = list()
            unknowns = list()
            for identifier in what:
                if identifier in var_list:
                    defines.append(var_list.repr_for_yaml(identifier))
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
        if "MAIN_INSTALL_TARGETS" not in var_list:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        for os_name in var_list.resolve_to_list("$(TARGET_OS_NAMES)"):
            InstallItem.begin_get_for_specific_os(os_name)
        self.installState.root_install_items.extend(var_list.resolve_to_list("$(MAIN_INSTALL_TARGETS)"))
        self.installState.root_install_items = filter(bool, self.installState.root_install_items)
        self.installState.calculate_full_install_items_set(self)
        var_list.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(self.installState.full_install_items)
        var_list.set_var("__ORPHAN_INSTALL_TARGETS__").extend(self.installState.orphan_install_items)

    def init_copy_vars(self):
        self.action_type_to_progress_message = {'copy_in': "pre-install step", 'copy_out': "post-install step",
                                                'folder_in': "pre-copy step", 'folder_out': "post-copy step"}
    def init_remove_vars(self):
        pass

    def create_copy_instructions(self):
        # copy and actions instructions for sources
        self.batch_accum.set_current_section('copy')
        self.batch_accum += self.platform_helper.progress("Starting copy from $(LOCAL_REPO_SOURCES_DIR)")

        sorted_target_folder_list = sorted(self.installState.install_items_by_target_folder, key=lambda fold: var_list.resolve(fold))

        # first create all target folders so to avoid dependency order problems such as creating links between folders
        for folder_name in sorted_target_folder_list:
            self.batch_accum += self.platform_helper.mkdir_with_owner(folder_name)
        self.batch_accum += self.platform_helper.progress("Make directories done")

        self.accumulate_unique_actions('copy_in', self.installState.full_install_items)

        if 'Mac' in var_list.resolve_to_list("$(__CURRENT_OS_NAMES__)") and 'Mac' in var_list.resolve_to_list("$(TARGET_OS)"):
            self.batch_accum += self.platform_helper.resolve_symlink_files(in_dir="$(LOCAL_REPO_SOURCES_DIR)")
            self.batch_accum += self.platform_helper.progress("Resolve .symlink files")

            have_map = svnTree.SVNTree()
            have_info_path = var_list.resolve("$(NEW_HAVE_INFO_MAP_PATH)") # in case we're in synccopy command
            if not os.path.isfile(have_info_path):
                have_info_path = var_list.resolve("$(HAVE_INFO_MAP_PATH)") # in case we're in copy command
            if os.path.isfile(have_info_path):
                have_map.read_info_map_from_file(have_info_path, format="text")
                num_files_to_set_exec = have_map.num_subs_in_tree(what="file", predicate=lambda in_item: in_item.isExecutable())
                logging.info("Num files to set exec: %d", num_files_to_set_exec)
                if num_files_to_set_exec > 0:
                    self.batch_accum += self.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
                    self.batch_accum += self.platform_helper.set_exec_for_folder(have_info_path)
                    self.platform_helper.num_items_for_progress_report += num_files_to_set_exec
                    self.batch_accum += self.platform_helper.progress("Set exec done")
                    self.batch_accum += self.platform_helper.new_line()
                    self.batch_accum += self.platform_helper.popd()

        for folder_name in sorted_target_folder_list:
            items_in_folder = self.installState.install_items_by_target_folder[folder_name]
            logging.info("folder %s", var_list.resolve(folder_name))
            self.batch_accum += self.platform_helper.new_line()
            self.batch_accum += self.platform_helper.cd(folder_name)

            # accumulate folder_in actions from all items, eliminating duplicates
            self.accumulate_unique_actions('folder_in', items_in_folder)

            batch_accum_len_before = len(self.batch_accum)
            self.batch_accum += self.platform_helper.copy_tool.begin_copy_folder()
            for IID in items_in_folder:
                with self.install_definitions_index[IID] as installi:
                    for source_var in var_list.get_configVar_obj("iid_source_var_list"):
                        source = var_list.resolve_var_to_list(source_var)
                        self.batch_accum += var_list.resolve_to_list("$(iid_action_list_before)")
                        self.create_copy_instructions_for_source(source)
                        self.batch_accum += var_list.resolve_to_list("$(iid_action_list_after)")
                        self.batch_accum += self.platform_helper.progress("Copy {installi.name}".format(**locals()))
            self.batch_accum += self.platform_helper.copy_tool.end_copy_folder()
            logging.info("... copy actions: %d", len(self.batch_accum) - batch_accum_len_before)

            # accumulate folder_out actions from all items, eliminating duplicates
            self.accumulate_unique_actions('folder_out', items_in_folder)

            self.batch_accum.indent_level -= 1

        # actions instructions for sources that do not need copying, here folder_name is the sync folder
        for folder_name, items_in_folder in self.installState.no_copy_items_by_sync_folder.iteritems():
            # calculate total number of actions for all items relating to folder_name, if 0 we can skip this folder altogether
            num_actions_for_folder = reduce(lambda x, y: x+len(self.install_definitions_index[y].all_action_list()), items_in_folder, 0)
            logging.info("%d non-copy items folder %s (%s)", num_actions_for_folder, folder_name, var_list.resolve(folder_name))

            if 0 == num_actions_for_folder:
                continue

            self.batch_accum += self.platform_helper.new_line()
            self.batch_accum += self.platform_helper.cd(folder_name)
            self.batch_accum.indent_level += 1

            # accumulate folder_in actions from all items, eliminating duplicates
            self.accumulate_unique_actions('folder_in', items_in_folder)

            for IID in items_in_folder:
                with self.install_definitions_index[IID]:
                    self.batch_accum += var_list.resolve_to_list("$(iid_action_list_before)")
                    self.batch_accum += var_list.resolve_to_list("$(iid_action_list_after)")

            # accumulate folder_out actions from all items, eliminating duplicates
            self.accumulate_unique_actions('folder_out', items_in_folder)

            self.batch_accum += self.platform_helper.progress("{folder_name}".format(**locals()))
            self.batch_accum.indent_level -= 1

        self.accumulate_unique_actions('copy_out', self.installState.full_install_items)

        self.platform_helper.copy_tool.finalize()

        # messages about orphan iids
        for iid in self.installState.orphan_install_items:
            logging.info("Orphan item: %s", iid)
            self.batch_accum += self.platform_helper.echo("Don't know how to install "+iid)
        self.batch_accum += self.platform_helper.progress("Done copy")

    def accumulate_unique_actions(self, action_type, iid_list):
            """ accumulate action_type actions from iid_list, eliminating duplicates"""
            unique_actions = unique_list() # unique_list will eliminate identical actions while keeping the order
            for IID in iid_list:
                with self.install_definitions_index[IID] as installi:
                    item_actions = var_list.resolve_to_list("$(iid_action_list_"+action_type+")")
                    num_unique_actions = 0
                    for an_action in item_actions:
                        len_before = len(unique_actions)
                        unique_actions.append(an_action)
                        len_after = len(unique_actions)
                        if len_before < len_after: # add progress only for the first same action
                            num_unique_actions += 1
                            action_description = self.action_type_to_progress_message[action_type]
                            if num_unique_actions > 1:
                                action_description = " ".join( (action_description, str(num_unique_actions)) )
                            unique_actions.append(self.platform_helper.progress("{installi.name} {action_description}".format(**locals())))
            self.batch_accum += unique_actions
            logging.info("... %s actions: %d", action_type, len(unique_actions))

    def create_copy_instructions_for_source(self, source):
        """ source is a tuple (source_folder, tag), where tag is either !file or !dir """

        source_path = os.path.normpath("$(LOCAL_REPO_SOURCES_DIR)/"+source[0])

        ignore_list = var_list.resolve_to_list("$(COPY_IGNORE_PATTERNS)")

        if source[1] == '!file':       # get a single file, not recommended
            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".", link_dest=True, ignore=ignore_list)
        elif source[1] == '!dir_cont': # get all files and folders from a folder
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(source_path, ".", link_dest=True, ignore=ignore_list)
        elif source[1] == '!files':    # get all files from a folder
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_files_to_dir(source_path, ".", link_dest=True, ignore=ignore_list)
        else: # !dir
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path, ".", link_dest=True, ignore=ignore_list)
        logging.debug("%s; (%s - %s)", source_path, var_list.resolve(source_path), source[1])

    def needs(self, iid, out_list):
        """ return all items that depend on iid """
        if iid not in self.install_definitions_index:
            raise KeyError(iid+" is not in index")
        InstallItem.begin_get_for_all_oses()
        with self.install_definitions_index[iid]:
            for dep in var_list.resolve_var_to_list("iid_depend_list"):
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

    def create_remove_instructions(self):
        self.batch_accum.set_current_section('remove')
        self.batch_accum += self.platform_helper.progress("Starting remove")
        sorted_target_folder_list = sorted(self.installState.install_items_by_target_folder, key=lambda fold: var_list.resolve(fold))
        print("create_remove_instructions")