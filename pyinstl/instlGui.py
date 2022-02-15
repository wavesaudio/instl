#!/usr/bin/env python3.9


import sys
import json
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
import re
log = logging.getLogger()

import utils
import aYaml
from .instlInstanceBase import InstlInstanceBase
from configVar import config_vars


from utils.redisClient import RedisClient

tk_global_master = Tk()

if getattr(os, "setsid", None):
    default_font_size = 17  # for Mac
else:
    default_font_size = 12  # for Windows

admin_command_template_variables = {
    'svn2stage': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'fix-symlinks': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'gather-manifest-files': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'wtar': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'verify-repo': '__ADMIN_CALL_INSTL_ONLY_CONFIG_FILE_TEMPLATE__',
    'stage2svn': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'fix-props': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'depend': '__ADMIN_CALL_INSTL_DEPEND_TEMPLATE__',
    'fix-perm': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'collect-manifests': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__'
    'collect-manifests': '__ADMIN_CALL_INSTL_ONLY_CONFIG_FILE_TEMPLATE__'
}


def CreateTkConfigClass(TkBase, convert_type_func):
    """ creates a class that connects between Tk Variable class (StringVar, intVar,...)
        and ConfigVar. The value is kept in the Tk Variable but the ConfigVar is updated whenever
        the tk variable updated. Implementation is is "double callback" where callbacks to tk and to configVar
        do the work of adjusting the values. This is done so because tk variables cannot be inherited.
    """
    class TkConfigVar(TkBase):
        """ bridge between tkinter StringVar to instl ConfigVar."""

        def __init__(self, config_var_name, master=None, value=None, debug_var=False):
            TkBase.__init__(self, master, value, config_var_name)
            self.debug_var = debug_var
            self.convert_type_func = convert_type_func
            self.config_var_name = config_var_name
            self.__internal_update = False
            config_vars.setdefault(self.config_var_name, value)  # create a ConfigVar is one does not exists
            # call set_callback_when_value_is_set because config_vars.setdefault will not assign the callback is the confiVar already exists
            config_vars[self.config_var_name].set_callback_when_value_is_set(self._config_var_set_value_callback)
            self._our_trace_write_callback = None
            self.trace("w", self._internal_trace_write_callback)
            if self.debug_var:
                print(f"TkConfigVar.__init__({self.config_var_name})")

        def _internal_trace_write_callback(self, *args, **kwargs):
            """
                this function will be set as the tk var trace
                if tk var was written, pass the value to the configVar
            """
            if not self.__internal_update:
                value = self._tk.globalgetvar(self.config_var_name)
                self.__internal_update = True
                config_vars[self.config_var_name] = value
                self.__internal_update = False
                if self._our_trace_write_callback:
                    self._our_trace_write_callback(*args, **kwargs)

        def _config_var_set_value_callback(self, var_name, new_var_value):
            """ ConfigVar will call this callback every time a value has been assigned """
            if not self.__internal_update:  # called from _trace_write_callback so need to avoid circular callback calls
                if self.debug_var:
                    print(f"TkConfigVar._config_var_set_value_callback({self.config_var_name}) <- {new_var_value}")
                TkBase.set(self, self.convert_type_func(new_var_value))
            else:  # configVar was changed, pass value to tk var
                self.__internal_update = True
                self._tk.globalsetvar(self.config_var_name, new_var_value)
                self.__internal_update = False

        def _get_value_from_config_var(self):
            retVal = self.convert_type_func(config_vars.get(self.config_var_name, self.convert_type_func()))
            return retVal

        def set_trace_write_callback(self, trace_write_callback):
            """ this is our way to set the callback"""
            self._our_trace_write_callback = trace_write_callback

    return TkConfigVar


TkConfigVarStr  = CreateTkConfigClass(StringVar, str)
TkConfigVarInt  = CreateTkConfigClass(IntVar, int)
TkConfigVarBool = CreateTkConfigClass(BooleanVar, bool)


