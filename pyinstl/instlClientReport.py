#!/usr/bin/env python3


import os

import json
from configVar import var_stack
from .instlClient import InstlClient
from .installItem import read_index_from_yaml
import utils

class InstlClientReport(InstlClient):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.current_index_yaml_path = None
        self.output_data = None

    def command_output(self):
        if "__MAIN_OUT_FILE__" in var_stack:
            out_file = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
        else:
            out_file = "stdout"

        output_format = var_stack.ResolveVarToStr("__OUTPUT_FORMAT__")
        if output_format == "text":
            lines = [", ".join(line_data) for line_data in self.output_data]
            output_text = "\n".join(lines)
        elif output_format == "json":
            output_text = json.dumps(self.output_data)

        with utils.write_to_file_or_stdout(out_file) as wfd:
            wfd.write(output_text)
            wfd.write("\n")

    def do_report_installed(self):
        self.current_index_yaml_path = var_stack.ResolveVarToStr('CURRENT_INDEX_YAML')
        self.current_require_yaml_path = var_stack.ResolveVarToStr('CURRENT_REQUIRE_YAML')

        output_text = ""
        if os.path.isfile(self.current_index_yaml_path) and os.path.isfile(self.current_require_yaml_path):
            self.current_index = dict()
            self.read_yaml_file(self.current_index_yaml_path, index_dict=self.current_index)
            self.resolve_index_inheritance(index_dict=self.current_index)

            self.read_yaml_file(self.current_require_yaml_path, req_reader=self.installState.req_man)
            root_items = self.installState.req_man.get_previously_installed_root_items()
            guids_to_ignore = set(var_stack.ResolveVarToList("IGNORED_GUIDS", []))
            report_only_items_with_guids = "REPORT_ONLY_ITEMS_WITH_GUIDS" in var_stack

            self.output_data = list()

            for iid in sorted(self. current_index):
                with self.current_index[iid].push_var_stack_scope():
                    guid_list = list(set(var_stack.get_configVar_obj('iid_guid')).difference(guids_to_ignore))
                    if len(guid_list) or not report_only_items_with_guids:
                        var_stack.set_var('iid_guid').extend(guid_list)
                        single_iid_report_data = var_stack.ResolveVarToList("REPORT_INSTALLED_FIELDS")
                        self.output_data.append(single_iid_report_data)
                        self.output_data.sort()
        else:
            self.output_data = self.report_no_current_installation()

    def do_report_update(self):
        print("report-update")

    def calculate_install_items(self):
        pass

    def report_no_current_installation(self):
        return "Looks like no product are installed, file not found: " + self.current_index_yaml_path
