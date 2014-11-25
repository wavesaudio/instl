#!/usr/bin/env python2.7

from __future__ import print_function

import shlex
from pyinstl.utils import *
from aYaml import augmentedYaml

from instlInstanceBase import InstlInstanceBase
from configVarStack import var_stack as var_list

from Tkinter import *
from ttk import *

def bool_int_to_str(in_bool_int):
    if in_bool_int == 0:
        retVal = "no"
    else:
        retVal = "yes"
    return retVal

def str_to_bool_int(the_str):
    if the_str.lower() in ("yes", "true", "y", 't'):
        retVal = 1
    elif the_str.lower() in ("no", "false", "n", "f"):
        retVal = 0
    else:
        raise ValueError("Cannot translate", the_str, "to bool-int")
    return retVal

class InstlGui(InstlInstanceBase):
    def __init__(self, initial_vars):
        super(InstlGui, self).__init__(initial_vars)
        self.master = Tk()

        self.commands_that_accept_limit_option = ("stage2svn", "svn2stage")

        self.client_command_name_var = StringVar()
        self.client_input_path_var = StringVar()
        self.client_output_path_var = StringVar()
        self.run_client_batch_file_var = IntVar()
        
        self.admin_command_name_var = StringVar()
        self.admin_config_path_var = StringVar()
        self.admin_output_path_var = StringVar()
        self.run_admin_batch_file_var = IntVar()
        self.admin_limit_var = StringVar()
        self.limit_path_entry_widget = None

    def set_default_variables(self):
        client_command_list = var_list.resolve_var_to_list("__CLIENT_GUI_COMMAND_LIST__")
        var_list.set_var("CLIENT_GUI_COMMAND").append(client_command_list[0])
        admin_command_list = var_list.resolve_var_to_list("__ADMIN_GUI_COMMAND_LIST__")
        var_list.set_var("ADMIN_GUI_COMMAND").append(admin_command_list[0])

    def do_command(self):
        self.set_default_variables()
        self.read_history()
        self.create_gui()
        self.write_history()

    def read_history(self):
        try:
            self.read_yaml_file(var_list.resolve_var("INSTL_GUI_CONFIG_FILE_NAME"))
        except:
            pass

        self.client_command_name_var.set(var_list.resolve("$(CLIENT_GUI_COMMAND)", default="sync"))
        self.client_input_path_var.set(var_list.unresolved_var("CLIENT_GUI_INPUT_FILE", default="$(CLIENT_GUI_COMMAND).yaml"))
        self.client_output_path_var.set(var_list.unresolved_var("CLIENT_GUI_OUTPUT_FILE", default="$(CLIENT_GUI_COMMAND).sh"))
        self.run_client_batch_file_var.set(str_to_bool_int(var_list.resolve("$(CLIENT_GUI_RUN_BATCH_FILE)", default="no")))

        self.admin_command_name_var.set(var_list.resolve("$(ADMIN_GUI_COMMAND)", default="svn2stage"))
        self.admin_config_path_var.set(var_list.unresolved_var("ADMIN_GUI_CONFIG_FILE", default=""))
        self.admin_output_path_var.set(var_list.unresolved_var("ADMIN_GUI_OUTPUT_FILE", default="$(ADMIN_GUI_COMMAND).sh"))
        self.run_admin_batch_file_var.set(str_to_bool_int(var_list.resolve("$(ADMIN_GUI_RUN_BATCH_FILE)", default="yes")))
        self.admin_limit_var.set(var_list.unresolved_var("ADMIN_GUI_LIMIT", default=""))


    def write_history(self):
        selected_tab = self.notebook.tab(self.notebook.select(), option='text')
        var_list.set_var("SELECTED_TAB").append(selected_tab)

        the_list_yaml_ready= var_list.repr_for_yaml(which_vars=var_list.resolve_var_to_list("__GUI_CONFIG_FILE_VARS__"), include_comments=False, resolve=False, ignore_unknown_vars=True)
        the_doc_yaml_ready = augmentedYaml.YamlDumpDocWrap(the_list_yaml_ready, '!define', "Definitions", explicit_start=True, sort_mappings=True)
        with open(var_list.resolve_var("INSTL_GUI_CONFIG_FILE_NAME"), "w") as wfd:
            augmentedYaml.writeAsYaml(the_doc_yaml_ready, wfd)

    def get_client_input_file(self):
        import tkFileDialog
        retVal = tkFileDialog.askopenfilename()
        if retVal:
            self.client_input_path_var.set(retVal)
            self.update_client_state()

    def get_client_output_file(self):
        import tkFileDialog
        retVal = tkFileDialog.asksaveasfilename()
        if retVal:
            self.client_output_path_var.set(retVal)
            self.update_client_state()

    def get_admin_config_file(self):
        import tkFileDialog
        retVal = tkFileDialog.askopenfilename()
        if retVal:
            self.admin_config_path_var.set(retVal)
            self.update_admin_state()

    def get_admin_output_file(self):
        import tkFileDialog
        retVal = tkFileDialog.asksaveasfilename()
        if retVal:
            self.admin_output_path_var.set(retVal)
            self.update_admin_state()

    def open_file_for_edit(self, var_name):
        path_to_file = var_list.resolve_var(var_name)
        try:
            os.startfile(path_to_file)
        except AttributeError:
            subprocess.call(['open', path_to_file])

    def create_client_command_line(self):
        retVal = [var_list.resolve_var("__INSTL_EXE_PATH__"), var_list.resolve_var("CLIENT_GUI_COMMAND"),
                        "--in", var_list.resolve_var("CLIENT_GUI_INPUT_FILE"),
                        "--out", var_list.resolve_var("CLIENT_GUI_OUTPUT_FILE")]
        if self.run_client_batch_file_var.get() == 1:
            retVal.append("--run")
        return retVal

    def create_admin_command_line(self):
        retVal = [var_list.resolve_var("__INSTL_EXE_PATH__"), var_list.resolve_var("ADMIN_GUI_COMMAND"),
                        "--config-file", var_list.resolve_var("ADMIN_GUI_CONFIG_FILE"),
                        "--out", var_list.resolve_var("ADMIN_GUI_OUTPUT_FILE")]

        if self.admin_command_name_var.get() in self.commands_that_accept_limit_option:
            limit_path = self.admin_limit_var.get()
            if limit_path != "":
                retVal.append("--limit")
                limit_paths = shlex.split(limit_path) # there might be space separated paths
                retVal.extend(limit_paths)

        if self.run_admin_batch_file_var.get() == 1:
            retVal.append("--run")
        return retVal

    def update_client_state(self, *args):
        var_list.set_var("CLIENT_GUI_COMMAND").append(self.client_command_name_var.get())
        var_list.set_var("CLIENT_GUI_INPUT_FILE").append(self.client_input_path_var.get())
        var_list.set_var("CLIENT_GUI_OUTPUT_FILE").append(self.client_output_path_var.get())
        var_list.set_var("CLIENT_GUI_RUN_BATCH_FILE").append(bool_int_to_str(self.run_client_batch_file_var.get()))

        command_line = " ".join(self.create_client_command_line())

        self.client_command_line_var.set(var_list.resolve(command_line))

    def update_admin_state(self, *args):
        var_list.set_var("ADMIN_GUI_COMMAND").append(self.admin_command_name_var.get())
        var_list.set_var("ADMIN_GUI_CONFIG_FILE").append(self.admin_config_path_var.get())
        var_list.set_var("ADMIN_GUI_OUTPUT_FILE").append(self.admin_output_path_var.get())
        var_list.set_var("ADMIN_GUI_RUN_BATCH_FILE").append(bool_int_to_str(self.run_admin_batch_file_var.get()))
        var_list.set_var("ADMIN_GUI_LIMIT").append(self.admin_limit_var.get())

        if self.admin_command_name_var.get() in self.commands_that_accept_limit_option:
            self.limit_path_entry_widget.configure(state='normal')
        else:
            self.limit_path_entry_widget.configure(state='disabled')

        command_line = " ".join(self.create_admin_command_line())

        self.admin_command_line_var.set(var_list.resolve(command_line))

    def run_client(self):
        self.update_client_state()
        command_line = self.create_client_command_line()

        from subprocess import Popen
        if getattr(os, "setsid", None):
            proc = subprocess.Popen(command_line, executable=command_line[0], shell=False, preexec_fn=os.setsid) # Unix
        else:
            proc = subprocess.Popen(command_line, executable=command_line[0], shell=False) # Windows
        unused_stdout, unused_stderr = proc.communicate()
        retcode = proc.returncode
        if retcode != 0:
            raise SystemExit(command_line + " returned exit code " + str(retcode))

    def run_admin(self):
        self.update_admin_state()
        command_line = self.create_admin_command_line()

        from subprocess import Popen
        if getattr(os, "setsid", None):
            proc = subprocess.Popen(command_line, executable=command_line[0], shell=False, preexec_fn=os.setsid) # Unix
        else:
            proc = subprocess.Popen(command_line, executable=command_line[0], shell=False) # Windows
        unused_stdout, unused_stderr = proc.communicate()
        retcode = proc.returncode
        if retcode != 0:
            raise SystemExit(" ".join(command_line) + " returned exit code " + str(retcode))

    def create_admin_frame(self, master):
        admin_frame = Frame(master)
        admin_frame.grid(row=0, column=1)

        curr_row = 0
        command_label = Label(admin_frame, text="Command:")
        command_label.grid(row=curr_row, column=0)

        # instl command selection
        admin_command_list = var_list.resolve_var_to_list("__ADMIN_GUI_COMMAND_LIST__")
        OptionMenu(admin_frame, self.admin_command_name_var, self.admin_command_name_var.get(), *admin_command_list, command=self.update_admin_state).grid(row=curr_row, column=1, sticky=W)

        Checkbutton(admin_frame, text="Run batch file", variable=self.run_admin_batch_file_var, command=self.update_admin_state).grid(row=curr_row, column=2, columnspan=2, sticky=E)

        # path to config file
        curr_row += 1
        Label(admin_frame, text="Config file:").grid(row=curr_row, column=0)
        Entry(admin_frame, textvariable=self.admin_config_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.admin_config_path_var.trace('w', self.update_admin_state)
        Button(admin_frame, width=2, text="...", command=self.get_admin_config_file).grid(row=curr_row, column=3, sticky=W)
        Button(admin_frame, width=3, text="Edit", command=lambda: self.open_file_for_edit("ADMIN_GUI_CONFIG_FILE")).grid(row=curr_row, column=4, sticky=W)

        # path to output file
        curr_row += 1
        command_label = Label(admin_frame, text="Batch file:").grid(row=curr_row, column=0)
        Entry(admin_frame, textvariable=self.admin_output_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.admin_output_path_var.trace('w', self.update_admin_state)
        Button(admin_frame, width=2, text="...", command=self.get_admin_output_file).grid(row=curr_row, column=3, sticky=W)
        Button(admin_frame, width=3, text="Edit", command=lambda: self.open_file_for_edit("ADMIN_GUI_OUTPUT_FILE")).grid(row=curr_row, column=4, sticky=W)

        # relative path to limit folder
        curr_row += 1
        Label(admin_frame, text="Limit:").grid(row=curr_row, column=0)
        self.limit_path_entry_widget = Entry(admin_frame, textvariable=self.admin_limit_var)
        self.limit_path_entry_widget.grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.admin_limit_var.trace('w', self.update_admin_state)

        # the combined command line text
        curr_row += 1
        Button(admin_frame, width=6, text="run:", command=self.run_admin).grid(row=curr_row, column=0, sticky=W)
        self.admin_command_line_var = StringVar()
        Label(admin_frame, textvariable=self.admin_command_line_var, wraplength=400, anchor=W).grid(row=curr_row, column=1, columnspan=2, sticky=W)

        #admin_frame.grid_columnconfigure(0, minsize=80)
        #admin_frame.grid_columnconfigure(1, minsize=300)
        #admin_frame.grid_columnconfigure(2, minsize=80)
        return admin_frame

    def create_client_frame(self, master):

        client_frame = Frame(master)
        client_frame.grid(row=0, column=0)


        curr_row = 0
        command_label = Label(client_frame, text="Command:")
        command_label.grid(row=curr_row, column=0, sticky=W)

        # instl command selection
        client_command_list = var_list.resolve_var_to_list("__CLIENT_GUI_COMMAND_LIST__")
        OptionMenu(client_frame, self.client_command_name_var, self.client_command_name_var.get(), *client_command_list, command=self.update_client_state).grid(row=curr_row, column=1, sticky=W)

        Checkbutton(client_frame, text="Run batch file", variable=self.run_client_batch_file_var, command=self.update_client_state).grid(row=curr_row, column=2, sticky=E)

        # path to input file
        curr_row += 1
        Label(client_frame, text="Input file:").grid(row=curr_row, column=0)
        Entry(client_frame, textvariable=self.client_input_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.client_input_path_var.trace('w', self.update_client_state)
        Button(client_frame, width=2, text="...", command=self.get_client_input_file).grid(row=curr_row, column=3, sticky=W)
        Button(client_frame, width=3, text="Edit", command=lambda: self.open_file_for_edit("CLIENT_GUI_INPUT_FILE")).grid(row=curr_row, column=4, sticky=W)

        # path to output file
        curr_row += 1
        Label(client_frame, text="Batch file:").grid(row=curr_row, column=0)
        Entry(client_frame, textvariable=self.client_output_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.client_output_path_var.trace('w', self.update_client_state)
        Button(client_frame, width=2, text="...", command=self.get_client_output_file).grid(row=curr_row, column=3, sticky=W)
        Button(client_frame, width=3, text="Edit", command=lambda: self.open_file_for_edit("CLIENT_GUI_OUTPUT_FILE")).grid(row=curr_row, column=4, sticky=W)

        # the combined command line text
        curr_row += 1
        Button(client_frame, width=6, text="run:", command=self.run_client).grid(row=curr_row, column=0, sticky=W)
        self.client_command_line_var = StringVar()
        Label(client_frame, textvariable=self.client_command_line_var, wraplength=400, anchor=W).grid(row=curr_row, column=1, columnspan=2, sticky=W)

        client_frame.grid_columnconfigure(0, minsize=80)
        client_frame.grid_columnconfigure(1, minsize=300)
        client_frame.grid_columnconfigure(2, minsize=80)

        return client_frame

    def create_gui(self):

        self.master.title("instl")

        self.notebook = Notebook(self.master)
        self.notebook.grid(row=0, column=0)

        # action buttons
        quit_button = Button(self.master, text="Quit", command=self.master.quit)
        quit_button.grid(row=1, column=0, sticky=N+S, padx=5, pady=5)
        #self.master.grid_rowconfigure(2, pad=20)

        client_frame = self.create_client_frame(self.notebook)
        admin_frame = self.create_admin_frame(self.notebook)

        self.notebook.add(client_frame, text='Client')
        self.notebook.add(admin_frame, text='Admin')

        to_be_selected_tab_name = var_list.resolve_var("SELECTED_TAB")
        for tab_id in self.notebook.tabs():
            tab_name = self.notebook.tab(tab_id, option='text')
            if tab_name == to_be_selected_tab_name:
                self.notebook.select(tab_id)
                break

        self.update_client_state()
        self.update_admin_state()
        self.master.resizable(0, 0)
        self.master.mainloop()
        #self.master.destroy() # optional; see description below
