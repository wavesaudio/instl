#!/usr/bin/env python2.7

from __future__ import print_function

import os
import time
from collections import OrderedDict, defaultdict
import logging

import utils
from installItem import InstallItem, guid_list, iids_from_guid
import aYaml
from instlInstanceBase import InstlInstanceBase
from configVar import var_stack


# noinspection PyPep8Naming
class InstallInstructionsState(object):
    """ holds state for specific creating of install instructions """

    def __init__(self):
        self.root_install_items = utils.unique_list()
        self.full_install_items = utils.unique_list()
        self.orphan_install_items = utils.unique_list()
        self.install_items_by_target_folder = defaultdict(utils.unique_list)
        self.no_copy_items_by_sync_folder = defaultdict(utils.unique_list)
        self.sync_paths = utils.unique_list()

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['root_install_items'] = list(self.root_install_items)
        retVal['full_install_items'] = list(self.full_install_items)
        retVal['orphan_install_items'] = list(self.orphan_install_items)
        retVal['install_items_by_target_folder'] = {folder: list(self.install_items_by_target_folder[folder]) for folder
                                                    in self.install_items_by_target_folder}
        retVal['no_copy_items_by_sync_folder'] = list(self.no_copy_items_by_sync_folder)
        retVal['sync_paths'] = list(self.sync_paths)
        return retVal

    def sort_install_items_by_target_folder(self, instlObj):
        for IID in self.full_install_items:
            with instlObj.install_definitions_index[IID] as installi:
                folder_list_for_idd = [folder for folder in var_stack["iid_folder_list"]]
                if folder_list_for_idd:
                    for folder in folder_list_for_idd:
                        norm_folder = os.path.normpath(folder)
                        self.install_items_by_target_folder[norm_folder].append(IID)
                else:  # items that need no copy
                    for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                        source = var_stack.resolve_var_to_list(source_var)
                        relative_sync_folder = instlObj.relative_sync_folder_for_source(source)
                        sync_folder = os.path.join("$(LOCAL_REPO_SYNC_DIR)", relative_sync_folder)
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

        root_install_iids_translated = utils.unique_list()
        for IID in self.root_install_items:
            # if IID is a guid iids_from_guid will translate to iid's, or return the IID otherwise
            iids_from_the_guid = iids_from_guid(instlObj.install_definitions_index, IID)
            if len(iids_from_the_guid) > 0:
                root_install_iids_translated.extend(iids_from_the_guid)
                logging.debug("GUID %s, translated to %d iids: %s", IID, len(iids_from_the_guid),
                              ", ".join(iids_from_the_guid))
            else:
                self.orphan_install_items.append(IID)
                logging.warning("%s is a guid but could not be translated to iids", IID)

        logging.info(" ".join(("Main install items translated:", ", ".join(root_install_iids_translated))))

        for IID in root_install_iids_translated:
            try:
                # all items in the root list are marked as required by them selves
                instlObj.install_definitions_index[IID].required_by.append(IID)
                instlObj.install_definitions_index[IID].get_recursive_depends(instlObj.install_definitions_index,
                                                                              self.full_install_items,
                                                                              self.orphan_install_items)
            except KeyError:
                self.orphan_install_items.append(IID)
                logging.warning("%s not found in index", IID)
        logging.info(" ".join(("Full install items:", ", ".join(self.full_install_items))))
        self.sort_install_items_by_target_folder(instlObj)


