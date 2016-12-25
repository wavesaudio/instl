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
        self.current_require_yaml_path = None
        self.guids_to_ignore = None
        self.report_only_items_with_guids = False
        self.report_installed_items = False
        self.report_remote_items = False
        self.output_data = []

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

    def do_report_versions(self):
        self.report_only_items_with_guids = "REPORT_ONLY_ITEMS_WITH_GUIDS" in var_stack
        self.report_installed_items = "REPORT_INSTALLED_ITEMS" in var_stack
        self.report_remote_items = "REPORT_REMOTE_ITEMS" in var_stack
        self.guids_to_ignore = set(var_stack.ResolveVarToList("IGNORED_GUIDS", []))

        report_data = self.items_table.versions_report()
        self.items_table.commit_changes()

        self.output_data.extend(report_data)

    def calculate_install_items(self):
        pass

    def report_no_current_installation(self):
        return (("Looks like no product are installed, file not found", self.current_index_yaml_path),)

    def do_report_gal(self):
        self.check_binaries_versions()

    def check_binaries_versions(self):
        try:
            path_to_search = var_stack.ResolveVarToList('CHECK_BINARIES_VERSION_FOLDERS')
            require_repo_rev = int(var_stack.ResolveVarToStr('REQUIRE_REPO_REV'))
            print("REQUIRE_REPO_REV", require_repo_rev)
            max_repo_rev = int(var_stack.ResolveVarToStr('CHECK_BINARIES_VERSION_MAXIMAL_REPO_REV'))
            print("CHECK_BINARIES_VERSION_MAXIMAL_REPO_REV", max_repo_rev)
            if require_repo_rev > max_repo_rev:
                raise Exception("require_repo_rev <= max_repo_rev")

            binaries_version_list = list()
            for a_path in path_to_search:
                binaries_version_from_folder = self.check_binaries_versions_in_folder(a_path)
                binaries_version_list.extend(binaries_version_from_folder)

        except Exception as ex:
            print("not doing check_binaries_versions", ex)

    def check_binaries_versions_in_folder(self, in_path):
        retVal = list()
        print("checking", in_path+":")
        current_os = var_stack.ResolveVarToStr("__CURRENT_OS__")
        for root_path, dirs, files in os.walk(in_path, followlinks=False):
            info = utils.extract_binary_info(current_os, root_path)
            if info is not None:
                print("    info for", root_path, info)
                retVal.append(info)
                del dirs[:]  # info was found for root_path, no need to dig deeper
                del files[:]
            else:
                print("    no info for", root_path)
                for a_file in files:
                    file_full_path = os.path.join(root_path, a_file)
                    if not os.path.islink(file_full_path):
                        info = utils.extract_binary_info(current_os, file_full_path)
                        if info is not None:
                            print("    info for", file_full_path, info)
                            retVal.append(info)
                        else:
                            print("    no info for", file_full_path)

        print(retVal)
        return retVal
