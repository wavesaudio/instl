#!/usr/bin/env python3



import sys
import os
import subprocess
from time import time
import shlex
from tkinter import *
from tkinter.ttk import *

import utils
import aYaml
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack


tab_names = {
    'ADMIN':   'Admin',
    'CLIENT':  'Client'
}

if getattr(os, "setsid", None):
    default_font_size = 17 # for Mac
else:
    default_font_size = 12 # for Windows

admin_command_template_variables = {
    'svn2stage': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'fix-symlinks': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'wtar': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'verify-repo': '__ADMIN_CALL_INSTL_ONLY_CONFIG_FILE_TEMPLATE__',
    'stage2svn': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'fix-props': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'depend': '__ADMIN_CALL_INSTL_DEPEND_TEMPLATE__',
    'fix-perm': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__',
    'create-infomap': '__ADMIN_CALL_INSTL_STANDARD_TEMPLATE__'
}


# noinspection PyAttributeOutsideInit
class InstlGui(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)

        self.master = Tk()
        self.master.createcommand('exit', self.quit_app)  # exit from quit menu or Command-Q
        self.master.protocol('WM_DELETE_WINDOW', self.quit_app)  # exit from closing the window
        self.commands_that_accept_limit_option = var_stack.ResolveVarToList("__COMMANDS_WITH_LIMIT_OPTION__")

        self.client_command_name_var = StringVar()
        self.client_input_path_var = StringVar()
        self.client_input_combobox = None
        self.client_output_path_var = StringVar()
        self.run_client_batch_file_var = IntVar()

        self.admin_command_name_var = StringVar()
        self.admin_config_path_var = StringVar()
        self.admin_output_path_var = StringVar()
        self.admin_stage_index_var = StringVar()
        self.admin_sync_url_var = StringVar()
        self.admin_svn_repo_var = StringVar()
        self.admin_config_file_dirty = True
        self.run_admin_batch_file_var = IntVar()
        self.admin_limit_var = StringVar()
        self.limit_path_entry_widget = None
        self.client_credentials_var = StringVar()
        self.client_credentials_on_var = IntVar()

    def quit_app(self):
        self.write_history()
        exit()

    def set_default_variables(self):
        client_command_list = var_stack.ResolveVarToList("__CLIENT_GUI_CMD_LIST__")
        var_stack.set_var("CLIENT_GUI_CMD").append(client_command_list[0])
        admin_command_list = var_stack.ResolveVarToList("__ADMIN_GUI_CMD_LIST__")
        var_stack.set_var("ADMIN_GUI_CMD").append(admin_command_list[0])
        self.commands_with_run_option_list = var_stack.ResolveVarToList("__COMMANDS_WITH_RUN_OPTION__")

        # create   - $(command_actual_name_$(...)) variables for commands that do not have them in InstlGui.yaml
        for command in var_stack.ResolveVarToList("__CLIENT_GUI_CMD_LIST__"):
            actual_command_var = "command_actual_name_"+command
            if actual_command_var not in var_stack:
                var_stack.set_var(actual_command_var).append(command)
        for command in var_stack.ResolveVarToList("__ADMIN_GUI_CMD_LIST__"):
            actual_command_var = "command_actual_name_"+command
            if actual_command_var not in var_stack:
                var_stack.set_var(actual_command_var).append(command)

    def do_command(self):
        self.set_default_variables()
        self.read_history()
        self.create_gui()

    def read_history(self):
        try:
            self.read_yaml_file(var_stack.ResolveVarToStr("INSTL_GUI_CONFIG_FILE_NAME"))
        except Exception:
            pass

    def write_history(self):
        selected_tab = self.notebook.tab(self.notebook.select(), option='text')
        var_stack.set_var("SELECTED_TAB").append(selected_tab)

        the_list_yaml_ready= var_stack.repr_for_yaml(which_vars=var_stack.ResolveVarToList("__GUI_CONFIG_FILE_VARS__", default=[]), include_comments=False, resolve=False, ignore_unknown_vars=True)
        the_doc_yaml_ready = aYaml.YamlDumpDocWrap(the_list_yaml_ready, '!define', "Definitions", explicit_start=True, sort_mappings=True)
        with utils.utf8_open(var_stack.ResolveVarToStr("INSTL_GUI_CONFIG_FILE_NAME"), "w") as wfd:
            utils.make_open_file_read_write_for_all(wfd)
            aYaml.writeAsYaml(the_doc_yaml_ready, wfd)

    def get_client_input_file(self):
        import tkinter.filedialog

        retVal = tkinter.filedialog.askopenfilename()
        if retVal:
            self.client_input_path_var.set(retVal)
            self.update_client_state()

    def get_client_output_file(self):
        import tkinter.filedialog

        retVal = tkinter.filedialog.asksaveasfilename()
        if retVal:
            self.client_output_path_var.set(retVal)
            self.update_client_state()

    def get_admin_config_file(self):
        import tkinter.filedialog

        retVal = tkinter.filedialog.askopenfilename()
        if retVal:
            self.admin_config_path_var.set(retVal)
            self.update_admin_state()

    def get_admin_output_file(self):
        import tkinter.filedialog

        retVal = tkinter.filedialog.asksaveasfilename()
        if retVal:
            self.admin_output_path_var.set(retVal)
            self.update_admin_state()

    def open_file_for_edit(self, path_to_file):
        if path_to_file == "": return
        path_to_file = os.path.relpath(path_to_file)
        if not os.path.isfile(path_to_file):
            print("File not found:", path_to_file)
            return

        try:
            # noinspection PyUnresolvedReferences
            os.startfile(path_to_file, 'edit')
        except AttributeError:
            subprocess.call(['open', path_to_file])

    def create_client_command_line(self):
        retVal = [var_stack.ResolveVarToStr("__INSTL_EXE_PATH__"), var_stack.ResolveVarToStr("CLIENT_GUI_CMD"),
                  "--in", var_stack.ResolveVarToStr("CLIENT_GUI_IN_FILE"),
                  "--out", var_stack.ResolveVarToStr("CLIENT_GUI_OUT_FILE")]

        if self.client_credentials_on_var.get():
            credentials = self.client_credentials_var.get()
            if credentials != "":
                retVal.append("--credentials")
                retVal.append(credentials)

        if self.run_client_batch_file_var.get() == 1:
            retVal.append("--run")

        if 'Win' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__"):
            if not getattr(sys, 'frozen', False):
                retVal.insert(0, sys.executable)

        return retVal

    def create_admin_command_line(self):
        command_name = var_stack.ResolveVarToStr("ADMIN_GUI_CMD")
        template_variable = admin_command_template_variables[command_name]
        retVal = var_stack.ResolveVarToList(template_variable)

        # some special handling of command line parameters cannot yet be expressed in the command template
        if command_name != 'depend':
            if self.admin_command_name_var.get() in self.commands_that_accept_limit_option:
                limit_paths = self.admin_limit_var.get()
                if limit_paths != "":
                    retVal.append("--limit")
                    try:
                        retVal.extend(shlex.split(limit_paths))
                    except ValueError:
                        retVal.append(limit_paths)
            if self.run_admin_batch_file_var.get() == 1 and command_name in self.commands_with_run_option_list:
                retVal.append("--run")

        if 'Win' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__"):
            if not getattr(sys, 'frozen', False):
                retVal.insert(0, sys.executable)

        return retVal

    def update_client_input_file_combo(self, *args):
        new_input_file = self.client_input_path_var.get()
        if os.path.isfile(new_input_file):
            new_input_file_dir, new_input_file_name = os.path.split(new_input_file)
            items_in_dir = os.listdir(new_input_file_dir)
            dir_items = [os.path.join(new_input_file_dir, item) for item in items_in_dir if os.path.isfile(os.path.join(new_input_file_dir, item))]
            self.client_input_combobox.configure(values=dir_items)

        var_stack.set_var("CLIENT_GUI_IN_FILE").append(self.client_input_path_var.get())

    def update_client_state(self, *args):
        var_stack.set_var("CLIENT_GUI_CMD").append(self.client_command_name_var.get())
        self.update_client_input_file_combo()

        _, input_file_base_name = os.path.split(var_stack.unresolved_var("CLIENT_GUI_IN_FILE"))
        var_stack.set_var("CLIENT_GUI_IN_FILE_NAME").append(input_file_base_name)

        var_stack.set_var("CLIENT_GUI_OUT_FILE").append(self.client_output_path_var.get())
        var_stack.set_var("CLIENT_GUI_RUN_BATCH").append(utils.bool_int_to_str(self.run_client_batch_file_var.get()))
        var_stack.set_var("CLIENT_GUI_CREDENTIALS").append(self.client_credentials_var.get())
        var_stack.set_var("CLIENT_GUI_CREDENTIALS_ON").append(self.client_credentials_on_var.get())

        if self.client_command_name_var.get() in self.commands_with_run_option_list:
            self.client_run_batch_file_checkbox.configure(state='normal')
        else:
            self.client_run_batch_file_checkbox.configure(state='disabled')

        command_line = " ".join(self.create_client_command_line())
        self.T_client.configure(state='normal')
        self.T_client.delete(1.0, END)
        self.T_client.insert(END, var_stack.ResolveStrToStr(command_line))
        self.T_client.configure(state='disabled')

    def read_admin_config_file(self):
        config_path = var_stack.ResolveVarToStr("ADMIN_GUI_CONFIG_FILE", default="")
        if config_path != "":
            if os.path.isfile(config_path):
                var_stack.get_configVar_obj("__SEARCH_PATHS__").clear_values() # so __include__ file will not be found on old paths
                self.read_yaml_file(config_path)
                self.admin_config_file_dirty = False
            else:
                print("File not found:", config_path)

    def update_admin_state(self, *args):
        var_stack.set_var("ADMIN_GUI_CMD").append(self.admin_command_name_var.get())
        current_config_path = var_stack.ResolveVarToStr("ADMIN_GUI_CONFIG_FILE", default="")
        new_config_path = self.admin_config_path_var.get()

        if current_config_path != new_config_path:
            self.admin_config_file_dirty = True
        var_stack.set_var("ADMIN_GUI_CONFIG_FILE").append(new_config_path)
        if self.admin_config_file_dirty:
            self.read_admin_config_file()

        _, input_file_base_name = os.path.split(var_stack.unresolved_var("ADMIN_GUI_CONFIG_FILE"))
        var_stack.set_var("ADMIN_GUI_CONFIG_FILE_NAME").append(input_file_base_name)

        var_stack.set_var("ADMIN_GUI_OUT_BATCH_FILE").append(self.admin_output_path_var.get())

        var_stack.set_var("ADMIN_GUI_RUN_BATCH").append(utils.bool_int_to_str(self.run_admin_batch_file_var.get()))

        limit_line = self.admin_limit_var.get()
        try:
            limit_lines = shlex.split(limit_line)
        except ValueError:
            limit_lines = [limit_line]
        if limit_lines:
            var_stack.set_var("ADMIN_GUI_LIMIT").extend(limit_lines)
        else:
            var_stack.set_var("ADMIN_GUI_LIMIT")

        self.admin_stage_index_var.set(var_stack.ResolveVarToStr("__STAGING_INDEX_FILE__"))
        self.admin_svn_repo_var.set(var_stack.ResolveStrToStr("$(SVN_REPO_URL), REPO_REV: $(REPO_REV)"))

        sync_url = var_stack.ResolveVarToStr("SYNC_BASE_URL")
        self.admin_sync_url_var.set(sync_url)

        if self.admin_command_name_var.get() in self.commands_that_accept_limit_option:
            self.limit_path_entry_widget.configure(state='normal')
        else:
            self.limit_path_entry_widget.configure(state='disabled')

        if self.admin_command_name_var.get() in self.commands_with_run_option_list:
            self.admin_run_batch_file_checkbox.configure(state='normal')
        else:
            self.admin_run_batch_file_checkbox.configure(state='disabled')

        command_line = " ".join([shlex.quote(p) for p in self.create_admin_command_line()])

        self.T_admin.configure(state='normal')
        self.T_admin.delete(1.0, END)
        self.T_admin.insert(END, var_stack.ResolveStrToStr(command_line))
        self.T_admin.configure(state='disabled')

    def run_client(self):
        self.update_client_state()
        command_line_parts = self.create_client_command_line()
        resolved_command_line_parts = var_stack.ResolveListToList(command_line_parts)

        if getattr(os, "setsid", None):
            client_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, preexec_fn=os.setsid)  # Unix
        else:
            client_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False)  # Windows
        unused_stdout, unused_stderr = client_process.communicate()
        return_code = client_process.returncode
        if return_code != 0:
            print(" ".join(resolved_command_line_parts) + " returned exit code " + str(return_code))

    def run_admin(self):
        self.update_admin_state()
        command_line_parts = self.create_admin_command_line()
        resolved_command_line_parts = [shlex.quote(p) for p in var_stack.ResolveListToList(command_line_parts)]

        if getattr(os, "setsid", None):
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False, preexec_fn=os.setsid)  # Unix
        else:
            admin_process = subprocess.Popen(resolved_command_line_parts, executable=resolved_command_line_parts[0], shell=False)  # Windows
        unused_stdout, unused_stderr = admin_process.communicate()
        return_code = admin_process.returncode
        if return_code != 0:
            print(" ".join(resolved_command_line_parts) + " returned exit code " + str(return_code))

    def create_admin_frame(self, master):

        admin_frame = Frame(master)
        admin_frame.grid(row=0, column=1)

        curr_row = 0
        Label(admin_frame, text="Command:").grid(row=curr_row, column=0, sticky=E)

        # instl command selection
        self.admin_command_name_var.set(var_stack.unresolved_var("ADMIN_GUI_CMD"))
        admin_command_list = var_stack.ResolveVarToList("__ADMIN_GUI_CMD_LIST__")
        commandNameMenu = OptionMenu(admin_frame, self.admin_command_name_var,
                                     self.admin_command_name_var.get(), *admin_command_list,
                                     command=self.update_admin_state)
        commandNameMenu.grid(row=curr_row, column=1, sticky=W)
        ToolTip(commandNameMenu, msg="instl admin command")

        self.run_admin_batch_file_var.set(utils.str_to_bool_int(var_stack.unresolved_var("ADMIN_GUI_RUN_BATCH")))
        self.admin_run_batch_file_checkbox = Checkbutton(admin_frame, text="Run batch file", variable=self.run_admin_batch_file_var,
                    command=self.update_admin_state)
        self.admin_run_batch_file_checkbox.grid(row=curr_row, column=2, columnspan=2, sticky=E)

        # path to config file
        curr_row += 1
        Label(admin_frame, text="Config file:").grid(row=curr_row, column=0, sticky=E)
        self.admin_config_path_var.set(var_stack.unresolved_var("ADMIN_GUI_CONFIG_FILE"))
        configFilePathEntry = Entry(admin_frame, textvariable=self.admin_config_path_var)
        configFilePathEntry.grid(row=curr_row, column=1, columnspan=2, sticky=W + E)
        ToolTip(configFilePathEntry, msg="path instl repository config file")
        self.admin_config_path_var.trace('w', self.update_admin_state)

        openConfigButt = Button(admin_frame, width=2, text="...", command=self.get_admin_config_file)
        openConfigButt.grid(row=curr_row, column=3, sticky=W)
        ToolTip(openConfigButt, msg="open admin config file")

        editConfigButt = Button(admin_frame, width=4, text="Edit",
                                command=lambda: self.open_file_for_edit(var_stack.ResolveVarToStr("ADMIN_GUI_CONFIG_FILE")))
        editConfigButt.grid(row=curr_row, column=4, sticky=W)
        ToolTip(editConfigButt, msg="edit admin config file")

        checkConfigButt = Button(admin_frame, width=3, text="Chk",
                                 command=lambda: self.check_yaml(var_stack.ResolveVarToStr("ADMIN_GUI_CONFIG_FILE")))
        checkConfigButt.grid(row=curr_row, column=5, sticky=W)
        ToolTip(checkConfigButt, msg="read admin config file to check it's structure")

        # path to stage index file
        curr_row += 1
        Label(admin_frame, text="Stage index:").grid(row=curr_row, column=0, sticky=E)
        Label(admin_frame, text="---", textvariable=self.admin_stage_index_var).grid(row=curr_row, column=1, columnspan=2, sticky=W)
        editIndexButt = Button(admin_frame, width=4, text="Edit", command=lambda: self.open_file_for_edit(var_stack.ResolveVarToStr("__STAGING_INDEX_FILE__")))
        editIndexButt.grid(row=curr_row, column=4, sticky=W)
        ToolTip(editIndexButt, msg="edit repository index")

        checkIndexButt = Button(admin_frame, width=3, text="Chk",  command=lambda: self.check_yaml(var_stack.ResolveVarToStr("__STAGING_INDEX_FILE__")))
        checkIndexButt.grid(row=curr_row, column=5, sticky=W)
        ToolTip(checkIndexButt, msg="read repository index to check it's structure")

        # path to svn repository
        curr_row += 1
        Label(admin_frame, text="Svn repo:").grid(row=curr_row, column=0, sticky=E)
        svnRepoLabel = Label(admin_frame, text="---", textvariable=self.admin_svn_repo_var)
        svnRepoLabel.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        ToolTip(svnRepoLabel, msg="URL of the SVN repository with current repo-rev")

        # sync URL
        curr_row += 1
        Label(admin_frame, text="Sync URL:").grid(row=curr_row, column=0, sticky=E)
        syncURLLabel = Label(admin_frame, text="---", textvariable=self.admin_sync_url_var)
        syncURLLabel.grid(row=curr_row, column=1, columnspan=2, sticky=W)
        ToolTip(syncURLLabel, msg="Top URL for uploading to the repository")

        # path to output file
        curr_row += 1
        Label(admin_frame, text="Batch file:").grid(row=curr_row, column=0, sticky=E)
        self.admin_output_path_var.set(var_stack.unresolved_var("ADMIN_GUI_OUT_BATCH_FILE"))
        Entry(admin_frame, textvariable=self.admin_output_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.admin_output_path_var.trace('w', self.update_admin_state)
        Button(admin_frame, width=2, text="...", command=self.get_admin_output_file).grid(row=curr_row, column=3, sticky=W)
        Button(admin_frame, width=4, text="Edit",
                command=lambda: self.open_file_for_edit(var_stack.ResolveVarToStr("ADMIN_GUI_OUT_BATCH_FILE"))).grid(row=curr_row, column=4, sticky=W)

        # relative path to limit folder
        curr_row += 1
        Label(admin_frame, text="Limit to:").grid(row=curr_row, column=0, sticky=E)
        ADMIN_GUI_LIMIT_values = var_stack.unresolved_var_to_list("ADMIN_GUI_LIMIT", default=list())
        ADMIN_GUI_LIMIT_values = list(filter(None, ADMIN_GUI_LIMIT_values))
        if ADMIN_GUI_LIMIT_values:
            print("ADMIN_GUI_LIMIT_values:", ADMIN_GUI_LIMIT_values)
            self.admin_limit_var.set(" ".join([shlex.quote(p) for p in ADMIN_GUI_LIMIT_values]))
        else:
            print("ADMIN_GUI_LIMIT_values:", "no values")
            self.admin_limit_var.set("")
        self.limit_path_entry_widget = Entry(admin_frame, textvariable=self.admin_limit_var)
        self.limit_path_entry_widget.grid(row=curr_row, column=1, columnspan=2, sticky=W + E)
        self.admin_limit_var.trace('w', self.update_admin_state)

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

        if value not in ["", "\n"]:
            self.master.clipboard_clear()
            self.master.clipboard_append(value)
            print("data was copied to clipboard!")

    def create_client_frame(self, master):

        client_frame = Frame(master)
        client_frame.grid(row=0, column=0)

        curr_row = 0
        command_label = Label(client_frame, text="Command:")
        command_label.grid(row=curr_row, column=0, sticky=W)

        # instl command selection
        client_command_list = var_stack.ResolveVarToList("__CLIENT_GUI_CMD_LIST__")
        self.client_command_name_var.set(var_stack.unresolved_var("CLIENT_GUI_CMD"))
        OptionMenu(client_frame, self.client_command_name_var,
                   self.client_command_name_var.get(), *client_command_list, command=self.update_client_state).grid(row=curr_row, column=1, sticky=W)

        self.run_client_batch_file_var.set(utils.str_to_bool_int(var_stack.unresolved_var("CLIENT_GUI_RUN_BATCH")))
        self.client_run_batch_file_checkbox = Checkbutton(client_frame, text="Run batch file",
                    variable=self.run_client_batch_file_var, command=self.update_client_state)
        self.client_run_batch_file_checkbox.grid(row=curr_row, column=2, sticky=E)

        # path to input file
        curr_row += 1
        Label(client_frame, text="Input file:").grid(row=curr_row, column=0)
        self.client_input_path_var.set(var_stack.unresolved_var("CLIENT_GUI_IN_FILE"))
        self.client_input_combobox = Combobox(client_frame, textvariable=self.client_input_path_var)
        self.client_input_combobox.grid(row=curr_row, column=1, columnspan=2, sticky=W + E)
        self.client_input_path_var.trace('w', self.update_client_state)
        Button(client_frame, width=2, text="...", command=self.get_client_input_file).grid(row=curr_row, column=3, sticky=W)
        Button(client_frame, width=4, text="Edit",
               command=lambda: self.open_file_for_edit(var_stack.ResolveVarToStr("CLIENT_GUI_IN_FILE"))).grid(row=curr_row, column=4, sticky=W)
        Button(client_frame, width=3, text="Chk",
               command=lambda: self.check_yaml(var_stack.ResolveVarToStr("CLIENT_GUI_IN_FILE"))).grid(row=curr_row, column=5, sticky=W)

        # path to output file
        curr_row += 1
        Label(client_frame, text="Batch file:").grid(row=curr_row, column=0)
        self.client_output_path_var.set(var_stack.unresolved_var("CLIENT_GUI_OUT_FILE"))
        Entry(client_frame, textvariable=self.client_output_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.client_output_path_var.trace('w', self.update_client_state)
        Button(client_frame, width=2, text="...", command=self.get_client_output_file).grid(row=curr_row, column=3, sticky=W)
        Button(client_frame, width=4, text="Edit",
                command=lambda: self.open_file_for_edit(var_stack.ResolveVarToStr("CLIENT_GUI_OUT_FILE"))).grid(row=curr_row, column=4, sticky=W)

        # s3 user credentials
        curr_row += 1
        Label(client_frame, text="Credentials:").grid(row=curr_row, column=0, sticky=E)
        self.client_credentials_var.set(var_stack.unresolved_var("CLIENT_GUI_CREDENTIALS"))
        Entry(client_frame, textvariable=self.client_credentials_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.client_credentials_var.trace('w', self.update_client_state)

        self.client_credentials_on_var.set(var_stack.unresolved_var("CLIENT_GUI_CREDENTIALS_ON"))
        Checkbutton(client_frame, text="", variable=self.client_credentials_on_var).grid(row=curr_row, column=3, sticky=W)
        self.client_credentials_on_var.trace('w', self.update_client_state)

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
        else:
            print("Unknown tab", self.tab_name)

    def create_gui(self):

        self.master.title(self.get_version_str())

        self.notebook = Notebook(self.master)
        self.notebook.grid(row=0, column=0)
        self.notebook.bind_all("<<NotebookTabChanged>>", self.tabChangedEvent)

        client_frame = self.create_client_frame(self.notebook)
        admin_frame = self.create_admin_frame(self.notebook)

        self.notebook.add(client_frame, text='Client')
        self.notebook.add(admin_frame, text='Admin')

        to_be_selected_tab_name = var_stack.ResolveVarToStr("SELECTED_TAB")
        for tab_id in self.notebook.tabs():
            tab_name = self.notebook.tab(tab_id, option='text')
            if tab_name == to_be_selected_tab_name:
                self.notebook.select(tab_id)
                break

        self.master.resizable(0, 0)

        # bring window to front, be default it stays behind the Terminal window
        if var_stack.ResolveVarToStr("__CURRENT_OS__") == "Mac":
            os.system('''/usr/bin/osascript -e 'tell app "Finder" to set frontmost of process "Python" to true' ''')

        self.master.mainloop()
        self.quit_app()
        # self.master.destroy() # optional; see description below

    def check_yaml(self, path_to_yaml):
        command_line = [var_stack.ResolveVarToStr("__INSTL_EXE_PATH__"), "read-yaml",
                        "--in", path_to_yaml]

        try:
            if getattr(os, "setsid", None):
                check_yaml_process = subprocess.Popen(command_line, executable=command_line[0], shell=False, preexec_fn=os.setsid)  # Unix
            else:
                check_yaml_process = subprocess.Popen(command_line, executable=command_line[0], shell=False)  # Windows
        except OSError:
            print("Cannot run:", command_line)
            return

        unused_stdout, unused_stderr = check_yaml_process.communicate()
        return_code = check_yaml_process.returncode
        if return_code != 0:
            print(" ".join(command_line) + " returned exit code " + str(return_code))
        else:
            print(path_to_yaml, "read OK")


class ToolTip(Toplevel):
    """
    Provides a ToolTip widget for Tkinter.
    To apply a ToolTip to any Tkinter widget, simply pass the widget to the
    ToolTip constructor
    """

    def __init__(self, wdgt, msg=None, msgFunc=None, delay=0.2, follow=True):
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
