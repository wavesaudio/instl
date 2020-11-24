#!/usr/bin/env python3.6

from collections import deque, defaultdict
from configVar import config_vars
import logging

log = logging.getLogger()

from .instlClientRemove import InstlClientRemove
from pybatch import PythonDoSomething


class InstlClientUninstall(InstlClientRemove):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        # noinspection PyUnresolvedReferences
        self.read_defaults_file(super().__thisclass__.__name__)
        self.calc_user_cache_dir_var()

    def do_uninstall(self):
        self.init_uninstall_vars()
        self.create_uninstall_instructions()

    def init_uninstall_vars(self):
        self.init_remove_vars()

    def calculate_install_items(self):
        self.calculate_main_install_items()
        self.calculate_all_uninstall_items_option_2()

    def calculate_all_uninstall_items_option_1(self):
        # option 1: remove instruction will be created only for items that were present in require.yaml file

        # force_uninstall_of_main_items: if true all main install items will be uninstalled regardless if they are indeed installed
        # and regardless if some other item depends on them
        force_uninstall_of_main_items = "FORCE_UNINSTALL_OF_MAIN_ITEMS" in config_vars
        if "DO_NOT_REMOVE_TARGETS" in config_vars:
            do_not_remove_iids = list(config_vars["DO_NOT_REMOVE_TARGETS"])
            self.items_table.set_ignore_iids(do_not_remove_iids)

        iid_candidates_for_uninstall = list(config_vars["__MAIN_INSTALL_IIDS__"])
        req_trans_items = self.items_table.get_all_require_translate_items()

        # create a count of how much require_by each item has
        how_many_require_by = defaultdict(lambda: 0)
        for rt in req_trans_items:
            how_many_require_by[rt['iid']] += 1

        if not force_uninstall_of_main_items:
            # some main uninstall items might be required by other items (that are not uninstalled),
            # and so should not be uninstalled
            for candi in iid_candidates_for_uninstall:
                for req_trans in req_trans_items:
                    if req_trans['status'] == 0:
                        if req_trans['require_by'] == candi:
                            req_trans['status'] += 1
                            how_many_require_by[req_trans['iid']] -= 1

            items_required_by_no_one = sorted([iid for iid, count in how_many_require_by.items() if count == 0])
            should_be_uninstalled = sorted(list(set(iid_candidates_for_uninstall) & set(items_required_by_no_one)))

            # zero status and count for next stage
            how_many_require_by = defaultdict(lambda: 0)
            for rt in req_trans_items:
                how_many_require_by[rt['iid']] += 1
                rt['status'] = 0
        else:
            should_be_uninstalled = iid_candidates_for_uninstall

        # now calculate dependencies for main items that should be uninstalled
        candi_que = deque(should_be_uninstalled)
        while len(candi_que) > 0:
            candi = candi_que.popleft()
            for req_trans in req_trans_items:
                if req_trans['status'] == 0:
                    if req_trans['require_by'] == candi:
                        req_trans['status'] += 1
                        how_many_require_by[req_trans['iid']] -= 1
                        if how_many_require_by[req_trans['iid']] == 0 and req_trans['iid'] != candi:
                            candi_que.append(req_trans['iid'])

        # items who's count is 0 should be uninstalled
        all_uninstall_items = [iid for iid, count in how_many_require_by.items() if count == 0]
        if force_uninstall_of_main_items:
            all_uninstall_items = list(set(all_uninstall_items + iid_candidates_for_uninstall))
        all_uninstall_items.sort()
        config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"] = all_uninstall_items

        iids_that_should_not_be_uninstalled = sorted(list(set(iid_candidates_for_uninstall) - set(all_uninstall_items)))
        config_vars["__ORPHAN_INSTALL_TARGETS__"] = iids_that_should_not_be_uninstalled

        # mark all uninstall items
        self.items_table.change_status_of_iids_to_another_status(
            self.items_table.install_status["none"],
            self.items_table.install_status["remove"],
            all_uninstall_items,
            progress_callback=self.progress)
        self.sort_all_items_by_target_folder(consider_direct_sync=False)

    def create_uninstall_instructions(self):

        if len(config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"]) > 0:
            self.create_remove_instructions()
            self.create_require_file_instructions()

            # uninstall might be done with index.yaml that is pre-python-batch.
            # And in any case uninstall should stop because any one commands failed/
            self.batch_accum.set_current_section("begin")
            self.batch_accum += PythonDoSomething(
                '''PythonBatchCommandBase.set_a_kwargs_default("ignore_all_errors", True)''')
        else:
            log.info("nothing to uninstall")

    def calculate_all_uninstall_items_option_2(self):
        # option 2: remove instructions will be created for items that are not in require.yaml

        # force_uninstall_of_main_items: if true all main install items will be uninstalled regardless if they are indeed installed
        # and regardless if some other item depends on them
        force_uninstall_of_main_items = "FORCE_UNINSTALL_OF_MAIN_ITEMS" in config_vars

        do_not_remove_iids = list(config_vars.get("DO_NOT_REMOVE_TARGETS", []))
        self.items_table.set_ignore_iids(do_not_remove_iids)

        iid_candidates_for_uninstall = list(config_vars["__MAIN_INSTALL_IIDS__"])
        req_trans_items = self.items_table.get_all_require_translate_items()

        # create a count of how much require_by each item has
        how_many_require_by = defaultdict(lambda: 0)
        iid_to_required_items = dict()
        for rt in req_trans_items:
            how_many_require_by[rt['iid']] += 1
            key = rt['iid']
            if key in iid_to_required_items:
                iid_to_required_items[key] += [rt['require_by']]
            else:
                iid_to_required_items[key] = [rt['require_by']]

        if not force_uninstall_of_main_items:
            for candi in iid_candidates_for_uninstall:
                for req_trans in req_trans_items:
                    if req_trans['status'] == 0:
                        if req_trans['require_by'] == candi:
                            req_trans['status'] += 1
                            iidKey = req_trans['iid']
                            how_many_require_by[iidKey] -= 1
                            if iid_to_required_items[iidKey] and candi in iid_to_required_items[iidKey]:
                                iid_to_required_items[iidKey].remove(candi)

            for iid in iid_to_required_items.keys():
                for depend_item in iid_to_required_items[iid]:
                    if how_many_require_by[depend_item] == 0:
                        iid_to_required_items[iid].remove(depend_item)
                        how_many_require_by[iid] -= 1

            items_required_by_someone = sorted([iid for iid, count in how_many_require_by.items() if count > 0])
            should_be_uninstalled = sorted(list(set(iid_candidates_for_uninstall) - set(items_required_by_someone)))

            # zero status and count for next stage
            how_many_require_by = defaultdict(lambda: 0)
            for rt in req_trans_items:
                how_many_require_by[rt['iid']] += 1
                rt['status'] = 0
        else:
            should_be_uninstalled = iid_candidates_for_uninstall

        # now calculate dependencies for main items that should be uninstalled
        candi_que = deque(should_be_uninstalled)
        while len(candi_que) > 0:
            candi = candi_que.popleft()
            for req_trans in req_trans_items:
                if req_trans['status'] == 0:
                    if req_trans['require_by'] == candi:
                        req_trans['status'] += 1
                        how_many_require_by[req_trans['iid']] -= 1
                        if how_many_require_by[req_trans['iid']] == 0 and req_trans['iid'] != candi:
                            candi_que.append(req_trans['iid'])

        # items who's count is 0 should be uninstalled
        all_uninstall_items = [iid for iid, count in how_many_require_by.items() if count == 0]
        if force_uninstall_of_main_items:
            all_uninstall_items = list(set(all_uninstall_items + iid_candidates_for_uninstall))
        all_uninstall_items.sort()
        config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"] = all_uninstall_items

        iids_that_should_not_be_uninstalled = sorted(list(set(iid_candidates_for_uninstall) - set(all_uninstall_items)))
        config_vars["__ORPHAN_INSTALL_TARGETS__"] = iids_that_should_not_be_uninstalled

        # mark all uninstall items
        self.items_table.change_status_of_iids_to_another_status(
            self.items_table.install_status["none"],
            self.items_table.install_status["remove"],
            all_uninstall_items,
            progress_callback=self.progress)
        self.sort_all_items_by_target_folder(consider_direct_sync=False)

