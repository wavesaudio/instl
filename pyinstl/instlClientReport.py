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

        orphan_require_items = self.items_table.require_items_without_version_or_guid()
        if len(orphan_require_items) > 0 and self.should_check_for_binary_versions():
            binaries_version_list = self.get_binaries_versions()  # returns [(index_version, require_version, index_guid, require_guid, generation), ...]
            if len(binaries_version_list) > 0:
                for bin_ver in binaries_version_list:
                    if bin_ver[2] is not None:  # we have a guid
                        for ori in orphan_require_items:
                            if ori[2] == bin_ver[2]:
                                print(ori, "new version:", bin_ver[1])

        self.output_data.extend(report_data)

    def should_check_for_binary_versions(self):
        try:
            retVal = 'CHECK_BINARIES_VERSION_FOLDERS' in var_stack \
                and int(var_stack.ResolveVarToStr('CHECK_BINARIES_VERSION_MAXIMAL_REPO_REV')) \
                    >= int(var_stack.ResolveVarToStr('REQUIRE_REPO_REV'))
        except Exception:
            retVal = False
        return retVal

    def calculate_install_items(self):
        pass

    def report_no_current_installation(self):
        return (("Looks like no product are installed, file not found", self.current_index_yaml_path),)

    def do_report_gal(self):
        self.get_binaries_versions()

    def get_binaries_versions(self):
        binaries_version_list = list()
        try:
            path_to_search = var_stack.ResolveVarToList('CHECK_BINARIES_VERSION_FOLDERS')

            for a_path in path_to_search:
                binaries_version_from_folder = self.check_binaries_versions_in_folder(a_path)
                binaries_version_list.extend(binaries_version_from_folder)

            self.items_table.insert_binary_versions(binaries_version_list)

        except Exception as ex:
            print("not doing check_binaries_versions", ex)
        return binaries_version_list

    def check_binaries_versions_in_folder(self, in_path):
        retVal = list()
        print("checking", in_path+":")
        current_os = var_stack.ResolveVarToStr("__CURRENT_OS__")
        for root_path, dirs, files in os.walk(in_path, followlinks=False):
            info = utils.extract_binary_info(current_os, root_path)
            if info is not None:
                #print("    info for", root_path, info)
                retVal.append(info)
                del dirs[:]  # info was found for root_path, no need to dig deeper
                del files[:]
            else:
                #print("    no info for", root_path)
                for a_file in files:
                    file_full_path = os.path.join(root_path, a_file)
                    if not os.path.islink(file_full_path):
                        info = utils.extract_binary_info(current_os, file_full_path)
                        if info is not None:
                        #    print("    info for", file_full_path, info)
                            retVal.append(info)
                        #else:
                        #    print("    no info for", file_full_path)

        #print(retVal)
        return retVal
