#!/usr/bin/env python3

import os
import time
from collections import defaultdict, namedtuple


import utils
from .installItem import InstallItem, guid_list
import aYaml
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack
from svnTree import SVNTable
from .indexItemTable import IndexItemsTable

NameAndVersion = namedtuple('name_ver', ['name', 'version', 'name_and_version'])
def NameAndVersionFromQueryResults(q_results_tuple):
    name = q_results_tuple[1] or q_results_tuple[0]
    n_and_v = q_results_tuple[1]
    if q_results_tuple[2]:
        n_and_v += " v" + q_results_tuple[2]

    retVal = NameAndVersion(name=name, version=q_results_tuple[2], name_and_version=n_and_v)
    return retVal


class InstlClient(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.info_map_table = SVNTable()
        self.items_table = IndexItemsTable()
        var_stack.add_const_config_variable("__DATABASE_URL__", "", self.items_table.get_db_url())
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.action_type_to_progress_message = None
        self.__all_iids_by_target_folder = defaultdict(utils.unique_list)
        self.__no_copy_iids_by_sync_folder = defaultdict(utils.unique_list)
        self.auxiliary_iids = utils.unique_list()

    @property
    def all_iids_by_target_folder(self):
        return self.__all_iids_by_target_folder

    @property
    def no_copy_iids_by_sync_folder(self):
        return self.__no_copy_iids_by_sync_folder

    def sort_all_items_by_target_folder(self):
        folder_to_iid_list = self.items_table.target_folders_to_items()
        for IID, folder, tag, direct_sync_indicator in folder_to_iid_list:
            direct_sync = self.get_direct_sync_status_from_indicator(direct_sync_indicator)
            if not direct_sync:
                norm_folder = os.path.normpath(folder)
                self.__all_iids_by_target_folder[norm_folder].append(IID)
            else:
                sync_folder = os.path.join(folder)
                self.__no_copy_iids_by_sync_folder[sync_folder].append(IID)

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
        active_oses = var_stack.ResolveVarToList("TARGET_OS_NAMES")
        self.items_table.begin_get_for_specific_oses(*active_oses)

        main_input_file_path = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        self.read_yaml_file(main_input_file_path)
        self.items_table.commit_changes()

        self.init_default_client_vars()
        active_oses = var_stack.ResolveVarToList("TARGET_OS_NAMES")
        self.items_table.begin_get_for_specific_oses(*active_oses)

        self.items_table.resolve_inheritance()
        if self.should_check_for_binary_versions():
            self.get_version_of_installed_binaries()
            self.items_table.add_require_version_from_binaries()
            self.items_table.add_require_guid_from_binaries()
        self.items_table.create_default_items(iids_to_ignore=self.auxiliary_iids)

        self.resolve_defined_paths()
        self.batch_accum.set_current_section('begin')
        self.batch_accum += self.platform_helper.setup_echo()
        self.platform_helper.init_platform_tools()
        # after reading variable COPY_TOOL from yaml, we might need to re-init the copy tool.
        self.platform_helper.init_copy_tool()
        self.resolve_index_inheritance()
        self.add_default_items()
        self.calculate_install_items()
        self.platform_helper.num_items_for_progress_report = int(var_stack.ResolveVarToStr("LAST_PROGRESS"))
        self.platform_helper.no_progress_messages = "NO_PROGRESS_MESSAGES" in var_stack

        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()
        self.create_instl_history_file()
        self.command_output()
        self.items_table.config_var_list_to_db(var_stack)
        self.items_table.commit_changes()

    def command_output(self):
        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def create_instl_history_file(self):
        var_stack.set_var("__BATCH_CREATE_TIME__").append(time.strftime("%Y/%m/%d %H:%M:%S"))
        yaml_of_defines = aYaml.YamlDumpDocWrap(var_stack, '!define', "Definitions",
                                                explicit_start=True, sort_mappings=True)

        # write the history file, but only if variable LOCAL_REPO_BOOKKEEPING_DIR is defined
        # and the folder actually exists.
        instl_temp_history_file_path = var_stack.ResolveVarToStr("INSTL_HISTORY_TEMP_PATH")
        instl_temp_history_folder, instl_temp_history_file_name = os.path.split(instl_temp_history_file_path)
        if os.path.isdir(instl_temp_history_folder):
            with open(instl_temp_history_file_path, "w", encoding='utf-8') as wfd:
                utils.make_open_file_read_write_for_all(wfd)
                aYaml.writeAsYaml(yaml_of_defines, wfd)
            self.batch_accum += self.platform_helper.append_file_to_file("$(INSTL_HISTORY_TEMP_PATH)",
                                                                         "$(INSTL_HISTORY_PATH)")

    def read_repo_type_defaults(self):
        if "REPO_TYPE" in var_stack:  # some commands do not need to have REPO_TYPE
            repo_type_defaults_file_path = os.path.join(var_stack.ResolveVarToStr("__INSTL_DATA_FOLDER__"), "defaults",
                                                    var_stack.ResolveStrToStr("$(REPO_TYPE).yaml"))
            if os.path.isfile(repo_type_defaults_file_path):
                self.read_yaml_file(repo_type_defaults_file_path)

    def init_default_client_vars(self):
        if "SYNC_BASE_URL" in var_stack:
            #raise ValueError("'SYNC_BASE_URL' was not defined")
            resolved_sync_base_url = var_stack.ResolveVarToStr("SYNC_BASE_URL")
            url_main_item = utils.main_url_item(resolved_sync_base_url)
            var_stack.set_var("SYNC_BASE_URL_MAIN_ITEM", description="from init_default_client_vars").append(url_main_item)
        # TARGET_OS_NAMES defaults to __CURRENT_OS_NAMES__, which is not what we want if syncing to
        # an OS which is not the current
        if var_stack.ResolveVarToStr("TARGET_OS") != var_stack.ResolveVarToStr("__CURRENT_OS__"):
            target_os_names = var_stack.ResolveVarToList(var_stack.ResolveStrToStr("$(TARGET_OS)_ALL_OS_NAMES"))
            var_stack.set_var("TARGET_OS_NAMES").extend(target_os_names)
            second_name = var_stack.ResolveVarToStr("TARGET_OS")
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            var_stack.set_var("TARGET_OS_SECOND_NAME").append(second_name)

        self.read_repo_type_defaults()
        if var_stack.ResolveVarToStr("REPO_TYPE", default="URL") == "P4":
            if "P4_SYNC_DIR" not in var_stack:
                if "SYNC_BASE_URL" in var_stack:
                    p4_sync_dir = utils.P4GetPathFromDepotPath(var_stack.ResolveVarToStr("SYNC_BASE_URL"))
                    var_stack.set_var("P4_SYNC_DIR", "from SYNC_BASE_URL").append(p4_sync_dir)
        self.auxiliary_iids.extend(var_stack.ResolveVarToList("AUXILIARY_IIDS", default=list()))

    def repr_for_yaml(self, what=None):
        """ Create representation of self suitable for printing as yaml.
            parameter 'what' is a list of identifiers to represent. If 'what'
            is None (the default) create representation of everything.
            InstlInstanceBase object is represented as two yaml documents:
            one for define (tagged !define), one for the index (tagged !index).
        """
        retVal = list()
        if what is None:  # None is all
            retVal.append(aYaml.YamlDumpDocWrap(var_stack, '!define', "Definitions",
                                                explicit_start=True, sort_mappings=True))
            retVal.append(aYaml.YamlDumpDocWrap(self.install_definitions_index,
                                                '!index', "Installation index",
                                                explicit_start=True, sort_mappings=True))
        else:
            defines = list()
            indexes = list()
            unknowns = list()
            for identifier in what:
                if identifier in var_stack:
                    defines.append(var_stack.repr_for_yaml(identifier))
                elif identifier in self.install_definitions_index:
                    indexes.append({identifier: self.install_definitions_index[identifier].repr_for_yaml()})
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

    def add_default_items(self):
        all_items_item = InstallItem("__ALL_ITEMS_IID__")
        all_items_item.name = "All IIDs"
        all_items_item.add_depends(*self.install_definitions_index.keys())
        self.install_definitions_index["__ALL_ITEMS_IID__"] = all_items_item

        all_guids_item = InstallItem("__ALL_GUIDS_IID__")
        all_guids_item.name = "All GUIDs"
        all_guids_item.add_depends(*guid_list(self.install_definitions_index))
        self.install_definitions_index["__ALL_GUIDS_IID__"] = all_guids_item

    def calculate_install_items(self):
        self.calculate_main_install_items()
        self.calculate_all_install_items()

    def calculate_main_install_items(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_INSTALL_TARGETS" not in var_stack:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        # legacy, to be removed when InstallItem is no longer in use
        active_oses = var_stack.ResolveVarToList("TARGET_OS_NAMES")
        for os_name in active_oses:
            InstallItem.begin_get_for_specific_os(os_name)

        main_install_targets = var_stack.ResolveVarToList("MAIN_INSTALL_TARGETS")
        main_iids, main_guids = utils.separate_guids_from_iids(main_install_targets)
        iids_from_main_guids, orphaned_main_guids = self.items_table.iids_from_guids(main_guids)
        main_iids.extend(iids_from_main_guids)
        main_iids, update_iids = self.resolve_special_build_in_iids(main_iids)

        main_iids, orphaned_main_iids = self.items_table.iids_from_iids(main_iids)
        update_iids, orphaned_update_iids = self.items_table.iids_from_iids(update_iids)

        var_stack.set_var("__MAIN_INSTALL_IIDS__").extend(sorted(main_iids))
        var_stack.set_var("__MAIN_UPDATE_IIDS__").extend(sorted(update_iids))
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(sorted(orphaned_main_guids+orphaned_main_iids+orphaned_update_iids))

    # install_status = {"none": 0, "main": 1, "update": 2, "depend": 3}
    def calculate_all_install_items(self):
        # marked ignored iids, all subsequent operations not act on these iids
        if "MAIN_IGNORED_TARGETS" in var_stack:
            ignored_iids = var_stack.ResolveVarToList("MAIN_IGNORED_TARGETS")
            self.items_table.set_ignore_iids(ignored_iids)

        # mark main install items
        main_iids = var_stack.ResolveVarToList("__MAIN_INSTALL_IIDS__")
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
        update_iids = var_stack.ResolveVarToList("__MAIN_UPDATE_IIDS__")
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
        self.items_table.commit_changes()

        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(sorted(all_items_to_install))

        self.sort_all_items_by_target_folder()
        self.calc_iid_to_name_and_version()

    def calc_iid_to_name_and_version(self):
        iids_and_names_from_db = self.items_table.name_and_version_report_for_active_iids()
        for from_db in iids_and_names_from_db:
            self.iid_to_name_and_version[from_db[0]] = NameAndVersionFromQueryResults(from_db)

    def resolve_special_build_in_iids(self, iids):
        iids_set = set(iids)
        update_iids_set = set()
        special_build_in_iids = set(var_stack.ResolveVarToList("SPECIAL_BUILD_IN_IIDS"))
        found_special_build_in_iids = special_build_in_iids & set(iids)
        if len(found_special_build_in_iids) > 0:
            iids_set -= special_build_in_iids
            # repair also does update so it takes precedent over update
            if "__REPAIR_INSTALLED_ITEMS__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value(iid="__REPAIR_INSTALLED_ITEMS__", detail_name='depends')
                iids_set.update(more_iids)
            elif "__UPDATE_INSTALLED_ITEMS__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value(iid="__UPDATE_INSTALLED_ITEMS__", detail_name='depends')
                update_iids_set = set(more_iids)-iids_set

            if "__ALL_GUIDS_IID__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value(iid="__ALL_GUIDS_IID__", detail_name='depends')
                iids_set.update(more_iids)

            if "__ALL_ITEMS_IID__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value(iid="__ALL_ITEMS_IID__", detail_name='depends')
                iids_set.update(more_iids)
        return list(iids_set), list(update_iids_set)

    def read_previous_requirements(self):
        require_file_path = var_stack.ResolveVarToStr("SITE_REQUIRE_FILE_PATH")
        if os.path.isfile(require_file_path):
            self.read_yaml_file(require_file_path)

    def accumulate_unique_actions(self, action_type, iid_list):
        """ accumulate action_type actions from iid_list, eliminating duplicates"""
        unique_actions = utils.unique_list()  # unique_list will eliminate identical actions while keeping the order
        for IID in sorted(iid_list):
            with self.install_definitions_index[IID].push_var_stack_scope() as installi:
                action_var_name = "iid_action_list_" + action_type
                item_actions = var_stack.ResolveVarToList(action_var_name, default=[])
                num_unique_actions = 0
                for an_action in item_actions:
                    len_before = len(unique_actions)
                    unique_actions.append(an_action)
                    len_after = len(unique_actions)
                    if len_before < len_after:  # add progress only for the first same action
                        num_unique_actions += 1
                        action_description = self.action_type_to_progress_message[action_type]
                        if num_unique_actions > 1:
                            action_description = " ".join((action_description, str(num_unique_actions)))
                        unique_actions.append(
                            self.platform_helper.progress("{installi.name} {action_description}".format(**locals())))
        self.batch_accum += unique_actions

    def accumulate_unique_actions_for_active_iids(self, action_type, limit_to_iids=None):
        """ accumulate action_type actions from iid_list, eliminating duplicates"""
        retVal = 0  # return number of real actions added (i.e. excluding progress message)
        iid_and_action = self.items_table.get_iids_and_details_for_active_iids(action_type, unique_values=True, limit_to_iids=limit_to_iids)
        iid_and_action.sort(key=lambda tup: tup[0])
        for IID, an_action in iid_and_action:
            self.batch_accum += an_action
            action_description = self.action_type_to_progress_message[action_type]
            self.batch_accum += self.platform_helper.progress("{0} {1}".format(self.iid_to_name_and_version[IID].name, action_description))
            retVal += 1
        return retVal

    def create_require_file_instructions(self):
        # write the require file as it should look after copy is done
        new_require_file_path = var_stack.ResolveVarToStr("NEW_SITE_REQUIRE_FILE_PATH")
        new_require_file_dir, new_require_file_name = os.path.split(new_require_file_path)
        os.makedirs(new_require_file_dir, exist_ok=True)
        self.write_require_file(new_require_file_path, self.repr_require_for_yaml())
        # Copy the new require file over the old one, if copy fails the old file remains.
        self.batch_accum += self.platform_helper.copy_file_to_file("$(NEW_SITE_REQUIRE_FILE_PATH)",
                                                                   "$(SITE_REQUIRE_FILE_PATH)")

    def create_folder_manifest_command(self, which_folder_to_manifest, output_folder, output_file_name):
        """ create batch commands to write a manifest of specific folder to a file """
        self.batch_accum += self.platform_helper.mkdir(output_folder)
        ls_output_file = os.path.join(output_folder, output_file_name)
        create_folder_ls_command_parts = [self.platform_helper.run_instl(), "ls",
                                      "--in",  utils.quoteme_double(which_folder_to_manifest),
                                      "--out", utils.quoteme_double(ls_output_file)]
        if var_stack.ResolveVarToStr("__CURRENT_OS__") == "Mac":
            create_folder_ls_command_parts.extend(("||", "true"))
        self.batch_accum += " ".join(create_folder_ls_command_parts)

    def create_sync_folder_manifest_command(self, manifest_file_name_prefix):
        """ create batch commands to write a manifest of the sync folder to a file """
        which_folder_to_manifest = "$(COPY_SOURCES_ROOT_DIR)"
        output_file_name = manifest_file_name_prefix+"-sync-folder-manifest.txt"
        for param_to_extract_output_folder_from in ('ECHO_LOG_FILE', '__MAIN_INPUT_FILE__', '__MAIN_OUT_FILE__'):
            if var_stack.defined(param_to_extract_output_folder_from):
                log_file_path = var_stack.ResolveVarToStr(param_to_extract_output_folder_from)
                output_folder, _ = os.path.split(log_file_path)
                if os.path.isdir(output_folder):
                    break
                output_folder = None
        if output_folder is not None:
            self.create_folder_manifest_command(which_folder_to_manifest, output_folder, output_file_name)

    def repr_require_for_yaml(self):
        translate_detail_name = {'require_version': 'version', 'require_guid': 'guid', 'require_by': 'require_by'}
        retVal = defaultdict(dict)
        require_details = self.items_table.get_details_by_name_for_all_iids("require_%")
        for require_detail in require_details:
            item_dict = retVal[require_detail.owner_iid]
            if require_detail.detail_name not in item_dict:
                item_dict[translate_detail_name[require_detail.detail_name]] = utils.unique_list()
            item_dict[translate_detail_name[require_detail.detail_name]].append(require_detail.detail_value)
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
        explicitly_asked_for_binaries_check = 'CHECK_BINARIES_VERSIONS' in var_stack
        update_was_requested = "__UPDATE_INSTALLED_ITEMS__" in var_stack.ResolveVarToList("MAIN_INSTALL_TARGETS", [])
        retVal = explicitly_asked_for_binaries_check or update_was_requested
        return retVal

    def get_version_of_installed_binaries(self):
        binaries_version_list = list()
        try:
            path_to_search = var_stack.ResolveVarToList('CHECK_BINARIES_VERSION_FOLDERS', default=[])

            compiled_ignore_folder_regex = None
            if "CHECK_BINARIES_VERSION_FOLDER_EXCLUDE_REGEX" in var_stack:
                ignore_folder_regex_list = var_stack.ResolveVarToList("CHECK_BINARIES_VERSION_FOLDER_EXCLUDE_REGEX")
                compiled_ignore_folder_regex = utils.compile_regex_list_ORed(ignore_folder_regex_list)

            compiled_ignore_file_regex = None
            if "CHECK_BINARIES_VERSION_FILE_EXCLUDE_REGEX" in var_stack:
                ignore_file_regex_list = var_stack.ResolveVarToList("CHECK_BINARIES_VERSION_FILE_EXCLUDE_REGEX")
                compiled_ignore_file_regex = utils.compile_regex_list_ORed(ignore_file_regex_list)

            for a_path in path_to_search:
                current_os = var_stack.ResolveVarToStr("__CURRENT_OS__")
                binaries_version_from_folder = utils.check_binaries_versions_in_folder(current_os, a_path, compiled_ignore_folder_regex, compiled_ignore_file_regex)
                binaries_version_list.extend(binaries_version_from_folder)

            self.items_table.insert_binary_versions(binaries_version_list)

        except Exception as ex:
            print("not doing check_binaries_versions", ex)
        return binaries_version_list

    def get_direct_sync_status_from_indicator(self, direct_sync_indicator):
        retVal = False
        if direct_sync_indicator is not None:
            try:
                retVal = utils.str_to_bool_int(var_stack.ResolveStrToStr(direct_sync_indicator))
            except:
                pass
        return retVal

    def set_sync_locations_for_active_items(self):
        # get_sync_folders_and_sources_for_active_iids returns: [(iid, direct_sync_indicator, source, source_tag, install_folder),...]
        # direct_sync_indicator will be None unless the items has "direct_sync" section in index.yaml
        # install_folder will be None for those items that require only sync not copy (such as Icons)
        sync_and_source = self.items_table.get_sync_folders_and_sources_for_active_iids()
        for iid, direct_sync_indicator, source, adjusted_source, source_tag, install_folder in sync_and_source:
            direct_sync = self.get_direct_sync_status_from_indicator(direct_sync_indicator)
            resolved_adjusted_source = var_stack.ResolveStrToStr(adjusted_source)
            resolved_adjusted_source_parts = resolved_adjusted_source.split("/")

            if source_tag in ('!dir', '!dir_cont'):
                items = self.info_map_table.get_file_items_of_dir(dir_path=resolved_adjusted_source)
                if direct_sync:
                    if  source_tag == '!dir':
                        source_parent = "/".join(resolved_adjusted_source_parts[:-1])
                    else:  # !dir_cont
                        source_parent = resolved_adjusted_source
                    assert install_folder is not None
                    for item in items:
                        item.download_path = var_stack.ResolveStrToStr("/".join((install_folder, item.path[len(source_parent)+1:])))
                        item.download_root  = var_stack.ResolveStrToStr("/".join((install_folder, resolved_adjusted_source_parts[-1])))
                else:
                    for item in items:
                        item.download_path = var_stack.ResolveStrToStr("/".join(("$(LOCAL_REPO_SYNC_DIR)", item.path)))
            elif source_tag == '!file':
                items_for_file = self.info_map_table.get_required_for_file(resolved_adjusted_source)
                if direct_sync:
                    assert install_folder is not None
                    for item in items_for_file:
                        item.download_path = var_stack.ResolveStrToStr("/".join((install_folder, item.path[len(source_parent)+1:])))
                        item.download_root = var_stack.ResolveStrToStr(item.download_path)
                else:
                    for item in items_for_file:
                        item.download_path = var_stack.ResolveStrToStr("/".join(("$(LOCAL_REPO_SYNC_DIR)", item.path)))
        self.items_table.commit_changes()

    def create_remove_previous_sources_instructions_for_target_folder(self, target_folder_path):
        iids_in_folder = self.all_iids_by_target_folder[target_folder_path]
        assert list(self.all_iids_by_target_folder[target_folder_path]) == list(iids_in_folder)
        previous_sources = self.items_table.get_details_and_tag_for_active_iids("previous_sources", unique_values=True, limit_to_iids=iids_in_folder)

        if len(previous_sources) > 0:
            self.batch_accum += self.platform_helper.new_line()
            self.batch_accum += self.platform_helper.remark("- Begin folder {0}".format(target_folder_path))
            self.batch_accum += self.platform_helper.cd(target_folder_path)
            self.batch_accum += self.platform_helper.progress("remove previous versions {0} ...".format(target_folder_path))

            for previous_source in previous_sources:
                self.create_remove_previous_sources_instructions_for_source(target_folder_path, previous_source)

            self.batch_accum += self.platform_helper.progress("remove previous versions {0} done".format(target_folder_path))
            self.batch_accum += self.platform_helper.remark("- End folder {0}".format(target_folder_path))

    def create_remove_previous_sources_instructions_for_source(self, folder, source):
        """ source is a tuple (source_folder, tag), where tag is either !file, !dir_cont or !dir """

        source_path, source_type = source[0], source[1]
        to_remove_path = os.path.normpath(os.path.join(folder, source_path))

        if source_type == '!dir':  # remove whole folder
            remove_action = self.platform_helper.rmdir(to_remove_path, recursive=True, check_exist=True)
            self.batch_accum += remove_action
        elif source_type == '!file':  # remove single file
            remove_action = self.platform_helper.rmfile(to_remove_path, check_exist=True)
            self.batch_accum += remove_action
        elif source_type == '!dir_cont':
            raise Exception("previous_sources cannot have tag !dir_cont")


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
            def __init__(self, sc_initial_vars=None):
                super().__init__(sc_initial_vars)

            def do_synccopy(self):
                self.do_sync()
                self.do_copy()
                self.batch_accum += self.platform_helper.progress("Done synccopy")
        retVal = InstlClientSyncCopy(initial_vars)
    return retVal
