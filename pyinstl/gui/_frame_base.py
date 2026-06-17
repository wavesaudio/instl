#!/usr/bin/env python3.12
"""FrameController base class extracted verbatim from pyinstl/instlGui.py.

Pure structural decomposition: code MOVED verbatim, no logic changes. Holds the
shared per-frame plumbing: file dialogs, clipboard copy, the create_line_for_file
layout helper, open/check yaml and the error-prompt used by the per-command frames.
"""
import json
import os
import subprocess
import functools
import shlex
from tkinter import *
from tkinter.ttk import *
from tkinter import messagebox
import logging
from pathlib import Path
import re
log = logging.getLogger()

from configVar import config_vars


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
