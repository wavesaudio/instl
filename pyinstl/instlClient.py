#!/usr/bin/env python3

import os
import sys
import time
from collections import defaultdict, namedtuple, OrderedDict
import logging
log = logging.getLogger()

import utils
import aYaml
from .instlInstanceBase import InstlInstanceBase, check_version_compatibility
from configVar import config_vars
from pybatch import *


class InstlClient(InstlInstanceBase):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.total_self_progress: int = 1000
        self.read_defaults_file(super().__thisclass__.__name__)
        self.action_type_to_progress_message = None
        self.__all_iids_by_target_folder = defaultdict(utils.unique_list)
        self.__no_copy_iids_by_sync_folder = defaultdict(utils.unique_list)
        self.auxiliary_iids = utils.unique_list()
        self.main_install_targets = list()

    @property
    def all_iids_by_target_folder(self):
        return self.__all_iids_by_target_folder

    @property
    def no_copy_iids_by_sync_folder(self):
        return self.__no_copy_iids_by_sync_folder

    def sort_all_items_by_target_folder(self, consider_direct_sync=True):
        folder_to_iid_list = self.items_table.target_folders_to_items()
        for IID, folder, tag, direct_sync_indicator in folder_to_iid_list:
            direct_sync = self.get_direct_sync_status_from_indicator(direct_sync_indicator)
            if direct_sync and consider_direct_sync:
                sync_folder = os.path.join(folder)
                self.__no_copy_iids_by_sync_folder[sync_folder].append(IID)
            else:
                norm_folder = os.path.normpath(folder)
                self.__all_iids_by_target_folder[norm_folder].append(IID)

        for folder_iids_list in self.__all_iids_by_target_folder.values():
            folder_iids_list.sort()

        for folder_copy_iids_list in self.__no_copy_iids_by_sync_folder.values():
            folder_copy_iids_list.sort()

        folder_to_iid_list = self.items_table.source_folders_to_items_without_target_folders()
        for adjusted_source, IID, tag in folder_to_iid_list:
            relative_sync_folder = self.relative_sync_folder_for_source_table(adjusted_source, tag)
            sync_folder = os.path.join("$(LOCAL_REPO_SYNC_DIR)", relative_sync_folder)
            self.__no_copy_iids_by_sync_folder[sync_folder].append(IID)

    def do_command(self):
        # print("client_commands", fixed_command_name)
        active_oses: List[str] = list(config_vars["TARGET_OS_NAMES"])
        self.items_table.activate_specific_oses(*active_oses)

        main_input_file_path: str = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        self.read_yaml_file(main_input_file_path)
        verOK, errorMessage = check_version_compatibility()
        if not verOK:
            raise Exception(errorMessage)

        self.init_default_client_vars()

        active_oses: List[str] = list(config_vars["TARGET_OS_NAMES"])
        self.items_table.activate_specific_oses(*active_oses)

        self.items_table.resolve_inheritance()

        if self.should_check_for_binary_versions():
            self.progress("check versions of installed binaries")
            self.get_version_of_installed_binaries()
            self.items_table.add_require_version_from_binaries()
            self.items_table.add_require_guid_from_binaries()
        self.items_table.create_default_items(iids_to_ignore=self.auxiliary_iids)

        self.resolve_defined_paths()
        self.batch_accum.set_current_section('begin')
        self.progress("calculate install items")
        self.calculate_install_items()
        self.read_defines_for_active_iids()
        #self.platform_helper.num_items_for_progress_report = int(config_vars["LAST_PROGRESS"])
        #self.platform_helper.no_progress_messages = "NO_PROGRESS_MESSAGES" in config_vars

        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()
        self.command_output()
        self.items_table.config_var_list_to_db(config_vars)

    def command_output(self):
        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def init_default_client_vars(self):
        if "SYNC_BASE_URL" in config_vars:
            #raise ValueError("'SYNC_BASE_URL' was not defined")
            resolved_sync_base_url = config_vars["SYNC_BASE_URL"].str()
            url_main_item = utils.main_url_item(resolved_sync_base_url)
            config_vars["SYNC_BASE_URL_MAIN_ITEM"] = url_main_item
        # TARGET_OS_NAMES defaults to __CURRENT_OS_NAMES__, which is not what we want if syncing to
        # an OS which is not the current
        if config_vars["TARGET_OS"].str() != config_vars["__CURRENT_OS__"].str():
            target_os_names = list(config_vars[config_vars.resolve_str("$(TARGET_OS)_ALL_OS_NAMES")])
            config_vars["TARGET_OS_NAMES"] = target_os_names
            second_name: str = config_vars["TARGET_OS"].str()
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            config_vars["TARGET_OS_SECOND_NAME"] = second_name

        if "REPO_TYPE" in config_vars:  # some commands do not need to have REPO_TYPE
            self.read_defaults_file(str(config_vars["REPO_TYPE"]))

        if str(config_vars.get("REPO_TYPE", "URL")) == "P4":
            if "P4_SYNC_DIR" not in config_vars:
                if "SYNC_BASE_URL" in config_vars:
                    p4_sync_dir = utils.P4GetPathFromDepotPath(config_vars["SYNC_BASE_URL"].str())
                    config_vars["P4_SYNC_DIR", "from SYNC_BASE_URL"] = p4_sync_dir
        # AUXILIARY_IIDS are iids that are not real products such as UNINSTALL_AS_... iids
        self.auxiliary_iids.extend(list(config_vars["AUXILIARY_IIDS"]))

    def repr_for_yaml(self, what=None):
        """ Create representation of self suitable for printing as yaml.
            parameter 'what' is a list of identifiers to represent. If 'what'
            is None (the default) create representation of everything.
            InstlInstanceBase object is represented as two yaml documents:
            one for define (tagged !define), one for the index (tagged !index).
        """
        retVal = list()
        all_iids = self.items_table.get_all_iids()
        all_vars = sorted(config_vars.keys())
        if what is None:  # None is all
            what = all_vars + all_iids

        defines = OrderedDict()
        indexes = OrderedDict()
        unknowns = list()
        for identifier in what:
            if identifier in all_vars:
                defines.update({identifier: config_vars.repr_var_for_yaml(identifier)})
            elif identifier in all_iids:
                indexes.update({identifier: self.items_table.repr_item_for_yaml(identifier)})
            else:
                unknowns.append(aYaml.YamlDumpWrap(value="UNKNOWN VARIABLE",
                                                   comment=identifier + " is not in variable list"))
        if defines:
            retVal.append(aYaml.YamlDumpDocWrap(defines, '!define', "Definitions",
                                                explicit_start=True, sort_mappings=True))
        if indexes:
            retVal.append(
                aYaml.YamlDumpDocWrap(indexes, '!index', "Installation index",
                                      explicit_start=True, sort_mappings=True))
        if unknowns:
            retVal.append(
                aYaml.YamlDumpDocWrap(unknowns, '!unknowns', "Installation index",
                                      explicit_start=True, sort_mappings=True))

        return retVal

    def calculate_install_items(self):
        self.calculate_main_install_items()
        self.calculate_all_install_items()
        self.items_table.db.lock_table("index_item_t")
        self.items_table.db.lock_table("index_item_detail_t")

    def calculate_main_install_items(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_INSTALL_TARGETS" not in config_vars:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")

        self.main_install_targets.extend(list(config_vars["MAIN_INSTALL_TARGETS"]))
        main_iids, main_guids = utils.separate_guids_from_iids(self.main_install_targets)
        iids_from_main_guids, orphaned_main_guids = self.items_table.iids_from_guids(main_guids)
        main_iids.extend(iids_from_main_guids)
        main_iids, update_iids = self.resolve_special_build_in_iids(main_iids)

        main_iids, orphaned_main_iids = self.items_table.iids_from_iids(main_iids)
        update_iids, orphaned_update_iids = self.items_table.iids_from_iids(update_iids)

        config_vars["__MAIN_INSTALL_IIDS__"] = sorted(main_iids)
        config_vars["__MAIN_UPDATE_IIDS__"] = sorted(update_iids)
        config_vars["__ORPHAN_INSTALL_TARGETS__"] = sorted(orphaned_main_guids+orphaned_main_iids+orphaned_update_iids)

    # install_status = {"none": 0, "main": 1, "update": 2, "depend": 3}
    def calculate_all_install_items(self):
        # mark ignored iids, so all subsequent operations not act on these iids
        ignored_iids = list(config_vars.get("MAIN_IGNORED_TARGETS", []))
        self.items_table.set_ignore_iids(ignored_iids)

        # mark main install items
        main_iids = list(config_vars["__MAIN_INSTALL_IIDS__"])
        self.items_table.change_status_of_iids_to_another_status(
                self.items_table.install_status["none"],
                self.items_table.install_status["main"],
                main_iids)

        # find dependant of main install items
        main_iids_and_dependents = self.items_table.get_recursive_dependencies(look_for_status=self.items_table.install_status["main"])
        # mark dependants of main items, but only if they are not already in main items
        self.items_table.change_status_of_iids_to_another_status(
            self.items_table.install_status["none"],
            self.items_table.install_status["depend"],
            main_iids_and_dependents)

        # mark update install items, but only those not already marked as main or depend
        update_iids = list(config_vars["__MAIN_UPDATE_IIDS__"])
        self.items_table.change_status_of_iids_to_another_status(
                self.items_table.install_status["none"],
                self.items_table.install_status["update"],
                update_iids)

        # find dependants of update install items
        update_iids_and_dependents = self.items_table.get_recursive_dependencies(look_for_status=self.items_table.install_status["update"])
        # mark dependants of update items, but only if they are not already marked
        self.items_table.change_status_of_iids_to_another_status(
            self.items_table.install_status["none"],
            self.items_table.install_status["depend"],
            update_iids_and_dependents)

        all_items_to_install = self.items_table.get_iids_by_status(
            self.items_table.install_status["main"],
            self.items_table.install_status["depend"])

        config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"] = sorted(all_items_to_install)

        self.sort_all_items_by_target_folder(consider_direct_sync=True)
        self.calc_iid_to_name_and_version()

    def calc_iid_to_name_and_version(self):
        self.items_table.set_name_and_version_for_active_iids()

    def resolve_special_build_in_iids(self, iids: List[str]):
        iids_set = set(iids)
        update_iids_set = set()
        special_build_in_iids = set(list(config_vars["SPECIAL_BUILD_IN_IIDS"]))
        found_special_build_in_iids = special_build_in_iids & set(iids)
        if len(found_special_build_in_iids) > 0:
            iids_set -= special_build_in_iids
            # repair also does update so it takes precedent over update
            if "__REPAIR_INSTALLED_ITEMS__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__REPAIR_INSTALLED_ITEMS__", detail_name='depends')
                iids_set.update(more_iids)
            elif "__UPDATE_INSTALLED_ITEMS__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__UPDATE_INSTALLED_ITEMS__", detail_name='depends')
                update_iids_set = set(more_iids)-iids_set

            if "__ALL_GUIDS_IID__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__ALL_GUIDS_IID__", detail_name='depends')
                iids_set.update(more_iids)

            if "__ALL_ITEMS_IID__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__ALL_ITEMS_IID__", detail_name='depends')
                iids_set.update(more_iids)
        return list(iids_set), list(update_iids_set)

    def read_previous_requirements(self):
        require_file_path = config_vars["SITE_REQUIRE_FILE_PATH"].Path()
        self.read_yaml_file(require_file_path, ignore_if_not_exist=True)

    def accumulate_unique_actions_for_active_iids(self, action_type: str, limit_to_iids=None) -> PythonBatchCommandBase:
        """ accumulate action_type actions from iid_list, eliminating duplicates"""
        retVal = AnonymousAccum()
        iid_and_action = self.items_table.get_iids_and_details_for_active_iids(action_type, unique_values=True, limit_to_iids=limit_to_iids)
        iid_and_action.sort(key=lambda tup: tup[0])
        previous_iid = ""
        for IID, an_action in iid_and_action:
            if IID != previous_iid:  # avoid multiple progress messages for same iid
                actions_of_iid_count = 0
                name_and_version = self.name_and_version_for_iid(iid=IID)
                action_description = self.action_type_to_progress_message[action_type]
                previous_iid = IID
            actions = config_vars.resolve_str_to_list(an_action)
            for action in actions:
                actions_of_iid_count += 1
                message = f"{name_and_version} {action_description} {actions_of_iid_count}"
                retVal += EvalShellCommand(action, message)
        return retVal

    def create_require_file_instructions(self):
        # write the require file as it should look after copy is done
        new_require_file_path = config_vars["NEW_SITE_REQUIRE_FILE_PATH"].str()
        new_require_file_dir, new_require_file_name = os.path.split(new_require_file_path)
        os.makedirs(new_require_file_dir, exist_ok=True)
        self.batch_accum += CopyFileToFile("$(SITE_REQUIRE_FILE_PATH)", "$(OLD_SITE_REQUIRE_FILE_PATH)", ignore_if_not_exist=True, hard_links=False, copy_owner=True)
        require_yaml = self.repr_require_for_yaml()
        if require_yaml:
            self.write_require_file(new_require_file_path, require_yaml)
            # Copy the new require file over the old one, if copy fails the old file remains.
            self.batch_accum += CopyFileToFile("$(NEW_SITE_REQUIRE_FILE_PATH)", "$(SITE_REQUIRE_FILE_PATH)", hard_links=False, copy_owner=True)
        else:   # remove previous require.yaml since the new one does not contain anything
            self.batch_accum += RmFile("$(SITE_REQUIRE_FILE_PATH)")

    def create_sync_folder_manifest_command(self, manifest_file_name_prefix: str, back_ground: bool=False):
        """ create batch commands to write a manifest of the sync folder to a file """
        retVal = AnonymousAccum()
        which_folder_to_manifest = "$(COPY_SOURCES_ROOT_DIR)"
        output_file_name = manifest_file_name_prefix+"-sync-folder-manifest.txt"
        output_folder = None
        for param_to_extract_output_folder_from in ('ECHO_LOG_FILE', '__MAIN_INPUT_FILE__', '__MAIN_OUT_FILE__'):
            if config_vars.defined(param_to_extract_output_folder_from):
                log_file_path = str(config_vars[param_to_extract_output_folder_from])
                output_folder, _ = os.path.split(log_file_path)
                if os.path.isdir(output_folder):
                    break
                output_folder = None

        if output_folder is not None:
            output_file_path = Path(output_folder, output_file_name)
            retVal += Ls(which_folder_to_manifest, out_file=output_file_path)
        return retVal

    def repr_require_for_yaml(self):
        translate_detail_name = {'require_version': 'version', 'require_guid': 'guid', 'require_by': 'require_by'}
        retVal = defaultdict(dict)
        require_details = self.items_table.get_details_by_name_for_all_iids("require_%")
        for require_detail in require_details:
            item_dict = retVal[require_detail['owner_iid']]
            if require_detail['detail_name'] not in item_dict:
                item_dict[translate_detail_name[require_detail['detail_name']]] = utils.unique_list()
            item_dict[translate_detail_name[require_detail['detail_name']]].append(require_detail['detail_value'])
        for item in retVal.values():
            for sub_item in item.values():
                sub_item.sort()
        return retVal

    def should_check_for_binary_versions(self):
        """ checking versions inside binaries is heavy task.
            should_check_for_binary_versions returns if it's needed.
            True value will be returned if check was explicitly requested
            or if update of installed items was requested
        """
        explicitly_asked_for_binaries_check = 'CHECK_BINARIES_VERSIONS' in config_vars
        update_was_requested = "__UPDATE_INSTALLED_ITEMS__" in config_vars.get("MAIN_INSTALL_TARGETS", []).list()
        retVal = explicitly_asked_for_binaries_check or update_was_requested
        return retVal

    def get_version_of_installed_binaries(self):
        binaries_version_list = list()
        try:
            path_to_search = list(config_vars.get('CHECK_BINARIES_VERSION_FOLDERS', []))

            ignore_regexes_filter = utils.check_binaries_versions_filter_with_ignore_regexes()

            if "CHECK_BINARIES_VERSION_FOLDER_EXCLUDE_REGEX" in config_vars:
                ignore_folder_regex_list = list(config_vars["CHECK_BINARIES_VERSION_FOLDER_EXCLUDE_REGEX"])
                ignore_regexes_filter.set_folder_ignore_regexes(ignore_folder_regex_list)

            if "CHECK_BINARIES_VERSION_FILE_EXCLUDE_REGEX" in config_vars:
                ignore_file_regex_list = list(config_vars["CHECK_BINARIES_VERSION_FILE_EXCLUDE_REGEX"])
                ignore_regexes_filter.set_file_ignore_regexes(ignore_file_regex_list)

            for a_path in path_to_search:
                current_os = config_vars["__CURRENT_OS__"].str()
                binaries_version_from_folder = utils.check_binaries_versions_in_folder(current_os, a_path, ignore_regexes_filter)
                binaries_version_list.extend(binaries_version_from_folder)

            self.items_table.insert_binary_versions(binaries_version_list)

        except Exception as ex:
            log.warning(f"""exception while in check_binaries_versions {ex}""")
        return binaries_version_list

    def get_direct_sync_status_from_indicator(self, direct_sync_indicator):
        retVal = False
        if direct_sync_indicator is not None:
            try:
                retVal = utils.str_to_bool_int(config_vars.resolve_str(direct_sync_indicator))
            except:
                pass
        return retVal

    def set_sync_locations_for_active_items(self):
        # get_sync_folders_and_sources_for_active_iids returns: [(iid, direct_sync_indicator, source, source_tag, install_folder),...]
        # direct_sync_indicator will be None unless the items has "direct_sync" section in index.yaml
        # source is the relative path as it appears in index.yaml
        # adjusted source is the source prefixed with $(SOURCE_PREFIX) -- it needed
        # source_tag is one of  '!dir', '!dir_cont', '!file'
        # install_folder is where the sources should be copied to OR, in case of direct syn where they should be synced to
        # install_folder will be None for those items that require only sync not copy (such as Icons)
        #
        # for each file item in the source this function will set the full path where to download the file: item.download_path
        # and the top folder common to all items in a single source: item.download_root
        sync_and_source = self.items_table.get_sync_folders_and_sources_for_active_iids()

        items_to_update = list()
        for iid, direct_sync_indicator, source, source_tag, install_folder in sync_and_source:
            direct_sync = self.get_direct_sync_status_from_indicator(direct_sync_indicator)
            resolved_source_parts = source.split("/")
            if install_folder:
                resolved_install_folder = config_vars.resolve_str(install_folder)
            else:
                resolved_install_folder = install_folder
            local_repo_sync_dir = os.fspath(config_vars["LOCAL_REPO_SYNC_DIR"])

            if source_tag in ('!dir', '!dir_cont'):
                if direct_sync:
                    # for direct-sync source, if one of the sources is Info.xml and it exists on disk AND source & file
                    # have the same checksum, then no sync is needed at all. All the above is not relevant in repair mode.
                    need_to_sync = True
                    if "__REPAIR_INSTALLED_ITEMS__" not in self.main_install_targets:
                        info_xml_item = self.info_map_table.get_file_item("/".join((source, "Info.xml")))
                        if info_xml_item:
                            info_xml_of_target = config_vars.resolve_str("/".join((resolved_install_folder, resolved_source_parts[-1], "Info.xml")))
                            need_to_sync = not utils.check_file_checksum(info_xml_of_target, info_xml_item.checksum)
                    if need_to_sync:
                        item_paths = self.info_map_table.get_file_paths_of_dir(dir_path=source)
                        if source_tag == '!dir':
                            source_parent = "/".join(resolved_source_parts[:-1])
                            for item in item_paths:
                                items_to_update.append({"_id": item['_id'],
                                                        "download_path": config_vars.resolve_str("/".join((resolved_install_folder, item['path'][len(source_parent)+1:]))),
                                                        "download_root": config_vars.resolve_str("/".join((resolved_install_folder, resolved_source_parts[-1])))})
                        else:  # !dir_cont
                            source_parent = source
                            for item in item_paths:
                                items_to_update.append({"_id": item['_id'],
                                                        "download_path": config_vars.resolve_str("/".join((resolved_install_folder, item['path'][len(source_parent)+1:]))),
                                                        "download_root": resolved_install_folder})
                    else:
                        num_ignored_files = self.info_map_table.ignore_file_paths_of_dir(dir_path=source)
                        if num_ignored_files < 1:
                            num_ignored_files = ""  # sqlite curs.rowcount does not always returns the number of effected rows
                        self.progress(f"avoid download {num_ignored_files} files of {iid}, Info.xml has not changed")

                else:
                    item_paths = self.info_map_table.get_file_paths_of_dir(dir_path=source)
                    for item in item_paths:
                        items_to_update.append({"_id": item['_id'],
                                                "download_path": config_vars.resolve_str("/".join((local_repo_sync_dir, item['path']))),
                                                "download_root": None})
            elif source_tag == '!file':
                # if the file was wtarred and split it would have multiple items
                items_for_file = self.info_map_table.get_required_paths_for_file(source)
                if direct_sync:
                    for item in items_for_file:
                        items_to_update.append({"_id": item['_id'],
                                                "download_path": config_vars.resolve_str("/".join((resolved_install_folder, item['leaf']))),
                                                "download_root": config_vars.resolve_str(item.download_path)})
                else:
                    for item in items_for_file:
                        items_to_update.append({"_id": item['_id'],
                                                "download_path": config_vars.resolve_str("/".join((local_repo_sync_dir, item['path']))),
                                                "download_root": None})  # no need to set item.download_root here - it will not be used

        self.info_map_table.update_downloads(items_to_update)

    def create_remove_previous_sources_instructions_for_target_folder(self, target_folder_path):
        retVal = AnonymousAccum()
        target_folder_path_resolved = config_vars.resolve_str(target_folder_path)
        if os.path.isdir(target_folder_path_resolved):  # no need to remove previous sources if folder does not exist
            iids_in_folder = self.all_iids_by_target_folder[target_folder_path]
            previous_sources = self.items_table.get_details_and_tag_for_active_iids("previous_sources", unique_values=True, limit_to_iids=iids_in_folder)

            if len(previous_sources) > 0:
                retVal += Cd(target_folder_path)
                # todo: conditional CD - if fails to not do other instructions
                retVal += Progress(f"remove previous versions {target_folder_path} ...")

                for previous_source in previous_sources:
                    retVal += self.create_remove_previous_sources_instructions_for_source(target_folder_path, previous_source)
        return retVal

    def create_remove_previous_sources_instructions_for_source(self, folder, source):
        """ source is a tuple (source_folder, tag), where tag is either !file, !dir_cont or !dir """

        retVal = AnonymousAccum()
        source_path, source_type = source[0], source[1]
        to_remove_path = os.path.normpath(os.path.join(folder, source_path))

        if source_type == '!dir':  # remove whole folder
            retVal += RmDir(to_remove_path)
        elif source_type == '!file':  # remove single file
            retVal += RmFile(to_remove_path)
        elif source_type == '!dir_cont':
            raise Exception("previous_sources cannot have tag !dir_cont")
        return retVal

    def name_from_iid(self, iid):
        """ for those cases when no name was given to the iid"""
        retVal = iid.replace("_IID", "")
        retVal = retVal.replace("_", " ")
        return retVal

    def name_and_version_for_iid(self, iid):
        name_and_version_list = self.items_table.get_resolved_details_value_for_active_iid(iid=iid, detail_name="name_and_version")
        if name_and_version_list:
            retVal = name_and_version_list[0]
        else:
            name = self.items_table.get_resolved_details_value_for_active_iid(iid=iid, detail_name="name")
            if name:
                retVal = name[0]
            else:
                retVal = self.name_from_iid(iid)
        return retVal

    def name_for_iid(self, iid):
        name_list = self.items_table.get_resolved_details_value_for_active_iid(iid=iid, detail_name="name")
        retVal = next(iter(name_list), iid)  # trick to get the first element in a list or default if list is empty
        return retVal

    def read_defines_for_active_iids(self):
        """ read the defines specific for each active iid
        """
        if self.items_table.defines_for_iids:
            config_vars.push_scope()
            active_iids = self.items_table.get_active_iids()
            for iid, defines_for_iid in self.items_table.defines_for_iids.items():
                if iid in active_iids:
                    self.read_yaml_from_node(defines_for_iid)


def InstlClientFactory(initial_vars, command):
    retVal = None
    if command == "sync":
        from .instlClientSync import InstlClientSync
        retVal = InstlClientSync(initial_vars)
    elif command == "copy":
        from .instlClientCopy import InstlClientCopy
        retVal = InstlClientCopy(initial_vars)
    elif command == "remove":
        from .instlClientRemove import InstlClientRemove
        retVal = InstlClientRemove(initial_vars)
    elif command == "uninstall":
        from .instlClientUninstall import InstlClientUninstall
        retVal = InstlClientUninstall(initial_vars)
    elif command in ('report-installed', 'report-update', 'report-versions', 'report-gal'):
        from .instlClientReport import InstlClientReport
        retVal = InstlClientReport(initial_vars)
    elif command == "synccopy":
        from .instlClientSync import InstlClientSync
        from .instlClientCopy import InstlClientCopy

        class InstlClientSyncCopy(InstlClientSync, InstlClientCopy):
            def __init__(self, sc_initial_vars=None) -> None:
                super().__init__(sc_initial_vars)

            def do_synccopy(self):
                self.do_sync()
                self.do_copy()
                self.batch_accum += Progress("Done synccopy")
        retVal = InstlClientSyncCopy(initial_vars)
    return retVal
