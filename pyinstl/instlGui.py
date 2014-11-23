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

class InstlGui(InstlInstanceBase):
    def __init__(self, initial_vars):
        super(InstlGui, self).__init__(initial_vars)
        self.master = None
        self.master = Tk()
        self.command_name_var = StringVar()
        self.input_path_var = StringVar()
        self.output_path_var = StringVar()

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
            self.update_commandline()
            print("input file:", retVal)
        else:
            print("input file:", "user canceled")

    def get_output_file(self):
        import tkFileDialog
        retVal = tkFileDialog.asksaveasfilename()
        if retVal:
            self.output_path_var.set(retVal)
            self.update_commandline()
            print("output file:", retVal)
        else:
            print("output file:", "user canceled")

    def update_commandline(self, *args):
        var_list.set_var("CLIENT_GUI_COMMAND").append(self.command_name_var.get())
        var_list.set_var("CLIENT_GUI_INPUT_FILE").append(self.input_path_var.get())
        var_list.set_var("CLIENT_GUI_OUTPUT_FILE").append(self.input_path_var.get())
        command_line = "$(CLIENT_GUI_COMMAND) --in $(CLIENT_GUI_INPUT_FILE) --out $(CLIENT_GUI_OUTPUT_FILE)"
        self.command_line_var.set(var_list.resolve(command_line))

    def go(self):
        self.update_commandline()

    def create_admin_frame(self, master):
        admin_frame = Frame(master)
        admin_frame.grid(row=0, column=1)
        return admin_frame

    def create_client_frame(self, master):

        client_frame = Frame(master);
        client_frame.grid(row=0, column=0)

        curr_row = 0
        command_label = Label(client_frame, text="Command:")
        command_label.grid(row=curr_row, column=0, sticky=W)

        # instl command selection
        client_command_list = var_list.resolve_var_to_list("__CLIENT_GUI_COMMAND_LIST__")
        #self.command_name_var = StringVar(client_frame)
        #self.command_name_var.set(commnads[0]) # default value
        OptionMenu(client_frame, self.command_name_var, self.command_name_var.get(), *client_command_list, command=self.update_commandline).grid(row=curr_row, column=1, sticky=W)

        # path to input file
        curr_row += 1
        Button(client_frame, width=6, text="Input:", command=self.get_input_file).grid(row=curr_row, column=0, sticky=W)
        Entry(client_frame, textvariable=self.input_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.input_path_var.trace('w', self.update_commandline)

        # path to output file
        curr_row += 1
        Button(client_frame, width=6, text="Output:", command=self.get_output_file).grid(row=curr_row, column=0, sticky=W)
        Entry(client_frame, textvariable=self.output_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.output_path_var.trace('w', self.update_commandline)

        # the combined command line text
        curr_row += 1
        Button(client_frame, width=6, text="run:", command=self.go).grid(row=curr_row, column=0, sticky=W)
        self.command_line_var = StringVar()
        Label(client_frame, textvariable=self.command_line_var).grid(row=curr_row, column=1, columnspan=2, sticky=W)

        # action buttons
        curr_row += 1
        quit_button = Button(client_frame, text="Quit", command=client_frame.quit)
        quit_button.grid(row=curr_row, column=1)

        client_frame.grid_columnconfigure(0, minsize=80)
        client_frame.grid_columnconfigure(1, minsize=500)
        client_frame.grid_columnconfigure(2, minsize=80)

        return client_frame

    def create_gui(self):

        self.master.title("instl")

        notebook = Notebook(self.master)
        notebook.grid(row=0, column=0)

        client_frame = self.create_client_frame(notebook)
        admin_frame = self.create_admin_frame(notebook)

        notebook.add(client_frame, text='Client')
        notebook.add(admin_frame, text='Admin')
        notebook.select(client_frame)

        self.update_commandline()
        self.master.resizable(0, 0)
        self.master.mainloop()
        #self.master.destroy() # optional; see description below
