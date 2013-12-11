#!/usr/bin/env python2.7

from __future__ import print_function
import datetime

from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *

from instlInstanceBase import InstlInstanceBase
from pyinstl import svnTree

map_info_extension_to_format = {"txt" : "text", "text" : "text",
                "inf" : "info", "info" : "info",
                "yml" : "yaml", "yaml" : "yaml",
                "pick" : "pickle", "pickl" : "pickle", "pickle" : "pickle",
                "props" : "props", "prop" : "props"
                }

class InstlAdmin(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlAdmin, self).__init__(initial_vars)
        self.cvl.set_variable("__ALLOWED_COMMANDS__").extend( ('trans', 'createlinks') )
        self.svnTree = svnTree.SVNTree()

    @func_log_wrapper
    def do_command(self):
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        if the_command in self.cvl.get_list("__ALLOWED_COMMANDS__"):
            #print("server_commands", the_command)
            if the_command == "trans":
                self.read_info_map_file(self.cvl.get_str("__MAIN_INPUT_FILE__"))
                if "__PROPS_FILE__" in self.cvl:
                    self.read_info_map_file(self.cvl.get_str("__PROPS_FILE__"))
                self.filter_out_info_map(self.cvl.get_list("__FILTER_OUT_PATHS__"))
                self.write_info_map_file()
            elif the_command == "createlinks":
                self.create_links()


    def read_info_map_file(self, in_file_path):
        _, extension = os.path.splitext(in_file_path)
        input_format = map_info_extension_to_format[extension[1:]]
        self.svnTree.comments.append("Original file "+in_file_path)
        self.svnTree.comments.append("      read on "+datetime.datetime.today().isoformat())
        self.svnTree.read_info_map_from_file(in_file_path, format=input_format)

    def write_info_map_file(self):
        _, extension = os.path.splitext(self.cvl.get_str("__MAIN_OUT_FILE__"))
        output_format = map_info_extension_to_format[extension[1:]]
        self.svnTree.write_to_file(self.cvl.get_str("__MAIN_OUT_FILE__"), in_format=output_format)

    def filter_out_info_map(self, paths_to_filter_out):
        for path in paths_to_filter_out:
            self.svnTree.remove_item_at_path(path)

    def create_links(self):
        print("createlinks", self.cvl.get_str("__SVN_URL__"), self.cvl.get_str("__ROOT_LINKS_FOLDER__"), self.cvl.get_str("__REPO_REV__"))
