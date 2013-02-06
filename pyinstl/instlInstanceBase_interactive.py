#!/usr/local/bin/python2.7

from __future__ import print_function

import os
import sys
import appdirs
import logging
import shlex

import platform
current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'mac'
elif current_os == 'Windows':
    current_os = 'win'

try:
    import cmd
except:
    print("failed to import cmd, interactive mode not supported")
    raise

readline_loaded = False
try:
    import readline
    readline_loaded = True
except ImportError:
    try:
        import pyreadline as readline
        readline_loaded = True
    except ImportError:
        print("failed to import pyreadline, readline functionality not supported")


colorama_loaded = False
try:
    import colorama
    colorama_loaded = True
except ImportError:
    print("failed to import colorama, color text functionality not supported")

import instlInstanceBase
from aYaml import augmentedYaml

if colorama_loaded:
    colors = {'reset': colorama.Fore.RESET, 'green': colorama.Fore.GREEN, 'blue': colorama.Fore.BLUE, 'yellow': colorama.Fore.YELLOW, 'red': colorama.Fore.RED}

def text_with_color(text, color):
    retVal = text
    if colorama_loaded and color in colors:
        retVal = colors[color]+text+colors['reset']
    return retVal

def insensitive_glob(pattern):
    import glob
    def either(c):
        return '[%s%s]'%(c.lower(),c.upper()) if c.isalpha() else c
    return glob.glob(''.join(map(either,pattern)))


this_program_name = "instl"

def go_interactive(prog_inst):
    try:
        instlInstanceBase.InstlInstanceBase.create_completion_list = create_completion_list_imp
        instlInstanceBase.InstlInstanceBase.do_list = do_list_imp
        with CMDObj(prog_inst) as icmd:
            icmd.cmdloop()
    except Exception as es:
        import traceback
        tb = traceback.format_exc()
        print("go_interactive", es, tb)

def restart_program():
    """Restarts the current program.
        Note: this function does not return. Any cleanup action (like
        saving data) must be done before calling this function."""
    python = sys.executable
    os.execl(python, python, * sys.argv)