class FrameController:
    """ base class for objects controlling a Tk frame """
    def __init__(self, name, instl_obj):
        self.name = name
        self.instl_obj = instl_obj
        self.tk_vars = dict()
        self.master = None
        self.frame = None
        self.text_widget = None  # if initialized will be target for clipboard copy

    def copy_to_clipboard(self):
        if self.text_widget:
            value = self.text_widget.get("1.0",END)

            if value and value not in ["\n"]:
                self.master.clipboard_clear()
                self.master.clipboard_append(value)
                log.info("instl command was copied to clipboard!")

    def dump_config_vars(self):
        command_line_parts = list(config_vars["__ADMIN_CALL_DUMP_CONFIG_VARS_TEMPLATE__"])
        resolved_command_line_parts = [shlex.quote(p) for p in config_vars.resolve_list_to_list(command_line_parts)]

        if getattr(os, "setsid", None):
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, preexec_fn=os.setsid, stderr=subprocess.PIPE)  # Unix
        else:
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, stderr=subprocess.PIPE)  # Windows
        unused_stdout, unused_stderr = admin_process.communicate()
        err_str = unused_stderr.decode()

        self.prompt_msg_on_err(admin_process.returncode, resolved_command_line_parts, err_msg=err_str)

    def update_state(self, *args, **kwargs):
        pass
        #print(f"{kwargs.get('who', '?')} initiated update_state")

    def open_file_dialog(self, config_var_name):
        import tkinter.filedialog

        retVal = tkinter.filedialog.askopenfilename()
        if retVal:
            self.tk_vars[config_var_name].set(retVal)

    def save_file_dialog(self, config_var_name):
        import tkinter.filedialog

        retVal = tkinter.filedialog.asksaveasfilename()
        if retVal:
            self.tk_vars[config_var_name].set(retVal)

    def create_line_for_file(self, curr_row, curr_column, label, var_name, locate=True, save_as=False, edit=True, check=False, combobox=None, columnspan=1, label_stick=E):

        Label(self.frame, text=label).grid(row=curr_row, column=curr_column, sticky=label_stick)
        curr_column += 1

        if combobox:
            combobox.grid(row=curr_row, column=curr_column, columnspan=columnspan, sticky="WE")
        else:
            Entry(self.frame, textvariable=self.tk_vars[var_name]).grid(row=curr_row, column=curr_column, columnspan=columnspan, sticky="WE")
        curr_column += columnspan

        if locate:
            if save_as:
                command = functools.partial(self.save_file_dialog, var_name)
            else:
                command = functools.partial(self.open_file_dialog, var_name)
            Button(self.frame, width=3, text="...", command=command).grid(row=curr_row, column=curr_column, sticky=W)
            curr_column += 1

        if edit:
            Button(self.frame, width=4, text="Edit",
                command=functools.partial(self.open_file_for_edit, config_var_containing_path_to_file=var_name)).grid(row=curr_row, column=curr_column, sticky=W)
            curr_column += 1

        if check:
            Button(self.frame, width=3, text="Chk",
               command=functools.partial(self.check_yaml, config_var_containing_path_to_file=var_name)).grid(row=curr_row, column=curr_column, sticky=W)
            curr_column += 1

    def create_frame(self, master):
        self.master = master
        self.frame = Frame(master)

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
                os.startfile(os.fspath(path_to_file), 'edit')  # windows
            except AttributeError:
                subprocess.call(['open', os.fspath(path_to_file)])

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

    def prompt_msg_on_err(self, return_code, resolved_command_line_parts, err_msg=''):

        if return_code != 0:
            match = re.findall(r"{.+[:,].+}|\[.+[,:].+\]", err_msg)
            result = json.loads(match[0]) if match else ''
            exception_sir = result['exception_str'] if result and result['exception_str'] else ''
            log.info(f"""{" ".join(resolved_command_line_parts)} returned exit code {return_code}""")
            messagebox.showwarning(message="Procces finnished with errors:" + exception_sir)


