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
import svnTree
from Tkinter import *
from ttk import *

def say_hi(self):
    print ("hi there, everyone!")

class InstlGui(InstlInstanceBase):
    def __init__(self, initial_vars):
        super(InstlGui, self).__init__(initial_vars)
        self.master = None

    def do_command(self):
        self.read_history()
        self.create_gui()
        self.write_history()

    def read_history(self):
        print("read_history")

    def write_history(self):
        print("write_history")

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
        command_name_var = self.command_name_var.get()
        input_path_var = self.input_path_var.get()
        output_path_var = self.output_path_var.get()
        self.command_line_var.set("{command_name_var} --in {input_path_var} --out {output_path_var}".format(**locals()))

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
        commnads = ("sync", "copy", "synccopy", "remove")
        self.command_name_var = StringVar(client_frame)
        #self.command_name_var.set(commnads[0]) # default value
        OptionMenu(client_frame, self.command_name_var, commnads[0], *commnads, command=self.update_commandline).grid(row=curr_row, column=1, sticky=W)

        # path to input file
        curr_row += 1
        Button(client_frame, width=6, text="Input:", command=self.get_input_file).grid(row=curr_row, column=0, sticky=W)
        self.input_path_var = StringVar()
        self.input_path_var.set("?")
        Entry(client_frame, textvariable=self.input_path_var).grid(row=curr_row, column=1, columnspan=2, sticky=W+E)
        self.input_path_var.trace('w', self.update_commandline)

        # path to output file
        curr_row += 1
        Button(client_frame, width=6, text="Output:", command=self.get_output_file).grid(row=curr_row, column=0, sticky=W)
        self.output_path_var = StringVar()
        self.output_path_var.set("?")
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

        self.master = Tk()
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
