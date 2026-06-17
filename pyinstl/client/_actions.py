#!/usr/bin/env python3.12
"""Action-accumulation behavior extracted verbatim from
pyinstl/instlClient.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

from configVar import config_vars
from pybatch import *


class _ActionsClientMixin:

    def accumulate_unique_actions_for_active_iids(self, action_type: str, limit_to_iids=None) -> PythonBatchCommandBase:
        """ accumulate action_type actions from iid_list, eliminating duplicates"""
        retVal = AnonymousAccum()
        iid_and_action = self.items_table.get_iids_and_details_for_active_iids(action_type, unique_values=True, limit_to_iids=limit_to_iids)
        iid_and_action.sort(key=lambda tup: tup[0])
        previous_iid = ""

        for IID, an_action in iid_and_action:
            #log.debug(f'Marking action {an_action} on - {IID}')
            if IID != previous_iid:  # avoid multiple progress messages for same iid
                actions_of_iid_count = 0
                name_and_version = self.name_and_version_for_iid(iid=IID)
                action_description = self.action_type_to_progress_message[action_type]
                previous_iid = IID
            if an_action:  # ~ was specified in yaml
                actions = config_vars.resolve_str_to_list(an_action)
                for action in actions:
                    actions_of_iid_count += 1
                    message = f"{name_and_version} {action_description} {actions_of_iid_count}"
                    retVal += EvalShellCommand(action, message, self.python_batch_names)
        return retVal

    def accumulate_actions_for_iid(self, iid, detail_name):
        retVal = AnonymousAccum()
        actions = self.items_table.get_resolved_details_value_for_active_iid(iid=iid, detail_name=detail_name)
        actions_of_iid_count = 0
        for an_action in actions:
            sub_actions = config_vars.resolve_str_to_list(an_action)
            for sub_action in sub_actions:
                actions_of_iid_count += 1
                message = f"{iid} {detail_name} {actions_of_iid_count}"
                retVal += EvalShellCommand(sub_action, message, self.python_batch_names)
        return retVal
