#!/usr/bin/env python3

import os
import time
from collections import defaultdict

import utils
from .installItem import InstallItem, guid_list
import aYaml
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack


class InstlClient(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.action_type_to_progress_message = None
        self.__all_items_by_target_folder = defaultdict(utils.unique_list)
        self.__no_copy_items_by_sync_folder = defaultdict(utils.unique_list)

    @property
    def all_items_by_target_folder(self):
        return self.__all_items_by_target_folder

    @property
    def no_copy_items_by_sync_folder(self):
        return self.__no_copy_items_by_sync_folder

    def sort_all_items_by_target_folder(self):
        folder_to_iid_list = self.items_table.target_folders_to_items()
        for folder, IID in folder_to_iid_list:
            norm_folder = os.path.normpath(folder)
            self.__all_items_by_target_folder[norm_folder].append(IID)

        folder_to_iid_list = self.items_table.source_folders_to_items_without_target_folders()
        for folder, IID, tag in folder_to_iid_list:
            source = folder # var_stack.ResolveVarToList(folder)
            relative_sync_folder = self.relative_sync_folder_for_source_table(source, tag)
            sync_folder = os.path.join("$(LOCAL_REPO_SYNC_DIR)", relative_sync_folder)
            self.__no_copy_items_by_sync_folder[sync_folder].append(IID)

    def do_command(self):
        # print("client_commands", fixed_command_name)
        active_oses = var_stack.ResolveVarToList("TARGET_OS_NAMES")
        self.items_table.begin_get_for_specific_oses(*active_oses)

        main_input_file_path = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        self.read_yaml_file(main_input_file_path)

        self.items_table.resolve_inheritance()
        self.items_table.create_default_items()

        self.init_default_client_vars()
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

        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()
        self.create_instl_history_file()
        self.command_output()
        self.items_table.commit_changes()

    def command_output(self):
        self.create_variables_assignment()
        self.write_batch_file()
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
        main_iids = self.resolve_special_build_in_iids(main_iids)

        main_iids, orphaned_main_iids = self.items_table.iids_from_iids(main_iids)

        var_stack.set_var("__MAIN_INSTALL_IIDS__").extend(sorted(main_iids))
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(sorted(orphaned_main_guids+orphaned_main_iids))

    def calculate_all_install_items(self):
        self.items_table.change_status_of_iids(0, 1, var_stack.ResolveVarToList("__MAIN_INSTALL_IIDS__"))
        all_items_from_table = self.items_table.get_recursive_dependencies(look_for_status=1)
        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(sorted(all_items_from_table))
        self.items_table.change_status_of_iids(0, 2, all_items_from_table)
        self.sort_all_items_by_target_folder()

    def resolve_special_build_in_iids(self, iids):
        iids_set = set(iids)
        special_build_in_iids = set(var_stack.ResolveVarToList("SPECIAL_BUILD_IN_IIDS"))
        found_special_build_in_iids = special_build_in_iids & set(iids)
        if len(found_special_build_in_iids) > 0:
            iids_set -= special_build_in_iids
            if "__UPDATE_INSTALLED_ITEMS__" in found_special_build_in_iids\
                and "__REPAIR_INSTALLED_ITEMS__" in found_special_build_in_iids:
                found_special_build_in_iids.remove("__UPDATE_INSTALLED_ITEMS__") # repair takes precedent over update
            for special_iid in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value(iid=special_iid, detail_name='depends')
                iids_set.update(more_iids)
        return list(iids_set)

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
                item_dict[translate_detail_name[require_detail.detail_name]] = list()
            item_dict[translate_detail_name[require_detail.detail_name]].append(require_detail.detail_value)
        for item in retVal.values():
            for sub_item in item.values():
                sub_item.sort()
        return retVal


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