class InstlClient(InstlInstanceBase):
    def __init__(self, initial_vars):
        super(InstlClient, self).__init__(initial_vars)

    def do_command(self):
        the_command = var_stack.resolve("$(__MAIN_COMMAND__)")
        fixed_command_name = the_command.replace('-', '_')
        # print("client_commands", fixed_command_name)
        self.installState = InstallInstructionsState()
        self.read_yaml_file(var_stack.resolve("$(__MAIN_INPUT_FILE__)"))
        self.init_default_client_vars()
        self.resolve_defined_paths()
        self.batch_accum.set_current_section('begin')
        self.batch_accum += self.platform_helper.setup_echo()
        self.platform_helper.init_download_tool()
        # after reading variable COPY_TOOL from yaml, we might need to re-init the copy tool.
        self.platform_helper.init_copy_tool()
        self.resolve_index_inheritance()
        self.add_default_items()
        self.calculate_default_install_item_set()
        self.platform_helper.num_items_for_progress_report = int(var_stack.resolve("$(LAST_PROGRESS)"))

        do_command_func = getattr(self, "do_" + fixed_command_name)
        do_command_func()
        self.create_instl_history_file()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def create_instl_history_file(self):
        var_stack.set_var("__BATCH_CREATE_TIME__").append(time.strftime("%Y/%m/%d %H:%M:%S"))
        yaml_of_defines = aYaml.YamlDumpDocWrap(var_stack, '!define', "Definitions",
                                                explicit_start=True, sort_mappings=True)
        # write the history file, but only if variable LOCAL_REPO_BOOKKEEPING_DIR is defined
        # and the folder actually exists.
        if os.path.isdir(var_stack.resolve("$(LOCAL_REPO_BOOKKEEPING_DIR)", default="")):
            with open(var_stack.resolve("$(INSTL_HISTORY_TEMP_PATH)"), "w") as wfd:
                utils.make_open_file_read_write_for_all(wfd)
                aYaml.writeAsYaml(yaml_of_defines, wfd)
            self.batch_accum += self.platform_helper.append_file_to_file("$(INSTL_HISTORY_TEMP_PATH)",
                                                                         "$(INSTL_HISTORY_PATH)")

    def read_repo_type_defaults(self):
        repo_type_defaults_file_path = os.path.join(var_stack.resolve("$(__INSTL_DATA_FOLDER__)"), "defaults",
                                                    var_stack.resolve("$(REPO_TYPE).yaml"))
        if os.path.isfile(repo_type_defaults_file_path):
            self.read_yaml_file(repo_type_defaults_file_path)

    def init_default_client_vars(self):
        if "LOCAL_SYNC_DIR" not in var_stack:
            if "SYNC_BASE_URL" in var_stack:
                # raise ValueError("'SYNC_BASE_URL' was not defined")
                resolved_sync_base_url = var_stack.resolve("$(SYNC_BASE_URL)")
                url_main_item = utils.main_url_item(resolved_sync_base_url)
                var_stack.set_var("SYNC_BASE_URL_MAIN_ITEM", description="from init_default_client_vars").append(url_main_item)
                default_sync_dir = self.get_default_sync_dir(continue_dir=url_main_item, mkdir=True)
                var_stack.set_var("LOCAL_SYNC_DIR", description="from init_default_client_vars").append(default_sync_dir)
        # TARGET_OS_NAMES defaults to __CURRENT_OS_NAMES__, which is not what we want if syncing to
        # an OS which is not the current
        if var_stack.resolve("$(TARGET_OS)") != var_stack.resolve("$(__CURRENT_OS__)"):
            target_os_names = var_stack.resolve_var_to_list(var_stack.resolve("$(TARGET_OS)_ALL_OS_NAMES"))
            var_stack.set_var("TARGET_OS_NAMES").extend(target_os_names)
            second_name = var_stack.resolve("$(TARGET_OS)")
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            var_stack.set_var("TARGET_OS_SECOND_NAME").append(second_name)

        self.read_repo_type_defaults()
        if var_stack.resolve("$(REPO_TYPE)") == "P4":
            if "P4_SYNC_DIR" not in var_stack:
                if "SYNC_BASE_URL" in var_stack:
                    p4_sync_dir = utils.P4GetPathFromDepotPath(var_stack.resolve("$(SYNC_BASE_URL)"))
                    var_stack.set_var("P4_SYNC_DIR", "from SYNC_BASE_URL").append(p4_sync_dir)

   # sync command implemented in instlClientSync.py file

    from instlClientSync import do_sync

    # copy command implemented in instlClientCopy.py file
    from instlClientCopy import do_copy
    from instlClientCopy import init_copy_vars
    from instlClientCopy import create_copy_instructions
    from instlClientCopy import create_copy_instructions_for_source
    from instlClientCopy import pre_copy_mac_handling

    # remove command implemented in instlClientRemove.py file
    from instlClientRemove import do_remove
    from instlClientRemove import init_remove_vars
    from instlClientRemove import create_remove_instructions
    from instlClientRemove import create_remove_instructions_for_source

    # uninstall command implemented in instlClientUninstall.py file
    from instlClientUninstall import do_uninstall
    from instlClientUninstall import init_uninstall_vars
    from instlClientUninstall import create_uninstall_instructions
    from instlClientUninstall import create_require_file_instructions

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
        if what is None:  # None is all
            retVal.append(aYaml.YamlDumpDocWrap(var_stack, '!define', "Definitions",
                                                explicit_start=True, sort_mappings=True))
            retVal.append(aYaml.YamlDumpDocWrap(self.install_definitions_index,
                                                '!index', "Installation index",
                                                explicit_start=True, sort_mappings=True))
        else:
            defines = list()
            indexes = list()
            unknowns = list()
            for identifier in what:
                if identifier in var_stack:
                    defines.append(var_stack.repr_for_yaml(identifier))
                elif identifier in self.install_definitions_index:
                    indexes.append({identifier: self.install_definitions_index[identifier].repr_for_yaml()})
                else:
                    unknowns.append(aYaml.YamlDumpWrap(value="UNKNOWN VARIABLE",
                                                       comment=identifier + " is not in variable list"))
            if defines:
                retVal.append(aYaml.YamlDumpDocWrap(defines, '!define', "Definitions",
                                                    explicit_start=True, sort_mappings=True))
            if indexes:
                retVal.append(
                    aYaml.YamlDumpDocWrap(indexes, '!index', "Installation index",
                                          explicit_start=True, sort_mappings=True))
            if unknowns:
                retVal.append(
                    aYaml.YamlDumpDocWrap(unknowns, '!unknowns', "Installation index",
                                          explicit_start=True, sort_mappings=True))

        return retVal

    def add_default_items(self):
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
        if "MAIN_INSTALL_TARGETS" not in var_stack:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        for os_name in var_stack.resolve_to_list("$(TARGET_OS_NAMES)"):
            InstallItem.begin_get_for_specific_os(os_name)
        self.installState.root_install_items.extend(var_stack.resolve_to_list("$(MAIN_INSTALL_TARGETS)"))
        self.installState.root_install_items = filter(bool, self.installState.root_install_items)
        if var_stack.resolve("$(__MAIN_COMMAND__)") != "uninstall":
            self.installState.calculate_full_install_items_set(self)
        self.read_previous_requirements()
        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(self.installState.full_install_items)
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(self.installState.orphan_install_items)

    def read_previous_requirements(self):
        require_file_path = var_stack.resolve("$(SITE_REQUIRE_FILE_PATH)")
        if os.path.isfile(require_file_path):
            self.read_yaml_file(require_file_path)

    def accumulate_unique_actions(self, action_type, iid_list):
        """ accumulate action_type actions from iid_list, eliminating duplicates"""
        unique_actions = utils.unique_list()  # unique_list will eliminate identical actions while keeping the order
        for IID in iid_list:
            with self.install_definitions_index[IID] as installi:
                action_var_name = "iid_action_list_" + action_type
                item_actions = var_stack.resolve_var_to_list_if_exists(action_var_name)
                num_unique_actions = 0
                for an_action in item_actions:
                    len_before = len(unique_actions)
                    unique_actions.append(an_action)
                    len_after = len(unique_actions)
                    if len_before < len_after:  # add progress only for the first same action
                        num_unique_actions += 1
                        action_description = self.action_type_to_progress_message[action_type]
                        if num_unique_actions > 1:
                            action_description = " ".join((action_description, str(num_unique_actions)))
                        unique_actions.append(
                            self.platform_helper.progress("{installi.name} {action_description}".format(**locals())))
        self.batch_accum += unique_actions
        logging.info("... %s actions: %d", action_type, len(unique_actions))
