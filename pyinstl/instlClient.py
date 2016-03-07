#!/usr/bin/env python3

import os
import time
from collections import OrderedDict, defaultdict, deque
import utils
from .installItem import InstallItem, guid_list, iids_from_guids
import aYaml
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack


class RequireMan(object):
    def __init__(self):
        self.require_map = defaultdict(set)

    def add_x_depends_on_ys(self, x, *ys):
        for y in ys:
            self.require_map[y].add(x)

    def read_require_node(self, a_node):
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                self.require_map[identifier].update([required_iid.value for required_iid in contents])

    def calc_items_to_remove(self, initial_items):
        require_map_keys_set = set(self.require_map.keys())
        initial_items_set = set(initial_items)
        unmentioned_items = sorted(list(initial_items_set - require_map_keys_set))

        to_remove_items = initial_items_set & require_map_keys_set  # no need to check items unmentioned in the require map
        new_to_remove_items = set()
        keys_to_check = require_map_keys_set
        while len(to_remove_items) > 0:
            new_to_remove_items.clear()
            for iid in keys_to_check:
                self.require_map[iid] -= to_remove_items
                if len(self.require_map[iid]) == 0:
                    new_to_remove_items.add(iid)
            keys_to_check -= new_to_remove_items  # so not to recheck empty items
            to_remove_items = new_to_remove_items - to_remove_items

        unrequired_items  = sorted([iid for iid, required_by in sorted(self.require_map.items()) if len(required_by) == 0])
        return unrequired_items, unmentioned_items

    def repr_for_yaml(self):
        retVal = OrderedDict()
        for i in sorted(self.require_map.keys()):
            if len(self.require_map[i]) > 0:
                retVal[i] = sorted(list(self.require_map[i]))
        return retVal

    def get_previously_installed_root_items(self):
        """
        :return: return only the items that the user requested to install, not those installed as dependents
                of other items. Such items identified by having themselves in their required_by list
        """
        retVal = [iid for iid, required_by in self.require_map.items() if iid in required_by]
        return retVal