class ClientFrameController(FrameController):
    def __init__(self, instl_obj):
        super().__init__("Client", instl_obj)
        self.tk_vars["CLIENT_GUI_CMD"] = TkConfigVarStr("CLIENT_GUI_CMD")
        self.tk_vars["CLIENT_GUI_IN_FILE"] = TkConfigVarStr("CLIENT_GUI_IN_FILE")
        self.tk_vars["CLIENT_GUI_OUT_FILE"] = TkConfigVarStr("CLIENT_GUI_OUT_FILE")
        self.tk_vars["CLIENT_GUI_RUN_BATCH"] = TkConfigVarInt("CLIENT_GUI_RUN_BATCH")
        self.tk_vars["CLIENT_GUI_CREDENTIALS"] = TkConfigVarStr("CLIENT_GUI_CREDENTIALS")
        self.tk_vars["CLIENT_GUI_CREDENTIALS_ON"] = TkConfigVarInt("CLIENT_GUI_CREDENTIALS_ON")
        self.client_input_combobox = None
        self.client_run_batch_file_checkbox = None

    def update_client_input_file_combo(self, *args):
        new_input_file = Path(self.tk_vars["CLIENT_GUI_IN_FILE"].get())
        if new_input_file.is_file():
            new_input_file_dir = new_input_file.parent
            dir_items = list()
            for item in os.listdir(new_input_file_dir):
                item_Path = new_input_file_dir.joinpath(item)
                if item_Path.is_file:
                    dir_items.append(item_Path)
            self.client_input_combobox.configure(values=dir_items)

    def update_state(self, *args, **kwargs):  # ClientFrameController
        super().update_state(*args, **kwargs)
        self.update_client_input_file_combo()

        input_file_base_name = config_vars["CLIENT_GUI_IN_FILE"].Path().name
        config_vars["CLIENT_GUI_IN_FILE_NAME"] = input_file_base_name

        if self.tk_vars["CLIENT_GUI_CMD"].get() in list(config_vars["__COMMANDS_WITH_RUN_OPTION__"]):
            self.client_run_batch_file_checkbox.configure(state='normal')
        else:
            self.client_run_batch_file_checkbox.configure(state='disabled')

        command_line = " ".join(self.create_client_command_line())
        self.text_widget.configure(state='normal')
        self.text_widget.delete(1.0, END)
        self.text_widget.insert(END, config_vars.resolve_str(command_line))
        self.text_widget.configure(state='disabled')

    def create_frame(self, master):  # ClientFrameController
        super().create_frame(master)
        self.frame.grid(row=0, column=0)

        # self.frame.grid_columnconfigure(0, minsize=80)
        # self.frame.grid_columnconfigure(1, minsize=200)
        # self.frame.grid_columnconfigure(2, minsize=80)

        curr_row = 0
        command_label = Label(self.frame, text="Command:")
        command_label.grid(row=curr_row, column=0, sticky=W)

        # instl command selection
        client_command_list = list(config_vars["__CLIENT_GUI_CMD_LIST__"])
        OptionMenu(self.frame, self.tk_vars["CLIENT_GUI_CMD"],
                   self.tk_vars["CLIENT_GUI_CMD"].get(), *client_command_list, command=functools.partial(self.update_state, who="CLIENT_GUI_CMD")).grid(row=curr_row, column=1, sticky=W)

        self.client_run_batch_file_checkbox = Checkbutton(self.frame, text="Run batch file",
                    variable=self.tk_vars["CLIENT_GUI_RUN_BATCH"], command=functools.partial(self.update_state, who="CLIENT_GUI_RUN_BATCH"))
        self.client_run_batch_file_checkbox.grid(row=curr_row, column=1, sticky=E)

        # path to input file
        curr_row += 1
        self.tk_vars["CLIENT_GUI_IN_FILE"].set_trace_write_callback(functools.partial(self.update_state, who="CLIENT_GUI_IN_FILE"))
        self.client_input_combobox = Combobox(self.frame, textvariable=self.tk_vars["CLIENT_GUI_IN_FILE"])
        self.create_line_for_file(curr_row=curr_row, curr_column=0, label="Input file:", var_name="CLIENT_GUI_IN_FILE", locate=True, edit=True, check=True, combobox=self.client_input_combobox)

        # path to output file
        curr_row += 1
        self.tk_vars["CLIENT_GUI_OUT_FILE"].set_trace_write_callback(functools.partial(self.update_state, who="CLIENT_GUI_OUT_FILE"))
        self.create_line_for_file(curr_row=curr_row, curr_column=0, label="Batch file:", var_name="CLIENT_GUI_OUT_FILE", locate=True, save_as=True, edit=True, check=False, combobox=None)

        # s3 user credentials
        curr_row += 1
        Label(self.frame, text="Credentials:").grid(row=curr_row, column=0, sticky=E)
        Entry(self.frame, textvariable=self.tk_vars["CLIENT_GUI_CREDENTIALS"]).grid(row=curr_row, column=1, columnspan=1, sticky="WE")
        self.tk_vars["CLIENT_GUI_CREDENTIALS"].set_trace_write_callback(functools.partial(self.update_state, who="CLIENT_GUI_CREDENTIALS"))

        Checkbutton(self.frame, text="", variable=self.tk_vars["CLIENT_GUI_CREDENTIALS_ON"], command=functools.partial(self.update_state, who="CLIENT_GUI_CREDENTIALS_ON")).grid(row=curr_row, column=2, sticky=W)

        # the combined client command line text
        curr_row += 1
        Button(self.frame, width=6, text="run:", command=self.run_client).grid(row=curr_row, column=0, sticky=W+N)

        self.text_widget = Text(self.frame, height=7, font=("Courier", default_font_size), width=40)
        self.text_widget.grid(row=curr_row, column=1, columnspan=1, sticky="W")
        self.text_widget.configure(state='disabled')

        curr_row += 1
        Button(self.frame, width=9, text="clipboard", command=self.copy_to_clipboard).grid(row=curr_row, column=1, sticky=W)

        return self.frame

    def create_client_command_line(self):
        retVal = [os.fspath(config_vars["__INSTL_EXE_PATH__"]), config_vars["CLIENT_GUI_CMD"].str(),
                  "--in", config_vars["CLIENT_GUI_IN_FILE"].str(),
                  "--out", config_vars["CLIENT_GUI_OUT_FILE"].str()]

        if bool(config_vars["CLIENT_GUI_CREDENTIALS_ON"]):
            credentials = self.tk_vars["CLIENT_GUI_CREDENTIALS"].get()
            if credentials != "":
                retVal.append("--credentials")
                retVal.append(credentials)

        run_batch_state = self.tk_vars["CLIENT_GUI_RUN_BATCH"].get()
        if run_batch_state == 1:
            retVal.append("--run")

        if 'Win' in list(config_vars["__CURRENT_OS_NAMES__"]):
            if not getattr(sys, 'frozen', False):
                retVal.insert(0, sys.executable)

        return retVal

    def run_client(self):
        self.update_state(who="ClientFrameController.run_client")
        command_line_parts = self.create_client_command_line()
        resolved_command_line_parts = config_vars.resolve_list_to_list(command_line_parts)

        if getattr(os, "setsid", None):
            client_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, preexec_fn=os.setsid,  stderr=subprocess.PIPE)  # Unix
        else:
            client_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # Windows
        unused_stdout, unused_stderr = client_process.communicate()
        err_str = unused_stderr.decode()

        self.prompt_msg_on_err(client_process.returncode, resolved_command_line_parts,err_msg=err_str)

        print("...")


