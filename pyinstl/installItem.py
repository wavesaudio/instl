#!/usr/local/bin/python2.7

from __future__ import print_function

"""
    class InstallItem hold information about how to install one or more install_sources.
    information include:
        iid - must be unique amongst all InstallItems.
        name - description for log and erros messages has no bering on the installation.
        guid - a standard 36 charcter guid. Can be used as addtional identification. Several idds can share the same guid.
        remark - remarks for human consumption has no bering on the installation.
        description - auto generated, usually the file and line from which the item was read.
        inherit - idds of other InstallItems to inherit from.
        These fields appear once for each InstallItem.
    Further fields can be be found in a common section or in a section for specific OS:
        install_sources - install_sources to install.
        install_folders - folders to install the install_sources to.
        depends - idds of other InstallItems that must be installed before the current item.
        actions - actions to preform. These actions are further divided into:
            folder_in - actions to preform before installing to each folder in install_folders section.
                        if several InstallItems have the same actions for the folder, each action
                        will be preformed only once.
            folder_out - actions to preform after installing to each folder in install_folders section.
                        if several InstallItems have the same actions for the folder, each action
                        will be preformed only once.
            before -    actions to preform before installing the install_sources in each folder.
            after -    actions to preform after installing the install_sources in each folder.
    Except iid field, all fields are optional.

    Example in Yaml:

    test:
        name: test
        guid: f01f84d6-ad21-11e0-822a-b7fd7bebd530
        remarks: testing, testing 1, 2, 3
        description: index.txt line 1245
        install_sources:
            - Plugins/test_1
            - Plugins/test_2
        install_folders:
            - test_target_folder_1
            - test_target_folder_2
        actions:
            folder_in:
                - action when entering folder
            before:
                - action before item
            after:
                - action after item
            folder_out:
                - action when leaving folder
"""

import sys
import platform
import yaml
import aYaml
from collections import OrderedDict, defaultdict

sys.path.append("..")
from aYaml import augmentedYaml
from pyinstl.utils import unique_list

current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'mac';
elif current_os == 'Windows':
    current_os = 'win';

def read_index_from_yaml(all_items_node):
    retVal = dict() #OrderedDict()
    for IID in all_items_node.iterkeys():
        if IID in retVal:
            pass#print(IID, "already in all_items_node")
        else:
            #print(IID, "not in all_items_node")
            item = InstallItem()
            item.read_from_yaml_by_idd(IID, all_items_node)
            retVal[IID] = item
    return retVal


