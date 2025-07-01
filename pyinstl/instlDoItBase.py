#!/usr/bin/env python3.12

import logging
log = logging.getLogger()

from pybatch import *


class InstlDoItBase:
    def __init__(self) -> None:
        self.need_items_table = True
        self.full_doit_order = utils.unique_list()

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

    def calculate_full_doit_order(self, doit_section_name="MAIN_DOIT_ITEMS"):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        if doit_section_name not in config_vars:
            raise ValueError(f"'{doit_section_name}' was not defined")

        for iid in list(config_vars[doit_section_name]):
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