# noinspection PyPep8Naming,PyUnresolvedReferences
class InstallInstructionsState(object):
    """ holds state for specific creating of install instructions """

    def __init__(self, instlObj):
        self.__instlObj = instlObj
        self.__root_items = utils.unique_list()
        self.__root_items_translated = utils.unique_list()
        self.__root_update_items = utils.unique_list()
        self.__all_update_items = utils.unique_list()
        self.__actual_update_items = utils.unique_list()
        self.__orphan_items = utils.unique_list()
        self.__all_items = utils.unique_list()
        self.__all_items_by_target_folder = None
        self.__no_copy_items_by_sync_folder = None
        self.__update_installed_items = False
        self.__repair_installed_items = False
        self.req_man = RequireMan()

    @property
    def root_items(self):
        return self.__root_items

    @root_items.setter
    def root_items(self, root_items):
        root_items = list(filter(bool, root_items))  # avoid empty strings
        self.__root_items.extend(sorted(root_items))
        self.__translate_root_items()

    @property
    def root_items_translated(self):
        return self.__root_items_translated

    @property
    def orphan_items(self):
        return self.__orphan_items

    @property
    def all_items(self):
        return self.__all_items

    @property
    def all_items_by_target_folder(self):
        return self.__all_items_by_target_folder

    @property
    def no_copy_items_by_sync_folder(self):
        return self.__no_copy_items_by_sync_folder

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['root_install_items'] = list(self.__root_items)
        retVal['root_install_items_translated'] = list(self.__root_items_translated)
        retVal['root_update_items'] = list(self.__root_update_items)
        retVal['all_update_items'] = list(self.__all_update_items)
        retVal['actual_update_items'] = list(self.__actual_update_items)
        retVal['full_install_items'] = list(self.__all_items)
        retVal['orphan_install_items'] = list(self.__orphan_items)
        retVal['install_items_by_target_folder'] = {folder: list(item) for folder, item in self.all_items_by_target_folder.items()}
        retVal['no_copy_items_by_sync_folder'] = list(self.__no_copy_items_by_sync_folder)
        retVal['update_installed_items'] = str(self.__update_installed_items)
        retVal['repair_installed_items'] = str(self.__repair_installed_items)
        return retVal

    def __sort_all_items_by_target_folder(self):
        self.__all_items_by_target_folder = defaultdict(utils.unique_list)
        self.__no_copy_items_by_sync_folder = defaultdict(utils.unique_list)
        for IID in self.__all_items:
            with self.__instlObj.install_definitions_index[IID].push_var_stack_scope():
                folder_list_for_idd = [folder for folder in var_stack["iid_folder_list"]]
                if folder_list_for_idd:
                    for folder in folder_list_for_idd:
                        norm_folder = os.path.normpath(folder)
                        self.__all_items_by_target_folder[norm_folder].append(IID)
                else:  # items that need no copy
                    for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                        source = var_stack.resolve_var_to_list(source_var)
                        relative_sync_folder = self.__instlObj.relative_sync_folder_for_source(source)
                        sync_folder = os.path.join("$(LOCAL_REPO_SYNC_DIR)", relative_sync_folder)
                        self.__no_copy_items_by_sync_folder[sync_folder].append(IID)

    def __translate_root_items(self):
        # root_install_items might have guid in it, translate them to iids
        for IID in self.__root_items:
            if IID == "__UPDATE_INSTALLED_ITEMS__":
                self.__update_installed_items = True
            elif IID == "__REPAIR_INSTALLED_ITEMS__":
                self.__update_installed_items = True
                self.__repair_installed_items = True
            else:
                # if IID is a guid, iids_from_guids will translate to iid's, or return the IID otherwise
                iids_from_the_guid = iids_from_guids(self.__instlObj.install_definitions_index, IID)
                if len(iids_from_the_guid) > 0:
                    self.__root_items_translated.extend(iids_from_the_guid)
                else:
                    self.__orphan_items.append(IID)


        self.__root_update_items = list()
        if self.__update_installed_items:
            self.__root_update_items.extend(self.req_man.get_previously_installed_root_items())

        self.__root_items_translated.sort()  # for repeatability

    def calculate_all_items(self):
        """ calculate the set of iids to install by starting with the root set and adding all dependencies.
            Initial list of iids should already be in self.__root_items_translated.
            If an install items was not found for a iid, the iid is added to the orphan set.
            Same is done for the update items. The actual update items list is then calculated by removing
            the root items and their dependencies from the update items.
        """
        for IID in self.__root_items_translated:
            try:
                self.__instlObj.install_definitions_index[IID].get_recursive_depends(self.__instlObj.install_definitions_index,
                                                                                     self.__all_items,
                                                                                     self.__orphan_items)
            except KeyError:
                self.__orphan_items.append(IID)

        for IID in self.__root_update_items:
            try:
                self.__instlObj.install_definitions_index[IID].get_recursive_depends(self.__instlObj.install_definitions_index,
                                                                                     self.__all_update_items,
                                                                                     self.__orphan_items)
            except KeyError:
                self.__orphan_items.append(IID)

        # remove from update items the items that will be installed anyway
        self.__actual_update_items.extend(sorted(list(set(self.__all_update_items) - set(self.__all_items))))

        # if there are items to update, but not in repair mode, assign require_file_repo_rev to
        # these items' last_require_repo_rev so copy command will consider not to copy them in
        # case their files have lower repo-rev.
        # if in repair mode (__repair_installed_items is true), all items get last_require_repo_rev==0
        # by default and all items will be copied.
        if not self.__repair_installed_items:
            require_file_repo_rev = int("$(REQUIRE_REPO_REV)" @ var_stack)
            for iid in self.__actual_update_items:
                self.__instlObj.install_definitions_index[iid].last_require_repo_rev = require_file_repo_rev

        self.__all_items.extend(self.__actual_update_items)

        self.calc_require_for_root_items()
        self.__all_items.sort()        # for repeatability
        self.__orphan_items.sort()     # for repeatability
        self.__sort_all_items_by_target_folder()

    def calc_require_for_root_items(self):

        all_root_items = list(set(self.__root_update_items) | set(self.__root_items_translated))
        # the root install items were required by themselves
        for IID in all_root_items:
            self.req_man.add_x_depends_on_ys(IID, IID)

        r_list = deque(all_root_items)
        while len(r_list) > 0:
            next_round = set()
            for IID in r_list:
                the_depends = iids_from_guids(self.__instlObj.install_definitions_index,
                                              *self.__instlObj.install_definitions_index[IID].get_depends())
                self.req_man.add_x_depends_on_ys(IID, *the_depends)
                next_round.update(the_depends)
            r_list = list(next_round)

    def calc_items_to_remove(self):
        unrequired_items, unmentioned_items = self.req_man.calc_items_to_remove(self.__root_items_translated)
        self.__all_items = sorted(unrequired_items + unmentioned_items)
        self.__orphan_items.extend(unmentioned_items)
        self.__sort_all_items_by_target_folder()


