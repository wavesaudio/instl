#!/usr/bin/env python3.12
"""IID naming helpers and per-iid defines reading behavior extracted verbatim
from pyinstl/instlClient.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

from configVar import config_vars
from pybatch import *


class _NamingClientMixin:

    def name_from_iid(self, iid):
        """ for those cases when no name was given to the iid"""
        retVal = iid.replace("_IID", "")
        retVal = retVal.replace("_", " ")
        return retVal

    def name_and_version_for_iid(self, iid):
        name_and_version_list = self.items_table.get_resolved_details_value_for_active_iid(iid=iid, detail_name="name_and_version")
        if name_and_version_list:
            retVal = name_and_version_list[0]
        else:
            name = self.items_table.get_resolved_details_value_for_active_iid(iid=iid, detail_name="name")
            if name:
                retVal = name[0]
            else:
                retVal = self.name_from_iid(iid)
        return retVal

    def name_for_iid(self, iid):
        name_list = self.items_table.get_resolved_details_value_for_active_iid(iid=iid, detail_name="name")
        retVal = next(iter(name_list), iid)  # trick to get the first element in a list or default if list is empty
        return retVal

    def read_defines_for_active_iids(self):
        """ read the defines specific for each active iid
        """
        if self.items_table.defines_for_iids:
            config_vars.push_scope()
            active_iids = self.items_table.get_active_iids()
            for iid, defines_for_iid in self.items_table.defines_for_iids.items():
                if iid in active_iids:
                    self.read_yaml_from_node(defines_for_iid)
