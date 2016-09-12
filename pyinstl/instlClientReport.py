#!/usr/bin/env python3


import os

import utils
from configVar import var_stack
from .instlClient import InstlClient
from .installItem import read_index_from_yaml


class InstlClientReport(InstlClient):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.current_index_yaml_path = None

    def do_report_installed(self):
        self.current_index_yaml_path = var_stack.ResolveVarToStr('CURRENT_INDEX_YAML')
        self.current_require_yaml_path = var_stack.ResolveVarToStr('CURRENT_REQUIRE_YAML')

        if os.path.isfile(self.current_index_yaml_path) and os.path.isfile(self.current_require_yaml_path):
            self.current_index = dict()
            self.read_yaml_file(self.current_index_yaml_path, index_dict=self.current_index)
            self.resolve_index_inheritance(index_dict=self.current_index)

            self.read_yaml_file(self.current_require_yaml_path, req_reader=self.installState.req_man)
            root_items = self.installState.req_man.get_previously_installed_root_items()
            guids_to_ignore = set(var_stack.ResolveVarToList("IGNORED_GUIDS", []))
            report_only_items_with_guids = "REPORT_ONLY_ITEMS_WITH_GUIDS" in var_stack

            for iid in sorted(self. current_index):
                with self.current_index[iid].push_var_stack_scope():
                    guid_list = list(set(var_stack.get_configVar_obj('iid_guid')).difference(guids_to_ignore))
                    if len(guid_list) or not report_only_items_with_guids:
                        var_stack.set_var('iid_guid').extend(guid_list)
                        mark = "!" if iid in root_items else "?"
                        line = var_stack.ResolveVarToStr("REPORT_INSTALLED_FORMAT")
                        line += mark
                        print(line)

        else:
            self.report_no_current_installation()

    def do_report_update(self):
        print("report-update")

    def calculate_install_items(self):
        pass

    def report_no_current_installation(self):
        print("Looks like no product are installed, file not found:", self.current_index_yaml_path)