class InstlClient(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.installState = None
        self.action_type_to_progress_message = None

    def do_command(self):
        # print("client_commands", fixed_command_name)
        self.installState = InstallInstructionsState(self)
        main_input_file_path = var_stack.resolve("$(__MAIN_INPUT_FILE__)")
        self.read_yaml_file(main_input_file_path)
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
        self.platform_helper.num_items_for_progress_report = int(var_stack.resolve("$(LAST_PROGRESS)"))

        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()
        self.create_instl_history_file()

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
        instl_temp_history_file_path = var_stack.resolve("$(INSTL_HISTORY_TEMP_PATH)")
        instl_temp_history_folder, instl_temp_history_file_name = os.path.split(instl_temp_history_file_path)
        if os.path.isdir(instl_temp_history_folder):
            with open(instl_temp_history_file_path, "w", encoding='utf-8') as wfd:
                utils.make_open_file_read_write_for_all(wfd)
                aYaml.writeAsYaml(yaml_of_defines, wfd)
            self.batch_accum += self.platform_helper.append_file_to_file("$(INSTL_HISTORY_TEMP_PATH)",
                                                                         "$(INSTL_HISTORY_PATH)")

    def read_repo_type_defaults(self):
        repo_type_defaults_file_path = os.path.join(var_stack.resolve("$(__INSTL_DATA_FOLDER__)"), "defaults",
                                                    var_stack.resolve("$(REPO_TYPE).yaml"))
        if os.path.isfile(repo_type_defaults_file_path):
            self.read_yaml_file(repo_type_defaults_file_path)

    def init_default_client_vars(self):
        if "SYNC_BASE_URL" in var_stack:
            #raise ValueError("'SYNC_BASE_URL' was not defined")
            resolved_sync_base_url = var_stack.resolve("$(SYNC_BASE_URL)")
            url_main_item = utils.main_url_item(resolved_sync_base_url)
            var_stack.set_var("SYNC_BASE_URL_MAIN_ITEM", description="from init_default_client_vars").append(url_main_item)
        # TARGET_OS_NAMES defaults to __CURRENT_OS_NAMES__, which is not what we want if syncing to
        # an OS which is not the current
        if var_stack.resolve("$(TARGET_OS)") != var_stack.resolve("$(__CURRENT_OS__)"):
            target_os_names = var_stack.resolve_var_to_list(var_stack.resolve("$(TARGET_OS)_ALL_OS_NAMES"))
            var_stack.set_var("TARGET_OS_NAMES").extend(target_os_names)
            second_name = var_stack.resolve("$(TARGET_OS)")
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            var_stack.set_var("TARGET_OS_SECOND_NAME").append(second_name)

        self.read_repo_type_defaults()
        if var_stack.resolve("$(REPO_TYPE)") == "P4":
            if "P4_SYNC_DIR" not in var_stack:
                if "SYNC_BASE_URL" in var_stack:
                    p4_sync_dir = utils.P4GetPathFromDepotPath(var_stack.resolve("$(SYNC_BASE_URL)"))
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
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        # read the require.yaml file, if any, we'll need it to calculate updates
        require_path = var_stack.resolve("$(SITE_REQUIRE_FILE_PATH)")
        if os.path.isfile(require_path):
            try:
                self.read_yaml_file(require_path, req_reader=self.installState.req_man)
            except Exception as ex:
                print("failed to read", require_path, ex)

        if "MAIN_INSTALL_TARGETS" not in var_stack:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")
        for os_name in var_stack.resolve_to_list("$(TARGET_OS_NAMES)"):
            InstallItem.begin_get_for_specific_os(os_name)
        self.installState.root_items = var_stack.resolve_to_list("$(MAIN_INSTALL_TARGETS)")
        self.installState.calculate_all_items()
        #self.read_previous_requirements()
        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(sorted(self.installState.all_items))
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(sorted(self.installState.orphan_items))

    def read_previous_requirements(self):
        require_file_path = var_stack.resolve("$(SITE_REQUIRE_FILE_PATH)")
        if os.path.isfile(require_file_path):
            self.read_yaml_file(require_file_path)

    def accumulate_unique_actions(self, action_type, iid_list):
        """ accumulate action_type actions from iid_list, eliminating duplicates"""
        unique_actions = utils.unique_list()  # unique_list will eliminate identical actions while keeping the order
        for IID in sorted(iid_list):
            with self.install_definitions_index[IID].push_var_stack_scope() as installi:
                action_var_name = "iid_action_list_" + action_type
                item_actions = var_stack.resolve_var_to_list_if_exists(action_var_name)
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
        new_require_file_path = var_stack.resolve("$(NEW_SITE_REQUIRE_FILE_PATH)", raise_on_fail=True)
        new_require_file_dir, new_require_file_name = os.path.split(new_require_file_path)
        os.makedirs(new_require_file_dir, exist_ok=True)
        self.write_require_file(new_require_file_path, self.installState.req_man.repr_for_yaml())
        # Copy the new require file over the old one, if copy fails the old file remains.
        self.batch_accum += self.platform_helper.copy_file_to_file("$(NEW_SITE_REQUIRE_FILE_PATH)",
                                                                   "$(SITE_REQUIRE_FILE_PATH)")


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
