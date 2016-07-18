#!/usr/bin/env python3


import os
from collections import OrderedDict, defaultdict

import utils
from .installItem import InstallItem, guid_list, iids_from_guids
from .instlInstanceBase import InstlInstanceBase
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

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['root_doit_items'] = list(self.root_doit_items)
        retVal['full_doit_items'] = list(self.full_doit_items)
        retVal['orphan_doit_items'] = list(self.orphan_doit_items)
        retVal['doit_items_by_target_folder'] = {folder: list(self.doit_items_by_target_folder[folder]) for folder
                                                    in self.doit_items_by_target_folder}
        retVal['no_copy_items_by_sync_folder'] = list(self.no_copy_items_by_sync_folder)
        return retVal

    def calculate_full_doit_items_set(self, instlObj):
        """ calculate the set of iids to install by starting with the root set and adding all dependencies.
            Initial list of iids should already be in self.root_doit_items.
            If an install items was not found for a iid, the iid is added to the orphan set.
        """

        root_install_iids_translated = utils.unique_list()
        for root_IID in self.root_doit_items:
            # if IID is a guid iids_from_guid will translate to iid's, or return the IID otherwise
            iids_from_the_root_iid = iids_from_guids(instlObj.install_definitions_index, root_IID)
            for IID in iids_from_the_root_iid:
                if IID in instlObj.install_definitions_index:
                    root_install_iids_translated.append(IID)
                else:
                    self.orphan_doit_items.append(IID)
        self.full_doit_items = root_install_iids_translated


class InstlDoIt(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)

    def do_command(self):
        # print("client_commands", fixed_command_name)
        self.installState = DoItInstructionsState()
        main_input_file_path = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
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
        self.platform_helper.num_items_for_progress_report = int(var_stack.ResolveVarToStr("LAST_PROGRESS"))

        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def init_default_doit_vars(self):
        if "SYNC_BASE_URL" in var_stack:
            #raise ValueError("'SYNC_BASE_URL' was not defined")
            resolved_sync_base_url = var_stack.ResolveVarToStr("SYNC_BASE_URL")
            url_main_item = utils.main_url_item(resolved_sync_base_url)
            var_stack.set_var("SYNC_BASE_URL_MAIN_ITEM", description="from init_default_client_vars").append(url_main_item)
        # TARGET_OS_NAMES defaults to __CURRENT_OS_NAMES__, which is not what we want if syncing to
        # an OS which is not the current
        if var_stack.ResolveVarToStr("TARGET_OS") != var_stack.ResolveVarToStr("__CURRENT_OS__"):
            target_os_names = var_stack.ResolveVarToList(var_stack.ResolveStrToStr("$(TARGET_OS)_ALL_OS_NAMES"))
            var_stack.set_var("TARGET_OS_NAMES").extend(target_os_names)
            second_name = var_stack.ResolveVarToStr("TARGET_OS")
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
        with self.install_definitions_index[IID].push_var_stack_scope() as doit_item:
            action_list = var_stack.ResolveVarToList("iid_action_list_"+action, default=[])
            if len(action_list) > 0:
                self.batch_accum += self.platform_helper.remark("--- Begin "+doit_item.name)
                self.batch_accum += self.platform_helper.progress(var_stack.ResolveVarToStr("iid_name")+"...")
            num_actions = len(action_list)
            for i in range(num_actions):
                self.batch_accum += action_list[i]
                if i != num_actions - 1:
                    self.batch_accum += self.platform_helper.progress(var_stack.ResolveVarToStr("iid_name") + " "+str(i+1))
            if len(action_list) > 0:
                self.batch_accum += self.platform_helper.progress(var_stack.ResolveVarToStr("iid_name") + ". done")
                self.batch_accum += self.platform_helper.remark("--- End "+doit_item.name+"\n")
            doit_item.user_data = True

    def add_default_items(self):
        all_items_item = InstallItem("__ALL_ITEMS_IID__")
        all_items_item.name = "All IIDs"
        all_items_item.add_depends(*self.install_definitions_index.keys())
        self.install_definitions_index["__ALL_ITEMS_IID__"] = all_items_item

        all_guids_item = InstallItem("__ALL_GUIDS_IID__")
        all_guids_item.name = "All GUIDs"
        all_guids_item.add_depends(*guid_list(self.install_definitions_index))
        self.install_definitions_index["__ALL_GUIDS_IID__"] = all_guids_item

    def calculate_default_doit_item_set(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_DOIT_ITEMS" not in var_stack:
            raise ValueError("'MAIN_DOIT_ITEMS' was not defined")
        for os_name in var_stack.ResolveVarToList("TARGET_OS_NAMES"):
            InstallItem.begin_get_for_specific_os(os_name)
        self.installState.root_doit_items.extend(var_stack.ResolveVarToList("MAIN_DOIT_ITEMS"))
        self.installState.root_doit_items = list(filter(bool, self.installState.root_doit_items))
        self.installState.calculate_full_doit_items_set(self)
        var_stack.set_var("__FULL_LIST_OF_DOIT_TARGETS__").extend(self.installState.full_doit_items)
        var_stack.set_var("__ORPHAN_DOIT_TARGETS__").extend(self.installState.orphan_doit_items)

    def accumulate_unique_actions(self, action_type, iid_list):
        """ accumulate action_type actions from iid_list, eliminating duplicates"""
        unique_actions = utils.unique_list()  # unique_list will eliminate identical actions while keeping the order
        for IID in iid_list:
            with self.install_definitions_index[IID].push_var_stack_scope() as installi:
                action_var_name = "iid_action_list_" + action_type
                item_actions = var_stack.ResolveVarToList(action_var_name, default=[])
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
