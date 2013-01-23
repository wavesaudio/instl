#!/usr/local/bin/python2.7

from __future__ import print_function

import os
import sys
import appdirs
import readline

import instlInstanceBase
from aYaml import augmentedYaml

def go_interactive(instl_inst):
    instlInstanceBase.InstlInstanceBase.parse_console_command = parse_console_command_imp
    instlInstanceBase.InstlInstanceBase.create_completion_list = create_completion_list_imp
    instlInstanceBase.InstlInstanceBase.do_list = do_list_imp
    with SetupConsole(instl_inst):
        goOn = True
        while goOn:
            inStr = raw_input("instl $ ")
            if inStr.lower() == "q" or inStr.lower() == "quit":
                goOn = False
            else:
                instl_inst.parse_console_command(inStr)

def parse_console_command_imp(self, inStr):
    command_parts = inStr.split()
    if command_parts[0] in self.install_definitions_map:
        pass
    elif command_parts[0] in self.cvl:
        pass
    elif command_parts[0] == "list":
        self.do_list()
    elif command_parts[0] == "read":
        if len(command_parts) > 1:
            for file in command_parts[1:]:
                self.read_file(file)
                self.resolve()
        else:
            print("Usage: read path_to_file1 [path_to_file [...]]")
    """
    if command_parts[0] == "read":
        if len(command_parts) > 1:
            read_myke_file(in_var_list, " ".join(command_parts[1:]))
        else:
            print("read what?")
    elif command_parts[0] == "print":
        if len(command_parts) > 1:
            valToPrint = in_var_list.resolve_string(" ".join(command_parts[1:]))
        else:
            dumpVarList(in_var_list)
    else:
        print("'"+command_parts[0]+"'", "unknown command")
    """

def do_list_imp(self):
    augmentedYaml.writeAsYaml(self, sys.stdout)

command_list = ["read", "write"]
def create_completion_list_imp(self):
    retVal = list(command_list)
    try:
        retVal.extend(self.install_definitions_map.keys())
        retVal.extend(self.cvl.keys())
        retVal.extend(os.listdir(os.getcwd()))
    except Exception as ex:
        print("create_completion_list:",   ex)
    return retVal
    
class SimpleCompleter(object):

    def __init__(self, instl_instance):
        self.instl_instance = instl_instance

    def complete(self, text, state):
        response = None
        if state == 0:
            # This is the first time for this text, so build a match list.
            try:
                completion_list = self.instl_instance.create_completion_list()
            except Exception as ex:
                print("except", ex)
                completion_list = []
            if text:
                self.matches = [s
                                for s in completion_list
                                if s and s.lower().startswith(text.lower())]
            else:
                self.matches = completion_list[:]

        # Return the state'th item from the match list,
        # if we have that many.
        try:
            response = self.matches[state]
        except IndexError:
            response = None
        return response

class SetupConsole(object):
    def __init__(self, instl_instance):
        self.instl_instance = instl_instance
    def __enter__(self):
        readline.parse_and_bind ("bind ^I rl_complete") # Enable tab completions on MacOS
        readline.parse_and_bind("tab: complete")        # and on other OSs
        readline.set_completer(SimpleCompleter(self.instl_instance).complete)
        history_file_dir = appdirs.user_data_dir("instl")
        try:
            os.makedirs(history_file_dir)
        except: # os.makedirs raises is the directory already exists
            pass
        self.history_file_path = os.path.join(history_file_dir, ".inslt_console_history")
        if os.path.isfile(self.history_file_path):
            readline.read_history_file(self.history_file_path)
    def __exit__(self, type, value, traceback):
        readline.set_history_length(1024)
        readline.write_history_file(self.history_file_path)
