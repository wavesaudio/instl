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
class DoItInstructionsState(object):
    """ holds state for specific creating of install instructions """

    def __init__(self):
        self.root_doit_items = utils.unique_list()
        self.full_doit_items = utils.unique_list()
        self.orphan_doit_items = utils.unique_list()
        self.doit_items_by_target_folder = defaultdict(utils.unique_list)
        self.no_copy_items_by_sync_folder = defaultdict(utils.unique_list)
        self.sync_paths = utils.unique_list()

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['root_doit_items'] = list(self.root_doit_items)
        retVal['full_doit_items'] = list(self.full_doit_items)
        retVal['orphan_doit_items'] = list(self.orphan_doit_items)
        retVal['doit_items_by_target_folder'] = {folder: list(self.doit_items_by_target_folder[folder]) for folder
                                                    in self.doit_items_by_target_folder}
        retVal['no_copy_items_by_sync_folder'] = list(self.no_copy_items_by_sync_folder)
        retVal['sync_paths'] = list(self.sync_paths)
        return retVal

    def calculate_full_doit_items_set(self, instlObj):
        """ calculate the set of iids to install by starting with the root set and adding all dependencies.
            Initial list of iids should already be in self.root_doit_items.
            If an install items was not found for a iid, the iid is added to the orphan set.
        """

        if len(self.root_doit_items) > 0:
            logging.info(" ".join(("Main install items:", ", ".join(self.root_doit_items))))
        else:
            logging.error("Main install items list is empty")
        # root_doit_items might have guid in it, translate them to iids

        root_install_iids_translated = utils.unique_list()
        for root_IID in self.root_doit_items:
            # if IID is a guid iids_from_guid will translate to iid's, or return the IID otherwise
            iids_from_the_root_iid = iids_from_guid(instlObj.install_definitions_index, root_IID)
            for IID in iids_from_the_root_iid:
                if IID in instlObj.install_definitions_index:
                    root_install_iids_translated.append(IID)
                else:
                    self.orphan_doit_items.append(IID)
        self.full_doit_items = root_install_iids_translated

class InstlDoIt(InstlInstanceBase):
    def __init__(self, initial_vars):
        super(InstlDoIt, self).__init__(initial_vars)

    def do_command(self):
        the_command = var_stack.resolve("$(__MAIN_COMMAND__)")
        fixed_command_name = the_command.replace('-', '_')
        # print("client_commands", fixed_command_name)
        self.installState = DoItInstructionsState()
        main_input_file_path = var_stack.resolve("$(__MAIN_INPUT_FILE__)")
        self.read_yaml_file(main_input_file_path)
        self.init_default_doit_vars()
        self.resolve_defined_paths()
        self.batch_accum.set_current_section('begin')
        self.batch_accum += self.platform_helper.setup_echo()
        # after reading variable COPY_TOOL from yaml, we might need to re-init the copy tool.
        self.platform_helper.init_copy_tool()
        self.resolve_index_inheritance()
        self.add_default_items()
        self.calculate_default_doit_item_set()
        self.platform_helper.num_items_for_progress_report = int(var_stack.resolve("$(LAST_PROGRESS)"))

        do_command_func = getattr(self, "do_" + fixed_command_name)
        do_command_func()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def init_default_doit_vars(self):
        if "SYNC_BASE_URL" in var_stack:
            #raise ValueError("'SYNC_BASE_URL' was not defined")
            resolved_sync_base_url = var_stack.resolve("$(SYNC_BASE_URL)")
            url_main_item = utils.main_url_item(resolved_sync_base_url)
            var_stack.set_var("SYNC_BASE_URL_MAIN_ITEM", description="from init_default_client_vars").append(url_main_item)
        # TARGET_OS_NAMES defaults to __CURRENT_OS_NAMES__, which is not what we want if syncing to
        # an OS which is not the current
        if var_stack.resolve("$(TARGET_OS)") != var_stack.resolve("$(__CURRENT_OS__)"):
            target_os_names = var_stack.resolve_var_to_list(var_stack.resolve("$(TARGET_OS)_ALL_OS_NAMES"))
            var_stack.set_var("TARGET_OS_NAMES").extend(target_os_names)
            second_name = var_stack.resolve("$(TARGET_OS)")
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            var_stack.set_var("TARGET_OS_SECOND_NAME").append(second_name)

    def do_doit(self):
        for action_type in ("pre_doit", "doit", "post_doit"):
            # mark all items as undone
            for IID in self.install_definitions_index:
                self.install_definitions_index[IID].user_data = False
            self.doit_for_items(self.installState.full_doit_items, action_type)

        if self.installState.orphan_doit_items:
            print("Don't know to do with these items:", ", ".join(self.installState.orphan_doit_items))

        self.batch_accum += self.platform_helper.progress("Done doing it")

    def doit_for_items(self, item_list, action):
         for IID in item_list:
            if IID in self.install_definitions_index:
                if not self.install_definitions_index[IID].user_data:
                    depends = self.install_definitions_index[IID].get_depends()
                    self.doit_for_items(depends, action)
                    self.doit_for_item(IID, action)
            else:
                self.installState.orphan_doit_items.append(IID)

    def doit_for_item(self, IID, action):
        print(action, "for", IID)
        with self.install_definitions_index[IID] as doit_item:
            self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_"+action)
            doit_item.user_data = True

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

    def calculate_default_doit_item_set(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_DOIT_ITEMS" not in var_stack:
            raise ValueError("'MAIN_DOIT_ITEMS' was not defined")
        for os_name in var_stack.resolve_to_list("$(TARGET_OS_NAMES)"):
            InstallItem.begin_get_for_specific_os(os_name)
        self.installState.root_doit_items.extend(var_stack.resolve_to_list("$(MAIN_DOIT_ITEMS)"))
        self.installState.root_doit_items = filter(bool, self.installState.root_doit_items)
        self.installState.calculate_full_doit_items_set(self)
        self.read_previous_requirements()
        var_stack.set_var("__FULL_LIST_OF_DOIT_TARGETS__").extend(self.installState.full_doit_items)
        var_stack.set_var("__ORPHAN_DOIT_TARGETS__").extend(self.installState.orphan_doit_items)

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