class InstallItem(object):
    __slots__ = ('iid', 'name', 'guid',
                'remark', "description", 'inherit',
                '__set_for_os', '__items', '__resolved_inherit')
    item_sections = ('common', 'mac', 'win')
    item_types = ('install_sources', 'install_folders', 'depends', 'actions')
    action_types = ('folder_in', 'before', 'after', 'folder_out')
    file_types = ('!dir_cont', '!files', '!file', '!dir')
    get_for_os = current_os
    resolve_inheritance_stack = list()

    @staticmethod
    def create_items_section():
        retVal = defaultdict(unique_list)
        return retVal

    @staticmethod
    def merge_item_sections(this_items, the_other_items):
        common_items = set(this_items.keys() + the_other_items.keys())
        try:
            for item in common_items:
                this_items[item].extend(the_other_items[item])
        except TypeError as te:
            print("TypeError for", item)
            raise

    def merge_all_item_sections(self, otherInstallItem):
        for section in InstallItem.item_sections:
            InstallItem.merge_item_sections(self.__items[section], otherInstallItem.__items[section])

    def __init__(self):
        self.__resolved_inherit = False
        self.iid = None
        self.name = None
        self.guid = None
        self.remark = ""
        self.description = ""
        self.inherit = unique_list()
        self.__set_for_os = [InstallItem.item_sections[0]] # reading for all platforms ('common') or for which specific platforms ('mac', 'win')?
        self.__items = defaultdict(InstallItem.create_items_section)

    def read_from_yaml_by_idd(self, IID, all_items_node):
        my_node = all_items_node[IID]
        self.read_from_yaml(my_node)
        self.iid = IID # restore the IID that might have been overwritten by inheritance
        self.description = str(my_node.start_mark)

    def read_from_yaml(self, my_node):
        if 'inherit' in my_node:
            for inheritoree in my_node['inherit'].value:
                self.add_inherit(inheritoree.value)
        if 'name' in my_node:
            self.name = my_node['name'].value
        if 'guid' in my_node:
            self.guid = my_node['guid'].value
        if 'remark' in my_node:
            self.remark = my_node['remark'].value
        if 'install_sources' in my_node:
            for source in my_node['install_sources']:
                self.add_source(source.value, source.tag)
        if 'install_folders' in my_node:
            for folder in my_node['install_folders']:
                self.add_folder(folder.value)
        if 'depends' in my_node:
            for source in my_node['depends']:
                self.add_depend(source.value)
        if 'actions' in my_node:
            self.read_actions(my_node['actions'])
        for itemSec in InstallItem.item_sections[1:]:
            if itemSec in my_node:
                self.begin_specific_os(itemSec)
                self.read_from_yaml(my_node[itemSec])
                self.end_specific_os()

    def begin_specific_os(self, for_os):
        self.__set_for_os.append(for_os)

    def end_specific_os(self):
        self.__set_for_os.pop()

    def __add_some_item(self, item_category, item_value):
        self.__items[self.__set_for_os[-1]][item_category].append(item_value)

    def __some_items_list(self, which_items, for_os):
        """ common function to get items for specific category of items.
            returned is s list that combines the 'common' section with the section
            for the specific os.
        """
        retVal = unique_list()
        retVal.extend(self.__items[InstallItem.item_sections[0]][which_items])
        retVal.extend(self.__items[for_os][which_items])
        return retVal

    def add_inherit(self, inherit_idd):
        self.inherit.append(inherit_idd)

    def inherit_list(self):
        retVal = self.inherit
        return retVal

    def add_source(self, new_source, file_type='!dir'):
        if file_type not in InstallItem.file_types:
            file_type = '!dir'
        self.__add_some_item('install_sources', (new_source, file_type) )

    def source_list(self):
        return self.__some_items_list('install_sources', InstallItem.get_for_os)

    def add_folder(self, new_folder):
        self.__add_some_item('install_folders', new_folder )

    def folder_list(self):
        return self.__some_items_list('install_folders', InstallItem.get_for_os)

    def add_depend(self, new_depend):
        self.__add_some_item('depends', new_depend )

    def depend_list(self):
        return self.__some_items_list('depends', InstallItem.get_for_os)

    def add_action(self, action_type, new_action):
        if action_type not in InstallItem.action_types:
            raise KeyError("actions type must be one of: "+str(InstallItem.action_types)+" not "+where)
        self.__add_some_item(action_type, new_action)

    def read_actions(self, action_nodes):
        for action_type, new_actions in action_nodes:
            for action in new_actions:
                self.add_action(action_type, action.value)

    def action_list(self, action_type):
        if action_type not in InstallItem.action_types:
            raise KeyError("actions type must be one of: "+str(InstallItem.action_types)+" not "+which)
        return self.__some_items_list(action_type, InstallItem.get_for_os)

    def get_recursive_depends(self, items_map, out_set, orphan_set):
        if self.iid not in out_set:
            out_set.append(self.iid)
            for depend in self.depend_list():
                if depend not in out_set: # avoid cycles, save time
                    try:
                        items_map[depend].get_recursive_depends(items_map, out_set, orphan_set)
                    except KeyError:
                        orphan_set.append(depend)


    def repr_for_yaml_items(self, for_what):
        retVal = None
        if self.__items[for_what]:
            retVal = OrderedDict()
            if self.__items[for_what]['install_sources']:
                source_list = list()
                for source in self.__items[for_what]['install_sources']:
                    if source[1] != '!dir':
                        source_list.append(aYaml.augmentedYaml.YamlDumpWrap(value=source[0], tag=source[1]))
                    else:
                        source_list.append(source[0])
                retVal['install_sources'] = source_list
            if self.__items[for_what]['install_folders']:
                retVal['install_folders'] = list(self.__items[for_what]['install_folders'])
            if self.__items[for_what]['depends']:
                retVal['depends'] = list(self.__items[for_what]['depends'])
            for action in InstallItem.action_types:
                if action in self.__items[for_what] and self.__items[for_what][action]:
                    actions_dict = retVal.setdefault('actions', OrderedDict())
                    actions_dict[action] = list(self.__items[for_what][action])
        return retVal

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['name'] = self.name
        if self.guid:
            retVal['guid'] = self.guid
        if self.remark:
            retVal['remark'] = self.remark
        if self.inherit:
            retVal['inherit'] = self.inherit_list()

        common_items = self.repr_for_yaml_items(InstallItem.item_sections[0])
        if common_items:
            retVal.update(common_items)
        for os_ in InstallItem.item_sections[1:]:
            os_items = self.repr_for_yaml_items(os_)
            if os_items:
                retVal[os_] = os_items

        return retVal

    def merge_from_another_InstallItem(self, otherInstallItem):
        """ merge the contents of another InstallItem """
        # self.iid = iid is not merged
        # self.name = name is not merged
        # self.guid = guid is not merged
        # name of the other item is added to the remark
        if not self.remark:
            self.remark = self.name
        self.remark += ", "+otherInstallItem.name
        self.inherit.update(otherInstallItem.inherit)
        self.merge_all_item_sections(otherInstallItem)

    def resolve_inheritance(self, InstallItemsDict):
        if not self.__resolved_inherit:
            if self.iid in self.resolve_inheritance_stack:
                raise Exception("circular resolve_inheritance of "+self.iid)
            self.resolve_inheritance_stack.append(self.iid)
            for ancestor in self.inherit_list():
                if ancestor not in InstallItemsDict:
                    raise KeyError(self.iid+" inherites from "+ancestor+" which is not in InstallItemsDict")
                ancestor_item = InstallItemsDict[ancestor]
                ancestor_item.resolve_inheritance(InstallItemsDict)
                self.merge_all_item_sections(ancestor_item)
                self.remark += ", "+ancestor_item.name+", "+ancestor_item.remark
            self.resolve_inheritance_stack.pop()


"""
            if 'inherit' in my_node:
                for inheritIDD in my_node['inherit']:
                    try:
                        self.read_from_yaml_by_idd(inheritIDD.value, all_items_node)
                    except KeyError as ke:
                        missingIDDMessage = "While reading "+IID+", Inheritance IID '"+ke.message+" " +my_node['inherit'].start_mark
                        raise KeyError(missingIDDMessage)
"""
