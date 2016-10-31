#!/usr/bin/env python3

import os
import time
from collections import OrderedDict, defaultdict, deque
import distutils.version

import utils
from .installItem import InstallItem, guid_list, iids_from_guids
import aYaml
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack


class RequireMan(object):
    class RequireItem(object):
        __slots__ = ('__required_by', '__version', '__guid')

        def __init__(self):
            self.__required_by = set()
            self.__version = None
            self.__guid = None

        def should_write_to_yaml(self):
            return self.has_required_by()

        def repr_for_yaml(self):
            retVal = dict()
            retVal['required_by'] = self.required_by
            if self.version:
                retVal['version'] = self.version
            if self.guid:
                retVal['guid'] = self.guid
            return retVal

        def read_from_yaml(self, in_node):
            if in_node.isSequence():
                self.__required_by.update([required_iid.value for required_iid in in_node])
            elif in_node.isMapping():
                for field, field_contents in in_node.items():
                    if field == 'required_by':
                        self.__required_by.update([required_iid.value for required_iid in field_contents])
                    elif field == 'version':
                        self.version = field_contents.value
                    elif field == 'guid':
                        self.guid = field_contents.value

        def has_required_by(self):
             return len(self.__required_by) > 0

        def add_required_by(self, new_required_by):
            self.__required_by.add(new_required_by)
            return self.__required_by

        def remove_required_by(self, to_remove_items):
            self.__required_by -= to_remove_items
            return self.__required_by

        # get the required by as sorted list
        @property
        def required_by(self):
            return sorted(list(self.__required_by))

        # get the required by as a set
        def required_by_set(self):
            return self.__required_by

        @property
        def version(self):
            return self.__version

        @version.setter
        def version(self, new_version):
            self.__version = new_version

        @property
        def guid(self):
            return self.__guid

        @guid.setter
        def guid(self, new_guid):
            self.__guid = new_guid

    def __init__(self):
        self.require_map = defaultdict(RequireMan.RequireItem)

    def __len__(self):
        """ return number of RequireItems """
        return len(self.require_map)

    def __getitem__(self, iid):
        """ return a RequireItem object by it's name """
        return self.require_map[iid]

    def __delitem__(self, key):
        """ remove a RequireItem object by it's name """
        if key in self.require_map:
            del self.require_map[key]

    def __iter__(self):
        return iter(self.require_map)

    def __contains__(self, iid):
        return iid in self.require_map

    def add_x_depends_on_ys(self, x, *ys):
        for y in ys:
            self.require_map[y].add_required_by(x)

    def read_require_node(self, a_node):
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                self.require_map[identifier].read_from_yaml(contents)

    def calc_items_to_remove(self, initial_items):
        explain_uninstall = False
        require_map_keys_set = set(self.require_map.keys())
        explain_uninstall and print("keys found in require file:", len(require_map_keys_set), sorted(require_map_keys_set))
        initial_items_set = set(initial_items)
        explain_uninstall and print("items to remove, translated:", len(initial_items_set), sorted(initial_items_set))
        unmentioned_items = sorted(list(initial_items_set - require_map_keys_set))
        explain_uninstall and print("items to remove that were not found in require file:", len(unmentioned_items), sorted(unmentioned_items))

        to_remove_items = initial_items_set & require_map_keys_set  # no need to check items unmentioned in the require map
        explain_uninstall and print("items to remove that were found in require file:", len(to_remove_items), sorted(to_remove_items))
        new_to_remove_items = set()
        keys_to_check = require_map_keys_set
        while len(to_remove_items) > 0:
            new_to_remove_items.clear()
            explain_uninstall and print("removing from", len(keys_to_check), "items depends on:", sorted(to_remove_items))
            for iid in sorted(keys_to_check):
                still_depends_on = self.require_map[iid].remove_required_by(to_remove_items)
                explain_uninstall and print("    ", "removed from", iid, ", depends left:", sorted(still_depends_on))
                if not self.require_map[iid].has_required_by():
                    new_to_remove_items.add(iid)
            keys_to_check -= new_to_remove_items  # so not to recheck empty items next round
            to_remove_items = new_to_remove_items - to_remove_items

        unrequired_items  = sorted([iid for iid, required_by in self.require_map.items() if not required_by.has_required_by()])
        explain_uninstall and print("keys to remove:", len(unrequired_items), unrequired_items)
        return unrequired_items, unmentioned_items

    def repr_for_yaml(self):
        retVal = OrderedDict()
        for iid, req_item in sorted(self.require_map.items()):
            if req_item.should_write_to_yaml():
                retVal[iid] = req_item.repr_for_yaml()
        return retVal

    def get_previously_installed_root_items(self):
        """
        :return: return only the items that the user requested to install, not those installed as dependents
                of other items. Such items identified by having themselves in their required_by list
        """
        retVal = [iid for iid, require_item in self.require_map.items() if iid in require_item.required_by_set()]
        return retVal

    def get_previously_installed_root_items_with_lower_version(self, iid_map):
        """
        :return: return only the items that the user requested to install, not those installed as dependents
                of other items - but only items with lower version than in the index.
        """
        retVal = []
        for iid, require_item in self.require_map.items():
            if iid in require_item.required_by_set():
                try:
                    old_version = distutils.version.LooseVersion(self.require_map[iid].version)
                    new_version = distutils.version.LooseVersion(iid_map[iid].version)
                    if old_version < new_version:
                        retVal.append(iid)
                except Exception:
                    retVal.append(iid)  # if no versions specified add it anyway
        return retVal

    def update_details(self, iid_map):
        for iid, require_item in self.require_map.items():
            if iid in iid_map:
                if iid_map[iid].version:
                    require_item.version = iid_map[iid].version
                if iid_map[iid].guids:
                    require_item.guid = iid_map[iid].guids[0]


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
        self.the_command = None

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
                        source = var_stack.ResolveVarToList(source_var)
                        relative_sync_folder = self.__instlObj.relative_sync_folder_for_source(source)
                        sync_folder = os.path.join("$(LOCAL_REPO_SYNC_DIR)", relative_sync_folder)
                        self.__no_copy_items_by_sync_folder[sync_folder].append(IID)

    def __translate_root_items(self):
        # root_install_items might have guid in it, translate them to iids
        for IID in self.__root_items:
            if IID == "__UPDATE_INSTALLED_ITEMS__":
                if self.the_command in ("sync", "synccopy"):
                    self.__repair_installed_items = True  # if syncing we want to sync everything
                else:
                    self.__update_installed_items = True  # if copying we want to copy only iid's whose version changed
            elif IID == "__REPAIR_INSTALLED_ITEMS__":
                self.__repair_installed_items = True
            else:
                # if IID is a guid, iids_from_guids will translate to iid's, or return the IID otherwise
                iids_from_the_guid = iids_from_guids(self.__instlObj.install_definitions_index, IID)
                if len(iids_from_the_guid) > 0:
                    self.__root_items_translated.extend(iids_from_the_guid)
                else:
                    self.__orphan_items.append(IID)

        self.__root_update_items = list()
        if self.__repair_installed_items:  # repair takes precedent over update
            items_to_repair = self.req_man.get_previously_installed_root_items()
            self.__root_update_items.extend(items_to_repair)
        elif self.__update_installed_items:
            items_to_update = self.req_man.get_previously_installed_root_items_with_lower_version(self.__instlObj.install_definitions_index)
            self.__root_update_items.extend(items_to_update)

        # find orphan IIDs that were not translated from guids
        for IID in self.__root_items_translated[:]:
            if IID not in self.__instlObj.install_definitions_index:
                self.__root_items_translated.remove(IID)
                self.__orphan_items.append(IID)

        self.__root_items_translated.sort()  # for repeatability

    #@utils.timing
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

        if False: # commented out currently we want all updates to always be installed
            # remove from update items the items that will be installed anyway
            self.__actual_update_items.extend(sorted(list(set(self.__all_update_items) - set(self.__all_items))))

            # if there are items to update, but not in repair mode, assign require_file_repo_rev to
            # these items' last_require_repo_rev so copy command will consider not to copy them in
            # case their files have lower repo-rev.
            # if in repair mode (__repair_installed_items is true), all items get last_require_repo_rev==0
            # by default and all items will be copied.
            if not self.__repair_installed_items:
                require_file_repo_rev = int(var_stack.ResolveVarToStr("REQUIRE_REPO_REV", default="0"))
                for iid in self.__actual_update_items:
                    self.__instlObj.install_definitions_index[iid].last_require_repo_rev = require_file_repo_rev

            self.__all_items.extend(self.__actual_update_items)
        self.__all_items.extend(self.__all_update_items)

        self.calc_require_for_root_items()
        self.__all_items.sort()        # for repeatability
        self.__orphan_items.sort()     # for repeatability
        self.__sort_all_items_by_target_folder()
        return self.__all_items

    def calc_require_for_root_items(self):

        all_root_items = list(set(self.__root_update_items) | set(self.__root_items_translated))
        # the root install items are required by themselves
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
        self.req_man.update_details(self.__instlObj.install_definitions_index)

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
        self.installState.the_command = self.the_command  # hack until db is fully used
        main_input_file_path = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        self.read_yaml_file(main_input_file_path, req_reader=self.installState.req_man)

        active_oses = var_stack.ResolveVarToList("TARGET_OS_NAMES")
        self.items_table.begin_get_for_specific_oses(*active_oses)
        self.items_table.resolve_inheritance()

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

    #@utils.timing
    def translate_root_items_table(self, main_install_targets):
        iids, guids = utils.separate_guids_from_iids(main_install_targets)
        iids_from_guids, orphaned_guids = self.items_table.iids_from_guids(guids)
        iids.extend(iids_from_guids)
        iids, orphaned_iids = self.items_table.iids_from_iids(iids)
        self.root_items_translated_from_table = sorted(iids)
        self.orphan_items_from_table = sorted(orphaned_guids + orphaned_iids)

    #@utils.timing
    def calculate_all_items_table(self):
        self.all_items_from_table = self.items_table.get_recursive_dependencies(self.root_items_translated_from_table)

    def calculate_install_items(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """

        if "MAIN_INSTALL_TARGETS" not in var_stack:
            raise ValueError("'MAIN_INSTALL_TARGETS' was not defined")

        active_oses = var_stack.ResolveVarToList("TARGET_OS_NAMES")
        for os_name in active_oses:
            InstallItem.begin_get_for_specific_os(os_name)

        main_install_targets = var_stack.ResolveVarToList("MAIN_INSTALL_TARGETS")
        self.installState.root_items = main_install_targets
        #print("self.installState.root_items_translated:", self.installState.root_items_translated)

        self.translate_root_items_table(main_install_targets)
        #print("root_items_from_table:", self.root_items_translated_from_table)
        #print("orphan_items_from_table:", self.orphan_items_from_table)

        #assert sorted(self.installState.root_items_translated) == sorted(self.root_items_translated_from_table)
        #assert sorted(self.installState.orphan_items), sorted(self.orphan_items_from_table)

        all_items_from_installState = self.installState.calculate_all_items()
        self.calculate_all_items_table()

        #print("all_items_from_installState:", all_items_from_installState)
        #print("all_items_from_table:", self.all_items_from_table)
        #assert sorted(all_items_from_installState) == sorted(self.all_items_from_table)

        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(sorted(self.installState.all_items))
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(sorted(self.installState.orphan_items))

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
        self.write_require_file(new_require_file_path, self.installState.req_man.repr_for_yaml())
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
    elif command in ('report-installed', 'report-update', 'report-versions'):
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