class AdminFrameController(FrameController):
    def __init__(self, instl_obj):
        super().__init__("Admin", instl_obj)
        self.tk_vars["ADMIN_GUI_CMD"] = TkConfigVarStr("ADMIN_GUI_CMD")
        self.tk_vars["ADMIN_GUI_TARGET_CONFIG_FILE"] = TkConfigVarStr("ADMIN_GUI_TARGET_CONFIG_FILE")
        self.tk_vars["ADMIN_GUI_LOCAL_CONFIG_FILE"] = TkConfigVarStr("ADMIN_GUI_LOCAL_CONFIG_FILE")
        self.tk_vars["ADMIN_GUI_OUT_BATCH_FILE"] = TkConfigVarStr("ADMIN_GUI_OUT_BATCH_FILE")
        self.tk_vars["__STAGING_INDEX_FILE__"] = TkConfigVarStr("__STAGING_INDEX_FILE__")
        self.tk_vars["SYNC_BASE_URL"] = TkConfigVarStr("SYNC_BASE_URL")
        self.tk_vars["DISPLAY_SVN_URL_AND_REPO_REV"] = TkConfigVarStr("DISPLAY_SVN_URL_AND_REPO_REV")
        self.tk_vars["ADMIN_GUI_LIMIT"] = TkConfigVarStr("ADMIN_GUI_LIMIT")
        self.tk_vars["ADMIN_GUI_RUN_BATCH"] = TkConfigVarInt("ADMIN_GUI_RUN_BATCH")
        self.limit_path_entry_widget = None
        self.admin_run_batch_file_checkbox = None

    def read_admin_config_files(self, *args, **kwargs):
        for config_file_var in ("ADMIN_GUI_TARGET_CONFIG_FILE", "ADMIN_GUI_LOCAL_CONFIG_FILE"):
            config_path = config_vars.get(config_file_var, None).Path()
            if config_path:
                if config_path.is_file():
                    config_vars[ "__SEARCH_PATHS__"].clear() # so __include__ file will not be found on old paths
                    self.instl_obj.read_yaml_file(config_path)
                else:
                    log.info(f"""File not found: {config_path}""")

    def update_state(self, *args, **kwargs):  # AdminFrameController
        super().update_state(*args, **kwargs)
        self.read_admin_config_files()

        input_file_base_name = Path(config_vars["ADMIN_GUI_LOCAL_CONFIG_FILE"].raw()).name
        config_vars["ADMIN_GUI_CONFIG_FILE_NAME"] = input_file_base_name

        if self.tk_vars["ADMIN_GUI_CMD"].get() in list(config_vars["__COMMANDS_WITH_LIMIT_OPTION__"]):
            self.limit_path_entry_widget.configure(state='normal')
        else:
            self.limit_path_entry_widget.configure(state='disabled')

        if self.tk_vars["ADMIN_GUI_CMD"].get() in list(config_vars["__COMMANDS_WITH_RUN_OPTION__"]):
            self.admin_run_batch_file_checkbox.configure(state='normal')
        else:
            self.admin_run_batch_file_checkbox.configure(state='disabled')

        command_line = " ".join([shlex.quote(p) for p in self.create_admin_command_line()])

        self.text_widget.configure(state='normal')
        self.text_widget.delete(1.0, END)
        self.text_widget.insert(END, config_vars.resolve_str(command_line))
        self.text_widget.configure(state='disabled')

    def create_frame(self, master):  # AdminFrameController
        super().create_frame(master)
        self.frame.grid(row=0, column=0)

        curr_row = 0
        Label(self.frame, text="Command:").grid(row=curr_row, column=0, sticky=E)

        # instl command selection
        admin_command_list = list(config_vars["__ADMIN_GUI_CMD_LIST__"])
        commandNameMenu = OptionMenu(self.frame, self.tk_vars["ADMIN_GUI_CMD"],
                                     self.tk_vars["ADMIN_GUI_CMD"].get(), *admin_command_list,
                                     command=functools.partial(self.update_state, who="ADMIN_GUI_CMD"))
        commandNameMenu.grid(row=curr_row, column=1, sticky=W)
        ToolTip(commandNameMenu, msg="instl admin command")

        self.admin_run_batch_file_checkbox = Checkbutton(self.frame, text="Run batch file", variable=self.tk_vars["ADMIN_GUI_RUN_BATCH"], command=functools.partial(self.update_state, who="ADMIN_GUI_RUN_BATCH"))
        self.admin_run_batch_file_checkbox.grid(row=curr_row, column=1, columnspan=1, sticky=E)

        # path to config files

        curr_row += 1
        self.tk_vars["ADMIN_GUI_TARGET_CONFIG_FILE"].set_trace_write_callback(functools.partial(self.update_state, who="ADMIN_GUI_TARGET_CONFIG_FILE"))
        self.create_line_for_file(curr_row=curr_row, curr_column=0, label="target config file:", var_name="ADMIN_GUI_TARGET_CONFIG_FILE", locate=True, edit=True, check=True, combobox=None)
        curr_row += 1
        self.tk_vars["ADMIN_GUI_LOCAL_CONFIG_FILE"].set_trace_write_callback(functools.partial(self.update_state, who="ADMIN_GUI_LOCAL_CONFIG_FILE"))
        self.create_line_for_file(curr_row=curr_row, curr_column=0, label="local config file:", var_name="ADMIN_GUI_LOCAL_CONFIG_FILE", locate=True, edit=True, check=True, combobox=None)

        # path to stage index file
        curr_row += 1
        Label(self.frame, text="Stage index:").grid(row=curr_row, column=0, sticky=E)
        Label(self.frame, text="---", textvariable=self.tk_vars["__STAGING_INDEX_FILE__"]).grid(row=curr_row, column=1, columnspan=2, sticky=W)

        editIndexButt = Button(self.frame, width=4, text="Edit", command=functools.partial(self.open_file_for_edit, config_var_containing_path_to_file="__STAGING_INDEX_FILE__"))
        editIndexButt.grid(row=curr_row, column=3, sticky=W)
        ToolTip(editIndexButt, msg="edit repository index")

        checkIndexButt = Button(self.frame, width=3, text="Chk", command=functools.partial(self.check_yaml, config_var_containing_path_to_file="__STAGING_INDEX_FILE__"))
        checkIndexButt.grid(row=curr_row, column=4, sticky=W)
        ToolTip(checkIndexButt, msg="read repository index to check it's structure")

        # path to svn repository
        curr_row += 1
        Label(self.frame, text="Svn repo:").grid(row=curr_row, column=0, sticky=E)
        svnRepoLabel = Label(self.frame, text="---", textvariable=self.tk_vars["DISPLAY_SVN_URL_AND_REPO_REV"])
        svnRepoLabel.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        ToolTip(svnRepoLabel, msg="URL of the SVN repository with current repo-rev")

        # sync URL
        curr_row += 1
        Label(self.frame, text="Sync URL:").grid(row=curr_row, column=0, sticky=E)
        syncURLLabel = Label(self.frame, text="---", textvariable=self.tk_vars["SYNC_BASE_URL"])
        syncURLLabel.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        ToolTip(syncURLLabel, msg="Top URL for uploading to the repository")

        # path to output file
        curr_row += 1
        self.tk_vars["ADMIN_GUI_OUT_BATCH_FILE"].set_trace_write_callback(functools.partial(self.update_state, who="ADMIN_GUI_OUT_BATCH_FILE"))
        self.create_line_for_file(curr_row=curr_row, curr_column=0, label="Batch file:", var_name="ADMIN_GUI_OUT_BATCH_FILE", locate=True, save_as=True, edit=True, check=False)

        # relative path to limit folder
        curr_row += 1
        Label(self.frame, text="Limit to:").grid(row=curr_row, column=0, sticky=E)
        ADMIN_GUI_LIMIT_values = config_vars.get("ADMIN_GUI_LIMIT", []).list()
        ADMIN_GUI_LIMIT_values = list(filter(None, ADMIN_GUI_LIMIT_values))
        self.limit_path_entry_widget = Entry(self.frame, textvariable=self.tk_vars["ADMIN_GUI_LIMIT"])
        self.limit_path_entry_widget.grid(row=curr_row, column=1, columnspan=1, sticky=W)
        self.tk_vars["ADMIN_GUI_LIMIT"].set_trace_write_callback(functools.partial(self.update_state, who="ADMIN_GUI_LIMIT"))

        # the combined command line text
        curr_row += 1
        Button(self.frame, width=6, text="run:", command=self.run_admin).grid(row=curr_row, column=0, sticky=N)
        self.text_widget = Text(self.frame, height=9, font=("Courier", default_font_size), width=40)
        self.text_widget.grid(row=curr_row, column=1, columnspan=1, sticky=W)
        self.text_widget.configure(state='disabled')

        #curr_row += 1
        Button(self.frame, width=16, text="Command to clipboard", command=self.copy_to_clipboard).grid(row=curr_row, column=2, sticky=N)
        Button(self.frame, width=16, text="ConfigVars to clipboard", command=self.dump_config_vars).grid(row=curr_row, column=2)
        Button(self.frame, width=16, text="Save state", command=self.instl_obj.write_history).grid(row=curr_row, column=2, sticky=S)

        return self.frame

    def create_admin_command_line(self):
        command_name = config_vars["ADMIN_GUI_CMD"].str()
        template_variable = admin_command_template_variables[command_name]
        retVal = list(config_vars[template_variable])

        # some special handling of command line parameters cannot yet be expressed in the command template
        if command_name != 'depend':
            if command_name in list(config_vars["__COMMANDS_WITH_LIMIT_OPTION__"]):
                limit_paths = self.tk_vars["ADMIN_GUI_LIMIT"].get()
                if limit_paths != "":
                    retVal.append("--limit")
                    try:
                        retVal.extend(shlex.split(limit_paths))
                    except ValueError:
                        retVal.append(limit_paths)
            if self.tk_vars["ADMIN_GUI_RUN_BATCH"].get() and command_name in list(config_vars["__COMMANDS_WITH_RUN_OPTION__"]):
                retVal.append("--run")

        if 'Win' in list(config_vars["__CURRENT_OS_NAMES__"]):
            if not getattr(sys, 'frozen', False):
                retVal.insert(0, sys.executable)

        return retVal

    def run_admin(self):
        self.update_state(who="AdminFrameController.run_admin")
        command_line_parts = self.create_admin_command_line()
        resolved_command_line_parts = [shlex.quote(p) for p in config_vars.resolve_list_to_list(command_line_parts)]

        if getattr(os, "setsid", None):
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, preexec_fn=os.setsid, stderr=subprocess.PIPE)  # Unix
        else:
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, stderr=subprocess.PIPE)  # Windows
        unused_stdout, unused_stderr = admin_process.communicate()
        err_str = unused_stderr.decode()

        self.prompt_msg_on_err(admin_process.returncode, resolved_command_line_parts, err_msg=err_str)


