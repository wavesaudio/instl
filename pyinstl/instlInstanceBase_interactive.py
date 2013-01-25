#!/usr/local/bin/python2.7

from __future__ import print_function

import os
import sys
import appdirs
import readline
import cmd

import instlInstanceBase
from aYaml import augmentedYaml

def go_interactive(instl_inst):
    instlInstanceBase.InstlInstanceBase.create_completion_list = create_completion_list_imp
    instlInstanceBase.InstlInstanceBase.do_list = do_list_imp
    with instlCMD(instl_inst) as icmd:
        icmd.cmdloop()

class instlCMD(cmd.Cmd):
    def __init__(self, instl_inst):
        readline.parse_and_bind ("bind ^I rl_complete") # Enable tab completions on MacOS
        readline.parse_and_bind("tab: complete")        # and on other OSs
        cmd.Cmd.__init__(self)
        self.instl_inst = instl_inst

    def __enter__(self):
        history_file_dir = appdirs.user_data_dir("instl")
        try:
            os.makedirs(history_file_dir)
        except: # os.makedirs raises is the directory already exists
            pass
        self.history_file_path = os.path.join(history_file_dir, ".instl_console_history")
        if os.path.isfile(self.history_file_path):
            readline.read_history_file(self.history_file_path)
        return self

    def __exit__(self, type, value, traceback):
        readline.set_history_length(1024)
        readline.write_history_file(self.history_file_path)

    def do_list(self, params):
        if params:
            for param in params.split():
                if param[-1] == '*':
                    identifier_list = self.complete_print(param[:-1], params, 0, 0)
                    self.do_print(" ".join(identifier_list))
                else:
                    identifier_list = self.complete_print(param, params, 0, 0)
                    self.do_print(" ".join(identifier_list))
        else:
            self.instl_inst.do_list()
        return False

    def complete_list(self, text, line, begidx, endidx):
        matches = []
        completion_list = ["define", "index"] + self.instl_inst.create_completion_list()
        if text and completion_list:
            matches = [s for s in completion_list
                         if s and s.lower().startswith(text.lower())]
        return matches

    def help_list(self):
        print( "list define" )
        print( "    lists all definitions" )
        print( "list index" )
        print( "    lists all index entries" )
        print( "list" )
        print( "    lists all definitions & index entries" )
        print( "list indentifier[*]" )
        print( "    lists indentifier(*)" )

    def do_read(self, params):
        for file in params.split():
            try:
                self.instl_inst.read_file(file)
                self.instl_inst.resolve()
            except Exception as ex:
                print(ex)
        return False

    def complete_read(self, text, line, begidx, endidx):
        completion_list = os.listdir(os.getcwd())
        matches = [s
                    for s in completion_list
                    if s and s.lower().startswith(text.lower())]
        return matches

    def do_print(self, params):
        for param in params.split():
            if param in self.instl_inst.cvl:
                print(self.instl_inst.cvl.get_str(param))
            elif param in self.instl_inst.install_definitions_index.keys():
                augmentedYaml.writeAsYaml({param: self.instl_inst.install_definitions_index[param].repr_for_yaml()}, sys.stdout)
        return False

    def complete_print(self, text, line, begidx, endidx):
        matches = []
        completion_list = self.instl_inst.create_completion_list()
        if text and completion_list:
            matches = [s
                        for s in completion_list
                        if s and s.lower().startswith(text.lower())]
        return matches

    def do_quit(self, params):
        return True

    def do_q(self, params):
        return self.do_quit(params)

    def default(self, line):
        print("unknown command: ", line)
        return False

def do_list_imp(self, what = None):
    if what is None:
        augmentedYaml.writeAsYaml(self, sys.stdout)
    elif what == "define":
        augmentedYaml.writeAsYaml(augmentedYaml.YamlDumpDocWrap(self.cvl, '!define', "Definitions", explicit_start=True, sort_mappings=True), sys.stdout)
    elif what == "index":
        augmentedYaml.writeAsYaml(augmentedYaml.YamlDumpDocWrap(self.install_definitions_index, '!index', "Installation index", explicit_start=True, sort_mappings=True), sys.stdout)

def create_completion_list_imp(self):
    retVal = list()
    try:
        retVal.extend(self.install_definitions_index.keys())
        retVal.extend(self.cvl.keys())
    except Exception as ex:
        print("create_completion_list:",   ex)
    return retVal
