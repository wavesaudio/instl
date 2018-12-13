#!/usr/bin/env python3.6


import os
import io
import json

import aYaml
from configVar import config_vars
from .instlClient import InstlClient
import utils


class InstlClientReport(InstlClient):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.read_defaults_file(super().__thisclass__.__name__)
        self.current_index_yaml_path = None
        self.current_require_yaml_path = None
        self.guids_to_ignore = None
        self.output_data = []

    def get_default_out_file(self) -> None:
        if "__MAIN_OUT_FILE__" not in config_vars:
            config_vars["__MAIN_OUT_FILE__"] = "stdout"

    def command_output(self):
        out_file = os.fspath(config_vars["__MAIN_OUT_FILE__"])

        output_format = str(config_vars.get("OUTPUT_FORMAT", 'text'))

        if output_format == "json":
            output_text = json.dumps(self.output_data, indent=1)
        elif output_format == "yaml":
            io_str = io.StringIO()
            for yaml_data in self.output_data:
                 aYaml.writeAsYaml(yaml_data, io_str)
            output_text = io_str.getvalue()
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

    def do_read_yaml(self):
        config_vars["OUTPUT_FORMAT"] = "yaml"
        config_vars_yaml_obj = config_vars.repr_for_yaml()
        config_vars_yaml = aYaml.YamlDumpDocWrap(config_vars_yaml_obj, '!define', "Definitions", explicit_start=True, sort_mappings=True, include_comments=False)
        self.output_data.append(config_vars_yaml)
        index_yaml_obj = self.items_table.repr_for_yaml()
        index_yaml = aYaml.YamlDumpDocWrap(index_yaml_obj, '!index', "Installation index", explicit_start=True, sort_mappings=True, include_comments=False)
        self.output_data.append(index_yaml)
