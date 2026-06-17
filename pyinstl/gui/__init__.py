#!/usr/bin/env python3.12
"""pyinstl.gui package.

This package is the result of a pure structural decomposition (extract-module
refactor) of the former god-object pyinstl/instlGui.py. The InstlGui class plus
its supporting Tk widgets/controllers are split across focused submodules and
re-assembled here. No behavior was changed: class/method names, signatures and
emitted output are identical, and the module-level Tk root is still created once
at import time (now in pyinstl/gui/_globals.py).

The original module pyinstl/instlGui.py is kept as a thin shim that re-exports
the same public surface (most importantly InstlGui) from this package.

Layout:
  _globals.py        -- tk_global_master (the single Tk root) and default_font_size
  _tkvars.py         -- CreateTkConfigClass + TkConfigVarStr/Int/Bool (ConfigVar bridge)
  _tooltip.py        -- ToolTip widget
  _frame_base.py     -- FrameController base (file dialogs, clipboard, layout helpers)
  _client_frame.py   -- ClientFrameController (Client tab)
  _admin_frame.py    -- AdminFrameController (Admin tab) + admin_command_template_variables
  _activate_frame.py -- ActivateFrameController (Activate tab, redis repo-rev table)
  __init__.py        -- InstlGui (main window / layout / GUI-state read+write) + re-exports
"""
import os
import logging
from tkinter import *
from tkinter.ttk import *
log = logging.getLogger()

import utils
import aYaml
from ..instlInstanceBase import InstlInstanceBase
from configVar import config_vars

from utils.redisClient import RedisClient

from ._globals import tk_global_master, default_font_size
from ._tkvars import CreateTkConfigClass, TkConfigVarStr, TkConfigVarInt, TkConfigVarBool
from ._tooltip import ToolTip
from ._frame_base import FrameController
from ._client_frame import ClientFrameController
from ._admin_frame import AdminFrameController, admin_command_template_variables
from ._activate_frame import ActivateFrameController


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
