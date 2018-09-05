#!/usr/bin/env python3


import sys
import os
import time
import shlex
import platform
import re
import traceback

import appdirs

import utils
from configVar import config_vars


current_os = platform.system()
if current_os == 'Darwin':
    current_os = 'Mac'
elif current_os == 'Windows':
    current_os = 'Win'
elif current_os == 'Linux':
    current_os = 'Linux'

try:
    import cmd
except Exception:
    print("failed to import cmd, interactive mode not supported")
    raise

readline_loaded = False
try:
    import readline

    readline_loaded = True
except ImportError:
    if current_os == 'Win':
        try:
            import pyreadline as readline

            readline_loaded = True
        except ImportError:
            print("failed to import pyreadline, readline functionality not supported")
        except BaseException as ex:
            print(type(ex), ex, "failed to import pyreadline, readline functionality not supported")
    else:
        print("failed to import readline, readline functionality not supported")

colorama_loaded = False
try:
    import colorama

    colorama_loaded = True
except ImportError:
    print("failed to import colorama, color text functionality not supported")

from . import instlInstanceBase
import aYaml

if colorama_loaded:
    colors = {'reset': colorama.Fore.RESET, 'green': colorama.Fore.GREEN, 'blue': colorama.Fore.BLUE, 'yellow': colorama.Fore.YELLOW, 'red': colorama.Fore.RED}


def text_with_color(text, color):
    retVal = text
    if colorama_loaded and color in colors:
        retVal = colors[color] + text + colors['reset']
    return retVal


def insensitive_glob(pattern):
    import glob

    def either(c):
        return '[%s%s]' % (c.lower(), c.upper()) if c.isalpha() else c

    return glob.glob(''.join(map(either, pattern)))


def go_interactive(client, admin):
    try:
        instlInstanceBase.InstlInstanceBase.create_completion_list = create_completion_list_imp
        instlInstanceBase.InstlInstanceBase.do_list = do_list_imp
        with CMDObj(client, admin) as icmd:
            icmd.cmdloop()
    except Exception as es:
        tb = traceback.format_exc()
        print("go_interactive", es, tb)


def restart_program():
    """Restarts the current program.
        Note: this function does not return. Any cleanup action (like
        saving data) must be done before calling this function."""
    python = sys.executable
    os.execl(python, python, *sys.argv)


