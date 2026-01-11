#!/usr/bin/env python3.12

import logging
log = logging.getLogger()

from .instlInstanceBase import InstlInstanceBase
from pybatch import *


class InstlDoIt(InstlInstanceBase):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.total_self_progress = 1000
        self.need_items_table = True
        self.read_defaults_file(super().__thisclass__.__name__)
        self.full_doit_order = utils.unique_list()

    def do_command(self):
        # __QUIET_UNTIL_ERROR__ is set to true when command line argument "--quiet-until-error" is found
        utils.set_log_quiet_until_error(config_vars.get("__QUIET_UNTIL_ERROR__", False))
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

    def do_doit(self):
        for doit_stage in ("pre_doit", "doit", "post_doit"):
            self.batch_accum.set_current_section(doit_stage)
            for IID in self.full_doit_order:
                self.doit_for_iid(IID, doit_stage)

        self.batch_accum += Echo("Done $(CURRENT_DOIT_DESCRIPTION)")

    def doit_for_iid(self, IID, doit_stage):
        action_list = self.items_table.get_resolved_details_value_for_active_iid(IID, doit_stage)
        try:
            name = self.items_table.get_resolved_details_value_for_active_iid(IID, "name")[0]
        except:
            name = IID

        with self.batch_accum.sub_accum(Stage(f"{name}...")) as iid_accum:
            if len(action_list) > 0:
                iid_accum += Remark(f"--- Begin {IID} {name}")
            num_actions = len(action_list)
            for i in range(num_actions):
                sub_actions = config_vars.resolve_str_to_list(action_list[i])
                for sub_action in sub_actions:
                    iid_accum += EvalShellCommand(sub_action, name, self.python_batch_names)
            if len(action_list) > 0:
                iid_accum += Remark(f"--- End {IID} {name}")

    def calculate_full_doit_order(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_DOIT_ITEMS" not in config_vars:
            raise ValueError("'MAIN_DOIT_ITEMS' was not defined")

        for iid in list(config_vars["MAIN_DOIT_ITEMS"]):
            self.resolve_dependencies_for_iid(iid)

        all_iis_set = set(self.items_table.get_all_iids())
        orphan_iids = list(set(self.full_doit_order)-all_iis_set)
        if orphan_iids:
            log.warning(f"""Don't know to do with these orphan items: {orphan_iids}""")
            config_vars["__ORPHAN_DOIT_TARGETS__"] = sorted(orphan_iids)
            for o_iid in orphan_iids:
                self.full_doit_order.remove(o_iid)

        # print("doit order:", self.full_doit_order)
        config_vars["__FULL_LIST_OF_DOIT_TARGETS__"] = self.full_doit_order

    def resolve_dependencies_for_iid(self, iid):
        depends_for_iid = self.items_table.get_resolved_details_value_for_active_iid(iid, "depends")
        for d_iid in depends_for_iid:
            self.resolve_dependencies_for_iid(d_iid)
        self.full_doit_order.append(iid)
