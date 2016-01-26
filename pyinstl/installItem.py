#!/usr/bin/env python3


"""
    class InstallItem hold information about how to install one or more install_sources.
    information include:
        iid - must be unique amongst all InstallItems.
        name - will appear in progress messages and logs.
        guids - a standard 36 character guid. Can be used as additional identification
        Several iids can share the same guid, same iid can have several guids.
        remark - remarks for human consumption has no bering on the installation.
        description - auto generated, usually the file and line from which the item was read.
                        can be used for debugging, log and errors messages has no bering on the installation.
        inherit - iids of other InstallItems to inherit from.
        These fields appear once for each InstallItem.
    Further fields can be be found in a common section or in a section for specific OS:
        install_sources - install_sources to install.
        install_folders - folders to install the install_sources to.
        depends - iids of other InstallItems that must be installed before the current item.
        actions - actions to preform. These actions are further divided into:
            pre_copy - actions to preform before starting the whole copy operation.
                        If several InstallItems have the same pre_copy actions, each such action
                        will be preformed only once.
            post_copy - actions to preform after finishing the whole copy operation.
                        If several InstallItems have the same post_copy actions, each such action
                        will be preformed only once.
            pre_copy_to_folder - actions to preform before installing to each of the folders in install_folders section.
                        If several InstallItems have the same pre_copy_to_folder actions for the folder, each such action
                        will be preformed only once.
            post_copy_to_folder - actions to preform after installing to each of the folders in install_folders section.
                        if several InstallItems have the same post_copy_to_folder actions for the folder, each such action
                        will be preformed only once.
            pre_copy_item -    actions to preform before copying each of the install_sources in each folder.
            post_copy_item -     actions to preform after installing each of the install_sources in each folder.
            pre_remove - actions to preform before starting the whole remove operation.
                        If several InstallItems have the same pre_remove actions, each such action
                        will be preformed only once.
            post_remove - actions to preform after finishing the whole remove operation.
                        If several InstallItems have the same post_remove actions, each such action
                        will be preformed only once.
            pre_remove_from_folder - actions to preform before removing from each of the folders in install_folders section.
                        If several InstallItems have the same pre_remove_from_folder actions for the folder, such each action
                        will be preformed only once.
            post_remove_from_folder - actions to preform after removing from each of the folders in install_folders section.
                        if several InstallItems have the same post_remove_from_folder actions for the folder, such each action
                        will be preformed only once.
            pre_remove_item -    actions to preform before removing each of the install_sources from each target folder.
            remove_item -        by default the remove_item action is to delete the files that were copied by the copy action.
                                 if remove_item action is explicitly specified, it will be done instead of deleting.
                                 To disable deleting the item specify a Null actions, thus: remove_item: ~
            post_remove_item -     actions to preform after removing each of the install_sources from each target folder.

    Except iid field, all fields are optional.

    Example in Yaml:

    test:
        name: test
        guid: f01f84d6-ad21-11e0-822a-b7fd7bebd530
        install_sources:
            - Plugins/test_1
            - Plugins/test_2
        install_folders:
            - test_target_folder_1
            - test_target_folder_2
        actions:
            pre_copy_to_folder:
                - action when entering folder
            pre_copy_item:
                - action before item
            post_copy_item:
                - action after item
            post_copy_to_folder:
                - action when leaving folder
"""

from collections import OrderedDict, defaultdict
from contextlib import contextmanager

import aYaml
import utils
import configVar
from configVar import var_stack

current_os_names = utils.get_current_os_names()
os_family_name = current_os_names[0]


def read_index_from_yaml(all_items_node):
    retVal = dict()
    for IID in all_items_node:
        if IID in retVal:
            print(IID, "found more than once in index")
        else:
            # print(IID, "not in all_items_node")
            item = InstallItem(IID)
            item.read_from_yaml_by_idd(all_items_node)
            retVal[IID] = item
    return retVal

