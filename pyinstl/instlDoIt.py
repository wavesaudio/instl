#!/usr/bin/env python3


import utils
from .instlInstanceBase import InstlInstanceBase
from configVar import var_stack
from .indexItemTable import IndexItemsTable


class InstlDoIt(InstlInstanceBase):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.init_items_table()
        var_stack.add_const_config_variable("__DATABASE_URL__", "", self.items_table.get_db_url())
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.full_doit_order = utils.unique_list()

    def do_command(self):
        # print("client_commands", fixed_command_name)
        main_input_file_path = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        self.read_yaml_file(main_input_file_path)
        active_oses = var_stack.ResolveVarToList("TARGET_OS_NAMES")
        self.items_table.begin_get_for_specific_oses(*active_oses)
        self.init_default_doit_vars()
        self.resolve_defined_paths()
        self.batch_accum.set_current_section('begin')
        self.batch_accum += self.platform_helper.setup_echo()
        # after reading variable COPY_TOOL from yaml, we might need to re-init the copy tool.
        self.platform_helper.init_copy_tool()
        self.items_table.resolve_inheritance()
        self.calculate_full_doit_order()
        self.platform_helper.num_items_for_progress_report = int(var_stack.ResolveVarToStr("LAST_PROGRESS"))

        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def init_default_doit_vars(self):
        if "SYNC_BASE_URL" in var_stack:
            resolved_sync_base_url = var_stack.ResolveVarToStr("SYNC_BASE_URL")
            url_main_item = utils.main_url_item(resolved_sync_base_url)
            var_stack.set_var("SYNC_BASE_URL_MAIN_ITEM", description="from init_default_doit_vars").append(url_main_item)

        if var_stack.ResolveVarToStr("TARGET_OS") != var_stack.ResolveVarToStr("__CURRENT_OS__"):
            target_os_names = var_stack.ResolveVarToList(var_stack.ResolveStrToStr("$(TARGET_OS)_ALL_OS_NAMES"))
            var_stack.set_var("TARGET_OS_NAMES").extend(target_os_names)
            second_name = var_stack.ResolveVarToStr("TARGET_OS")
            if len(target_os_names) > 1:
                second_name = target_os_names[1]
            var_stack.set_var("TARGET_OS_SECOND_NAME").append(second_name)
        self.platform_helper.no_progress_messages = "NO_PROGRESS_MESSAGES" in var_stack


    def do_doit(self):
        for action_type in ("pre_doit", "doit", "post_doit"):
            for IID in self.full_doit_order:
                self.doit_for_iid(IID, action_type)

        self.batch_accum += self.platform_helper.echo("Done $(CURRENT_DOIT_DESCRIPTION)")

    def doit_for_iid(self, IID, action):
        action_list = self.items_table.get_resolved_details_value_for_active_iid(IID, action)
        try:
            name = self.items_table.get_resolved_details_value_for_active_iid(IID, "name")[0]
        except:
            name = IID

        if len(action_list) > 0:
            self.batch_accum += self.platform_helper.remark("--- Begin "+name)
            self.batch_accum += self.platform_helper.progress(name+"...")
        num_actions = len(action_list)
        for i in range(num_actions):
            self.batch_accum += action_list[i]
            if i != num_actions - 1:
                self.batch_accum += self.platform_helper.progress(name + " "+str(i+1))
        if len(action_list) > 0:
            self.batch_accum += self.platform_helper.progress(name + ". done")
            self.batch_accum += self.platform_helper.remark("--- End "+name+"\n")

    def calculate_full_doit_order(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if "MAIN_DOIT_ITEMS" not in var_stack:
            raise ValueError("'MAIN_DOIT_ITEMS' was not defined")

        for iid in var_stack.ResolveVarToList("MAIN_DOIT_ITEMS"):
            self.resolve_dependencies_for_iid(iid)

        all_iis_set = set(self.items_table.get_all_iids())
        orphan_iids = list(set(self.full_doit_order)-all_iis_set)
        if orphan_iids:
            print("Don't know to do with these orphan items::", orphan_iids)
            var_stack.set_var("__ORPHAN_DOIT_TARGETS__").extend(sorted(orphan_iids))
            for o_iid in orphan_iids:
                self.full_doit_order.remove(o_iid)

        # print("doit order:", self.full_doit_order)
        var_stack.set_var("__FULL_LIST_OF_DOIT_TARGETS__").extend(self.full_doit_order)

    def resolve_dependencies_for_iid(self, iid):
        depends_for_iid = self.items_table.get_resolved_details_value_for_active_iid(iid, "depends")
        for d_iid in depends_for_iid:
            self.resolve_dependencies_for_iid(d_iid)
        self.full_doit_order.append(iid)
