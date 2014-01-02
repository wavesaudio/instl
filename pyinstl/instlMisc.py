#!/usr/bin/env python2.7

from __future__ import print_function

from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *

from instlInstanceBase import InstlInstanceBase
from pyinstl import svnTree

class InstlMisc(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlMisc, self).__init__(initial_vars)
        self.cvl.set_variable("__ALLOWED_COMMANDS__").extend( ('create_readlinks', 'resolve_readlinks', 'version') )
        self.svnTree = svnTree.SVNTree()

    @func_log_wrapper
    def do_command(self):
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        if the_command in self.cvl.get_list("__ALLOWED_COMMANDS__"):
            #print("server_commands", the_command)
            if the_command == "create_readlinks":
                self.do_create_readlinks()
            elif the_command == "resolve_readlinks":
                self.do_resolve_readlinks()
            elif the_command == "version":
                self.do_version()

    def do_version(self):
        print(self.get_version_str())

    def do_create_readlinks(self):
        folder_to_work_on = self.cvl.get_str("__MAIN_INPUT_FILE__")
        map_file_path					= 'instl/info_map.txt'
        info_map_path = "/".join( (folder_to_work_on, map_file_path) )
        self.svnTree.read_info_map_from_file(info_map_path, format='text')
        for item in self.svnTree.walk_items():
            if item.isSymlink():
                link_full_path = "/".join( (folder_to_work_on, item.full_path()) )
                if os.path.islink(link_full_path):
                    link_value = os.readlink(link_full_path)
                    readlink_file_path = link_full_path+".readlink"
                    open(readlink_file_path, "w").write(link_value)
                    os.unlink(link_full_path)

    def do_resolve_readlinks(self):
        folder_to_work_on = self.cvl.get_str("__MAIN_INPUT_FILE__")
        map_file_path					= 'instl/info_map.txt'
        info_map_path = "/".join( (folder_to_work_on, map_file_path) )
        self.svnTree.read_info_map_from_file(info_map_path, format='text')
        for item in self.svnTree.walk_items():
            if item.isSymlink():
                link_full_path = "/".join( (folder_to_work_on, item.full_path()) )
                print("link file:", link_full_path)
                readlink_file_path = link_full_path+".readlink"
                print("readlink file:", readlink_file_path)
                link_value = open(readlink_file_path, "r").read()
                print("link value:", link_value)
                if os.path.islink(link_full_path):
                    os.unlink(link_full_path)
                os.symlink(link_value, link_full_path)
                os.unlink(readlink_file_path)
                print()
