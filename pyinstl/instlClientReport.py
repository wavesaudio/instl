#!/usr/bin/env python3


import os

import json
from configVar import config_vars
from .instlClient import InstlClient
import utils


class InstlClientReport(InstlClient):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.current_index_yaml_path = None
        self.current_require_yaml_path = None
        self.guids_to_ignore = None
        self.output_data = []

    def get_default_out_file(self):
        retVal = "stdout"
        return retVal

    def command_output(self):
        out_file = config_vars["__MAIN_OUT_FILE__"].str()

        output_format = str(config_vars.get("OUTPUT_FORMAT", 'text'))

        if output_format == "json":
            output_text = json.dumps(self.output_data, indent=1)
        else:  # output_format == "text":  text is the default format
            lines = [", ".join(line_data) for line_data in self.output_data]
            output_text = "\n".join(lines)

        with utils.write_to_file_or_stdout(out_file) as wfd:
            wfd.write(output_text)
            wfd.write("\n")

    def do_report_versions(self):
        self.guids_to_ignore = set(list(config_vars.get("MAIN_IGNORED_TARGETS", [])))

        report_only_installed =  bool(config_vars["__REPORT_ONLY_INSTALLED__"])
        report_data = self.items_table.versions_report(report_only_installed=report_only_installed)

        self.output_data.extend(report_data)

    def calculate_install_items(self):
        pass

    def report_no_current_installation(self):
        return (("Looks like no product are installed, file not found", self.current_index_yaml_path),)

    def do_report_gal(self):
        self.get_version_of_installed_binaries()
