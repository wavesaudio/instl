#!/usr/local/bin/python2.7

from __future__ import print_function

"""
    class InstallItem hold information about how to install one or more sources.
    information include:
        guid - must be unique amongst all InstallItems.
        name - description for log and erros messages has no bering on the installation.
        license - the license guid, so the item can be identified by licensing system.
                  license can be different from or identical to the guid.
        remark - remarks for human consumption has no bering on the installation.
        description - auto generated, usually the file and line from which the item was read.
        inherit - guids of other InstallItems to inherit from.
        These fields appear once for each InstallItem.
    Further fields can be be found in a common section or in a section for specific OS:
        sources - sources to install.
        folders - folders to install the sources to.
        depends - guids of other InstallItems that must be installed before the current item.
        actions - actions to preform. These actions are further divided into:
            folder_in - actions to preform before installing to each folder in 'folders' section.
                        if several InstallItems have the same actions for the folder, each action
                        will be preformed only once.
            folder_out - actions to preform after installing to each folder in 'folders' section.
                        if several InstallItems have the same actions for the folder, each action
                        will be preformed only once.
            before -    actions to preform before installing the sources in each folder.
            after -    actions to preform after installing the sources in each folder.
    Except guid field, all fields are optional.
"""

import sys
import platform
import yaml
import aYaml
from collections import OrderedDict, defaultdict

sys.path.append("..")
from aYaml import augmentedYaml

current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'mac';
elif current_os == 'Windows':
    current_os = 'win';

def read_index_from_yaml(all_items_node):
    retVal = dict() #OrderedDict()
    for GUID in all_items_node.iterkeys():
        if GUID in retVal:
            pass#print(GUID, "already in all_items_node")
        else:
            #print(GUID, "not in all_items_node")
            item = InstallItem()
            item.read_from_yaml_by_guid(GUID, all_items_node)
            retVal[GUID] = item
    return retVal


