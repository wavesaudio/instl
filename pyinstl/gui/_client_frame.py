#!/usr/bin/env python3.12
"""ClientFrameController (the Client command tab) extracted verbatim from
pyinstl/instlGui.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import sys
import os
import subprocess
import functools
from tkinter import *
from tkinter.ttk import *
import logging
from pathlib import Path
log = logging.getLogger()

from configVar import config_vars

from ._globals import default_font_size
from ._frame_base import FrameController
from ._tkvars import TkConfigVarStr, TkConfigVarInt


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
