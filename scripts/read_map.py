#!/usr/local/bin/python

from __future__ import print_function

import sys
import os
import platform
import yaml

import augmentedYaml

current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'mac';
elif current_os == 'Windows':
    current_os = 'win';


def replace_all_from_dict(in_text, **in_replacement_dic):
    """ replace all occurrences of the values in in_replace_only_these
        with the values in in_replacement_dic. If in_replace_only_these is empty
        use in_replacement_dic.keys() as the list of values to replace."""
    retVal = in_text
    for look_for in in_replacement_dic:
        retVal = retVal.replace(look_for, in_replacement_dic[look_for])
    return retVal

class InstallDef(object):
    __slots__ = ("guid", "name", "install_sources", "install_targets", "depends")
    def __init__(self):
        self.guid = None 
        self.name = None 
        self.install_sources = None 
        self.install_targets = None 
        self.depends = None 
    
    def to_python(self):
        retVal = {}
        if self.name:
            retVal['name'] = self.name
        else:
            retVal['name'] = "unnamed"
        if self.install_sources:
            if len(self.install_sources) == 1:
                retVal['install_sources'] = self.install_sources[0]
            else:
                retVal['install_sources'] = self.install_sources
        if self.install_targets:
            if len(self.install_targets) == 1:
                retVal['install_targets'] = self.install_targets[0]
            else:
                retVal['install_targets'] = self.install_targets
        if self.depends:
            if len(self.depends) == 1:
                retVal['depends'] = self.depends[0]
            else:
                retVal['depends'] = self.depends
        return retVal
        
    def resolve(self, def_map):
        if self.install_sources:
            self.install_sources = [replace_all_from_dict(source_text, **def_map) for source_text in self.install_sources]
        
        if self.install_targets:
            self.install_targets = [replace_all_from_dict(source_text, **def_map) for source_text in self.install_targets]
        
        if self.depends:
            self.depends = [replace_all_from_dict(source_text, **def_map) for source_text in self.depends]
        
    def read_from_yaml_by_guid(self, GUID, all_nodes):
        if GUID and GUID not in all_nodes:
            missingGUIDMessage = "'"+GUID+"' was not found in map"
            raise KeyError(missingGUIDMessage)
        my_node = all_nodes[GUID]
        self.read_from_yaml(my_node, all_nodes)
        self.guid = GUID # restore the GUID that might have been overwritten by inheritance 
    
    def read_from_yaml(self, my_node, all_nodes):
        if "inherit" in my_node:
            for inheriteGUID in my_node["inherit"]:
                try:
                    self.read_from_yaml_by_guid(inheriteGUID.value, all_nodes)
                except KeyError as ke:
                    missingGUIDMessage = "While reading "+GUID+", Inheritance GUID '"+ke.message+" " +my_node["inherit"].start_mark
                    raise KeyError(missingGUIDMessage)
        if "name" in my_node:
            self.name = my_node["name"].value
        if "install_sources" in my_node:
            for source in my_node["install_sources"]:
                self.add_source(source.value)
        if "install_targets" in my_node:
            for source in my_node["install_targets"]:
                self.add_target(source.value)
        if "depends" in my_node:
            for source in my_node["depends"]:
                self.add_depend(source.value)
        if current_os in my_node:
            self.read_from_yaml(my_node[current_os], all_nodes)
            
    def add_source(self, new_source):
        if not self.install_sources:
            self.install_sources = []
        if new_source not in self.install_sources:
            self.install_sources.append(new_source)
            
    def add_target(self, new_target):
        if not self.install_targets:
            self.install_targets = []
        if new_target not in self.install_targets:
            self.install_targets.append(new_target)
            
    def add_depend(self, new_depend):
        if not self.depends:
            self.depends = []
        if new_depend not in self.depends:
            self.depends.append(new_depend)
    
    def source_list(self):
        if not self.install_sources:
            return []
        else:
            return self.install_sources
    
    def target_list(self):
        if not self.install_targets:
            return []
        else:
            return self.install_targets

        
def read_map_yaml(a_node, install_db_map):
    for GUID, defi_node in a_node:
        instDef = InstallDef()
        instDef.read_from_yaml_by_guid(GUID, a_node)
        install_db_map[GUID] = instDef
        
def read_map_file(map_file_path, install_db_map):
    with open(map_file_path, "r") as map_fd:
        for a_node in yaml.compose_all(map_fd):
            read_map_yaml(a_node, install_db_map)

def read_def_yaml(a_node, var_definitions, install_list):
    for def_name, def_node in a_node:
        if def_node.isScalar():
            var_definitions["$("+def_name+")"] = def_node.value
        elif def_node.isSequence() and def_name == "install":
            install_list.extend([node.value for node in def_node])

def read_def_file(def_file_path, var_definitions, install_list):
    with open(def_file_path, "r") as map_fd:
        for a_node in yaml.compose_all(map_fd):
            read_def_yaml(a_node, var_definitions, install_list)

def create_install_by_folder(install_db_map, install_by_folder):
    for GUID in install_db_map:
        for target in install_db_map[GUID].target_list():
            if not target in install_by_folder:
                install_by_folder[target] = [GUID]
            else:
                if GUID not in install_by_folder:
                    install_by_folder[target].append(GUID)
        
def create_install_batch(install_by_folder, install_db_map):
    retVal = []
    retVal.append("SAVE_DIR=`pwd`")
    for folder in install_by_folder:
        retVal.append(" ".join(("mkdir", "-p", "'"+folder+"'")))
        retVal.append(" ".join(("cd", "'"+folder+"'")))
        for GUID in install_by_folder[folder]:
            installi = install_db_map[GUID]
            for source in installi.source_list():
                retVal.append(" ".join(("svn", "checkout", "--revision", "HEAD", "'"+"$(BASE_URL)"+source+"'")))
    retVal.append("cd ${SAVE_DIR}")
    return retVal

if __name__ == "__main__":
    install_db_map = {}
    if len(sys.argv) > 1:
        map_file_path = sys.argv[1]
        read_map_file(map_file_path, install_db_map)

    if len(sys.argv) > 2:
        def_file_path = sys.argv[2]
        var_definitions = {}
        install_list = []
        read_def_file(def_file_path, var_definitions, install_list)
 
    install_by_folder = {}
    create_install_by_folder(install_db_map, install_by_folder)
    install_batch_list = create_install_batch(install_by_folder, install_db_map)
    install_batch_text = os.linesep.join(install_batch_list)
    install_batch_text = replace_all_from_dict(install_batch_text, **var_definitions)
    print (install_batch_text)
