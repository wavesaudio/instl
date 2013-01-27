#!/usr/local/bin/python2.7

from __future__ import print_function

import os
import sys
import appdirs
import readline
import cmd
import logging
import glob

import instlInstanceBase
from aYaml import augmentedYaml

def insensitive_glob(pattern):
    def either(c):
        return '[%s%s]'%(c.lower(),c.upper()) if c.isalpha() else c
    return glob.glob(''.join(map(either,pattern)))

def go_interactive(instl_inst):
    instlInstanceBase.InstlInstanceBase.create_completion_list = create_completion_list_imp
    instlInstanceBase.InstlInstanceBase.do_list = do_list_imp
    with instlCMD(instl_inst) as icmd:
        icmd.cmdloop()

class instlCMD(cmd.Cmd, object):
    def __init__(self, instl_inst):
        cmd.Cmd.__init__(self)
        self.instl_inst = instl_inst

    def __enter__(self):
        readline.parse_and_bind ("bind ^I rl_complete") # Enable tab completions on MacOS
        readline.parse_and_bind("tab: complete")        # and on other OSs
        history_file_dir = appdirs.user_data_dir("instl")
        try:
            os.makedirs(history_file_dir)
        except: # os.makedirs raises is the directory already exists
            pass
        self.history_file_path = os.path.join(history_file_dir, ".instl_console_history")
        if os.path.isfile(self.history_file_path):
            readline.read_history_file(self.history_file_path)
        self.prompt = "instl: "
        return self

    def __exit__(self, type, value, traceback):
        readline.set_history_length(1024)
        readline.write_history_file(self.history_file_path)

    def path_completion(self, text, line, begidx, endidx):
        matches = []
        if text:
            try:
                matches.extend(insensitive_glob(text+'*'))
            except Exception as es:
                logging.info(es)
        return matches

    def do_shell(self, s):
        os.system(s)

    def help_shell(self):
        print("execute shell commands")

    def do_cd(self, s):
        os.chdir(s)

    def complete_cd(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)
        
    def help_cd(self):
        print("cd path, change current directory")

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
        return self.path_completion(text, line, begidx, endidx)
        
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

    # evaluate python expressions
    def do_eval(self, param):
        print(eval(param))

    def help_eval(self):
        print("evaluate python expressions, instlInstance is accessible as self.instl_inst")

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
