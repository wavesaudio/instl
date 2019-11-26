#!/usr/bin/env python3.6


import os
import io
import json
from collections import defaultdict

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
        pass

    def command_output(self):
        if not bool(config_vars.get('__SILENT__', "false")):

            output_format = str(config_vars.get("OUTPUT_FORMAT", 'text'))

            if output_format == "json":
                output_text = json.dumps(self.output_data, indent=1, default=utils.extra_json_serializer)
            elif output_format == "yaml":
                io_str = io.StringIO()
                for yaml_data in self.output_data:
                     aYaml.writeAsYaml(yaml_data, io_str)
                output_text = io_str.getvalue()
            else:  # output_format == "text":  text is the default format
                lines = [", ".join(line_data) for line_data in self.output_data]
                output_text = "\n".join(lines)

            out_file = config_vars.get("__MAIN_OUT_FILE__", None).Path()
            with utils.write_to_file_or_stdout(out_file) as wfd:
                wfd.write(output_text)
                wfd.write("\n")

    def do_report_versions(self):
        self.guids_to_ignore = set(list(config_vars.get("MAIN_IGNORED_TARGETS", [])))

        report_only_installed =  bool(config_vars["__REPORT_ONLY_INSTALLED__"])
        report_data = self.items_table.versions_report(report_only_installed=report_only_installed, progress_callback=self.progress("calculate versions report"))

        self.output_data.extend(report_data)

    def calculate_install_items(self):
        pass

    def report_no_current_installation(self):
        return (("Looks like no product are installed, file not found", self.current_index_yaml_path),)

    def do_report_gal(self):
        self.get_version_of_installed_binaries()

    def do_read_yaml(self):
        config_vars["OUTPUT_FORMAT"] = "yaml"
        config_vars["DEBUG_INDEX_DB"] = True
        config_vars_yaml_obj = config_vars.repr_for_yaml()
        config_vars_yaml = aYaml.YamlDumpDocWrap(config_vars_yaml_obj, '!define', "Definitions", explicit_start=True, sort_mappings=True, include_comments=False)
        self.output_data.append(config_vars_yaml)
        index_yaml_obj = self.items_table.repr_for_yaml(resolve=True)
        index_yaml = aYaml.YamlDumpDocWrap(index_yaml_obj, '!index', "Installation index", explicit_start=True, sort_mappings=True, include_comments=False)
        self.output_data.append(index_yaml)

    def do_short_index(self):
        short_index_data = self.items_table.get_data_for_short_index()  # IID, GUID, NAME, VERSION, generation
        short_index_dict = defaultdict(dict)
        for data_line in short_index_data:
            short_index_dict[data_line[0]]['guid'] = data_line[1]
            if data_line[4] and data_line[1] != data_line[4]:  # uninstall gui
                short_index_dict[data_line[0]]['guid'] = list((data_line[1], data_line[4]))
            if data_line[2]:
                short_index_dict[data_line[0]]['name'] = data_line[2]
            if data_line[3] or data_line[4]:
                short_index_dict[data_line[0]]['version'] = data_line[3]

        defines_dict = config_vars.repr_for_yaml(which_vars=['AUXILIARY_IIDS'], resolve=True, ignore_unknown_vars=False)
        defines_yaml_doc = aYaml.YamlDumpDocWrap(defines_dict, '!define', "Definitions",
                                                explicit_start=True, sort_mappings=True)

        index_yaml_doc = aYaml.YamlDumpDocWrap(value=short_index_dict, tag="!index",
                                            explicit_start=True, explicit_end=False,
                                            sort_mappings=True, include_comments=False)

        def __command_output(self, _as_yaml_doc):
            out_file_path = config_vars.get("__MAIN_OUT_FILE__", None).Path()
            with utils.write_to_file_or_stdout(out_file_path) as wfd:
                aYaml.writeAsYaml(defines_yaml_doc, wfd)
                aYaml.writeAsYaml(index_yaml_doc, wfd)

        from functools import partial
        self.command_output = partial(__command_output, self, index_yaml_doc)