class CMDObj(cmd.Cmd, object):
    def __init__(self, prog_inst):
        cmd.Cmd.__init__(self)
        self.prog_inst = prog_inst
        self.restart = False
        self.prog_inst.resolve()

    def __enter__(self):
        if readline_loaded:
            readline.parse_and_bind ("bind ^I rl_complete") # Enable tab completions on MacOS
            readline.parse_and_bind("tab: complete")        # and on other OSs
            readline.parse_and_bind("set completion-ignore-case on")
            readline.parse_and_bind("set show-all-if-ambiguous on")
            readline.parse_and_bind("set completion-map-case on")
            readline.parse_and_bind("set show-all-if-unmodified on")
            readline.parse_and_bind("set expand-tilde on")
            history_file_dir = appdirs.user_data_dir(this_program_name, this_program_name)
            try:
                os.makedirs(history_file_dir)
            except: # os.makedirs raises is the directory already exists
                pass
            self.history_file_path = os.path.join(history_file_dir, "."+this_program_name+"_console_history")
            if os.path.isfile(self.history_file_path):
                readline.read_history_file(self.history_file_path)
        if colorama_loaded:
            colorama.init()
        self.prompt = this_program_name+": "
        self.save_dir = os.getcwd()
        return self

    def __exit__(self, type, value, traceback):
        if readline_loaded:
            readline.set_history_length(1024)
            readline.write_history_file(self.history_file_path)
        # restart only after saving history, otherwise history will not be saved (8-().
        os.chdir(self.save_dir)
        if self.restart:
            restart_program()

    def path_completion(self, text, line, begidx, endidx):
        matches = []
        if text:
            try:
                matches.extend(insensitive_glob(text+'*'))
            except Exception as es:
                logging.info(es)
        return matches

    def dir_completion(self, text, line, begidx, endidx):
        matches = []
        if text:
            try:
                matches.extend([dir for dir in insensitive_glob(text+'*') if os.path.isdir(dir)])
            except Exception as es:
                logging.info(es)
        return matches

    def do_shell(self, s):
        if s:
            os.system(s)
        return False

    def help_shell(self):
        print("execute shell commands")

    def do_cd(self, s):
        if os.path.isdir(s):
            os.chdir(s)
        else:
            print(s, "is not a directory")
        return False

    def complete_cd(self, text, line, begidx, endidx):
        return self.dir_completion(text, line, begidx, endidx)

    def help_cd(self):
        print("cd path, change current directory")

    colors = {'reset': colorama.Fore.RESET, 'green': colorama.Fore.GREEN, 'blue': colorama.Fore.BLUE, 'yellow': colorama.Fore.YELLOW, 'red': colorama.Fore.RED}

    def prepare_coloring_dict(self):
        """ Prepare a dictionary with identifiers mapped to their "colored" representation.
            Left hand index enrties: 'C1_GUID:' translates to colorama.Fore.GREEN+'C1_GUID'+colorama.Fore.RESET+":".
            Right hand index enrties: '- C1_GUID:' translates to "- "+colorama.Fore.YELLOW+'C1_GUID'+colorama.Fore.RESET.
            Variable references: $(WAVES_PLUGINS_DIR) translates to colorama.Fore.BLUE+$(WAVES_PLUGINS_DIR).
            The returned disctionary can be used in replace_all_from_dict() for "coloring" the text before output to stdcout.
        """
        retVal = dict()
        defs = self.prog_inst.create_completion_list("define")
        index = self.prog_inst.create_completion_list("index")
        retVal.update({"$("+identi+")": text_with_color("$("+identi+")", "blue") for identi in defs})
        retVal.update({identi+":": text_with_color(identi, "green")+":" for identi in defs})
        retVal.update({"- "+identi: "- "+text_with_color(identi, "yellow") for identi in defs})
        
        retVal.update({dex+":": text_with_color(dex, "green")+":" for dex in index})
        retVal.update({"- "+dex: "- "+text_with_color(dex, "yellow") for dex in index})
        return retVal

    def color_vars(self, text):
        """ Add color codes to index identifiers and variables in text.
        """
        retVal = None
        try:
            coloring_dict = self.prepare_coloring_dict()
            from configVarList import replace_all_from_dict
            retVal = replace_all_from_dict(text, *[], **coloring_dict)
        except Exception as es:
            import traceback
            tb = traceback.format_exc()
            print("color_vars", es, tb)
        return retVal


    def do_list(self, params):
        try:
            from utils import write_to_list
            out_list = write_to_list()
            if params:
                for param in params.split():
                    if param[-1] == '*':
                        identifier_list = self.indentifier_completion_list(param[:-1], params, 0, 0)
                        self.prog_inst.do_list(identifier_list, out_list)
                    else:
                        identifier_list = self.indentifier_completion_list(param, params, 0, 0)
                        if identifier_list:
                            self.prog_inst.do_list(identifier_list, out_list)
                        else:
                            print("Unknown identifier:", param)
            else:
                self.prog_inst.do_list(None, out_list)
            colored_string = self.color_vars("".join(out_list.list()))
            sys.stdout.write(colored_string)
        except Exception as es:
            print("list", es)
        return False

    def indentifier_completion_list(self, text, line, begidx, endidx):
        matches = []
        if text:
            completion_list = self.prog_inst.create_completion_list()
            if completion_list:
                matches.extend([s for s in completion_list
                         if s and s.lower().startswith(text.lower())])
        return matches

    def complete_list(self, text, line, begidx, endidx):
        #print("complete_list, text:", text)
        matches = self.indentifier_completion_list(text, line, begidx, endidx)
        for s in ("define", "index"):
            if s.lower().startswith(text.lower()):
                matches.append(s)
        return matches

    def help_list(self):
        print( "list define" )
        print( "    lists all definitions" )
        print( "list index" )
        print( "    lists all index entries" )
        print( "list" )
        print( "    lists all definitions & index entries" )
        print( "list indentifier[*]" )
        print( "    lists variable(*)" )

    def do_set(self, params):
        if params:
            params = shlex.split(params)
            identi, values = params[0], params[1:]
            self.prog_inst.cvl.set_variable(identi, "set interactively").extend(values)
            self.prog_inst.resolve()
            self.do_list(identi)

    def complete_set(self, text, line, begidx, endidx):
        return self.indentifier_completion_list(text, line, begidx, endidx)

    def help_set(self):
        print("set identifier [value, ...]")
        print("    set values of variable")

    def do_del(self, params):
        for identi in params.split():
            del self.prog_inst.cvl[identi]

    def complete_del(self, text, line, begidx, endidx):
        return self.indentifier_completion_list(text, line, begidx, endidx)

    def help_del(self):
        print("del [identifier, ...]")
        print("    deletes a variable")

    def do_read(self, params):
        try:
            if params:
                for file in shlex.split(params):
                    try:
                        self.prog_inst.read_file(file)
                        self.prog_inst.resolve()
                    except Exception as ex:
                        print("read", file, ex)
            else:
                print("read what?")
            return False
        except Exception as es:
            import traceback
            tb = traceback.format_exc()
            print("do_read", es, tb)

    def complete_read(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def do_write(self, params):
        self.prog_inst.dedigest()
        self.prog_inst.digest()
        self.prog_inst.create_install_instructions()
        outfile = "stdout"
        if params:
            outfile = shlex.split(params)[0]
        main_out_file_obj = self.prog_inst.cvl.get_configVar_obj("__MAIN_OUT_FILE__")
        main_out_file_obj.clear_values()
        main_out_file_obj.append(outfile)
        self.prog_inst.resolve()
        self.prog_inst.write_install_batch_file()
        return False

    def complete_write(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def do_cycles(self, params):
        self.prog_inst.find_cycles()
        return False

    def help_cycles(self):
        print("cycles:", "check index dependencies for cycles")

    def do_depend(self, params):
        try:
            if params:
                for param in shlex.split(params):
                    if param not in self.prog_inst.install_definitions_index:
                        print(text_with_color(param, 'green'), "not in index")
                        continue
                    depend_list = list()
                    self.prog_inst.needs(param, depend_list)
                    if not depend_list:
                        depend_list = ("no one",)
                    depend_text_list = list()
                    for depend in depend_list:
                        if depend.endswith("(missing)"):
                            depend_text_list.append(text_with_color(depend, 'red'))
                        else:
                            depend_text_list.append(text_with_color(depend, 'yellow'))
                    print (text_with_color(param, 'green'), "needs:\n    ", ", ".join(depend_text_list))
                    needed_by_list = self.prog_inst.needed_by(param)
                    if needed_by_list is None:
                        print("could not get needed by list for", text_with_color(param, 'green'))
                    else:
                        if not needed_by_list:
                            needed_by_list = ("no one",)
                        needed_by_list = [text_with_color(needed_by, 'yellow') for needed_by in needed_by_list]
                        print (text_with_color(param, 'green'), "needed by:\n    ", ", ".join(needed_by_list))
        except Exception as es:
            import traceback
            tb = traceback.format_exc()
            print("do_depend", es, tb)
        return False

    def complete_depend(self, text, line, begidx, endidx):
        return self.indentifier_completion_list(text, line, begidx, endidx)

    def help_depend(self):
        print("depend [identifier, ...]")
        print("    dependecies for an item")

    def do_restart(self, params):
        print("restarting", this_program_name)
        self.restart = True
        return True # stops cmdloop

    def help_restart(self):
        print("restart:", "reloads", this_program_name)

    def do_quit(self, params):
        return True

    def help_quit(self):
        print("quit, q: quits", this_program_name)

    def do_q(self, params):
        return self.do_quit(params)

    def help_q(self):
        return self.help_quit()

    def default(self, line):
        print("unknown command: ", line)
        return False

    def help_help(self):
        self.do_help("")

    # evaluate python expressions
    def do_eval(self, param):
        try:
            if param:
                print(eval(param))
        except Exception as ex:
            print("eval:",  ex)

    def help_eval(self):
        print("evaluate python expressions, instlInstance is accessible as self.prog_inst")

def do_list_imp(self, what = None, stream=sys.stdout):
    if what is None:
        augmentedYaml.writeAsYaml(self, stream)
    elif isinstance(what, list):
        item_list = self.repr_for_yaml(what)
        for item in item_list:
            augmentedYaml.writeAsYaml(item, stream)
    elif isinstance(what, str):
        if what == "define":
            augmentedYaml.writeAsYaml(augmentedYaml.YamlDumpDocWrap(self.cvl, '!define', "Definitions", explicit_start=True, sort_mappings=True), stream)
        elif what == "index":
            augmentedYaml.writeAsYaml(augmentedYaml.YamlDumpDocWrap(self.install_definitions_index, '!index', "Installation index", explicit_start=True, sort_mappings=True), stream)
        else:
            item_list = self.repr_for_yaml(what)
            for item in item_list:
                augmentedYaml.writeAsYaml(item, stream)


def create_completion_list_imp(self, for_what="all"):
    retVal = list()
    try:
        if for_what in ("all", "index"):
            retVal.extend(self.install_definitions_index.keys())
        if for_what in ("all", "define"):
            retVal.extend(self.cvl.keys())
    except Exception as ex:
        print("create_completion_list:",   ex)
    return retVal