class InstallItem(object):
    __slots__ = ('__iid', '__name', '__guids',
                 '__remark', "__description", '__inherit_from',
                 '__install_for_os_stack', '__items', '__resolved_inherit',
                 '__var_list', '__required_by', '__user_data')
    os_names = ('common', 'Mac', 'Mac32', 'Mac64', 'Win', 'Win32', 'Win64')
    allowed_item_keys = ('name', 'guid','install_sources', 'install_folders', 'inherit', 'depends', 'actions', 'remark')
    allowed_top_level_keys = os_names[1:] + allowed_item_keys
    action_types = ('pre_copy', 'pre_copy_to_folder', 'pre_copy_item',
                    'post_copy_item', 'post_copy_to_folder', 'post_copy',
                    'pre_remove', 'pre_remove_from_folder', 'pre_remove_item',
                    'remove_item', 'post_remove_item', 'post_remove_from_folder',
                    'post_remove', 'pre_doit', 'doit', 'post_doit')
    file_types = ('!dir_cont', '!files', '!file', '!dir')
    resolve_inheritance_stack = list()
    _get_for_os = [
        os_names[0]]  # _get_for_os is a class member since we usually want to get for same oses for all InstallItems

    @staticmethod
    def create_items_section():
        retVal = defaultdict(utils.unique_list)
        return retVal

    @staticmethod
    def merge_item_sections(this_items, the_other_items):
        common_items = set(list(this_items.keys()) + list(the_other_items.keys()))
        try:
            for item in common_items:
                this_items[item].extend(the_other_items[item])
        except TypeError:
            print("TypeError for", item)
            raise

    @staticmethod
    def begin_get_for_all_oses():
        """ adds all known os names to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        InstallItem._get_for_os = []
        InstallItem._get_for_os.extend(InstallItem.os_names)

    @staticmethod
    def reset_get_for_all_oses():
        """ resets the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        InstallItem._get_for_os = [InstallItem.os_names[0]]

    @staticmethod
    def begin_get_for_specific_os(for_os):
        """ adds another os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
        """
        InstallItem._get_for_os.append(for_os)

    @staticmethod
    def end_get_for_specific_os():
        """ removed the last added os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
             This is a static method so it will influence all InstallItem objects.
        """
        InstallItem._get_for_os.pop()

    def merge_all_item_sections(self, otherInstallItem):
        for os_ in InstallItem.os_names:
            InstallItem.merge_item_sections(self.__items[os_], otherInstallItem.__items[os_])
        self.__guids.extend(otherInstallItem.guids)

    def __init__(self, iid):
        self.__resolved_inherit = False
        self.__iid = iid
        self.__name = ""
        self.__guids = utils.unique_list()
        self.__remark = ""
        self.__description = ""
        self.__inherit_from = utils.unique_list()
        self.__install_for_os_stack = [InstallItem.os_names[0]] # reading for all platforms ('common') or for which specific platforms ('Mac', 'Win')?
        self.__items = defaultdict(InstallItem.create_items_section)
        self.__var_list = None
        self.__required_by = utils.unique_list()
        self.__user_data = None

    def read_from_yaml_by_idd(self, all_items_node):
        my_node = all_items_node[self.__iid]
        save_iid = self.__iid
        # set description here, even though it might be overwritten,
        # so if there's an error during read_from_yaml exact location could be printed
        self.__description = str(my_node.start_mark)
        self.read_from_yaml(my_node)
        self.__iid = save_iid  # restore the IID & description that might have been overwritten by inheritance
        self.__description = str(my_node.start_mark)

    def read_from_yaml(self, my_node):
        element_names = set([a_key for a_key in my_node])
        if not element_names.issubset(self.allowed_top_level_keys):
            print("Warning: illegal keys {}; IID: {}, {}".format(list(element_names.difference(self.allowed_top_level_keys)), self.__iid, self.__description))

        if 'inherit' in my_node:
            self.__inherit_from.extend(inheritoree.value for inheritoree in my_node['inherit'])
        if 'name' in my_node:
            self.__name = my_node['name'].value
        if 'guid' in my_node:
            self.__guids.extend(source.value.lower() for source in my_node['guid'])
        if 'remark' in my_node:
            self.__remark = my_node['remark'].value
        if 'install_sources' in my_node:
            self.add_sources(*[(source.value, source.tag) for source in my_node['install_sources']])
        if 'install_folders' in my_node:
            self.add_folders(*[folder.value for folder in my_node['install_folders']])
        if 'depends' in my_node:
            self.add_depends(*[source.value for source in my_node['depends']])
        if 'actions' in my_node:
            self.read_actions(my_node['actions'])
        for os_ in InstallItem.os_names[1:]:
            if os_ in my_node:
                with self.set_for_specific_os(os_):
                    self.read_from_yaml(my_node[os_])

    def get_var_list(self):
        """
        :return: ConfigVarList object with variables for properties of this object
                self.__var_list is a member so it will be cached for multiple accesses
                (which happens, many times!)
        """
        if self.__var_list is None:
            self.__var_list = configVar.ConfigVarList()
            self.__var_list.set_var("iid_iid").append(self.__iid)
            if self.__name:
                self.__var_list.set_var("iid_name").append(self.__name)
            for a_guid in self.__guids:
                self.__var_list.get_configVar_obj("iid_guid").append(a_guid)
            if self.__remark:
                self.__var_list.set_var("iid_remark").append(self.__remark)
            self.__var_list.set_var("iid_inherit").extend(self.__inherit_from)
            self.__var_list.set_var("iid_folder_list").extend(self._folder_list())
            self.__var_list.set_var("iid_depend_list").extend(self._depend_list())
            for action_type in self.action_types:
                action_list_for_type = self._action_list(action_type)
                if len(action_list_for_type) > 0:
                    self.__var_list.set_var("iid_action_list_" + action_type).extend(action_list_for_type)
            source_vars_obj = self.__var_list.set_var("iid_source_var_list")
            source_list = self._source_list()
            for i, source in enumerate(source_list):
                source_var = "iid_source_" + str(i)
                source_vars_obj.append(source_var)
                self.__var_list.set_var(source_var).extend(source)
        return self.__var_list

    @contextmanager
    def push_var_stack_scope(self):
        var_stack.push_scope(self.get_var_list())
        yield self
        var_stack.pop_scope()

    @contextmanager
    def set_for_specific_os(self, for_os):
        self.__install_for_os_stack.append(for_os)
        yield self
        self.__install_for_os_stack.pop()

    def __add_items_by_os_and_category(self, item_os, item_category, *item_values):
        """ Add an item to one of the oses and category e.g.:
            __add_item_by_os_and_category("Win", "install_sources", "x.dll")
            __add_item_by_os_and_category("common", "install_sources", "AudioTrack.bundle")
        """
        self.__items[item_os][item_category].extend(item_values)

    def __add_items_to_default_os_by_category(self, item_category, *item_values):
        """ Add an item to currently default os and category, e.g.:
             begin_set_for_specific_os("Win")
             __add_items_to_default_os_by_category("install_sources", "x.dll")
             self.end_set_for_specific_os()
             __add_items_to_default_os_by_category("install_sources", "AudioTrack.bundle")

             The default os is the one at the top of the __install_for_os_stack stack. __install_for_os_stack
             starts with "common" as the first o.
         """
        self.__add_items_by_os_and_category(self.current_os, item_category, *item_values)

    def __get_item_list_by_os_and_category(self, item_os, item_category):
        retVal = list()
        if item_os in self.__items and item_category in self.__items[item_os]:
            retVal.extend(self.__items[item_os][item_category])
        return retVal

    def __get_item_list_for_default_oses_by_category(self, item_category):
        retVal = utils.unique_list()
        for os_name in InstallItem._get_for_os:
            retVal.extend(self.__get_item_list_by_os_and_category(os_name, item_category))
        return retVal

    def add_sources(self, *new_sources):
        adjusted_sources = list()
        for new_source in new_sources:
            if new_source[1] in InstallItem.file_types:
                source_type = new_source[1]
            else:
                source_type = '!dir'
            if new_source[0].startswith("/"):  # absolute path
                adjusted_source = new_source[0][1:], source_type, self.current_os
            elif new_source[0].startswith("$("):  # explicitly relative to some variable
                adjusted_source = new_source[0], source_type, self.current_os
            else:  # implicitly relative to $(SOURCE_PREFIX)
                adjusted_source = "$(SOURCE_PREFIX)/" + new_source[0], source_type, self.current_os
            adjusted_sources.append(adjusted_source)

        self.__add_items_to_default_os_by_category('install_sources', *adjusted_sources)

    def _source_list(self):
        return self.__get_item_list_for_default_oses_by_category('install_sources')

    def add_folders(self, *new_folders):
        self.__add_items_to_default_os_by_category('install_folders', *new_folders)

    def _folder_list(self):
        return self.__get_item_list_for_default_oses_by_category('install_folders')

    def add_depends(self, *new_depends):
        if not new_depends:
            raise ValueError("new_depend cannot be null")
        self.__add_items_to_default_os_by_category('depends', *new_depends)

    def _depend_list(self):
        return self.__get_item_list_for_default_oses_by_category('depends')

    def add_actions(self, action_type, *new_actions):
        self.__add_items_to_default_os_by_category(action_type, *new_actions)

    def read_actions(self, action_nodes):
        for action_type, new_actions in action_nodes.items():
            self.add_actions(action_type, *[action.value for action in new_actions])

    def _action_list(self, action_type):
        if action_type not in InstallItem.action_types:
            raise KeyError("actions type must be one of: " + str(InstallItem.action_types) + " not " + action_type)
        return self.__get_item_list_for_default_oses_by_category(action_type)

    def all_action_list(self):
        """ Get a list of all types of actions, can be used to find how many actions there are.
        """
        retVal = list()
        for action_type in InstallItem.action_types:
            retVal.extend(self.__get_item_list_for_default_oses_by_category(action_type))
        return retVal

    def get_depends(self):
        return self._depend_list()

    def calc_required(self, items_map, is_top_item):
        for depend in self._depend_list():
            if len(items_map[depend].__required_by) == 0: # so calc_required will be called only once for each iid
                items_map[depend].calc_required(items_map, is_top_item=False)
            items_map[depend].add_required_by(self.__iid)
            if is_top_item:
                self.__required_by.append(self.__iid) # top level items are marked as required by themselves

    def get_recursive_depends(self, items_map, out_set, orphan_set):
        if self.__iid not in out_set:
            out_set.append(self.__iid)
            # print("get_recursive_depends: added", self.__iid)
            for depend in self._depend_list():
                try:
                    # if IID is a guid, iids_from_guids will translate to iid's, or return the IID otherwise
                    dependees = iids_from_guids(items_map, depend)
                    for dependee in dependees:
                        items_map[dependee].add_required_by(self.__iid)
                        if dependee not in out_set:  # avoid cycles, save time
                            items_map[dependee].get_recursive_depends(items_map, out_set, orphan_set)
                except KeyError:
                    orphan_set.append(depend)
                    # else:
                    #    print("get_recursive_depends: already added", self.__iid)

    def repr_for_yaml_items(self, for_which_os):
        retVal = None
        if self.__items[for_which_os]:
            retVal = OrderedDict()
            if self.__items[for_which_os]['install_sources']:
                source_list = list()
                for source in self.__items[for_which_os]['install_sources']:
                    if source[1] != '!dir':
                        source_list.append(aYaml.YamlDumpWrap(value=source[0], tag=source[1]))
                    else:
                        source_list.append(source[0])
                retVal['install_sources'] = source_list
            if self.__items[for_which_os]['install_folders']:
                retVal['install_folders'] = list(self.__items[for_which_os]['install_folders'])
            if self.__items[for_which_os]['depends']:
                retVal['depends'] = list(self.__items[for_which_os]['depends'])
            for action in InstallItem.action_types:
                if action in self.__items[for_which_os] and self.__items[for_which_os][action]:
                    actions_dict = retVal.setdefault('actions', OrderedDict())
                    actions_dict[action] = list(self.__items[for_which_os][action])
        return retVal

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['name'] = self.__name
        if self.__guids:
            retVal['guid'] = self.__guids
        if self.__remark:
            retVal['remark'] = self.__remark
        if self.__inherit_from:
            retVal['inherit'] = self.__inherit_from

        common_items = self.repr_for_yaml_items(InstallItem.os_names[0])
        if common_items:
            retVal.update(common_items)
        for os_ in InstallItem.os_names[1:]:
            os_items = self.repr_for_yaml_items(os_)
            if os_items:
                retVal[os_] = os_items

        return retVal

    def merge_from_another_InstallItem(self, otherInstallItem):
        """ merge the contents of another InstallItem """
        # self.__iid = iid is not merged
        # self.name = name is not merged
        # self.__guids = guid is not merged
        # name of the other item is added to the remark
        if not self.__remark:
            self.__remark = self.__name
        self.__remark += ", " + otherInstallItem.name
        self.__inherit_from.update(otherInstallItem.__inherit_from)
        self.merge_all_item_sections(otherInstallItem)

    def resolve_inheritance(self, InstallItemsDict):
        if not self.__resolved_inherit:
            if self.__iid in self.resolve_inheritance_stack:
                raise Exception("circular resolve_inheritance of " + self.__iid)
            self.resolve_inheritance_stack.append(self.__iid)
            for ancestor in self.__inherit_from:
                if ancestor not in InstallItemsDict:
                    raise KeyError(self.__iid + " inherits from " + ancestor + " which is not in InstallItemsDict")
                ancestor_item = InstallItemsDict[ancestor]
                ancestor_item.resolve_inheritance(InstallItemsDict)
                self.merge_all_item_sections(ancestor_item)
            self.resolve_inheritance_stack.pop()

    @property
    def guids(self):
        return self.__guids

    @property
    def user_data(self):
        """ return user_data """
        return self.__user_data

    @user_data.setter
    def user_data(self, new_user_data):
        """ update user_data """
        self.__user_data = new_user_data

    @property
    def current_os(self):
        return self.__install_for_os_stack[-1]

    @property
    def name(self):
        return self.__name

    @name.setter
    def name(self, new_name):
        """ update name """
        self.__name = new_name

    @property
    def remark(self):
        return self.__remark

    @property
    def iid(self):
        return self.__iid

    @property
    def required_by(self):
        return self.__required_by

    def add_required_by(self, *another_required_by):
        self.__required_by.extend(another_required_by)


def guid_list(items_map):
    retVal = utils.unique_list()
    for install_def in list(items_map.values()):
        retVal.extend(list(filter(bool, install_def.guids)))
    return retVal


def iids_from_guids(items_map, *guids_or_iids):
    """ guid_or_iid might be a guid or normal IID
        if it's a guid return all IIDs that have this gui
        if it's not return the IID itself. """
    retVal = list()
    for guid_or_iid in guids_or_iids:
        if utils.guid_re.match(guid_or_iid.lower()):  # it's a guid, get iids for all items with that guid
            for iid, install_def in items_map.items():
                    if guid_or_iid.lower() in install_def.guids:
                        retVal.append(iid)
        else:
            retVal.append(guid_or_iid)  # it's a regular iid, not a guid, no need to lower case
    return retVal
