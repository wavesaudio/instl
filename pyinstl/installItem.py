#!/usr/local/bin/python2.7

from __future__ import print_function

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
                'remark', "description", "set_for_os", 
                '__items')
    action_types = ('folder_in', 'before', 'after', 'folder_out')
    file_types = ('!file', '!dir')
    get_for_os = current_os

    @staticmethod
    def create_items_section():
        retVal = {'sources': set(),
                      'folders': set(),
                      'depends': set(),
                      'actions': defaultdict(set)
                      }
        return retVal

    def __init__(self):
        self.guid = None
        self.name = None
        self.license = None
        self.remark = None
        self.description = ""
        self.set_for_os = ['common'] # reading for all platforms ('common') or for which specific platforms ('mac', 'win')?
        self.__items = defaultdict(InstallItem.create_items_section)

    def read_from_yaml_by_guid(self, GUID, all_items_node):
        my_node = all_items_node[GUID]
        self.read_from_yaml(my_node, all_items_node)
        self.guid = GUID # restore the GUID that might have been overwritten by inheritance
        self.description = str(my_node.start_mark)

    def read_from_yaml(self, my_node, all_items_node):
        if 'inherit' in my_node:
            for inheriteGUID in my_node['inherit']:
                try:
                    self.read_from_yaml_by_guid(inheriteGUID.value, all_items_node)
                except KeyError as ke:
                    missingGUIDMessage = "While reading "+GUID+", Inheritance GUID '"+ke.message+" " +my_node['inherit'].start_mark
                    raise KeyError(missingGUIDMessage)
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
        if 'mac' in my_node:
            self.begin_specific_os('mac')
            self.read_from_yaml(my_node['mac'], all_items_node)
            self.end_specific_os()
        if 'win' in my_node:
            self.begin_specific_os('win')
            self.read_from_yaml(my_node['win'], all_items_node)
            self.end_specific_os()

    def begin_specific_os(self, for_os):
        self.set_for_os.append(for_os)

    def end_specific_os(self):
        self.set_for_os.pop()

    def some_items_list(self, which_items, for_os):
        retVal = list(self.__items['common'][which_items].union(self.__items[for_os][which_items]))
        return retVal

    def add_source(self, new_source, file_type='!dir'):
        if file_type not in InstallItem.file_types:
            file_type = '!dir'
        self.__items[self.set_for_os[-1]]['sources'].add( (new_source, file_type) )

    def source_list(self):
        return self.some_items_list('sources', InstallItem.get_for_os)

    def add_folder(self, new_folder):
        self.__items[self.set_for_os[-1]]['folders'].add(new_folder)

    def folder_list(self):
        return self.some_items_list('folders', InstallItem.get_for_os)

    def add_depend(self, new_depend):
        self.__items[self.set_for_os[-1]]['depends'].add(new_depend)

    def depend_list(self):
        return self.some_items_list('depends', InstallItem.get_for_os)

    def add_action(self, where, action):
        if where in InstallItem.action_types:
            self.__items[self.set_for_os[-1]]['actions'][where].append(action)
        else:
            raise KeyError("actions type must be one of: "+str(InstallItem.action_types)+" not "+where)

    def read_actions(self, action_nodes):
        for action_pair in action_nodes:
            if action_pair[0] in InstallItem.action_types:
                for action in action_pair[1]:
                    self.__items[self.set_for_os[-1]]['actions'][action_pair[0]].add(action.value)
            else:
                raise KeyError("actions type must be one of: "+str(InstallItem.action_types)+" not "+action_pair[0])

    def action_list(self, which):
        if which not in InstallItem.action_types:
            raise KeyError("actions type must be one of: "+str(InstallItem.action_types)+" not "+which)
        retVal = list(self.__items['common']['actions'][which].union(self.__items[InstallItem.get_for_os]['actions'][which]))
        return retVal

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
            if self.__items[for_what]['actions']:
                retVal['actions'] = OrderedDict()
                for action_type in InstallItem.action_types:
                    action_list_for_type = list(self.__items[for_what]['actions'][action_type])
                    if len(action_list_for_type) > 0:
                        retVal['actions'][action_type] = sorted(action_list_for_type)
        return retVal

    def repr_for_yaml(self):
        retVal = OrderedDict()
        retVal['name'] = self.name
        if self.license:
            retVal['license'] = self.license
        if self.remark:
            retVal['remark'] = self.remark

        common_items = self.repr_for_yaml_items('common')
        retVal.update(common_items)
        for os_ in ('mac', 'win'):
            os_items = self.repr_for_yaml_items(os_)
            if os_items:
                retVal[os_] = os_items

        return retVal
