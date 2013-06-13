#!/usr/local/bin/python2.7

from __future__ import print_function

import os
import sys
import appdirs
import logging
import shlex
from pyinstl.instlException import InstlException
from pyinstl.utils import *

import platform
current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'Mac'
elif current_os == 'Windows':
    current_os = 'Win'

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

from pyinstl.utils import unique_list

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


this_program_name = instlInstanceBase.this_program_name

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

    def __enter__(self):
        if readline_loaded:
            if readline.__doc__ and 'libedit' in readline.__doc__:
                readline.parse_and_bind ("bind '\t' rl_complete") # Enable tab completions on MacOS
            else:
                readline.parse_and_bind("tab: complete")        # and on other OSs
            readline.parse_and_bind("set completion-ignore-case on")
            readline.parse_and_bind("set show-all-if-ambiguous on")
            readline.parse_and_bind("set completion-map-case on")
            readline.parse_and_bind("set show-all-if-unmodified on")
            readline.parse_and_bind("set expand-tilde on")
            history_file_dir = appdirs.user_data_dir(instlInstanceBase.this_program_name, instlInstanceBase.this_program_name)
            try:
                os.makedirs(history_file_dir)
            except: # os.makedirs raises is the directory already exists
                pass
            self.history_file_path = os.path.join(history_file_dir, "."+instlInstanceBase.this_program_name+"_console_history")
            try:
                readline.read_history_file(self.history_file_path)
            except: # Corrupt or non existent history file might raise an exception
                try:
                    os.remove(self.history_file_path)
                except:
                    pass # if removing the file also fail - just ignore it
        if colorama_loaded:
            colorama.init()
        self.prompt = instlInstanceBase.this_program_name+": "
        self.save_dir = os.getcwd()
        return self

    def __exit__(self, type, value, traceback):
        try:
            if readline_loaded:
                compact_history()
                readline.set_history_length(32)
                readline.write_history_file(self.history_file_path)
        except:
            pass
        # restart only after saving history, otherwise history will not be saved (;-o).
        os.chdir(self.save_dir)
        if self.restart:
            restart_program()

    def onecmd(self, line):
        retVal = False
        try:
            retVal = super (CMDObj, self).onecmd(line)
        except InstlException as ie:
            print("instl exception",ie.message)
            from pyinstl.log_utils import debug_logging_started
            if debug_logging_started:
                import traceback
                traceback.print_exception(type(ie.original_exception), ie.original_exception,  sys.exc_info()[2])
        except Exception as ex:
            print("unhandled exception")
            import traceback
            traceback.print_exc()
        return retVal

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
                matches.extend([adir for adir in insensitive_glob(text+'*') if os.path.isdir(adir)])
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

    def prepare_coloring_dict(self):
        """ Prepare a dictionary with identifiers mapped to their "colored" representation.
            Left hand index enrties: 'C1_IID:' translates to colorama.Fore.GREEN+'C1_IID'+colorama.Fore.RESET+":".
            Right hand index enrties: '- C1_IID:' translates to "- "+colorama.Fore.YELLOW+'C1_IID'+colorama.Fore.RESET.
            Variable references: $(WAVES_PLUGINS_DIR) translates to colorama.Fore.BLUE+$(WAVES_PLUGINS_DIR).
            The returned disctionary can be used in replace_all_from_dict() for "coloring" the text before output to stdcout.
        """
        retVal = dict()
        defs = self.prog_inst.create_completion_list("define")
        index = self.prog_inst.create_completion_list("index")
        guids = self.prog_inst.create_completion_list("guid")

        retVal.update({"$("+identi+")": text_with_color("$("+identi+")", "blue")    for identi in defs})
        retVal.update({identi+":":      text_with_color(identi, "green")+":"        for identi in defs})
        retVal.update({"- "+identi:     "- "+text_with_color(identi, "yellow")      for identi in defs})

        retVal.update({dex+":":         text_with_color(dex, "green")+":"           for dex in index})
        retVal.update({"- "+dex:        "- "+text_with_color(dex, "yellow")         for dex in index})

        retVal.update({lic+":":         text_with_color(lic, "green")+":"           for lic in guids})
        retVal.update({"- "+lic:        "- "+text_with_color(lic, "yellow")         for lic in guids})
        return retVal

    def color_vars(self, text):
        """ Add color codes to index identifiers and variables in text.
        """
        retVal = None
        coloring_dict = self.prepare_coloring_dict()
        from configVarList import replace_all_from_dict
        retVal = replace_all_from_dict(text, *[], **coloring_dict)
        return retVal

    def do_list(self, params):
        from utils import write_to_list
        out_list = write_to_list()
        if params:
            for param in params.split():
                identifier_list = self.complete_list(param, params, 0, 0)
                if identifier_list:
                    self.prog_inst.do_list(identifier_list, out_list)
                else:
                    print("Unknown identifier:", param)
        else:
            self.prog_inst.do_list(None, out_list)
        joined_list = "".join(out_list.list()).encode('ascii','ignore') # just in case some unicode got in...
        colored_string = self.color_vars(joined_list)
        sys.stdout.write(colored_string)
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
        for s in ("define", "index", "guid"):
            if s.lower().startswith(text.lower()):
                matches.append(s)
        return matches

    def help_list(self):
        print( "list identifier" )
        print( "    lists identifier" )
        print( "list define" )
        print( "    lists all definitions" )
        print( "list index" )
        print( "    lists all index entries" )
        print( "list guid" )
        print( "    lists all guid entries" )
        print( "list" )
        print( "    lists all definitions, index & guid entries" )

    def do_set(self, params):
        if params:
            params = shlex.split(params)
            identi, values = params[0], params[1:]
            self.prog_inst.cvl.set_variable(identi, "set interactively").extend(values)
            self.do_list(identi)
        return False

    def complete_set(self, text, line, begidx, endidx):
        return self.indentifier_completion_list(text, line, begidx, endidx)

    def help_set(self):
        print("set identifier [value, ...]")
        print("    set values of variable")

    def do_del(self, params):
        for identi in params.split():
            del self.prog_inst.cvl[identi]
        return False

    def complete_del(self, text, line, begidx, endidx):
        return self.indentifier_completion_list(text, line, begidx, endidx)

    def help_del(self):
        print("del [identifier, ...]")
        print("    deletes a variable")

    def do_read(self, params):
        if params:
            for afile in shlex.split(params):
                try:
                    self.prog_inst.read_file(afile)
                except Exception as ex:
                    print("read", afile, ex)
        else:
            print("read what?")
        return False

    def complete_read(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def help_read(self):
        print("read path_to_file")
        print("    reads a file")
        
    def do_cycles(self, params):
        self.prog_inst.find_cycles()
        return False

    def help_cycles(self):
        print("cycles:", "check index dependencies for cycles")

    def do_depend(self, params):
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
        return False

    def complete_depend(self, text, line, begidx, endidx):
        return self.indentifier_completion_list(text, line, begidx, endidx)

    def help_depend(self):
        print("depend [identifier, ...]")
        print("    dependecies for an item")

    def do_alias(self, params):
        if current_os == 'Mac':
            params = shlex.split(params)
            if len(params) == 2:
                print("creating alias of", params[0], "as", params[1])
                import do_something
                do_something.do_something( ('alias', params) )
            else:
                print("alias requires two parameters, not", len(params), params)
        else:
            print("alias can only be created on Mac OS")
        return False
        
    def help_alias(self):
        print("alias source_file alias_file")
        print("    creaets Mac OS alias (Mac OS only)")

    def complete_alias(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def do_sync(self, params):
        self.do_command_interactive("sync", params)
        return False
    
    def help_sync(self):
        print("sync")
        print("    creaet sync commands")
        
    def do_copy(self, params):
        self.do_command_interactive("copy", params)
        return False
    
    def help_copy(self):
        print("copy")
        print("    creaet copy commands")

    def do_version(self, params):
        print(" ".join( (this_program_name, "version", ".".join(self.prog_inst.cvl.get_list("__INSTL_VERSION__")))))
        return False
    def help_version(self):
        print("version: print", instlInstanceBase.this_program_name, "version")

    def do_restart(self, params):
        print("restarting", instlInstanceBase.this_program_name)
        self.restart = True
        return True # stops cmdloop

    def help_restart(self):
        print("restart:", "reloads", instlInstanceBase.this_program_name)

    def do_quit(self, params):
        return True

    def help_quit(self):
        print("quit, q: quits", instlInstanceBase.this_program_name)

    def do_q(self, params):
        return self.do_quit(params)

    def help_q(self):
        return self.help_quit()

    def default(self, line):
        print("unknown command: ", line)
        return False

    def help_help(self):
        self.do_help("")

    def do_hist(self, params):
        for index in range(readline.get_current_history_length()):
            print(index, readline.get_history_item(index))
        print(readline.get_current_history_length(), "items in history")
        return False
    
    def help_hist(self):
        print("hist")
        print("   display command line history")
        
    def report_logging_state(self):
        import pyinstl.log_utils
        top_logger = logging.getLogger()
        print("logging level:", logging.getLevelName(top_logger.getEffectiveLevel()))
        log_file_path = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=False)
        print("logging INFO level to",  log_file_path)
        debug_log_file_path = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=True)
        if os.path.isfile(debug_log_file_path):
            print("logging DEBUG level to",  debug_log_file_path)
        else:
            print("Not logging DEBUG level to",  debug_log_file_path)
        
    def do_log(self, params):
        import pyinstl.log_utils
        top_logger = logging.getLogger()
        if params:
            params = shlex.split(params)
            if params[0].lower() == "debug":
                debug_log_file_path = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=True)
                if len(params) == 1 or params[1].lower() in ("on", "true", "yes"):
                    if top_logger.getEffectiveLevel() > pyinstl.log_utils.debug_logging_level or not os.path.isfile(debug_log_file_path):
                        pyinstl.log_utils.setup_file_logging(debug_log_file_path, pyinstl.log_utils.debug_logging_level)
                        pyinstl.log_utils.debug_logging_started = True
                elif params[1].lower() in ("off", "false", "no"):
                    top_logger.setLevel(pyinstl.log_utils.default_logging_level)
                    try:
                        pyinstl.log_utils.teardown_file_logging(debug_log_file_path, pyinstl.log_utils.default_logging_level)
                    except:
                        pass
                self.prog_inst.cvl.get_configVar_obj("LOG_DEBUG_FILE")[2] = pyinstl.log_utils.debug_logging_started
        self.report_logging_state()
    
    def help_log(self):
        print("log: displays log status")
        print("log debug [on | true | yes]: starts debug level logging")
        print("log debug off | false | no: stops debug level logging")

    # evaluate python expressions
    def do_eval(self, param):
        if param:
            print(eval(param))
        return False

    def help_eval(self):
        print("evaluate python expressions, instlInstance is accessible as self.prog_inst")

