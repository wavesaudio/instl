#!/usr/bin/env python2.7

from __future__ import print_function
import time
from collections import OrderedDict, defaultdict
import logging

from pyinstl.utils import *
from installItem import InstallItem, guid_list, iids_from_guid
from aYaml import augmentedYaml

from instlInstanceBase import InstlInstanceBase
from configVarStack import var_stack as var_list
from configVarList import ConfigVarList

from Tkinter import *
from ttk import *

def bool_int_to_str(in_bool_int):
    if in_bool_int == 0:
        retVal = "no"
    else:
        retVal = "yes"
    return retVal

def str_to_bool_int(the_str):
    retVal = 0
    if the_str.lower() in ("yes", "true", "y", 't'):
        retVal = 1
    elif the_str.lower() in ("no", "false", "n", "f"):
        retVal = 0
    else:
        print("Cannot translate", the_str, "to bool-int")
    return retVal

class InstlGui(InstlInstanceBase):
    def __init__(self, initial_vars):
        super(InstlGui, self).__init__(initial_vars)
        self.master = Tk()
        self.current_frame = None
        self.command_name_var = StringVar()
        self.input_path_var = StringVar()
        self.output_path_var = StringVar()
        self.run_batch_file_var = IntVar()

    def set_default_variables(self):
        client_command_list = var_list.resolve_var_to_list("__CLIENT_GUI_COMMAND_LIST__")
        var_list.set_var("CLIENT_GUI_COMMAND").append(client_command_list[0])

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
        self.command_name_var.set(var_list.resolve("$(CLIENT_GUI_COMMAND)", default="sync"))
        self.input_path_var.set(var_list.unresolved_var("CLIENT_GUI_INPUT_FILE", default="$(CLIENT_GUI_COMMAND).yaml"))
        self.output_path_var.set(var_list.unresolved_var("CLIENT_GUI_OUTPUT_FILE", default="$(CLIENT_GUI_COMMAND).sh"))
        self.run_batch_file_var.set(str_to_bool_int(var_list.resolve("$(CLIENT_GUI_RUN_BATCH_FILE)", default="no")))

    def write_history(self):
        the_list_yaml_ready= var_list.repr_for_yaml(which_vars=var_list.resolve_var_to_list("__GUI_CONFIG_FILE_VARS__"), include_comments=False, resolve=False)
        the_doc_yaml_ready = augmentedYaml.YamlDumpDocWrap(the_list_yaml_ready, '!define', "Definitions", explicit_start=True, sort_mappings=True)
        with open(var_list.resolve_var("INSTL_GUI_CONFIG_FILE_NAME"), "w") as wfd:
            augmentedYaml.writeAsYaml(the_doc_yaml_ready, wfd)

    def get_input_file(self):
        import tkFileDialog
        retVal = tkFileDialog.askopenfilename()
        if retVal:
            self.input_path_var.set(retVal)
            self.update_client_state()
            print("input file:", retVal)
        else:
            print("input file:", "user canceled")

    def get_output_file(self):
        import tkFileDialog
        retVal = tkFileDialog.asksaveasfilename()
        if retVal:
            self.output_path_var.set(retVal)
            self.update_client_state()
            print("output file:", retVal)
        else:
            print("output file:", "user canceled")

    def create_command_line(self):
        retVal = [var_list.resolve_var("__INSTL_EXE_PATH__"), var_list.resolve_var("CLIENT_GUI_COMMAND"),
                        "--in", var_list.resolve_var("CLIENT_GUI_INPUT_FILE"),
                        "--out", var_list.resolve_var("CLIENT_GUI_OUTPUT_FILE")]
        if self.run_batch_file_var.get() == 1:
            retVal.append("--run")
        return retVal

    def update_client_state(self, *args):
        var_list.set_var("CLIENT_GUI_COMMAND").append(self.command_name_var.get())
        var_list.set_var("CLIENT_GUI_INPUT_FILE").append(self.input_path_var.get())
        var_list.set_var("CLIENT_GUI_OUTPUT_FILE").append(self.output_path_var.get())
        var_list.set_var("CLIENT_GUI_RUN_BATCH_FILE").append(bool_int_to_str(self.run_batch_file_var.get()))

        command_line = " ".join(self.create_command_line())

        self.command_line_var.set(var_list.resolve(command_line))

    def run_client(self):
        self.update_client_state()
        command_line = self.create_command_line()

        from subprocess import Popen
        if getattr(os, "setsid", None):
            proc = subprocess.Popen(command_line, executable=command_line[0], shell=False, preexec_fn=os.setsid) # Unix
        else:
            proc = subprocess.Popen(command_line, executable=command_line[0], shell=False) # Windows
        unused_stdout, unused_stderr = proc.communicate()
        retcode = proc.returncode
        if retcode != 0:
            raise SystemExit(command_line + " returned exit code " + str(retcode))

    def create_admin_frame(self, master):
        admin_frame = Frame(master)
        admin_frame.grid(row=0, column=1)
        return admin_frame

    def create_client_frame(self, master):

        client_frame = Frame(master)
        client_frame.grid(row=0, column=0)


        curr_row = 0
        command_label = Label(client_frame, text="Command:")
        command_label.grid(row=curr_row, column=0, sticky=W)

        # instl command selection
        client_command_list = var_list.resolve_var_to_list("__CLIENT_GUI_COMMAND_LIST__")
        OptionMenu(client_frame, self.command_name_var, self.command_name_var.get(), *client_command_list, command=self.update_client_state).grid(row=curr_row, column=1, sticky=W)

        Checkbutton(client_frame, text="Run batch file", variable=self.run_batch_file_var, command=self.update_client_state).grid(row=curr_row, column=2, sticky=E)

        # path to input file
        curr_row += 1
        Button(client_frame, width=6, text="Input:", command=self.get_input_file).grid(row=curr_row, column=0, sticky=W)
        Entry(client_frame, textvariable=self.input_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.input_path_var.trace('w', self.update_client_state)

        # path to output file
        curr_row += 1
        Button(client_frame, width=6, text="Output:", command=self.get_output_file).grid(row=curr_row, column=0, sticky=W)
        Entry(client_frame, textvariable=self.output_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.output_path_var.trace('w', self.update_client_state)

        # the combined command line text
        curr_row += 1
        Button(client_frame, width=6, text="run:", command=self.run_client).grid(row=curr_row, column=0, sticky=W)
        self.command_line_var = StringVar()
        Label(client_frame, textvariable=self.command_line_var, wraplength=400, anchor=W).grid(row=curr_row, column=1, columnspan=2, sticky=W)

        client_frame.grid_columnconfigure(0, minsize=80)
        client_frame.grid_columnconfigure(1, minsize=300)
        client_frame.grid_columnconfigure(2, minsize=80)

        return client_frame

    def create_gui(self):

        self.master.title("instl")

        notebook = Notebook(self.master)
        notebook.grid(row=0, column=0)

        # action buttons
        quit_button = Button(self.master, text="Quit", command=self.master.quit)
        quit_button.grid(row=1, column=0, sticky=N+S, padx=5, pady=5)
        #self.master.grid_rowconfigure(2, pad=20)

        client_frame = self.create_client_frame(notebook)
        admin_frame = self.create_admin_frame(notebook)

        notebook.add(client_frame, text='Client')
        notebook.add(admin_frame, text='Admin')
        notebook.select(client_frame)

        self.update_client_state()
        self.master.resizable(0, 0)
        self.master.mainloop()
        #self.master.destroy() # optional; see description below
