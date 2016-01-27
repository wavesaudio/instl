#!/usr/bin/env python3



import os

import utils
from configVar import var_stack

from .installItem import InstallItem, guid_list, iids_from_guids
from .instlClient import InstlClient


class InstlClientUninstall(InstlClient):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)

    def do_uninstall(self):
        self.init_uninstall_vars()
        self.create_uninstall_instructions()

    def init_uninstall_vars(self):
        pass

    def calculate_install_items(self):
        if "MAIN_INSTALL_TARGETS" not in var_stack:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        for os_name in var_stack.resolve_to_list("$(TARGET_OS_NAMES)"):
            InstallItem.begin_get_for_specific_os(os_name)
        require_path = var_stack.resolve("$(SITE_REQUIRE_FILE_PATH)")
        if os.path.isfile(require_path):
            try:
                self.read_yaml_file(require_path, req_reader=self.installState.req_man)
            except Exception as ex:
                print("failed to read", require_path, ex)
        self.installState.root_items = var_stack.resolve_to_list("$(MAIN_INSTALL_TARGETS)")
        unrequired_items, unmentioned_items = self.installState.calc_items_to_remove()
        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(sorted(self.installState.all_items))
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(sorted(self.installState.orphan_items))

    def create_uninstall_instructions(self):
        pass

    def old_create_uninstall_instructions(self):
        self.init_uninstall_vars()
        # self.uninstall_definitions_index = dict()
        full_list_of_iids_to_uninstall = list()
        from collections import deque

        iids_to_check = deque()
        iids_to_check.extend(self.installState.root_install_items)
        while len(iids_to_check) > 0:
            curr_iid = iids_to_check.popleft()
            for item in self.install_definitions_index.values():
                if len(item.required_by) > 0:  # to avoid repeated checks
                    item.required_by.remove(curr_iid)
                    if len(item.required_by) == 0:
                        full_list_of_iids_to_uninstall.append(item.iid)
                        iids_to_check.append(item.iid)

        print("requested items to uninstall:", self.installState.root_install_items)
        if len(full_list_of_iids_to_uninstall) > 0:
            self.installState.all_items.extend(full_list_of_iids_to_uninstall)
            self.installState.__sort_all_items_by_target_folder(self)
            print("actual items to uninstall:", self.installState.all_items)
            self.create_require_file_instructions()
            self.init_remove_vars()
            self.create_remove_instructions()
        else:
            print("nothing to uninstall")
