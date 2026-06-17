#!/usr/bin/env python3.12
"""AdminFrameController (the Admin command tab) and its command-template lookup
table extracted verbatim from pyinstl/instlGui.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import sys
import os
import subprocess
import functools
import shlex
from tkinter import *
from tkinter.ttk import *
import logging
from pathlib import Path
log = logging.getLogger()

from configVar import config_vars

from ._globals import default_font_size
from ._frame_base import FrameController
from ._tkvars import TkConfigVarStr, TkConfigVarInt
from ._tooltip import ToolTip


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
    'collect-manifests': '__ADMIN_CALL_INSTL_ONLY_CONFIG_FILE_TEMPLATE__'
}


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
