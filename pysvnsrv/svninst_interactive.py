#!/usr/bin/env python2.7
from __future__ import print_function

import os
import sys
import appdirs
import shlex
import svnTree

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

import svnTree
from aYaml import augmentedYaml
from pyinstl.utils import *

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


this_program_name = "svninstl"

def go_interactive():
    try:
        with CMDObj() as icmd:
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
    class CommandLineParamException(BaseException):
        pass

    def __init__(self):
        cmd.Cmd.__init__(self)
        self.prog_inst = svnTree.SVNTree()
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
            history_file_dir = appdirs.user_data_dir(this_program_name, this_program_name)
            try:
                os.makedirs(history_file_dir)
            except: # os.makedirs raises is the directory already exists
                pass
            self.history_file_path = os.path.join(history_file_dir, "."+this_program_name+"_console_history")
            try:
                readline.read_history_file(self.history_file_path)
            except: # Corrupt or non existent history file might raise an exception
                try:
                    os.remove(self.history_file_path)
                except:
                    pass # if removing the file also fail - just ignore it
        if colorama_loaded:
            colorama.init()
        self.prompt = this_program_name+": "
        self.save_dir = os.getcwd()
        return self

    def __exit__(self, type, value, traceback):
        try:
            if readline_loaded:
                compact_history()
                readline.set_history_length(32)
                readline.write_history_file(self.history_file_path)
        except Exception as es:
            #import traceback
            #tb = traceback.format_exc()
            #print("__exit__", es, tb)
            pass
        # restart only after saving history, otherwise history will not be saved (;-o).
        os.chdir(self.save_dir)
        if self.restart:
            restart_program()

    def onecmd(self, line):
        retVal = False
        try:
            retVal = super (CMDObj, self).onecmd(line)
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

    def do_read(self, params):
        try:
            if not params:
                raise CMDObj.CommandLineParamException
            split_params = shlex.split(params)
            if len(split_params) < 2:
                raise CMDObj.CommandLineParamException
            format = split_params[0]
            if format not in self.prog_inst.valid_read_formats():
                raise CMDObj.CommandLineParamException
            self.prog_inst.read_from_file(split_params[1], format=format, report_level=1)
        except CMDObj.CommandLineParamException:
            self.help_read()
        return False

    def complete_read(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def help_read(self):
        print("read", "|".join(self.prog_inst.valid_read_formats()), "path_to_file")
        print("    reads a svn hierarchy from a file in one of the formats:", ", ".join(self.prog_inst.valid_read_formats()))

    def do_write(self, params):
        try:
            if not params:
                raise CMDObj.CommandLineParamException
            split_params = shlex.split(params)
            format = split_params[0]
            if format not in self.prog_inst.valid_write_formats():
                raise CMDObj.CommandLineParamException
            if len(split_params) < 2:
                file = "stdout"
            else:
                file = split_params[1]
            self.prog_inst.write_to_file(file, format=format, report_level=1)
        except CMDObj.CommandLineParamException:
            self.help_write()
        return False

    def complete_write(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def help_write(self):
        print("write", "|".join(self.prog_inst.valid_write_formats()), "path_to_file|stdout")
        print("    writes a svn hierarchy from a file in one of the formats:", ", ".join(self.prog_inst.valid_write_formats()))

    def do_popu(self, params):
        if not params:
            raise CMDObj.CommandLineParamException
        split_params = shlex.split(params)
        folder = split_params[0]
        self.prog_inst.populate(folder)

    def complete_popu(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def help_popu(self):
        pass

    def do_version(self, params):
        print(" ".join( (this_program_name, "version", ".".join( ("0", "0", "1") ))))
        return False
    def help_version(self):
        print("version: print", this_program_name, "version")

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

    def do_hist(self, params):
        for index in range(readline.get_current_history_length()):
            print(index, readline.get_history_item(index))
        print(readline.get_current_history_length(), "items in history")
        return False

    def help_hist(self):
        print("hist")
        print("   display command line history")

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


