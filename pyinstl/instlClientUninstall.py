#!/usr/bin/env python3



import os

from configVar import var_stack

from .installItem import InstallItem
from .instlClientRemove import InstlClientRemove


class InstlClientUninstall(InstlClientRemove):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)

    def do_uninstall(self):
        self.init_uninstall_vars()
        self.create_uninstall_instructions()

    def init_uninstall_vars(self):
        self.init_remove_vars()

    def calculate_install_items(self):
        if "MAIN_INSTALL_TARGETS" not in var_stack:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        for os_name in var_stack.resolve_to_list("$(TARGET_OS_NAMES)"):
            InstallItem.begin_get_for_specific_os(os_name)
        require_path = var_stack.ResolveVarToStr("SITE_REQUIRE_FILE_PATH")
        if os.path.isfile(require_path):
            try:
                self.read_yaml_file(require_path, req_reader=self.installState.req_man)
            except Exception as ex:
                print("failed to read", require_path, ex)
        self.installState.root_items = var_stack.resolve_to_list("$(MAIN_INSTALL_TARGETS)")
        self.installState.calc_items_to_remove()
        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(sorted(self.installState.all_items))
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(sorted(self.installState.orphan_items))

    def create_uninstall_instructions(self):

        print("requested items to uninstall:", self.installState.root_items)
        if len(self.installState.all_items) > 0:
            print("actual items to uninstall:", self.installState.all_items)
            self.create_remove_instructions()
            self.create_require_file_instructions()
        else:
            print("nothing to uninstall")