class ActivateFrameController(FrameController):
    def __init__(self, instl_obj):
        super().__init__("Activate", instl_obj)
        self.tk_vars["REDIS_HOST"] = TkConfigVarStr("REDIS_HOST")
        self.tk_vars["REDIS_PORT"] = TkConfigVarInt("REDIS_PORT")
        self.tk_vars["ACTIVATE_CONFIG_FILE"] = TkConfigVarStr("ACTIVATE_CONFIG_FILE")
        self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"] = TkConfigVarStr("DOMAIN_REPO_TO_ACTIVATE")
        #todo oren - ??
        self.tk_vars["DOMAIN_REPO_TO_UPLOAD"] = TkConfigVarStr("DOMAIN_REPO_TO_UPLOAD")
        self.tk_vars["IN_PROGRESS_VALUE"] = TkConfigVarStr("IN_PROGRESS_VALUE")
        self.tk_vars["HEARTBEAT_VALUE"] = TkConfigVarStr("HEARTBEAT_VALUE")

        self.tk_vars["REDIS_KEY_VALUE_1"] = TkConfigVarStr("REDIS_KEY_VALUE_1")
        self.tk_vars["REPO_REV_TO_ACTIVATE"] = TkConfigVarStr("REPO_REV_TO_ACTIVATE")
        # todo oren - ??
        self.tk_vars["REPO_REV_TO_UPLOAD"] = TkConfigVarStr("REPO_REV_TO_UPLOAD")
        self.tk_vars["REDIS_KEY_VALUE_2"] = TkConfigVarStr("REDIS_KEY_VALUE_2")
        self.redis_conn: utils.redisClient.RedisClient = None
        self.update_redis_table_working_id = None
        self.last_heartbeat_value = ""
        self.heartbeat_no_diff_counter = 0

    def read_activate_config_files(self):
        for config_file_var in ("ACTIVATE_CONFIG_FILE", ):
            config_path = config_vars.get(config_file_var, None).Path()
            if config_path:
                if config_path.is_file():
                    config_vars[ "__SEARCH_PATHS__"].clear() # so __include__ file will not be found on old paths
                    self.instl_obj.read_yaml_file(config_path)
                else:
                    log.info(f"""File not found: {config_path}""")

    def update_state(self, *args, **kwargs):
        super().update_state(*args, **kwargs)
        self.read_activate_config_files()

        host = config_vars.get("REDIS_HOST", "").str()
        port = config_vars.get("REDIS_PORT", 0).int()

        if self.redis_conn is not None:
            if self.redis_conn.host != host or self.redis_conn.port != port:
                self.stop_update_redis_table()
                log.info(f"disconnected from redis host: {self.redis_conn.host}, port: {self.redis_conn.port}")
                self.redis_conn.close()
                self.redis_conn = None
        if self.redis_conn is None and host and port:
            self.redis_conn = utils.redisClient.RedisClient(host, port)
            log.info(f"connected to redis host: {self.redis_conn.host}, port: {self.redis_conn.port}")
            self.start_update_redis_table()

    def update_redis_table(self):
        if self.redis_conn is not None:
            unified_dict = defaultdict(dict)

            active_repo_rev_keys = self.redis_conn.keys(str(config_vars["ACTIVATE_REPO_REV_WILDCARD"]))
            for active_repo_rev_key in active_repo_rev_keys:
                active_repo_rev_value = self.redis_conn.get(active_repo_rev_key)
                splited = active_repo_rev_key.split(":")
                domain = splited[1]
                major_version = splited[2]
                if major_version not in unified_dict[domain]:
                    unified_dict[domain][major_version] = dict()
                unified_dict[domain][major_version]['activated'] = active_repo_rev_value

            last_uploaded_repo_rev_keys = self.redis_conn.keys(str(config_vars["UPLOAD_REPO_REV_WILDCARD"]))
            for last_uploaded_repo_rev_key in last_uploaded_repo_rev_keys:
                last_uploaded_repo_rev_value = self.redis_conn.get(last_uploaded_repo_rev_key)
                splited = last_uploaded_repo_rev_key.split(":")
                domain = splited[1]
                major_version = splited[2]
                if major_version not in unified_dict[domain]:
                    unified_dict[domain][major_version] = dict()
                unified_dict[domain][major_version]['uploaded'] = last_uploaded_repo_rev_value

            current_items = list(self.tree.get_children())
            for domain_key, domain_dict in unified_dict.items():
                for major_version_key, major_version_dict in domain_dict.items():
                    activated = major_version_dict.get('activated', "N/A")
                    uploaded = major_version_dict.get('uploaded', "N/A")
                    item_id = f"{domain_key}:{major_version_key}"
                    if item_id in current_items:
                        self.tree.item(item_id, text=domain_key, values=(major_version_key, uploaded, activated))
                        current_items.remove(item_id)
                    else:
                        self.tree.insert('', 'end', item_id, text=domain_key, values=(major_version_key, uploaded, activated))

            # clean leftovers
            for left_over_id in current_items:
                self.tree.delete(left_over_id)

            focused_item = self.tree.focus()
            if focused_item != self.prev_focused_item:
                if focused_item:
                    focused_item_values = self.tree.item(focused_item)
                    new_value = ":".join((focused_item_values['text'], str(focused_item_values['values'][0])))
                    self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"].set(new_value)
                    self.tk_vars["DOMAIN_REPO_TO_UPLOAD"].set(new_value)
                    uploaded_rep_rev = focused_item_values['values'][1]
                    activated_rep_rev = int(focused_item_values['values'][2])
                    self.tk_vars["REPO_REV_TO_ACTIVATE"].set(uploaded_rep_rev)
                    self.tk_vars["REPO_REV_TO_UPLOAD"].set(uploaded_rep_rev)
                self.prev_focused_item = focused_item


            heartbeat_redis_key = config_vars['HEARTBEAT_COUNTER_REDIS_KEY'].str()
            heartbeat_value = config_vars['HEARTBEAT_VALUE'] = self.redis_conn.get(heartbeat_redis_key)
            if heartbeat_value == self.last_heartbeat_value:
                self.heartbeat_no_diff_counter += 1
            else:
                self.last_heartbeat_value = heartbeat_value
                self.heartbeat_no_diff_counter = 0

            if self.heartbeat_no_diff_counter > 10:
                config_vars['IN_PROGRESS_VALUE'] = f"Looks dead"
            else:
                in_progress_redis_key = config_vars['IN_PROGRESS_REDIS_KEY'].str()
                in_progress_value = self.redis_conn.get(in_progress_redis_key)
                config_vars['IN_PROGRESS_VALUE'] = in_progress_value

            self.update_redis_table_working_id = None
            self.start_update_redis_table()
        else:
            log.info(f"update_redis_table: no redis connection")

    def start_update_redis_table(self):
        if not self.update_redis_table_working_id:
            self.update_redis_table_working_id = self.instl_obj.notebook.after(1500, self.update_redis_table)
            #log.info("update_redis_table STARTEd")

    def stop_update_redis_table(self):
        if self.update_redis_table_working_id:
            self.instl_obj.notebook.after_cancel(self.update_redis_table_working_id)
            self.update_redis_table_working_id = None
            #log.info("update_redis_table STOPPEd")

    def activate_repo_rev(self): #oren todo - add something simmilar for upload SI-300
        try:
            if self.redis_conn:
                current_items = self.tree.get_children()
                domain_repo = self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"].get()
                if domain_repo in current_items:
                    host = self.redis_conn.host
                    repo_rev = self.tk_vars["REPO_REV_TO_ACTIVATE"].get()
                    redis_value = config_vars.resolve_str(":".join(('activate', domain_repo, str(repo_rev))))
                    redis_key   = config_vars.resolve_str(":".join(("$(REDIS_KEYS_PREFIX)", host, "waiting_list")))
                    answer = messagebox.askyesno("Activate repo-rev", f"Activate repo-rev {repo_rev} on {domain_repo} ?")
                    if answer:
                        self.redis_conn.lpush(redis_key, redis_value)
        except Exception as ex:
            print(f"activate_repo_rev exception {ex}")

    def upload_repo_rev(self): #oren todo - add something simmilar for upload SI-300
        try:
            if self.redis_conn:
                current_items = self.tree.get_children()
                domain_repo = self.tk_vars["DOMAIN_REPO_TO_UPLOAD"].get()
                if domain_repo in current_items:
                    host = self.redis_conn.host
                    repo_rev = self.tk_vars["REPO_REV_TO_UPLOAD"].get()
                    redis_value = config_vars.resolve_str(":".join(('up2s3', domain_repo, str(repo_rev))))
                    redis_key   = config_vars.resolve_str(":".join(("$(REDIS_KEYS_PREFIX)", host, "waiting_list")))
                    answer = messagebox.askyesno("Upload repo-rev", f"upload repo-rev {repo_rev} on {domain_repo} ?")
                    if answer:
                        self.redis_conn.lpush(redis_key, redis_value)
        except Exception as ex:
            print(f"upload_repo_rev exception {ex}")

    def remove_redis_key(self, key_config_var, value_config_var=None):
        key_to_remove = config_vars[key_config_var].str()
        self.redis_conn.delete(key_to_remove)
        if value_config_var is not None:
            self.tk_vars[value_config_var].set("")

    def lpush_redis_key(self, key_config_var, value_config_var):
        key_to_set = config_vars[key_config_var].str()
        value_to_push = config_vars[value_config_var].str()
        self.redis_conn.lpush(key_to_set, value_to_push)

    def get_redis_key(self, key_config_var, result_config_var):
        key_to_get = config_vars[key_config_var].str()
        value = self.redis_conn.get(key_to_get)
        if value is None:
            value = "UNKNOWN KEY"
        config_vars[result_config_var] = value

    def set_redis_key(self, key_config_var, value_config_var):
        key_to_set = config_vars[key_config_var].str()
        value_to_set = config_vars[value_config_var].str()
        self.redis_conn.set(key_to_set, value_to_set)

    def create_frame(self, master):  # ActivateFrameController
        super().create_frame(master)

        self.frame = Frame(master)

        curr_row = 0
        self.tk_vars["ACTIVATE_CONFIG_FILE"].set_trace_write_callback(functools.partial(self.update_state, who="ACTIVATE_CONFIG_FILE"))
        self.create_line_for_file(curr_row=curr_row, curr_column=0, label="Server config:", var_name="ACTIVATE_CONFIG_FILE", locate=True, edit=True, check=True, columnspan=3, label_stick=W)

        curr_row += 1
        Label(self.frame, text="Host:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["REDIS_HOST"]).grid(row=curr_row, column=1, sticky=W)

        curr_row += 1
        Label(self.frame, text="Port:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["REDIS_PORT"]).grid(row=curr_row, column=1, sticky=W)

        curr_row += 1
        Label(self.frame, text="Doing:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["IN_PROGRESS_VALUE"]).grid(row=curr_row, column=1, columnspan=1, sticky=W)
        Label(self.frame, text="Heartbeat:").grid(row=curr_row, column=2)
        Label(self.frame, textvariable=self.tk_vars["HEARTBEAT_VALUE"]).grid(row=curr_row, column=3, columnspan=1, sticky=E)

        curr_row += 1
        self.tree = Treeview(self.frame, columns=('major version', 'uploaded', 'activated'))
        self.tree.column('major version', width=100, anchor='center')
        self.tree.heading('major version', text='Major Version')
        self.tree.column('uploaded', width=100, anchor='center')
        self.tree.heading('uploaded', text='Uploaded')
        self.tree.column('activated', width=100, anchor='center')
        self.tree.heading('activated', text='Activated')
        self.tree.grid(row=curr_row, column=0, columnspan=4, sticky=W)

        curr_row += 1
        Label(self.frame, text="Repository:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"]).grid(row=curr_row, column=1, columnspan=1, sticky=W)

        Label(self.frame, text="rep-rev:").grid(row=curr_row, column=2, sticky=E)
        Entry(self.frame, textvariable=self.tk_vars["REPO_REV_TO_ACTIVATE"]).grid(row=curr_row, column=3, columnspan=1, sticky=W + E)
        Button(self.frame, width=7, text="Activate", command=self.activate_repo_rev).grid(row=curr_row, column=4, columnspan=1, sticky="E")

        curr_row += 1
        Label(self.frame, text="Repository:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["DOMAIN_REPO_TO_UPLOAD"]).grid(row=curr_row, column=1,
                                                                                     columnspan=1, sticky=W)

        Label(self.frame, text="rep-rev:").grid(row=curr_row, column=2, sticky=E)
        Entry(self.frame, textvariable=self.tk_vars["REPO_REV_TO_UPLOAD"]).grid(row=curr_row, column=3, columnspan=1,
                                                                                  sticky=W + E)
        Button(self.frame, width=7, text="Upload", command=self.upload_repo_rev).grid(row=curr_row, column=4,
                                                                                          columnspan=1, sticky="E")

        self.prev_focused_item = None

        return self.frame


# noinspection PyAttributeOutsideInit
class InstlGui(InstlInstanceBase):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_defaults_file(super().__thisclass__.__name__)

        self.master = tk_global_master
        self.master.createcommand('exit', self.quit_app)  # exit from quit menu or Command-Q
        self.master.protocol('WM_DELETE_WINDOW', self.quit_app)  # exit from closing the window

        self.client_controller = ClientFrameController(self)
        self.admin_controller = AdminFrameController(self)
        self.activate_controller = ActivateFrameController(self)

        self.tab_name_to_controller = {
            'Client': self.client_controller,
            'Admin': self.admin_controller,
            'Activate': self.activate_controller,
            }

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
        self.config_vars_stack_size_before_mainloop = config_vars.stack_size()
        self.master.mainloop()

    def read_history(self):
        try:
            instl_gui_config_file_name = config_vars["INSTL_GUI_CONFIG_FILE_NAME"].str()
            self.read_yaml_file(instl_gui_config_file_name)
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

    def tabChangedEvent(self, *args):
        tab_id = self.notebook.select()
        tab_name = self.notebook.tab(tab_id, option='text')
        #log.info(f"tabChangedEvent: {tab_name}")
        if tab_name in self.tab_name_to_controller.keys():
            self.tab_name_to_controller[tab_name].update_state(who="tabChangedEvent")
        else:
            log.info(f"""Unknown tab {tab_name}""")
        self.write_history()

    def create_gui(self):

        self.master.title(self.get_version_str())

        self.notebook = Notebook(self.master)
        self.notebook.grid(row=0, column=0)
        self.notebook.bind_all("<<NotebookTabChanged>>", self.tabChangedEvent)

        self.notebook.add(self.client_controller.create_frame(self.notebook), text='Client')
        self.notebook.add(self.admin_controller.create_frame(self.notebook), text='Admin')
        self.notebook.add(self.activate_controller.create_frame(self.notebook), text='Activate')

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
