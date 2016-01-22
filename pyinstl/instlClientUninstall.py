#!/usr/bin/env python3



import os

import utils
from configVar import var_stack

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

    def create_uninstall_instructions(self):
        self.init_uninstall_vars()
        print("original list", self.installState.root_install_items)
        print("translated list", self.installState.root_install_iids_translated)
        unrequired_items, unmentioned_items = self.require_man.calc_to_remove_items(self.installState.root_install_iids_translated)
        print("unrequired", unrequired_items)
        print("unmentioned", unmentioned_items)

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
            self.installState.full_install_items.extend(full_list_of_iids_to_uninstall)
            self.installState.sort_install_items_by_target_folder(self)
            print("actual items to uninstall:", self.installState.full_install_items)
            self.create_require_file_instructions()
            self.init_remove_vars()
            self.create_remove_instructions()
        else:
            print("nothing to uninstall")
