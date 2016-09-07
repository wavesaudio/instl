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
        if os.path.isfile(self.current_index_yaml_path):
            self.current_index = dict()
            self.read_yaml_file(self.current_index_yaml_path, index_dict=self.current_index)
            guids_to_ignore = var_stack.ResolveVarToList("IGNORED_GUIDS", [])

            for iid in sorted(self.current_index):
                guids = []
                for guid in self.current_index[iid].guids:
                    if guid not in guids_to_ignore:
                        guids.append(guid)
                if guids or "REPORT_ONLY_ITEMS_WITH_GUIDS" not in var_stack:
                    line = ", ".join((iid, self.current_index[iid].name, *guids, self.current_index[iid].version))
                    print(line)
        else:
            self.report_no_current_installation()

    def do_report_update(self):
        print("report-update")

    def calculate_install_items(self):
        pass

    def report_no_current_installation(self):
        print("Looks like no product are installed, file not found:", self.current_index_yaml_path)
