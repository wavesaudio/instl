#!/usr/bin/env python3.12
"""Verify / depend commands extracted verbatim from pyinstl/instlAdmin.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

import os

import utils
import aYaml
from pybatch import *
from configVar import main_input_file_path, main_input_file_str


class _VerifyAdminMixin:

    def do_verify_index(self):
        self.read_yaml_file(main_input_file_path())
        self.info_map_table.read_from_file(config_vars["FULL_INFO_MAP_FILE_PATH"].Path(), disable_indexes_during_read=True)
        self.verify_actions()
        self.verify_index_to_repo()

    def do_depend(self):
        from .. import installItemGraph

        self.read_yaml_file(main_input_file_str())
        self.items_table.activate_all_oses()
        self.items_table.resolve_inheritance()
        depend_result = defaultdict(dict)
        graph = installItemGraph.create_dependencies_graph(self.items_table)
        all_iids = self.items_table.get_all_iids()
        cache_for_needs = dict()
        for IID in all_iids:
            depend_result[IID]['depends'] = self.needs(IID, set(all_iids), cache_for_needs)
            if not depend_result[IID]['depends']:
                depend_result[IID]['depends'] = None   # so '~' is displayed instead of []

            depend_result[IID]['needed_by'] = self.needed_by(IID, graph)
            if not depend_result[IID]['needed_by']:
                depend_result[IID]['needed_by'] = None # so '~' is displayed instead of []

        out_file_path = config_vars.get("__MAIN_OUT_FILE__", None).Path()
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            aYaml.writeAsYaml(aYaml.YamlDumpWrap(depend_result, sort_mappings=True), out_file)
        self.progress("dependencies written to", out_file_path)

    def do_verify_repo(self):
        self.read_yaml_file(config_vars["STAGING_FOLDER_INDEX"].str())

        the_folder = config_vars["STAGING_FOLDER"].str()
        self.info_map_table.initialize_from_folder(the_folder, progress_callback=self.progress)
        self.items_table.activate_all_oses()
        problem_messages_by_iid = defaultdict(list)
        self.verify_inheritance(problem_messages_by_iid)  # must be done before resolve_inheritance
        self.verify_dependencies(problem_messages_by_iid) # must be done before resolve_inheritance
        if problem_messages_by_iid:
            self.print_problem_messages(problem_messages_by_iid)
            self.progress(" >>> cannot continue checking - THESE ISSUES MUST BE FIXED <<<")
            raise AssertionError(f"Found {len(problem_messages_by_iid)} missing inherit/depends")
        else:
            self.items_table.resolve_inheritance()
            self.verify_actions(problem_messages_by_iid)
            self.verify_index_to_repo(problem_messages_by_iid)

    def verify_inheritance(self, problem_messages_by_iid):
        # check inherit
        self.progress("checking inheritance")
        missing_inheritees = self.items_table.get_missing_iids_from_details("inherit")
        self.progress(f"{len(missing_inheritees)} missing inheritees found")
        for missing_inheritee in missing_inheritees:
            err_message = f"inherits from non existing '{missing_inheritee[1]}'"
            problem_messages_by_iid[missing_inheritee[0]].append(err_message)

    def verify_dependencies(self, problem_messages_by_iid):
        # check depends
        self.progress("checking dependencies")
        missing_dependees = self.items_table.get_missing_iids_from_details("depends")
        self.progress(f"{len(missing_dependees)} missing dependees found")
        for missing_dependee in missing_dependees:
            err_message = f"depends on non existing '{missing_dependee[1]}'"
            problem_messages_by_iid[missing_dependee[0]].append(err_message)

    def print_problem_messages(self, problem_messages_by_iid: dict):
        if problem_messages_by_iid:
            for iid in sorted(problem_messages_by_iid.keys()):
                self.progress(iid + ":")
                for problem_message in sorted(problem_messages_by_iid[iid]):
                    self.progress("   ", problem_message)
        else:
            self.progress(f"No problems found")

    def verify_index_to_repo(self, problem_messages_by_iid=None):
        """ helper function for verify-repo and verify-index commands
            Assuming the index and info-map have already been read
            check the expect files from the index appear in the info-map
        """

        no_target_folder_ok = config_vars.get("NO_TARGET_FOLDER_OK", []).list()
        common_name_ok = config_vars.get("COMMON_NAME_OK", []).list()
        no_files_or_folders_ok = config_vars.get("NO_FILES_OR_FOLDERS_OK", []).list()

        all_iids = sorted(self.items_table.get_all_iids())
        self.total_self_progress += len(all_iids)
        self.items_table.change_status_of_all_iids(1)

        if problem_messages_by_iid is None:
            problem_messages_by_iid = defaultdict(list)

        names_to_iids = defaultdict(list)
        for iid in all_iids:
            self.progress("checking sources for", iid)

            name = self.items_table.get_details_for_active_iids("name", unique_values=True, limit_to_iids=[iid])
            if name:
                names_to_iids[name[0]].append(iid)

            # check sources
            source_and_tag_list = self.items_table.get_details_and_tag_for_active_iids("install_sources", unique_values=True, limit_to_iids=(iid,))
            for source in source_and_tag_list:
                iid, source_path, source_type = source[0], source[1], source[2]
                num_files_for_source = self.info_map_table.mark_required_for_source(source_path, source_type)
                if num_files_for_source == 0:
                    case_insensitive_items = self.info_map_table.get_any_item_recursive(source_path, case_sensitive=False)
                    if iid not in no_files_or_folders_ok:
                        err_message = f"""source, '{source_path}' required by {iid}, does not have any files or folders"""
                        if case_insensitive_items:
                            err_message += f"""\nthere are some files/folders with similar name but different case:\n{[s.path for s in case_insensitive_items]}"""
                        problem_messages_by_iid[iid].append(err_message)

            # check previous sources
            previous_sources = self.items_table.get_details_and_tag_for_active_iids("previous_sources", unique_values=True)
            for previous_source in previous_sources:
                iid, previous_source_path, source_type = previous_source[0], previous_source[1], previous_source[2]
                if not previous_source_path:
                    err_message = f"previous source for {iid} is empty"
                    problem_messages_by_iid[iid].append(err_message)
                if source_type not in ("!dir", "!file"):
                    err_message = f"previous source for {iid} has type {source_type}, should be !file or !dir"
                    problem_messages_by_iid[iid].append(err_message)

            # check targets
            if len(source_and_tag_list) > 0:
                target_folders = set(self.items_table.get_resolved_details_value_for_active_iid(iid, "install_folders", unique_values=True))
                if len(target_folders) == 0 and iid not in no_target_folder_ok:
                    err_message = f"iid {iid}, does not have target folder"
                    problem_messages_by_iid[iid].append(err_message)

        for name, iids in names_to_iids.items():
            if len(iids) > 1:
                err_message = f"name '{name}', is common to {len(iids)} iids: {iids}"
                for iid in iids:
                    if iid not in common_name_ok:
                        problem_messages_by_iid[iid].append(err_message)

        self.progress("checking for cyclic dependencies")
        self.info_map_table.mark_required_completion()
        self.find_cycles()

        self.print_problem_messages(problem_messages_by_iid)

        self.progress("index:", len(all_iids), "iids")
        num_files = self.info_map_table.num_items("all-files")
        num_dirs = self.info_map_table.num_items("all-dirs")
        num_required_files = self.info_map_table.num_items("required-files")
        num_required_dirs = self.info_map_table.num_items("required-dirs")
        self.progress("info map:", num_files, "files in", num_dirs, "folders")
        self.progress("info map:", num_required_files, "required files, ", num_required_dirs, "required folders")

        unrequired_files = self.info_map_table.get_unrequired_items(what="file")
        self.progress("unrequired files:")
        [self.progress("    ", f.path) for f in unrequired_files]
        unrequired_dirs = self.info_map_table.get_unrequired_items(what="dir")
        self.progress("unrequired dirs:")
        [self.progress("    ", d.path) for d in unrequired_dirs]