class CMDObj(cmd.Cmd, object):
    def __init__(self, client, admin) -> None:
        cmd.Cmd.__init__(self)
        self.client_prog_inst = client
        self.admin_prog_inst = admin
        self.restart = False
        self.history_file_path = None
        self.prompt = None
        self.save_dir = None
        self.this_program_name = config_vars["INSTL_EXEC_DISPLAY_NAME"].str()

    def __enter__(self):
        if readline_loaded:
            if readline.__doc__ and 'libedit' in readline.__doc__:
                readline.parse_and_bind("bind '\t' rl_complete")  # Enable tab completions on MacOS
            else:
                readline.parse_and_bind("tab: complete")  # and on other OSs
            readline.parse_and_bind("set completion-ignore-case on")
            readline.parse_and_bind("set show-all-if-ambiguous on")
            readline.parse_and_bind("set completion-map-case on")
            readline.parse_and_bind("set show-all-if-unmodified on")
            readline.parse_and_bind("set expand-tilde on")
            history_file_dir = appdirs.user_data_dir(self.this_program_name, self.this_program_name)
            os.makedirs(history_file_dir, exist_ok=True)
            self.history_file_path = os.path.join(history_file_dir, "." + self.this_program_name + "_console_history")
            try:
                readline.read_history_file(self.history_file_path)
            except Exception:  # Corrupt or non existent history file might raise an exception
                try:
                    os.remove(self.history_file_path)
                except Exception:
                    pass  # if removing the file also fail - just ignore it
        if colorama_loaded:
            colorama.init()
        self.prompt = self.this_program_name + ": "
        self.save_dir = os.getcwd()
        return self

    def __exit__(self, unused_type, unused_value, unused_traceback):
        try:
            if readline_loaded:
                compact_history()
                readline.set_history_length(32)
                readline.write_history_file(self.history_file_path)
        except Exception:
            pass
        # restart only after saving history, otherwise history will not be saved (;-o).
        os.chdir(self.save_dir)
        if self.restart:
            restart_program()

    def emptyline(self):
        """ override just to overcome a bug while running in under PyCharm
            PyCharm is entering a blank line after each input(...) and CMD.emptyline
            therefor repeats the last command, resulting in each command preformed twice.
        """
        return False

    def onecmd(self, line):
        retVal = False
        try:
            retVal = super().onecmd(line)
        except utils.InstlException as ie:
            print("instl exception", ie.message)
            traceback.print_exception(type(ie.original_exception), ie.original_exception, sys.exc_info()[2])
        except Exception:
            print("unhandled exception")
            traceback.print_exc()
        return retVal

    def path_completion(self, text, unused_line, unused_begidx, unused_endidx):
        matches = []
        if text:
            try:
                matches.extend(insensitive_glob(text + '*'))
            except Exception as es:
                pass
        return matches

    def dir_completion(self, text, unused_line, unused_begidx, unused_endidx):
        matches = []
        if text:
            try:
                matches.extend([a_dir for a_dir in insensitive_glob(text + '*') if os.path.isdir(a_dir)])
            except Exception as es:
                pass
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
            Left hand index entries: 'SAMPLE_IID:' translates to colorama.Fore.GREEN+'SAMPLE_IID'+colorama.Fore.RESET+":".
            Right hand index entries: '- SAMPLE_IID:' translates to "- "+colorama.Fore.YELLOW+'SAMPLE_IID'+colorama.Fore.RESET.
            Variable references: $(SAMPLE_VARIABLE) translates to colorama.Fore.BLUE+$(SAMPLE_VARIABLE).
            The returned dictionary can be used in replace_all_from_dict() for "coloring" the text before output to stdout.
        """
        retVal = dict()
        definitions = self.client_prog_inst.create_completion_list("define")
        index = self.client_prog_inst.create_completion_list("index")
        guids = self.client_prog_inst.create_completion_list("guid")

        retVal.update({"$(" + identi + ")": text_with_color("$(" + identi + ")", "blue") for identi in definitions})
        retVal.update({identi + ":": text_with_color(identi, "green") + ":" for identi in definitions})
        retVal.update({"- " + identi: "- " + text_with_color(identi, "yellow") for identi in definitions})

        retVal.update({dex + ":": text_with_color(dex, "green") + ":" for dex in index})
        retVal.update({"- " + dex: "- " + text_with_color(dex, "yellow") for dex in index})

        retVal.update({lic + ":": text_with_color(lic, "green") + ":" for lic in guids})
        retVal.update({"- " + lic: "- " + text_with_color(lic, "yellow") for lic in guids})
        return retVal

    def color_vars(self, text):
        """ Add color codes to index identifiers and variables in text.
        """
        coloring_dict = self.prepare_coloring_dict()
        retVal = utils.replace_all_from_dict(text, *[], **coloring_dict)
        return retVal

    def do_apropos(self, params):
        definitions = self.client_prog_inst.create_completion_list("define")
        index = self.client_prog_inst.create_completion_list("index")
        guids = self.client_prog_inst.create_completion_list("guid")
        definitions_results = utils.unique_list()
        index_results = utils.unique_list()
        guids_results = utils.unique_list()
        search_for = params.split()
        work_list = ((definitions, definitions_results), (index, index_results), (guids, guids_results))
        for param in search_for:
            for id_list, results in work_list:
                for identifier in id_list:
                    found_it = re.search(param, identifier, flags=re.IGNORECASE)
                    if found_it:
                        results.append (identifier)
        print ("variables:")
        if definitions_results:
            for var in definitions_results:
                print ("   ", var)
        else:
            print ("    no matching variables were found")
        print ("index items:")
        if index_results:
            for iid in index_results:
                print ("   ", iid)
        else:
            print ("    no matching iids were found")
        print ("guids:")
        if guids_results:
            for guid in guids_results:
                iids_of_guids = self.client_prog_inst.items_table.get_iids_with_specific_detail_values("guid", guid)
                print ("   ", guid, iids_of_guids)
        else:
            print ("    no matching guids were found")

    def do_list(self, params):
        out_list = utils.write_to_list()
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
        joined_list = "".join(out_list.list())
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
        # print("complete_list, text:", text)
        matches = self.identifier_completion_list(text, line, begidx, endidx)
        for s in ("define", "index", "guid"):
            if s.lower().startswith(text.lower()):
                matches.append(s)
        return matches

    def help_list(self):
        print("list identifier")
        print("    lists identifier")
        print("list define")
        print("    lists all definitions")
        print("list index")
        print("    lists all index entries")
        print("list guid")
        print("    lists all guid entries")
        print("list")
        print("    lists all definitions, index & guid entries")

    def do_statistics(self, unused_params):
        num_files = self.admin_prog_inst.info_map_table.num_items("all-files")
        num_dirs =  self.admin_prog_inst.info_map_table.num_items("all-dirs")
        num_total = self.admin_prog_inst.info_map_table.num_items("all-items")
        min_revision, max_revision = self.admin_prog_inst.info_map_table.min_max_revision()

        print("Num files:", num_files)
        print("Num dirs:", num_dirs)
        print("Total items:", num_total)
        print("Lowest revision:", min_revision)
        print("Highest revision:", max_revision)

    def do_set(self, params):
        if params:
            params = shlex.split(params)
            identi, values = params[0], params[1:]
            config_vars[identi, "set interactively"] = values
            self.do_list(identi)
        return False

    def complete_set(self, text, line, begidx, endidx):
        return self.identifier_completion_list(text, line, begidx, endidx)

    def help_set(self):
        print("set identifier [value, ...]")
        print("    set values of variable")

    def do_del(self, params):
        for identi in params.split():
            del config_vars[identi]
        return False

    def complete_del(self, text, line, begidx, endidx):
        return self.identifier_completion_list(text, line, begidx, endidx)

    def help_del(self):
        print("del [identifier, ...]")
        print("    deletes a variable")

    def do_read(self, params):
        if params:
            self.client_prog_inst.items_table.activate_all_oses()
            for a_file in shlex.split(params):
                try:
                    self.client_prog_inst.read_yaml_file(a_file)
                    self.client_prog_inst.items_table.create_default_index_items(iids_to_ignore=[])
                except Exception as ex:
                    print("read", a_file, ex)
            self.client_prog_inst.items_table.resolve_inheritance()
            self.client_prog_inst.items_table.reset_active_oses()
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
            for a_file in shlex.split(params):
                time_start = time.perf_counter()
                self.admin_prog_inst.info_map_table.read_from_file(a_file)
                time_end = time.perf_counter()
                print("opened file:", "'" + a_file + "'")
                print("    %d items read in %0.3f ms" % (self.admin_prog_inst.info_map_table.num_items("all-items"), (time_end-time_start)*1000.0))
        else:
            self.help_read()
        return False

    def complete_readinfo(self, text, line, begidx, endidx):
        return self.path_completion(text, line, begidx, endidx)

    def help_readinfo(self):
        print("read path_to_file")
        print("    reads an info_map file")

    def do_listinfo(self, params):
        items_to_list = list()
        if params:
            for param in shlex.split(params):
                item = self.admin_prog_inst.info_map_table.get_any_item(param.rstrip("/"))
                if item:
                    items_to_list.append(item)
                    if item.isDir():
                        items_to_list.extend(self.admin_prog_inst.info_map_table.get_items_in_dir(dir_path=item.path))
                else:
                    print("No item named:", param)
        else:
            items_to_list = self.admin_prog_inst.get_items(what="any")
        for item in items_to_list:
            print(str(item))
        return False

#    def complete_listinfo(self, text, line, unused_begidx, unused_endidx):
#        complete_listinfo_line_re = re.compile("""listinfo\s+(?P<the_text>.*)""")
#        match = complete_listinfo_line_re.match(line)
#        if match:
#            text = match["the_text"]
#        retVal = list()
#        if text.endswith("/"):
#            items = self.admin_prog_inst.info_map_table.get_items_in_dir(text.rstrip("/"), levels_deep=1)
#            if items:
#                retVal.extend([a_file.name for a_file in items if a_file.isFile()])
#                retVal.extend([a_dir.name + "/" for a_dir in items if a_file.isDir()])
#        else:
#            item = self.admin_prog_inst.info_map_table.get_item(text)
#            if item:
#                if item.isDir():
#                    items = self.admin_prog_inst.info_map_table.get_items_in_dir(text, levels_deep=1)
#                    if items:
#                        retVal.extend([a_file.name for a_file in items if a_file.isFile()])
#                        retVal.extend([a_dir.name + "/" for a_dir in items if a_file.isDir()])
#            elif False:
#                path_parts = text.split("/")
#                if len(path_parts) == 1:
#                    item = self.admin_prog_inst.svnTree
#                else:
#                    item = self.admin_prog_inst.svnTree.get_item(path_parts[:-1])
#                if item:
#                    file_list, dir_list = item.sorted_sub_items()
#                    retVal.extend([a_file.name for a_file in file_list if a_file.name.startswith(path_parts[-1])])
#                    retVal.extend([a_dir.name + "/" for a_dir in dir_list if a_dir.name.startswith(path_parts[-1])])
#        return retVal

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
            self.client_prog_inst.items_table.activate_all_oses()
            all_iids = self.client_prog_inst.items_table.get_all_iids()
            for param in shlex.split(params):
                if param not in all_iids:
                    print(text_with_color(param, 'green'), "not in index")
                    continue
                needs_list = self.client_prog_inst.needs(param, all_iids_set=set(all_iids))
                if not needs_list:
                    needs_list = ("no one",)
                depend_text_list = list()
                for depend in needs_list:
                    if depend.endswith("(missing)"):
                        depend_text_list.append(text_with_color(depend, 'red'))
                    else:
                        depend_text_list.append(text_with_color(depend, 'yellow'))
                print(text_with_color(param, 'green'), "needs:\n    ", ", ".join(sorted(depend_text_list)))
                needed_by_list = self.client_prog_inst.needed_by(param)
                if needed_by_list is None:
                    print("could not get needed by list for", text_with_color(param, 'green'))
                else:
                    if not needed_by_list:
                        needed_by_list = ("no one",)
                    needed_by_list = [text_with_color(needed_by, 'yellow') for needed_by in needed_by_list]
                    print(text_with_color(param, 'green'), "needed by:\n    ", ", ".join(sorted(needed_by_list)))
        self.client_prog_inst.items_table.reset_active_oses()
        return False

    def complete_depend(self, text, line, begidx, endidx):
        return self.identifier_completion_list(text, line, begidx, endidx)

    def help_depend(self):
        print("Usage: depend [identifier, ...]")
        print("    list dependencies for an item: all other items that needs or are needed-by the item")
        print("Example: depend ABC__IID")

    def do_sync(self, params):
        out_file = "stdout"
        if params:
            out_file = params
        config_vars["__MAIN_OUT_FILE__"] = out_file
        config_vars["__MAIN_COMMAND__"] = "sync"
        self.client_prog_inst.do_command()
        return False

    def help_sync(self):
        print("sync [file_name]")
        print("    write sync commands to stdout or to file_name if given")

    def do_copy(self, params):
        out_file = "stdout"
        if params:
            out_file = params
        config_vars["__MAIN_OUT_FILE__"] = out_file
        config_vars["__MAIN_COMMAND__"] = "copy"
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
        print("restarting...")
        self.restart = True
        return True  # stops cmdloop

    def do_r(self, unused_params):
        return self.do_restart(unused_params)

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
            print(config_vars.resolve_str(param))
        return False

    def help_resolve(self):
        print("")

    def do_which(self, param):
        print(os.fspath(config_vars["__INSTL_EXE_PATH__"]))

    def help_which(self):
        print("print full path to currently running instl")

    def do_stam(self, params):
        params = [param for param in shlex.split(params)]
        self.client_prog_inst.items_table.iids_from_guids2(params)

def compact_history():
    if hasattr(readline, "replace_history_item"):
        unique_history = utils.unique_list()
        for index in reversed(list(range(1, readline.get_current_history_length()))):
            hist_item = readline.get_history_item(index)
            if hist_item:  # some history items are None (usually at index 0)
                unique_history.append(readline.get_history_item(index))
        unique_history.reverse()
        for index in range(len(unique_history)):
            readline.replace_history_item(index + 1, unique_history[index])
        for index in reversed(list(range(len(unique_history) + 1, readline.get_current_history_length()))):
            readline.remove_history_item(index)


def do_list_imp(self, what=None, stream=sys.stdout):
    if what is None:
        aYaml.writeAsYaml(self, stream)
    list_to_do = list()
    if isinstance(what, str):
        list_to_do.append(what)
    elif isinstance(what, list):
        list_to_do.extend(what)
    whole_sections_to_write = list()
    individual_items_to_write = list()
    for item_to_do in list_to_do:
        if utils.guid_re.match(item_to_do):
            translated_iids, orphaned_guids = self.items_table.iids_from_guids([item_to_do])
            whole_sections_to_write.append({item_to_do: translated_iids})
        elif item_to_do == "define":
            whole_sections_to_write.append(aYaml.YamlDumpDocWrap(config_vars, '!define', "Definitions", explicit_start=True, sort_mappings=True))
        elif item_to_do == "index":
            whole_sections_to_write.append(aYaml.YamlDumpDocWrap(self.items_table.repr_for_yaml(), '!index', "Installation index", explicit_start=True, sort_mappings=True))
        elif item_to_do == "guid":
            guid_dict = dict()
            all_guids = self.items_table.get_detail_values_by_name_for_all_iids("guid")
            for a_guid in all_guids:
                translated_iids, orphaned_guids = self.items_table.iids_from_guids([a_guid])
                guid_dict[a_guid] = translated_iids
            whole_sections_to_write.append(aYaml.YamlDumpDocWrap(guid_dict, '!guid', "guid to IID", explicit_start=True, sort_mappings=True))
        else:
            individual_items_to_write.append(item_to_do)

    aYaml.writeAsYaml(whole_sections_to_write + self.repr_for_yaml(individual_items_to_write), stream)


def create_completion_list_imp(self, for_what="all"):
    retVal = list()
    try:
        if for_what in ("all", "index"):
            retVal.extend(list(self.items_table.get_all_iids()))
        if for_what in ("all", "define"):
            retVal.extend(list(config_vars.keys()))
        if for_what in ("all", "guid"):
            retVal.extend(self.items_table.get_detail_values_by_name_for_all_iids("guid"))
    except Exception as ex:
        print("create_completion_list:", ex)
    return retVal