def compact_history():
    if hasattr(readline, "replace_history_item"):
        unique_history = unique_list()
        for index in reversed(range(1, readline.get_current_history_length())):
            hist_item = readline.get_history_item(index)
            if hist_item: # some history items are None (usually at index 0)
                unique_history.append(readline.get_history_item(index))
        unique_history.reverse()
        for index in range(len(unique_history)):
            readline.replace_history_item(index+1, unique_history[index])
        for index in reversed(range(len(unique_history)+1, readline.get_current_history_length())):
            readline.remove_history_item(index)

def do_list_imp(self, what = None, stream=sys.stdout):
    if what is None:
        augmentedYaml.writeAsYaml(self, stream)
    elif isinstance(what, list):
        for item in what:
            self.do_list(str(item), stream)
    elif isinstance(what, str):
        if self.guid_re.match(what):
            augmentedYaml.writeAsYaml({what: self.iids_from_guid(what)}, stream)
        elif what == "define":
            augmentedYaml.writeAsYaml(augmentedYaml.YamlDumpDocWrap(self.cvl, '!define', "Definitions", explicit_start=True, sort_mappings=True), stream)
        elif what == "index":
            augmentedYaml.writeAsYaml(augmentedYaml.YamlDumpDocWrap(self.install_definitions_index, '!index', "Installation index", explicit_start=True, sort_mappings=True), stream)
        elif what == "guid":
            guid_dict = dict()
            for lic in self.guid_list():
                guid_dict[lic] = self.iids_from_guid(lic)
            augmentedYaml.writeAsYaml(guid_dict, stream)
        else:
            item_list = self.repr_for_yaml((what,))
            for item in item_list:
                augmentedYaml.writeAsYaml(item, stream)


def create_completion_list_imp(self, for_what="all"):
    retVal = list()
    try:
        if for_what in ("all", "index"):
            retVal.extend(self.install_definitions_index.keys())
        if for_what in ("all", "define"):
            retVal.extend(self.cvl.keys())
        if for_what in ("all", "guid"):
            retVal.extend(self.guid_list())
    except Exception as ex:
        print("create_completion_list:",   ex)
    return retVal
