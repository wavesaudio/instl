#!/usr/bin/env python3



import sys
from collections import deque, defaultdict
from configVar import var_stack

from .installItem import InstallItem
from .instlClientRemove import InstlClientRemove


class InstlClientUninstall(InstlClientRemove):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)

    def do_uninstall(self):
        self.init_uninstall_vars()
        self.create_uninstall_instructions()

    def init_uninstall_vars(self):
        self.init_remove_vars()

    def calculate_install_items(self):
        self.calculate_main_install_items()
        self.calculate_all_uninstall_items()

    def calculate_all_uninstall_items(self):
        iid_candidates_for_uninstall = var_stack.ResolveVarToList("__MAIN_INSTALL_IIDS__")
        req_trans_items = self.items_table.get_all_require_translate_items()

        # create a count of how much require_by each item has
        how_many_require_by = defaultdict( lambda: 0 )
        for rt in req_trans_items:
            how_many_require_by[rt.iid] += 1

        # some main uninstall items might be required by other items (that are not uninstalled), and so should not be uninstalled
        for candi in iid_candidates_for_uninstall:
            for req_trans in req_trans_items:
                if req_trans.status == 0:
                    if req_trans.require_by == candi:
                        req_trans.status += 1
                        how_many_require_by[req_trans.iid] -= 1

        items_required_by_no_one = [iid for iid, count in how_many_require_by.items() if count == 0]
        should_be_uninstalled = list(set(iid_candidates_for_uninstall) & set(items_required_by_no_one))

        # now calculate dependencies for main items that should be uninstalled
        # zero status and count
        how_many_require_by = defaultdict( lambda: 0 )
        for rt in req_trans_items:
            how_many_require_by[rt.iid] +=1
            rt.status = 0

        candi_que = deque(should_be_uninstalled)
        while len(candi_que) > 0:
            candi = candi_que.popleft()
            for req_trans in req_trans_items:
                if req_trans.status == 0:
                    if req_trans.require_by == candi:
                        req_trans.status += 1
                        how_many_require_by[req_trans.iid] -= 1
                        if how_many_require_by[req_trans.iid] == 0 and req_trans.iid != candi:
                            candi_que.append(req_trans.iid)

        # items who's count is 0 should be uninstalled
        all_uninstall_items = [iid for iid, count in how_many_require_by.items() if count == 0]
        var_stack.set_var("__FULL_LIST_OF_INSTALL_TARGETS__").extend(sorted(all_uninstall_items))

        iids_that_should_not_be_uninstalled = list(set(iid_candidates_for_uninstall)-set(all_uninstall_items))
        var_stack.set_var("__ORPHAN_INSTALL_TARGETS__").extend(iids_that_should_not_be_uninstalled)

        self.items_table.change_status_of_iids(0, -1, all_uninstall_items)
        self.installState.set_from_db(var_stack.ResolveVarToList("MAIN_INSTALL_TARGETS"),
                                      var_stack.ResolveVarToList("__MAIN_INSTALL_IIDS__"),
                                      var_stack.ResolveVarToList("__ORPHAN_INSTALL_TARGETS__"),
                                      var_stack.ResolveVarToList("__FULL_LIST_OF_INSTALL_TARGETS__"))

    def create_uninstall_instructions(self):

        if len(var_stack.ResolveVarToList("__FULL_LIST_OF_INSTALL_TARGETS__")) > 0:
            self.create_remove_instructions()
            self.create_require_file_instructions()
        else:
            print("nothing to uninstall")