class InstallItem(object):
    __slots__ = ('guid', 'name', 'license',
                'remark', "description", 'inherit',
                '__set_for_os', '__items', '__resolved_inherit')
    item_sections = ('common', 'mac', 'win')
    item_types = ('sources', 'folders', 'depends', 'actions')
    action_types = ('folder_in', 'before', 'after', 'folder_out')
    file_types = ('!file', '!dir')
    get_for_os = current_os
    resolve_inheritance_stack = list()

    @staticmethod
    def create_items_section():
        retVal = defaultdict(set)
        return retVal

    def merge_item_sections(self, this_items, the_other_items):
        common_items = set(this_items.keys() + the_other_items.keys())
        for item in common_items:
            this_items[item].update(the_other_items[item])

    def __init__(self):
        self.__resolved_inherit = False
        self.guid = None
        self.name = None
        self.license = None
        self.remark = None
        self.description = ""
        self.inherit = set()
        self.__set_for_os = [InstallItem.item_sections[0]] # reading for all platforms ('common') or for which specific platforms ('mac', 'win')?
        self.__items = defaultdict(InstallItem.create_items_section)

    def read_from_yaml_by_guid(self, GUID, all_items_node):
        my_node = all_items_node[GUID]
        self.read_from_yaml(my_node)
        self.guid = GUID # restore the GUID that might have been overwritten by inheritance
        self.description = str(my_node.start_mark)

    def read_from_yaml(self, my_node):
        if 'inherit' in my_node:
            for inheritoree in my_node['inherit'].value:
                self.add_inherit(inheritoree.value)
        if 'name' in my_node:
            self.name = my_node['name'].value
        if 'license' in my_node:
            self.license = my_node['license'].value
        if 'remark' in my_node:
            self.remark = my_node['remark'].value
        if 'install_from' in my_node:
            for source in my_node['install_from']:
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

    def add_some_item(self, item_category, item_value):
        self.__items[self.__set_for_os[-1]][item_category].add(item_value)

    def __some_items_list(self, which_items, for_os):
        """ common function to get items for specific category of items.
            returned is s list that combines the 'common' section with the section
            for the specific os.
        """
        retVal = list(self.__items[InstallItem.item_sections[0]][which_items].union(self.__items[for_os][which_items]))
        return retVal

    def add_inherit(self, inherit_guid):
        self.inherit.add(inherit_guid)

    def inherit_list(self):
        retVal = sorted(list(self.inherit))
        return retVal

    def add_source(self, new_source, file_type='!dir'):
        if file_type not in InstallItem.file_types:
            file_type = '!dir'
        self.add_some_item('sources', (new_source, file_type) )

    def source_list(self):
        return self.__some_items_list('sources', InstallItem.get_for_os)

    def add_folder(self, new_folder):
        self.add_some_item('folders', new_folder )

    def folder_list(self):
        return self.__some_items_list('folders', InstallItem.get_for_os)

    def add_depend(self, new_depend):
        self.add_some_item('depends', new_depend )

    def depend_list(self):
        return self.__some_items_list('depends', InstallItem.get_for_os)

    def add_action(self, action_type, new_action):
        if action_type not in InstallItem.action_types:
            raise KeyError("actions type must be one of: "+str(InstallItem.action_types)+" not "+where)
        self.add_some_item(action_type, new_action)

    def read_actions(self, action_nodes):
        for action_type, new_actions in action_nodes:
            for action in new_actions:
                self.add_action(action_type, action.value)

    def action_list(self, action_type):
        if action_type not in InstallItem.action_types:
            raise KeyError("actions type must be one of: "+str(InstallItem.action_types)+" not "+which)
        return self.__some_items_list('action_type', InstallItem.get_for_os)

    def get_recursive_depends(self, items_map, out_set, orphan_set):
        if self.guid not in out_set:
            out_set.add(self.guid)
            for depend in self.__items['depends']:
                if depend not in out_set: # avoid cycles
                    try:
                        items_map[depend].get_recursive_depends(items_map, out_set, orphan_set)
                    except KeyError:
                        orphan_set.add(depend)

    def repr_for_yaml_items(self, for_what):
        retVal = None
        if self.__items[for_what]:
            retVal = OrderedDict()
            if self.__items[for_what]['sources']:
                source_list = list()
                for source in sorted(self.__items[for_what]['sources']):
                    if source[1] != '!dir':
                        source_list.append(aYaml.augmentedYaml.YamlDumpWrap(value=source[0], tag=source[1]))
                    else:
                        source_list.append(source[0])
                retVal['install_from'] = source_list
            if self.__items[for_what]['folders']:
                retVal['install_folders'] = sorted(self.__items[for_what]['folders'])
            if self.__items[for_what]['depends']:
                retVal['depends'] = sorted(list(self.__items[for_what]['depends']))
            for action in InstallItem.action_types:
                if action in self.__items[for_what] and self.__items[for_what][action]:
                    actions_dict = retVal.setdefault('actions', OrderedDict())
                    actions_dict[action] = sorted(list(self.__items[for_what][action]))
        return retVal

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['name'] = self.name
        if self.license:
            retVal['license'] = self.license
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

    def resolve_inheritance(self, InstallItemsDict):
        if not self.__resolved_inherit:
            if self.guid in self.resolve_inheritance_stack:
                raise Exception("circular resolve_inheritance of "+self.guid)
            self.resolve_inheritance_stack.append(self.guid)
            for ancestor in self.inherit_list():
                if ancestor not in InstallItemsDict:
                    raise KeyError(self.guid+" inherites from "+ancestor+" which is not in InstallItemsDict")
                ancestor_item = InstallItemsDict[ancestor]
                ancestor_item.resolve_inheritance(InstallItemsDict)
                for section in InstallItem.item_sections:
                    self.merge_item_sections(self.__items[section], ancestor_item.__items[section])
            self.resolve_inheritance_stack.pop()


"""
            if 'inherit' in my_node:
                for inheritGUID in my_node['inherit']:
                    try:
                        self.read_from_yaml_by_guid(inheritGUID.value, all_items_node)
                    except KeyError as ke:
                        missingGUIDMessage = "While reading "+GUID+", Inheritance GUID '"+ke.message+" " +my_node['inherit'].start_mark
                        raise KeyError(missingGUIDMessage)
"""
