#!/usr/bin/env python3.12

import logging
log = logging.getLogger()

from .instlInstanceBase import InstlInstanceBase
from .instlDoItBase import InstlDoItBase
from pybatch import *


class InstlDoIt(InstlInstanceBase, InstlDoItBase):
    def __init__(self, initial_vars) -> None:
        InstlInstanceBase.__init__(self, initial_vars)
        InstlDoItBase.__init__(self)
        self.total_self_progress = 1000
        self.read_defaults_file(super().__thisclass__.__name__)

    def do_command(self):
        # print("client_commands", fixed_command_name)
        main_input_file_path = os.fspath(config_vars["__MAIN_INPUT_FILE__"])
        self.read_yaml_file(main_input_file_path)
        active_oses = list(config_vars["TARGET_OS_NAMES"])
        self.items_table.activate_specific_oses(*active_oses)
        self.init_default_doit_vars()
        self.resolve_defined_paths()
        self.batch_accum.set_current_section('begin')
        # after reading variable COPY_TOOL from yaml, we might need to re-init the copy tool.
        self.items_table.resolve_inheritance()
        self.calculate_full_doit_order()
        #self.platform_helper.num_items_for_progress_report = int(config_vars["LAST_PROGRESS"])

        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()

        self.write_batch_file(self.batch_accum)

        self.write_config_vars_to_file(config_vars.get("__WRITE_CONFIG_VARS_TO_FILE__", None).Path())

        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def init_default_doit_vars(self):
        if "SYNC_BASE_URL" in config_vars:
            resolved_sync_base_url = config_vars["SYNC_BASE_URL"].str()
            url_main_item = utils.main_url_item(resolved_sync_base_url)
            config_vars["SYNC_BASE_URL_MAIN_ITEM"] = url_main_item

        if config_vars["TARGET_OS"].str() != config_vars["__CURRENT_OS__"].str():
            target_os_names = list(config_vars[config_vars.resolve_str("$(TARGET_OS)_ALL_OS_NAMES")])
            config_vars["TARGET_OS_NAMES"] = target_os_names
            second_name = config_vars["TARGET_OS"].str()
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            config_vars["TARGET_OS_SECOND_NAME"] = second_name
        #self.platform_helper.no_progress_messages = "NO_PROGRESS_MESSAGES" in config_vars
