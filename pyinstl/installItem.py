import sys
import platform
import yaml

sys.path.append("..")
from aYaml import augmentedYaml

current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'mac';
elif current_os == 'Windows':
    current_os = 'win';

def read_yaml_items_map(all_items_node):
    retVal = {}
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
    __slots__ = ("guid", "name", "install_sources", "install_folders", "depends", "description")
    def __init__(self):
        self.guid = None
        self.name = None
        self.install_sources = []
        self.install_folders = []
        self.depends = []
        self.description = ""

    def read_from_yaml_by_guid(self, GUID, all_items_node):
        my_node = all_items_node[GUID]
        self.read_from_yaml(my_node, all_items_node)
        self.guid = GUID # restore the GUID that might have been overwritten by inheritance
        self.description = str(my_node.start_mark)

    def read_from_yaml(self, my_node, all_items_node):
        if "inherit" in my_node:
            for inheriteGUID in my_node["inherit"]:
                try:
                    self.read_from_yaml_by_guid(inheriteGUID.value, all_items_node)
                except KeyError as ke:
                    missingGUIDMessage = "While reading "+GUID+", Inheritance GUID '"+ke.message+" " +my_node["inherit"].start_mark
                    raise KeyError(missingGUIDMessage)
        if "name" in my_node:
            self.name = my_node["name"].value
        if "install_sources" in my_node:
            for source in my_node["install_sources"]:
                self.add_source(source.value)
        if "install_folders" in my_node:
            for folder in my_node["install_folders"]:
                self.add_folder(folder.value)
        if "depends" in my_node:
            for source in my_node["depends"]:
                self.add_depend(source.value)
        if current_os in my_node:
            self.read_from_yaml(my_node[current_os], all_items_node)

    def add_source(self, new_source):
        if new_source not in self.install_sources:
            self.install_sources.append(new_source)

    def add_folder(self, new_folder):
        if new_folder not in self.install_folders:
            self.install_folders.append(new_folder)

    def add_depend(self, new_depend):
        if new_depend not in self.depends:
            self.depends.append(new_depend)

    def get_recursive_depends(self, items_map, out_set, orphan_set):
        if self.guid not in out_set:
            out_set.add(self.guid)
            for depend in self.depends:
                if depend not in out_set: # avoid cycles
                    try:
                        items_map[depend].get_recursive_depends(items_map, out_set, orphan_set)
                    except KeyError:
                        orphan_set.add(depend)

    def source_list(self):
        return self.install_sources

    def folder_list(self):
        return self.install_folders

    def repr_for_yaml(self):
        retVal = dict()
        retVal["name"] = self.name
        if self.install_sources:
            retVal["install_sources"] = self.install_sources
        if self.install_folders:
            retVal["install_folders"] = self.install_folders
        if self.depends:
            retVal["depends"] = self.depends
        return retVal
