#!/usr/bin/env python3.6



import sys
import os
import subprocess
import functools
from time import time
import shlex
from tkinter import *
from tkinter.ttk import *
from tkinter import messagebox
import logging
from pathlib import Path
import functools
from collections import defaultdict
log = logging.getLogger()

import utils
import aYaml
from .instlInstanceBase import InstlInstanceBase
from configVar import config_vars

tab_names = {
    'ADMIN':  'Admin',
    'CLIENT': 'Client',
    'REDIS':  'Redis'
}

if getattr(os, "setsid", None):
    default_font_size = 17  # for Mac
else:
    default_font_size = 12  # for Windows

admin_command_template_variables = {
    'svn2stage': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'fix-symlinks': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'wtar': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'verify-repo': '__ADMIN_CALL_INSTL_ONLY_CONFIG_FILE_TEMPLATE__',
    'stage2svn': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'fix-props': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'depend': '__ADMIN_CALL_INSTL_DEPEND_TEMPLATE__',
    'fix-perm': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
}


class TkConfigVar(Variable):
    """ bridge between tkinter StringVar to instl ConfigVar."""
    convert_type_func = None
    _default = None

    def __init_subclass__(cls, convert_type_func, _default, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.convert_type_func = convert_type_func
        cls._default = _default

    def __init__(self, config_var_name, master=None, value=None):
        self.config_var_name = config_var_name
        if value is None:
            value = config_vars.get(self.config_var_name, self._default)
        else:
            config_vars[self.config_var_name] = value
        Variable.__init__(self, master, value, config_var_name)

    def value_from_config_var(self):
        retVal = self.convert_type_func(str(config_vars.get(self.config_var_name, self._default)))
        return retVal

    def get(self):
        retVal = self.value_from_config_var()
        return retVal

    def set(self, value):
        config_vars[self.config_var_name] = value
        Variable.set(self, value)

    def realign_from_config_var(self):  # in case we know the configVar changed
        value = self.value_from_config_var()
        Variable.set(self, value)

    def realign_from_tk_var(self):  # in case we know the tk changed
        config_vars[self.config_var_name] = Variable.get(self)


class TkConfigVarStr(TkConfigVar, convert_type_func=str, _default=""):
    pass


class TkConfigVarInt(TkConfigVar, convert_type_func=int, _default=0):
    pass


# failed to make TkConfigVarBool work: Checkbutton does not call the set function
class TkConfigVarBool(TkConfigVar, convert_type_func=bool, _default=False):
    pass


# noinspection PyAttributeOutsideInit
class InstlGui(InstlInstanceBase):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_defaults_file(super().__thisclass__.__name__)

        self.master = Tk()
        self.master.createcommand('exit', self.quit_app)  # exit from quit menu or Command-Q
        self.master.protocol('WM_DELETE_WINDOW', self.quit_app)  # exit from closing the window
        self.commands_that_accept_limit_option = list(config_vars["__COMMANDS_WITH_LIMIT_OPTION__"])

        self.client_input_combobox = None
        self.client_vars = dict()
        self.client_vars["CLIENT_GUI_CMD"] = TkConfigVarStr("CLIENT_GUI_CMD")
        self.client_vars["CLIENT_GUI_IN_FILE"] = TkConfigVarStr("CLIENT_GUI_IN_FILE")
        self.client_vars["CLIENT_GUI_OUT_FILE"] = TkConfigVarStr("CLIENT_GUI_OUT_FILE")
        self.client_vars["CLIENT_GUI_RUN_BATCH"] = TkConfigVarInt("CLIENT_GUI_RUN_BATCH")
        self.client_vars["CLIENT_GUI_CREDENTIALS"] = TkConfigVarStr("CLIENT_GUI_CREDENTIALS")
        self.client_vars["CLIENT_GUI_CREDENTIALS"] = TkConfigVarStr("CLIENT_GUI_CREDENTIALS")
        self.client_vars["CLIENT_GUI_CREDENTIALS_ON"] = TkConfigVarInt("CLIENT_GUI_CREDENTIALS_ON")

        self.admin_vars = dict()
        self.admin_vars["ADMIN_GUI_CMD"] = TkConfigVarStr("ADMIN_GUI_CMD")
        self.admin_vars["ADMIN_GUI_TARGET_CONFIG_FILE"] = TkConfigVarStr("ADMIN_GUI_TARGET_CONFIG_FILE")
        self.admin_vars["ADMIN_GUI_LOCAL_CONFIG_FILE"] = TkConfigVarStr("ADMIN_GUI_LOCAL_CONFIG_FILE")
        self.admin_vars["ADMIN_GUI_OUT_BATCH_FILE"] = TkConfigVarStr("ADMIN_GUI_OUT_BATCH_FILE")
        self.admin_vars["__STAGING_INDEX_FILE__"] = TkConfigVarStr("__STAGING_INDEX_FILE__")
        self.admin_vars["SYNC_BASE_URL"] = TkConfigVarStr("SYNC_BASE_URL")
        self.admin_vars["DISPLAY_SVN_URL_AND_REPO_REV"] = TkConfigVarStr("DISPLAY_SVN_URL_AND_REPO_REV")
        self.admin_vars["ADMIN_GUI_LIMIT"] = TkConfigVarStr("ADMIN_GUI_LIMIT")
        self.admin_vars["ADMIN_GUI_RUN_BATCH"] = TkConfigVarInt("ADMIN_GUI_RUN_BATCH")
        self.limit_path_entry_widget = None

        self.redis_vars = dict()
        self.redis_vars["REDIS_HOST"] = TkConfigVarStr("REDIS_HOST")
        self.redis_vars["REDIS_PORT"] = TkConfigVarInt("REDIS_PORT")
        self.redis_vars["DOMAIN_REPO_TO_ACTIVATE"] = TkConfigVarStr("DOMAIN_REPO_TO_ACTIVATE")
        self.redis_vars["REDIS_KEY_VALUE_1"] = TkConfigVarStr("REDIS_KEY_VALUE_1")
        self.redis_vars["REPO_REV_TO_ACTIVATE"] = TkConfigVarInt("REPO_REV_TO_ACTIVATE")
        self.redis_vars["REDIS_KEY_VALUE_2"] = TkConfigVarStr("REDIS_KEY_VALUE_2")

        self.redis_conn: utils.RedisClient = None

    def realign_from_config_vars(self, var_dict):
        for v in var_dict.values():
            v.realign_from_config_var()

    def realign_from_tk_vars(self, var_dict):
        for v in var_dict.values():
            v.realign_from_tk_var()

    def quit_app(self):
        self.write_history()
        self.master.destroy()

    def set_default_variables(self):
        client_command_list = list(config_vars["__CLIENT_GUI_CMD_LIST__"])
        config_vars["CLIENT_GUI_CMD"] = client_command_list[0]
        admin_command_list = list(config_vars["__ADMIN_GUI_CMD_LIST__"])
        config_vars["ADMIN_GUI_CMD"] = admin_command_list[0]
        self.commands_with_run_option_list = list(config_vars["__COMMANDS_WITH_RUN_OPTION__"])

        # create   - $(command_actual_name_$(...)) variables for commands that do not have them in InstlGui.yaml
        for command in list(config_vars["__CLIENT_GUI_CMD_LIST__"]):
            actual_command_var = "command_actual_name_"+command
            if actual_command_var not in config_vars:
                config_vars[actual_command_var] = command
        for command in list(config_vars["__ADMIN_GUI_CMD_LIST__"]):
            actual_command_var = "command_actual_name_"+command
            if actual_command_var not in config_vars:
                config_vars[actual_command_var] = command

    def do_command(self):
        self.set_default_variables()
        self.read_history()
        self.create_gui()

    def read_history(self):
        try:
            instl_gui_config_file_name = config_vars["INSTL_GUI_CONFIG_FILE_NAME"].str()
            self.read_yaml_file(instl_gui_config_file_name)
            # adjust files created with previous versions
            config_vars["CLIENT_GUI_RUN_BATCH"] = utils.str_to_bool_int(config_vars.get("CLIENT_GUI_RUN_BATCH", "0").str())
            config_vars["CLIENT_GUI_CREDENTIALS_ON"] = utils.str_to_bool_int(config_vars.get("CLIENT_GUI_CREDENTIALS_ON", "0").str())
            config_vars["ADMIN_GUI_RUN_BATCH"] = utils.str_to_bool_int(config_vars.get("ADMIN_GUI_RUN_BATCH", "0").str())
        except Exception:
            pass

    def write_history(self):
        selected_tab = self.notebook.tab(self.notebook.select(), option='text')
        config_vars["SELECTED_TAB"] = selected_tab

        which_vars_for_yaml = config_vars.get("__GUI_CONFIG_FILE_VARS__", []).list()
        the_list_yaml_ready= config_vars.repr_for_yaml(which_vars=which_vars_for_yaml, resolve=False, ignore_unknown_vars=True)
        the_doc_yaml_ready = aYaml.YamlDumpDocWrap(the_list_yaml_ready, '!define', "Definitions", explicit_start=True, sort_mappings=True)
        with utils.utf8_open_for_write(config_vars["INSTL_GUI_CONFIG_FILE_NAME"].str(), "w") as wfd:
            aYaml.writeAsYaml(the_doc_yaml_ready, wfd)

    def get_client_input_file(self):
        import tkinter.filedialog

        retVal = tkinter.filedialog.askopenfilename()
        if retVal:
            self.client_vars["CLIENT_GUI_IN_FILE"].set(retVal)
            self.update_client_state()

    def get_client_output_file(self):
        import tkinter.filedialog

        retVal = tkinter.filedialog.asksaveasfilename()
        if retVal:
            self.client_vars["CLIENT_GUI_OUT_FILE"].set(retVal)
            self.update_client_state()

    def get_admin_config_file(self, path_config_var):
        import tkinter.filedialog

        retVal = tkinter.filedialog.askopenfilename()
        if retVal:
            self.admin_vars[path_config_var].set(retVal)
            self.update_admin_state()

    def get_admin_output_file(self):
        import tkinter.filedialog

        retVal = tkinter.filedialog.asksaveasfilename()
        if retVal:
            self.admin_vars["ADMIN_GUI_OUT_BATCH_FILE"].set(retVal)

    def open_file_for_edit(self, path_to_file=None, config_var_containing_path_to_file=None):
        if not path_to_file:
            path_to_file = config_vars.get(config_var_containing_path_to_file, "").str()
        if path_to_file:
            path_to_file = Path(path_to_file).resolve()
            if not path_to_file.is_file():
                log.info(f"""File not found:{path_to_file}""")
                return

            try:
                # noinspection PyUnresolvedReferences
                os.startfile(path_to_file, 'edit')
            except AttributeError:
                subprocess.call(['open', path_to_file])

    def create_client_command_line(self):
        retVal = [os.fspath(config_vars["__INSTL_EXE_PATH__"]), config_vars["CLIENT_GUI_CMD"].str(),
                  "--in", config_vars["CLIENT_GUI_IN_FILE"].str(),
                  "--out", config_vars["CLIENT_GUI_OUT_FILE"].str()]

        if bool(config_vars["CLIENT_GUI_CREDENTIALS_ON"]):
            credentials = self.client_vars["CLIENT_GUI_CREDENTIALS"].get()
            if credentials != "":
                retVal.append("--credentials")
                retVal.append(credentials)

        if self.client_vars["CLIENT_GUI_RUN_BATCH"].get() == 1:
            retVal.append("--run")

        if 'Win' in list(config_vars["__CURRENT_OS_NAMES__"]):
            if not getattr(sys, 'frozen', False):
                retVal.insert(0, sys.executable)

        return retVal

    def create_admin_command_line(self):
        command_name = config_vars["ADMIN_GUI_CMD"].str()
        template_variable = admin_command_template_variables[command_name]
        retVal = list(config_vars[template_variable])

        # some special handling of command line parameters cannot yet be expressed in the command template
        if command_name != 'depend':
            if command_name in self.commands_that_accept_limit_option:
                limit_paths = self.admin_vars["ADMIN_GUI_LIMIT"].get()
                if limit_paths != "":
                    retVal.append("--limit")
                    try:
                        retVal.extend(shlex.split(limit_paths))
                    except ValueError:
                        retVal.append(limit_paths)
            if self.admin_vars["ADMIN_GUI_RUN_BATCH"].get() and command_name in self.commands_with_run_option_list:
                retVal.append("--run")

        if 'Win' in list(config_vars["__CURRENT_OS_NAMES__"]):
            if not getattr(sys, 'frozen', False):
                retVal.insert(0, sys.executable)

        return retVal

    def update_client_input_file_combo(self, *args):
        new_input_file = self.client_vars["CLIENT_GUI_IN_FILE"].get()
        if os.path.isfile(new_input_file):
            new_input_file_dir, new_input_file_name = os.path.split(new_input_file)
            items_in_dir = os.listdir(new_input_file_dir)
            dir_items = [os.path.join(new_input_file_dir, item) for item in items_in_dir if os.path.isfile(os.path.join(new_input_file_dir, item))]
            self.client_input_combobox.configure(values=dir_items)

    def update_client_state(self, *args):
        self.realign_from_tk_vars(self.client_vars)

        self.update_client_input_file_combo()

        _, input_file_base_name = os.path.split(config_vars["CLIENT_GUI_IN_FILE"])
        config_vars["CLIENT_GUI_IN_FILE_NAME"] = input_file_base_name

        if self.client_vars["CLIENT_GUI_CMD"].get() in self.commands_with_run_option_list:
            self.client_run_batch_file_checkbox.configure(state='normal')
        else:
            self.client_run_batch_file_checkbox.configure(state='disabled')

        command_line = " ".join(self.create_client_command_line())
        self.T_client.configure(state='normal')
        self.T_client.delete(1.0, END)
        self.T_client.insert(END, config_vars.resolve_str(command_line))
        self.T_client.configure(state='disabled')

    def read_admin_config_files(self, *args, **kwargs):
        for config_file_var in ("ADMIN_GUI_TARGET_CONFIG_FILE", "ADMIN_GUI_LOCAL_CONFIG_FILE"):
            config_path = str(config_vars.get(config_file_var, ""))
            if config_path:
                if os.path.isfile(config_path):
                    config_vars[ "__SEARCH_PATHS__"].clear() # so __include__ file will not be found on old paths
                    self.read_yaml_file(config_path)
                else:
                    log.info(f"""File not found: {config_path}""")
                #_, input_file_base_name = os.path.split(config_path)
                #config_vars["ADMIN_GUI_LOCAL_CONFIG_FILE_NAME"] = input_file_base_name

    def update_admin_state(self, *args):
        self.realign_from_tk_vars(self.admin_vars)
        self.read_admin_config_files()

        _, input_file_base_name = os.path.split(config_vars["ADMIN_GUI_LOCAL_CONFIG_FILE"].raw())
        config_vars["ADMIN_GUI_CONFIG_FILE_NAME"] = input_file_base_name

        if self.admin_vars["ADMIN_GUI_CMD"].get() in self.commands_that_accept_limit_option:
            self.limit_path_entry_widget.configure(state='normal')
        else:
            self.limit_path_entry_widget.configure(state='disabled')

        if self.admin_vars["ADMIN_GUI_CMD"].get() in self.commands_with_run_option_list:
            self.admin_run_batch_file_checkbox.configure(state='normal')
        else:
            self.admin_run_batch_file_checkbox.configure(state='disabled')

        command_line = " ".join([shlex.quote(p) for p in self.create_admin_command_line()])

        self.T_admin.configure(state='normal')
        self.T_admin.delete(1.0, END)
        self.T_admin.insert(END, config_vars.resolve_str(command_line))
        self.T_admin.configure(state='disabled')

    def run_client(self):
        self.update_client_state()
        command_line_parts = self.create_client_command_line()
        resolved_command_line_parts = config_vars.resolve_list_to_list(command_line_parts)

        if getattr(os, "setsid", None):
            client_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, preexec_fn=os.setsid)  # Unix
        else:
            client_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False)  # Windows
        unused_stdout, unused_stderr = client_process.communicate()
        return_code = client_process.returncode
        if return_code != 0:
            log.info(f"""{" ".join(resolved_command_line_parts)} returned exit code {return_code}""")
        print("...")

    def run_admin(self):
        self.update_admin_state()
        command_line_parts = self.create_admin_command_line()
        resolved_command_line_parts = [shlex.quote(p) for p in config_vars.resolve_list_to_list(command_line_parts)]

        if getattr(os, "setsid", None):
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, preexec_fn=os.setsid)  # Unix
        else:
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False)  # Windows
        unused_stdout, unused_stderr = admin_process.communicate()
        return_code = admin_process.returncode
        if return_code != 0:
            log.info(f"""{" ".join(resolved_command_line_parts)} returned exit code {return_code}""")
        print("...")

    def create_admin_frame(self, master):

        admin_frame = Frame(master)
        admin_frame.grid(row=0, column=1)

        curr_row = 0
        Label(admin_frame, text="Command:").grid(row=curr_row, column=0, sticky=E)

        self.realign_from_config_vars(self.admin_vars)

        # instl command selection
        admin_command_list = list(config_vars["__ADMIN_GUI_CMD_LIST__"])
        commandNameMenu = OptionMenu(admin_frame, self.admin_vars["ADMIN_GUI_CMD"],
                                     self.admin_vars["ADMIN_GUI_CMD"].get(), *admin_command_list,
                                     command=self.update_admin_state)
        commandNameMenu.grid(row=curr_row, column=1, sticky=W)
        ToolTip(commandNameMenu, msg="instl admin command")

        self.admin_run_batch_file_checkbox = Checkbutton(admin_frame, text="Run batch file", variable=self.admin_vars["ADMIN_GUI_RUN_BATCH"], command=self.update_admin_state)
        self.admin_run_batch_file_checkbox.grid(row=curr_row, column=2, columnspan=2, sticky=E)

        # path to config files

        for config_file_type, config_file_config_var_name in (('target', "ADMIN_GUI_TARGET_CONFIG_FILE"), ('local', "ADMIN_GUI_LOCAL_CONFIG_FILE")):
            curr_row += 1
            Label(admin_frame, text=f"{config_file_type} config file:").grid(row=curr_row, column=0, sticky=E)
            configFilePathEntry = Entry(admin_frame, textvariable=self.admin_vars[config_file_config_var_name])
            configFilePathEntry.grid(row=curr_row, column=1, columnspan=2, sticky=W + E)
            ToolTip(configFilePathEntry, msg=f"{config_file_type} config file")
            self.admin_vars[config_file_config_var_name].trace('w', self.read_admin_config_files)

            openConfigButt = Button(admin_frame, width=2, text="...", command=functools.partial(self.get_admin_config_file, config_file_config_var_name))
            openConfigButt.grid(row=curr_row, column=3, sticky=W)
            ToolTip(openConfigButt, msg="open {config_file_type} config file")

            editConfigButt = Button(admin_frame, width=4, text="Edit",
                                    command=functools.partial(self.open_file_for_edit, config_var_containing_path_to_file=config_file_config_var_name))
            editConfigButt.grid(row=curr_row, column=4, sticky=W)
            ToolTip(editConfigButt, msg=f"edit {config_file_type} config file")

            checkConfigButt = Button(admin_frame, width=3, text="Chk",
                                     command=functools.partial(self.check_yaml, config_var_containing_path_to_file=config_file_config_var_name))
            checkConfigButt.grid(row=curr_row, column=5, sticky=W)
            ToolTip(checkConfigButt, msg=f"read {config_file_type} config file to check it's structure")

        # path to stage index file
        curr_row += 1
        Label(admin_frame, text="Stage index:").grid(row=curr_row, column=0, sticky=E)
        Label(admin_frame, text="---", textvariable=self.admin_vars["__STAGING_INDEX_FILE__"]).grid(row=curr_row, column=1, columnspan=2, sticky=W)

        editIndexButt = Button(admin_frame, width=4, text="Edit", command=functools.partial(self.open_file_for_edit, config_var_containing_path_to_file="__STAGING_INDEX_FILE__"))
        editIndexButt.grid(row=curr_row, column=4, sticky=W)
        ToolTip(editIndexButt, msg="edit repository index")

        checkIndexButt = Button(admin_frame, width=3, text="Chk", command=functools.partial(self.check_yaml, config_var_containing_path_to_file="__STAGING_INDEX_FILE__"))
        checkIndexButt.grid(row=curr_row, column=5, sticky=W)
        ToolTip(checkIndexButt, msg="read repository index to check it's structure")

        # path to svn repository
        curr_row += 1
        Label(admin_frame, text="Svn repo:").grid(row=curr_row, column=0, sticky=E)
        svnRepoLabel = Label(admin_frame, text="---", textvariable=self.admin_vars["DISPLAY_SVN_URL_AND_REPO_REV"])
        svnRepoLabel.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        ToolTip(svnRepoLabel, msg="URL of the SVN repository with current repo-rev")

        # sync URL
        curr_row += 1
        Label(admin_frame, text="Sync URL:").grid(row=curr_row, column=0, sticky=E)
        syncURLLabel = Label(admin_frame, text="---", textvariable=self.admin_vars["SYNC_BASE_URL"])
        syncURLLabel.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        ToolTip(syncURLLabel, msg="Top URL for uploading to the repository")

        # path to output file
        curr_row += 1
        Label(admin_frame, text="Batch file:").grid(row=curr_row, column=0, sticky=E)
        Entry(admin_frame, textvariable=self.admin_vars["ADMIN_GUI_OUT_BATCH_FILE"]).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        Button(admin_frame, width=2, text="...", command=self.get_admin_output_file).grid(row=curr_row, column=3, sticky=W)
        Button(admin_frame, width=4, text="Edit",
                command=functools.partial(self.open_file_for_edit, config_var_containing_path_to_file="ADMIN_GUI_OUT_BATCH_FILE")).grid(row=curr_row, column=4, sticky=W)

        # relative path to limit folder
        curr_row += 1
        Label(admin_frame, text="Limit to:").grid(row=curr_row, column=0, sticky=E)
        ADMIN_GUI_LIMIT_values = config_vars.get("ADMIN_GUI_LIMIT", []).list()
        ADMIN_GUI_LIMIT_values = list(filter(None, ADMIN_GUI_LIMIT_values))
        self.limit_path_entry_widget = Entry(admin_frame, textvariable=self.admin_vars["ADMIN_GUI_LIMIT"])
        self.limit_path_entry_widget.grid(row=curr_row, column=1, columnspan=2, sticky=W + E)
        self.admin_vars["ADMIN_GUI_LIMIT"].trace('w', self.update_admin_state)

        # the combined command line text
        curr_row += 1
        Button(admin_frame, width=6, text="run:", command=self.run_admin).grid(row=curr_row, column=0, sticky=N)
        self.T_admin = Text(admin_frame, height=7, font=("Courier", default_font_size))
        self.T_admin.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        self.T_admin.configure(state='disabled')

        curr_row += 1
        Button(admin_frame, width=9, text="clipboard", command=self.copy_to_clipboard).grid(row=curr_row, column=1, sticky=W)
        Button(admin_frame, width=9, text="Save state", command=self.write_history).grid(row=curr_row, column=2, sticky=E)

        return admin_frame

    def copy_to_clipboard(self):
        value = ""
        if self.tab_name == tab_names['ADMIN']:
            value = self.T_admin.get("1.0",END)
        elif self.tab_name == tab_names['CLIENT']:
            value = self.T_client.get("1.0",END)
        elif self.tab_name == tab_names['REDIS']:
            value = self.T_client.get("1.0",END)

        if value not in ["", "\n"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(value)
            log.info("instl command was copied to clipboard!")

    def create_client_frame(self, master):

        client_frame = Frame(master)
        client_frame.grid(row=0, column=0)

        curr_row = 0
        command_label = Label(client_frame, text="Command:")
        command_label.grid(row=curr_row, column=0, sticky=W)

        self.realign_from_config_vars(self.client_vars)

        # instl command selection
        client_command_list = list(config_vars["__CLIENT_GUI_CMD_LIST__"])
        OptionMenu(client_frame, self.client_vars["CLIENT_GUI_CMD"],
                   self.client_vars["CLIENT_GUI_CMD"].get(), *client_command_list, command=self.update_client_state).grid(row=curr_row, column=1, sticky=W)

        self.client_run_batch_file_checkbox = Checkbutton(client_frame, text="Run batch file",
                    variable=self.client_vars["CLIENT_GUI_RUN_BATCH"], command=self.update_client_state)
        self.client_run_batch_file_checkbox.grid(row=curr_row, column=2, sticky=E)

        # path to input file
        curr_row += 1
        Label(client_frame, text="Input file:").grid(row=curr_row, column=0)
        self.client_input_combobox = Combobox(client_frame, textvariable=self.client_vars["CLIENT_GUI_IN_FILE"])
        self.client_input_combobox.grid(row=curr_row, column=1, columnspan=2, sticky=W + E)
        self.client_vars["CLIENT_GUI_IN_FILE"].trace('w', self.update_client_state)
        Button(client_frame, width=2, text="...", command=self.get_client_input_file).grid(row=curr_row, column=3, sticky=W)
        Button(client_frame, width=4, text="Edit",
               command=functools.partial(self.open_file_for_edit, config_var_containing_path_to_file="CLIENT_GUI_IN_FILE")).grid(row=curr_row, column=4, sticky=W)
        Button(client_frame, width=3, text="Chk",
               command=functools.partial(self.check_yaml, config_var_containing_path_to_file="CLIENT_GUI_IN_FILE")).grid(row=curr_row, column=5, sticky=W)

        # path to output file
        curr_row += 1
        Label(client_frame, text="Batch file:").grid(row=curr_row, column=0)
        Entry(client_frame, textvariable=self.client_vars["CLIENT_GUI_OUT_FILE"]).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.client_vars["CLIENT_GUI_OUT_FILE"].trace('w', self.update_client_state)
        Button(client_frame, width=2, text="...", command=self.get_client_output_file).grid(row=curr_row, column=3, sticky=W)
        Button(client_frame, width=4, text="Edit",
                command=functools.partial(self.open_file_for_edit, config_var_containing_path_to_file="CLIENT_GUI_OUT_FILE")).grid(row=curr_row, column=4, sticky=W)

        # s3 user credentials
        curr_row += 1
        Label(client_frame, text="Credentials:").grid(row=curr_row, column=0, sticky=E)
        Entry(client_frame, textvariable=self.client_vars["CLIENT_GUI_CREDENTIALS"]).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.client_vars["CLIENT_GUI_CREDENTIALS"].trace('w', self.update_client_state)

        Checkbutton(client_frame, text="", variable=self.client_vars["CLIENT_GUI_CREDENTIALS_ON"]).grid(row=curr_row, column=3, sticky=W)
        self.client_vars["CLIENT_GUI_CREDENTIALS_ON"].trace('w', self.update_client_state)

        # the combined command line text
        curr_row += 1
        Button(client_frame, width=6, text="run:", command=self.run_client).grid(row=curr_row, column=0, sticky=N)
        self.T_client = Text(client_frame, height=7, font=("Courier", default_font_size))
        self.T_client.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        self.T_client.configure(state='disabled')

        curr_row += 1
        Button(client_frame, width=9, text="clipboard", command=self.copy_to_clipboard).grid(row=curr_row, column=1, sticky=W)

        client_frame.grid_columnconfigure(0, minsize=80)
        client_frame.grid_columnconfigure(1, minsize=300)
        client_frame.grid_columnconfigure(2, minsize=80)

        return client_frame

    def tabChangedEvent(self, *args):
        tab_id = self.notebook.select()
        self.tab_name = self.notebook.tab(tab_id, option='text')
        if self.tab_name == tab_names['ADMIN']:
            self.update_admin_state()
        elif self.tab_name == tab_names['CLIENT']:
            self.update_client_state()
        elif self.tab_name == tab_names['REDIS']:
            self.update_redis_state()
        else:
            log.info(f"""Unknown tab {self.tab_name}""")

    def create_gui(self):

        self.master.title(self.get_version_str())

        self.notebook = Notebook(self.master)
        self.notebook.grid(row=0, column=0)
        self.notebook.bind_all("<<NotebookTabChanged>>", self.tabChangedEvent)

        client_frame = self.create_client_frame(self.notebook)
        admin_frame = self.create_admin_frame(self.notebook)
        redis_frame = self.create_redis_frame(self.notebook)

        self.notebook.add(client_frame, text='Client')
        self.notebook.add(admin_frame, text='Admin')
        self.notebook.add(redis_frame, text='Activate')

        to_be_selected_tab_name = config_vars["SELECTED_TAB"].str()
        for tab_id in self.notebook.tabs():
            tab_name = self.notebook.tab(tab_id, option='text')
            if tab_name == to_be_selected_tab_name:
                self.notebook.select(tab_id)
                break

        self.master.resizable(0, 0)

        # bring window to front, be default it stays behind the Terminal window
        if config_vars["__CURRENT_OS__"].str() == "Mac":
            os.system('''/usr/bin/osascript -e 'tell app "Finder" to set frontmost of process "Python" to true' ''')

        self.master.mainloop()

    def check_yaml(self, path_to_yaml=None, config_var_containing_path_to_file=None):

        if not path_to_yaml:
            path_to_yaml = config_vars.get(config_var_containing_path_to_file, "").str()

        if path_to_yaml:

            command_line = [os.fspath(config_vars["__INSTL_EXE_PATH__"]), "read-yaml",
                            "--in", path_to_yaml, "--silent"]

            try:
                if getattr(os, "setsid", None):
                    check_yaml_process = subprocess.Popen(command_line, executable=command_line[0], shell=False, preexec_fn=os.setsid)  # Unix
                else:
                    check_yaml_process = subprocess.Popen(command_line, executable=command_line[0], shell=False)  # Windows
            except OSError:
                log.info(f"""Cannot run: {command_line}""")
                return

        unused_stdout, unused_stderr = check_yaml_process.communicate()
        return_code = check_yaml_process.returncode
        if return_code != 0:
            log.info(f"""{" ".join(command_line)} returned exit code {return_code}""")
        else:
            log.info(f"""{path_to_yaml} read OK""")

    def create_redis_frame(self, master):

        self.realign_from_config_vars(self.redis_vars)

        redis_frame = Frame(master)
        #redis_frame.grid(row=0, column=2)

        curr_row = 0
        Label(redis_frame, text="Host:").grid(row=curr_row, column=0)
        Entry(redis_frame, textvariable=self.redis_vars["REDIS_HOST"]).grid(row=curr_row, column=1, sticky=W)
        self.redis_vars["REDIS_HOST"].trace('w', self.update_redis_state)

        Label(redis_frame, text="Port:").grid(row=curr_row, column=2)
        Entry(redis_frame, textvariable=self.redis_vars["REDIS_PORT"]).grid(row=curr_row, column=3, sticky=W)
        self.redis_vars["REDIS_PORT"].trace('w', self.update_redis_state)

        #redis_frame.grid_rowconfigure(0)

        curr_row += 1
        Label(redis_frame, text="Repository:").grid(row=curr_row, column=0)
        Entry(redis_frame, textvariable=self.redis_vars["DOMAIN_REPO_TO_ACTIVATE"]).grid(row=curr_row, column=1, columnspan=1, sticky=W+E)
        self.redis_vars["DOMAIN_REPO_TO_ACTIVATE"].trace('w', self.update_redis_state)

        Label(redis_frame, text="rep-rev:").grid(row=curr_row, column=2, sticky=W)
        Entry(redis_frame, textvariable=self.redis_vars["REPO_REV_TO_ACTIVATE"]).grid(row=curr_row, column=3, columnspan=1, sticky=W+E)
        Button(redis_frame, width=7, text="Activate", command=self.activate_repo_rev).grid(row=curr_row, column=4, columnspan=1, sticky=W)

        curr_row += 1
        self.tree = Treeview(redis_frame, columns=('major version', 'uploaded', 'activated'))
        self.tree.column('major version', width=100, anchor='center')
        self.tree.heading('major version', text='Major Version')
        self.tree.column('uploaded', width=100, anchor='center')
        self.tree.heading('uploaded', text='Uploaded')
        self.tree.column('activated', width=100, anchor='center')
        self.tree.heading('activated', text='Activated')
        self.tree.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        self.tree_focused_item = None

        self.update_redis_table()

        return redis_frame

    def update_redis_table(self):
        self.update_redis_state()
        unified_dict = defaultdict(dict)

        active_repo_rev_keys = self.redis_conn.keys("wv:*:*:active_repo_rev")
        for active_repo_rev_key in active_repo_rev_keys:
            active_repo_rev_value = self.redis_conn.get(active_repo_rev_key)
            splited = active_repo_rev_key.split(":")
            domain = splited[1]
            major_version = splited[2]
            if major_version not in unified_dict[domain]:
                unified_dict[domain][major_version] = dict()
            unified_dict[domain][major_version]['activated'] = active_repo_rev_value

        last_uploaded_repo_rev_keys = self.redis_conn.keys("wv:*:*:last_uploaded_repo_rev")
        for last_uploaded_repo_rev_key in last_uploaded_repo_rev_keys:
            last_uploaded_repo_rev_value = self.redis_conn.get(last_uploaded_repo_rev_key)
            splited = last_uploaded_repo_rev_key.split(":")
            domain = splited[1]
            major_version = splited[2]
            if major_version not in unified_dict[domain]:
                unified_dict[domain][major_version] = dict()
            unified_dict[domain][major_version]['uploaded'] = last_uploaded_repo_rev_value

        current_items = self.tree.get_children()
        for domain_key, domain_dict in unified_dict.items():
            for major_version_key, major_version_dict in domain_dict.items():
                activated = major_version_dict.get('activated', "N/A")
                uploaded = major_version_dict.get('uploaded', "N/A")
                item_id = f"{domain_key}:{major_version_key}"
                if item_id in current_items:
                    self.tree.item(item_id, text=domain_key, values=(major_version_key, uploaded, activated))
                else:
                    self.tree.insert('', 'end', item_id, text=domain_key, values=(major_version_key, uploaded, activated))

        focused_item = self.tree.focus()
        if focused_item != self.tree_focused_item:
            self.tree_focused_item = focused_item
            if self.tree_focused_item:
                focused_item_values = self.tree.item(self.tree_focused_item)
                new_value = ":".join((focused_item_values['text'], str(focused_item_values['values'][0])))
                self.redis_vars["DOMAIN_REPO_TO_ACTIVATE"].set(new_value)
                uploaded_rep_rev = focused_item_values['values'][1]
                activated_rep_rev = int(focused_item_values['values'][2])
                self.redis_vars["REPO_REV_TO_ACTIVATE"].set(uploaded_rep_rev)

        self.notebook.after(1500, self.update_redis_table)

    def activate_repo_rev(self):
        try:
            current_items = self.tree.get_children()
            domain_repo = self.redis_vars["DOMAIN_REPO_TO_ACTIVATE"].get()
            if domain_repo in current_items:
                host = self.redis_vars["REDIS_HOST"].get()
                repo_rev = self.redis_vars["REPO_REV_TO_ACTIVATE"].get()
                redis_value = ":".join(('activate', domain_repo, str(repo_rev)))
                redis_key = ":".join(("wv", host, "waiting_list"))
                answer = messagebox.askyesno("Activate repo-rev", f"Activate repo-rev {repo_rev} on {domain_repo} ?")
                if answer:
                    self.redis_conn.lpush(redis_key, redis_value)
        except Exception as ex:
            print(f"activate_repo_rev exception {ex}")

    def remove_redis_key(self, key_config_var, value_config_var=None):
        self.redis_vars[key_config_var].realign_from_tk_var()
        key_to_remove = config_vars[key_config_var].str()
        self.redis_conn.delete(key_to_remove)
        if value_config_var is not None:
            self.redis_vars[value_config_var].set("")

    def lpush_redis_key(self, key_config_var, value_config_var):
        self.redis_vars[key_config_var].realign_from_tk_var()
        self.redis_vars[value_config_var].realign_from_tk_var()
        key_to_set = config_vars[key_config_var].str()
        value_to_push = config_vars[value_config_var].str()
        self.redis_conn.lpush(key_to_set, value_to_push)

    def get_redis_key(self, key_config_var, result_config_var):
        self.redis_vars[key_config_var].realign_from_tk_var()
        key_to_get = config_vars[key_config_var].str()
        value = self.redis_conn.get(key_to_get)
        if value is None:
            value = "UNKNOWN KEY"
        config_vars[result_config_var] = value
        self.redis_vars[result_config_var].realign_from_config_var()

    def set_redis_key(self, key_config_var, value_config_var):
        self.redis_vars[key_config_var].realign_from_tk_var()
        self.redis_vars[value_config_var].realign_from_tk_var()
        key_to_set = config_vars[key_config_var].str()
        value_to_set = config_vars[value_config_var].str()
        self.redis_conn.set(key_to_set, value_to_set)
        self.redis_vars[value_config_var].realign_from_config_var()

    def update_redis_state(self, *args):
        self.realign_from_tk_vars(self.redis_vars)

        host = config_vars["REDIS_HOST"].str()
        port = config_vars["REDIS_PORT"].int()

        if self.redis_conn is not None:
            if self.redis_conn.host != host or self.redis_conn.port != port:
                self.redis_conn = None
        if self.redis_conn is None:
            self.redis_conn = utils.RedisClient(host, port)


class ToolTip(Toplevel):
    """
    Provides a ToolTip widget for Tkinter.
    To apply a ToolTip to any Tkinter widget, simply pass the widget to the
    ToolTip constructor
    """

    def __init__(self, wdgt, msg=None, msgFunc=None, delay=0.2, follow=True) -> None:
        """
        Initialize the ToolTip

        Arguments:
          wdgt: The widget this ToolTip is assigned to
          msg:  A static string message assigned to the ToolTip
          msgFunc: A function that retrieves a string to use as the ToolTip text
          delay:   The delay in seconds before the ToolTip appears(may be float)
          follow:  If True, the ToolTip follows motion, otherwise hides
        """
        self.wdgt = wdgt
        self.parent = self.wdgt.master  # The parent of the ToolTip is the parent of the ToolTips widget
        Toplevel.__init__(self, self.parent, bg='black', padx=1, pady=1)  # Initalise the Toplevel
        self.withdraw()  # Hide initially
        self.overrideredirect(True)  # The ToolTip Toplevel should have no frame or title bar

        self.msgVar = StringVar()  # The msgVar will contain the text displayed by the ToolTip
        if msg is None:
            self.msgVar.set('No message provided')
        else:
            self.msgVar.set(msg)
        self.msgFunc = msgFunc
        self.delay = delay
        self.follow = follow
        self.visible = 0
        self.lastMotion = 0
        Message(self, textvariable=self.msgVar, bg='#FFFFDD',
                aspect=1000).grid()  # The test of the ToolTip is displayed in a Message widget
        self.wdgt.bind( '<Enter>', self.spawn, '+' )                      # Add bindings to the widget. This will NOT override bindings widget already has
        self.wdgt.bind('<Leave>', self.hide, '+')
        self.wdgt.bind('<Motion>', self.move, '+')

    def spawn(self, event=None):
        """
        Spawn the ToolTip.  This simply makes the ToolTip eligible for display.
        Usually this is caused by entering the widget

        Arguments:
          event: The event that called this funciton
        """
        self.visible = 1
        self.after(int(self.delay * 1000), self.show)  # The after function takes a time argument in miliseconds

    def show(self):
        """
        Displays the ToolTip if the time delay has been long enough
        """
        if self.visible == 1 and time() - self.lastMotion > self.delay:
            self.visible = 2
        if self.visible == 2:
            self.deiconify()

    def move(self, event):
        """
        Processes motion within the widget.

        Arguments:
          event: The event that called this function
        """
        self.lastMotion = time()
        if self.follow is False:  # If the follow flag is not set, motion within the widget will make the ToolTip dissapear
            self.withdraw()
            self.visible = 1
        self.geometry( '+%i+%i' % ( event.x_root+10, event.y_root+10 ) )        # Offset the ToolTip 10x10 pixes southwest of the pointer
        try:
            self.msgVar.set( self.msgFunc() )                                   # Try to call the message function.  Will not change the message if the message function is None or the message function fails
        except Exception:
            pass
        self.after(int(self.delay * 1000), self.show)

    def hide(self, event=None):
        """
        Hides the ToolTip.  Usually this is caused by leaving the widget

        Arguments:
          event: The event that called this function
        """
        self.visible = 0
        self.withdraw()
