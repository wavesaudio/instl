#!/usr/bin/env python2.7
from __future__ import print_function

import time
import appdirs
import logging
import shlex
from pyinstl.instlException import InstlException
from pyinstl.utils import *
from installItem import guid_list, iids_from_guid
from configVarStack import var_stack

import platform
current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'Mac'
elif current_os == 'Windows':
    current_os = 'Win'
elif current_os == 'Linux':
    current_os = 'Linux'

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

def go_interactive(client, admin):
    try:
        instlInstanceBase.InstlInstanceBase.create_completion_list = create_completion_list_imp
        instlInstanceBase.InstlInstanceBase.do_list = do_list_imp
        with CMDObj(client, admin) as icmd:
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
    def __init__(self, client, admin):
        cmd.Cmd.__init__(self)
        self.client_prog_inst = client
        self.admin_prog_inst = admin
        self.restart = False
        self.history_file_path = None
        self.prompt = None
        self.save_dir = None
        self.this_program_name = var_stack.resolve("$(INSTL_EXEC_DISPLAY_NAME)")

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
            history_file_dir = appdirs.user_data_dir(self.this_program_name, self.this_program_name)
            try:
                os.makedirs(history_file_dir)
            except: # os.makedirs raises is the directory already exists
                pass
            self.history_file_path = os.path.join(history_file_dir, "."+self.this_program_name+"_console_history")
            try:
                readline.read_history_file(self.history_file_path)
            except: # Corrupt or non existent history file might raise an exception
                try:
                    os.remove(self.history_file_path)
                except:
                    pass # if removing the file also fail - just ignore it
        if colorama_loaded:
            colorama.init()
        self.prompt = self.this_program_name+": "
        self.save_dir = os.getcwd()
        return self

    def __exit__(self, unused_type, unused_value, unused_traceback):
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
        except Exception as unused_ex:
            print("unhandled exception")
            import traceback
            traceback.print_exc()
        return retVal

    def path_completion(self, text, unused_line, unused_begidx, unused_endidx):
        matches = []
        if text:
            try:
                matches.extend(insensitive_glob(text+'*'))
            except Exception as es:
                logging.info(es)
        return matches

    def dir_completion(self, text, unused_line, unused_begidx, unused_endidx):
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
            Left hand index enrties: 'SAMPLE_IID:' translates to colorama.Fore.GREEN+'SAMPLE_IID'+colorama.Fore.RESET+":".
            Right hand index enrties: '- SAMPLE_IID:' translates to "- "+colorama.Fore.YELLOW+'SAMPLE_IID'+colorama.Fore.RESET.
            Variable references: $(SAMPLE_VARAIBLE) translates to colorama.Fore.BLUE+$(SAMPLE_VARAIBLE).
            The returned dictionary can be used in replace_all_from_dict() for "coloring" the text before output to stdcout.
        """
        retVal = dict()
        defs = self.client_prog_inst.create_completion_list("define")
        index = self.client_prog_inst.create_completion_list("index")
        guids = self.client_prog_inst.create_completion_list("guid")

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
        coloring_dict = self.prepare_coloring_dict()
        retVal = replace_all_from_dict(text, *[], **coloring_dict)
        return retVal

    def do_list(self, params):
        from utils import write_to_list
        out_list = write_to_list()
        if params:
            identifier_list = list()
            for param in params.split():
                comp_list_for_param = self.complete_list(param, params, 0, 0)
                if comp_list_for_param:
                    identifier_list.extend(comp_list_for_param)
                else:
                    print("Unknown identifier:", param)
            if identifier_list:
                self.client_prog_inst.do_list(identifier_list, out_list)
        else:
            self.client_prog_inst.do_list(None, out_list)
        joined_list = "".join(out_list.list()).encode('ascii','ignore') # just in case some unicode got in...
        colored_string = self.color_vars(joined_list)
        sys.stdout.write(colored_string)
        return False

    def identifier_completion_list(self, text, unused_line, unused_begidx, unused_endidx):
        matches = []
        if text:
            completion_list = self.client_prog_inst.create_completion_list()
            if completion_list:
                matches.extend([s for s in completion_list
                         if s and s.lower().startswith(text.lower())])
        return matches

    def complete_list(self, text, line, begidx, endidx):
        #print("complete_list, text:", text)
        matches = self.identifier_completion_list(text, line, begidx, endidx)
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

    def do_listindex(self, params):
        if params:
            params = shlex.split(params)
            params_not_in_index = list()
            for param in params:
                if param in self.client_prog_inst.install_definitions_index:
                    self.client_prog_inst.install_definitions_index[param].resolve_inheritance(self.client_prog_inst.install_definitions_index)
                    augmentedYaml.writeAsYaml({param: self.client_prog_inst.install_definitions_index[param].repr_for_yaml()})
                else:
                    params_not_in_index.append(param)
            if params_not_in_index:
                print("Not found in index:\n    ", "\n    ".join(params_not_in_index))


    def do_statistics(self, unused_params):
        num_files = self.admin_prog_inst.svnTree.num_subs_in_tree(what="file")
        num_dirs = self.admin_prog_inst.svnTree.num_subs_in_tree(what="dir")
        num_total = self.admin_prog_inst.svnTree.num_subs_in_tree(what="all")
        min_revision = 4000000000
        max_revision = 0
        for item in self.admin_prog_inst.svnTree.walk_items():
            min_revision = min(min_revision, item.last_rev())
            max_revision = max(max_revision, item.last_rev())
        print("Num files:", num_files)
        print("Num dirs:", num_dirs)
        print("Total items:", num_total)
        print("Lowest revision:", min_revision)
        print("Highest revision:", max_revision)

    def do_set(self, params):
        if params:
            params = shlex.split(params)
            identi, values = params[0], params[1:]
            var_stack.set_var(identi, "set interactively").extend(values)
            self.do_list(identi)
        return False

    def complete_set(self, text, line, begidx, endidx):
        return self.identifier_completion_list(text, line, begidx, endidx)

    def help_set(self):
        print("set identifier [value, ...]")
        print("    set values of variable")

    def do_del(self, params):
        for identi in params.split():
            del var_stack[identi]
        return False

    def complete_del(self, text, line, begidx, endidx):
        return self.identifier_completion_list(text, line, begidx, endidx)

    def help_del(self):
        print("del [identifier, ...]")
        print("    deletes a variable")

    def do_read(self, params):
        if params:
            for afile in shlex.split(params):
                try:
                    self.client_prog_inst.read_yaml_file(afile)
                    self.client_prog_inst.add_default_items()
                except Exception as ex:
                    print("read", afile, ex)
            self.client_prog_inst.resolve_index_inheritance()
        else:
            self.help_read()
        return False

    def complete_read(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def help_read(self):
        print("read path_to_file")
        print("    reads an instl file")

    def do_readinfo(self, params):
        if params:
            for afile in shlex.split(params):
                time_start = time.time()
                self.admin_prog_inst.read_info_map_file(afile)
                time_end = time.time()
                print("opened file:", "'"+afile+"'")
                print("    %d items read in %0.3f ms" % (self.admin_prog_inst.svnTree.num_subs_in_tree(), (time_end-time_start)*1000.0))
        else:
            self.help_read()
        return False

    def complete_readinfo(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def help_readinfo(self):
        print("read path_to_file")
        print("    reads an svn info file")

    def do_listinfo(self, params):
        items_to_list = list()
        if params:
            for param in shlex.split(params):
                item = self.admin_prog_inst.svnTree.get_item_at_path(param.rstrip("/"))
                if item:
                    items_to_list.append(item)
                else:
                    print("No item named:", param)
        else:
            items_to_list = [self.admin_prog_inst.svnTree]
        for item in items_to_list:
            print(str(item))
            if item.isDir():
                for sub_item in item.walk_items():
                    print(str(sub_item))
        return False

    def complete_listinfo(self, text, line, unused_begidx, unused_endidx):
        complete_listinfo_line_re = re.compile("""listinfo\s+(?P<the_text>.*)""")
        match = complete_listinfo_line_re.match(line)
        if match:
            text = match.group("the_text")
        retVal = list()
        if text.endswith("/"):
            item = self.admin_prog_inst.svnTree.get_item_at_path(text.rstrip("/"))
            if item and item.isDir():
                file_list, dir_list = item.sorted_sub_items()
                retVal.extend([a_file.name() for a_file in file_list])
                retVal.extend([a_dir.name()+"/" for a_dir in dir_list])
        else:
            item = self.admin_prog_inst.svnTree.get_item_at_path(text)
            if item and item.isDir():
                file_list, dir_list = item.sorted_sub_items()
                retVal.extend(["/"+a_file.name() for a_file in file_list])
                retVal.extend(["/"+a_dir.name()+"/" for a_dir in dir_list])
            else:
                path_parts = text.split("/")
                if len(path_parts) == 1:
                    item = self.admin_prog_inst.svnTree
                else:
                    item = self.admin_prog_inst.svnTree.get_item_at_path(path_parts[:-1])
                if item:
                    file_list, dir_list = item.sorted_sub_items()
                    retVal.extend([a_file.name()     for a_file in file_list if a_file.name().startswith(path_parts[-1])])
                    retVal.extend([ a_dir.name()+"/" for a_dir  in dir_list  if a_dir.name().startswith(path_parts[-1])])
        return retVal

    def help_listinfo(self):
        print("listinfo [path_to_item [...]]")
        print("    lists items from the info map")

    def do_cycles(self, unused_params):
        self.client_prog_inst.find_cycles()
        return False

    def help_cycles(self):
        print("cycles:", "check index dependencies for cycles")

    def do_depend(self, params):
        if params:
            for param in shlex.split(params):
                if param not in self.client_prog_inst.install_definitions_index:
                    print(text_with_color(param, 'green'), "not in index")
                    continue
                depend_list = unique_list()
                self.client_prog_inst.needs(param, depend_list)
                if not depend_list:
                    depend_list = ("no one",)
                depend_text_list = list()
                for depend in depend_list:
                    if depend.endswith("(missing)"):
                        depend_text_list.append(text_with_color(depend, 'red'))
                    else:
                        depend_text_list.append(text_with_color(depend, 'yellow'))
                print (text_with_color(param, 'green'), "needs:\n    ", ", ".join(depend_text_list))
                needed_by_list = self.client_prog_inst.needed_by(param)
                if needed_by_list is None:
                    print("could not get needed by list for", text_with_color(param, 'green'))
                else:
                    if not needed_by_list:
                        needed_by_list = ("no one",)
                    needed_by_list = [text_with_color(needed_by, 'yellow') for needed_by in needed_by_list]
                    print (text_with_color(param, 'green'), "needed by:\n    ", ", ".join(needed_by_list))
        return False

    def complete_depend(self, text, line, begidx, endidx):
        return self.identifier_completion_list(text, line, begidx, endidx)

    def help_depend(self):
        print("depend [identifier, ...]")
        print("    dependencies for an item")

    def do_sync(self, params):
        out_file = "stdout"
        if params:
            out_file = params
        var_stack.set_var("__MAIN_OUT_FILE__").append(out_file)
        var_stack.set_var("__MAIN_COMMAND__").append("sync")
        self.client_prog_inst.do_command()
        return False

    def help_sync(self):
        print("sync [file_name]")
        print("    write sync commands to stdout or to file_name if given")

    def do_copy(self, params):
        out_file = "stdout"
        if params:
            out_file = params
        var_stack.set_var("__MAIN_OUT_FILE__").append(out_file)
        var_stack.set_var("__MAIN_COMMAND__").append("copy")
        self.client_prog_inst.do_command()
        return False

    def help_copy(self):
        print("copy [file_name]")
        print("    write copy commands to stdout or to file_name if given")

    def do_version(self, unused_params):
        print(self.client_prog_inst.get_version_str())
        return False

    def help_version(self):
        print("version: print", self.this_program_name, "version")

    def do_restart(self, unused_params):
        self.restart = True
        return True # stops cmdloop

    def help_restart(self):
        print("restart:", "reloads", self.this_program_name)

    def do_quit(self, unused_params):
        return True

    def help_quit(self):
        print("quit, q: quits", self.this_program_name)

    def do_q(self, params):
        return self.do_quit(params)

    def help_q(self):
        return self.help_quit()

    def default(self, line):
        print("unknown command: ", line)
        return False

    def help_help(self):
        self.do_help("")

    def do_hist(self, unused_params):
        for index in range(readline.get_current_history_length()):
            print(index, readline.get_history_item(index))
        print(readline.get_current_history_length(), "items in history")
        return False

    def help_hist(self):
        print("hist")
        print("   display command line history")

    def do_hh(self, params):
        params = [param for param in shlex.split(params)]
        from pyinstl.helpHelper import do_help
        if not params:
            do_help(None)
        else:
            for param in params:
                do_help(param)

    def report_logging_state(self):
        import pyinstl.log_utils
        top_logger = logging.getLogger()
        print("logging level:", logging.getLevelName(top_logger.getEffectiveLevel()))
        log_file_path = pyinstl.log_utils.get_log_file_path(self.this_program_name, self.this_program_name, debug=False)
        print("logging INFO level to",  log_file_path)
        debug_log_file_path = pyinstl.log_utils.get_log_file_path(self.this_program_name, self.this_program_name, debug=True)
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
                debug_log_file_path = pyinstl.log_utils.get_log_file_path(self.this_program_name, self.this_program_name, debug=True)
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
                var_stack.get_configVar_obj("LOG_FILE_DEBUG")[2] = pyinstl.log_utils.debug_logging_started
        self.report_logging_state()

    def help_log(self):
        print("log: displays log status")
        print("log debug [on | true | yes]: starts debug level logging")
        print("log debug off | false | no: stops debug level logging")

    # evaluate python expressions
    def do_python(self, param):
        if param:
            print(eval(param))
        return False

    def help_python(self):
        print("evaluate python expressions, instlObj is accessible as self.client_prog_inst")

    # resolve a string containing variables.
    def do_resolve(self, param):
        if param:
            print(var_stack.resolve(param))
        return False

    def help_resolve(self):
        print("")

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
    list_to_do = list()
    if isinstance(what, str):
        list_to_do.append(what)
    elif isinstance(what, list):
        list_to_do.extend(what)
    whole_sections_to_write = list()
    individual_items_to_write = list()
    for item_to_do in list_to_do:
        if guid_re.match(item_to_do):
            whole_sections_to_write.append({item_to_do: iids_from_guid(self.install_definitions_index, item_to_do)})
        elif item_to_do == "define":
            whole_sections_to_write.append(augmentedYaml.YamlDumpDocWrap(var_stack, '!define', "Definitions", explicit_start=True, sort_mappings=True))
        elif item_to_do == "index":
            whole_sections_to_write.append(augmentedYaml.YamlDumpDocWrap(self.install_definitions_index, '!index', "Installation index", explicit_start=True, sort_mappings=True))
        elif item_to_do == "guid":
            guid_dict = dict()
            for lic in guid_list(self.install_definitions_index):
                guid_dict[lic] = iids_from_guid(self.install_definitions_index, lic)
            whole_sections_to_write.append(augmentedYaml.YamlDumpDocWrap(guid_dict, '!guid', "guid to IID", explicit_start=True, sort_mappings=True))
        else:
            individual_items_to_write.append(item_to_do)

    augmentedYaml.writeAsYaml(whole_sections_to_write+self.repr_for_yaml(individual_items_to_write), stream)


def create_completion_list_imp(self, for_what="all"):
    retVal = list()
    try:
        if for_what in ("all", "index"):
            retVal.extend(self.install_definitions_index.keys())
        if for_what in ("all", "define"):
            retVal.extend(var_stack.keys())
        if for_what in ("all", "guid"):
            retVal.extend(guid_list(self.install_definitions_index))
    except Exception as ex:
        print("create_completion_list:",   ex)
    return retVal
