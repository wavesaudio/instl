#!/usr/bin/env python3



import os

import utils
from configVar import var_stack


def do_uninstall(self):
    self.init_uninstall_vars()
    self.create_uninstall_instructions()


def init_uninstall_vars(self):
    pass


def create_uninstall_instructions(self):
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


def create_require_file_instructions(self):
    # write the require file as it should look after copy is done
    new_require_file_path = var_stack.resolve("$(NEW_SITE_REQUIRE_FILE_PATH)", raise_on_fail=True)
    new_require_file_dir, new_require_file_name = os.path.split(new_require_file_path)
    utils.safe_makedirs(new_require_file_dir)
    self.write_require_file(new_require_file_path)
    # Copy the new require file over the old one, if copy fails the old file remains.
    self.batch_accum += self.platform_helper.copy_file_to_file("$(NEW_SITE_REQUIRE_FILE_PATH)",
                                                               "$(SITE_REQUIRE_FILE_PATH)")
