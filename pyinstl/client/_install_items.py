#!/usr/bin/env python3.12
"""Install-items calculation behavior extracted verbatim from
pyinstl/instlClient.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

import utils
from configVar import config_vars
from pybatch import *
from ..instlException import InstlFatalException


class _InstallItemsClientMixin:

    def calculate_install_items(self):
        self.calculate_main_install_items()
        self.calculate_all_install_items()
        self.items_table.db.lock_table("index_item_t")  # locks db, to prevent us from insert bugs, by not allowing changes after this point
        self.items_table.db.lock_table("index_item_detail_t")

    def calculate_main_install_items(self):
        """ calculate the set of iids to install from the "MAIN_INSTALL_TARGETS" variable.
            Full set of install iids and orphan iids are also writen to variable.
        """
        # TODO(W7/W6): these __MAIN_INSTALL_IIDS__ / __MAIN_UPDATE_IIDS__ /
        # __ORPHAN_INSTALL_TARGETS__ / __FULL_LIST_OF_INSTALL_TARGETS__ writes use
        # config_vars as an implicit, order-dependent data channel between
        # calculate_*_install_items and downstream do_copy/do_remove. Containing
        # this coupling means returning an explicit InstallPlan dataclass (W6) and
        # keeping the public keys as a thin write-through at the boundary.
        #
        # Why NOT in this incremental pass: the channel is genuinely cross-module
        # (it is not local to the client calculate path), so it cannot be made a
        # safe, output-preserving local change. The concrete writer/reader map is:
        #   writers (here): __MAIN_INSTALL_IIDS__/__MAIN_UPDATE_IIDS__/
        #     __ORPHAN_INSTALL_TARGETS__ in calculate_main_install_items;
        #     __FULL_LIST_OF_INSTALL_TARGETS__ in calculate_all_install_items.
        #   cross-module readers (must all migrate together to a threaded
        #   InstallPlan, or keep these keys as a write-through):
        #     - instlClientUninstall.py:41,124 read __MAIN_INSTALL_IIDS__ and
        #       :87,90,183,186 *re-write* __FULL_LIST_OF_INSTALL_TARGETS__ /
        #       __ORPHAN_INSTALL_TARGETS__ (uninstall reuses the same channel);
        #     - instlInstanceSync_p4.py:32, instlInstanceSync_svn.py:34,40 and
        #       instlClientRemove.py:44,66 read __FULL_LIST_OF_INSTALL_TARGETS__;
        #     - instlClientCopy.py:135 reads __ORPHAN_INSTALL_TARGETS__.
        # W6 step (4) keeps these public keys as a thin boundary write-through so
        # sync/remove/uninstall are unaffected; doing it piecemeal here would
        # change emitted batch scripts (a behavior change) and break goldens.
        # Belongs to the dedicated W6 workstream, sequenced with W7's run context.
        # utils.add_to_actions_stack("calculating main items to install")
        if "MAIN_INSTALL_TARGETS" not in config_vars:
            # Without MAIN_INSTALL_TARGETS there is nothing to install and no way
            # to proceed. Spell out what is missing and where it should come from
            # rather than raising a bare ValueError naming only the variable.
            raise InstlFatalException(
                "Nothing to install: the configuration variable 'MAIN_INSTALL_TARGETS' was not defined.",
                "This variable lists the items (IIDs/GUIDs) to install and is normally supplied by the",
                f"installation input file '{config_vars.get('__MAIN_INPUT_FILE__', '<unknown>')}'",
                "or on the command line. Make sure at least one install target is provided.")

        self.main_install_targets.extend(list(config_vars["MAIN_INSTALL_TARGETS"]))
        main_iids, main_guids = utils.separate_guids_from_iids(self.main_install_targets)
        iids_from_main_guids, orphaned_main_guids = self.items_table.iids_from_guids(main_guids)
        main_iids.extend(iids_from_main_guids)
        main_iids, update_iids = self.resolve_special_build_in_iids(main_iids)
        # this is a second time we run this commadn since it's possible more items were added
        main_iids, orphaned_main_iids = self.items_table.iids_from_iids(main_iids)
        update_iids, orphaned_update_iids = self.items_table.iids_from_iids(update_iids)

        config_vars["__MAIN_INSTALL_IIDS__"] = sorted(main_iids)
        config_vars["__MAIN_UPDATE_IIDS__"] = sorted(update_iids)
        config_vars["__ORPHAN_INSTALL_TARGETS__"] = sorted(orphaned_main_guids+orphaned_main_iids+orphaned_update_iids)

        self.update_mode = "__REPAIR_INSTALLED_ITEMS__" in self.main_install_targets

    # install_status = {"none": 0, "main": 1, "update": 2, "depend": 3}
    def calculate_all_install_items(self):
        # mark ignored iids, so all subsequent operations not act on these iids
        # utils.add_to_actions_stack("calculate install items")
        ignored_iids = list(config_vars.get("MAIN_IGNORED_TARGETS", []))
        self.items_table.set_ignore_iids(ignored_iids)

        # mark main install items
        main_iids = list(config_vars["__MAIN_INSTALL_IIDS__"])
        self.items_table.change_status_of_iids_to_another_status(
                self.items_table.install_status["none"],
                self.items_table.install_status["main"],
                main_iids,
                progress_callback=self.progress)


        # find dependant of main install items
        main_iids_and_dependents = self.items_table.get_recursive_dependencies(look_for_status=self.items_table.install_status["main"])
        # mark dependants of main items, but only if they are not already in main items
        self.items_table.change_status_of_iids_to_another_status(
            self.items_table.install_status["none"],
            self.items_table.install_status["depend"],
            main_iids_and_dependents,
            progress_callback=self.progress)

        # mark update install items, but only those not already marked as main or depend
        update_iids = list(config_vars["__MAIN_UPDATE_IIDS__"])
        self.items_table.change_status_of_iids_to_another_status(
                self.items_table.install_status["none"],
                self.items_table.install_status["update"],
                update_iids,
                progress_callback=self.progress)


        # find dependants of update install items
        update_iids_and_dependents = self.items_table.get_recursive_dependencies(look_for_status=self.items_table.install_status["update"])
        # mark dependants of update items, but only if they are not already marked
        self.items_table.change_status_of_iids_to_another_status(
            self.items_table.install_status["none"],
            self.items_table.install_status["depend"],
            update_iids_and_dependents,
            progress_callback=self.progress)

        all_items_to_install = self.items_table.get_iids_by_status(
            self.items_table.install_status["main"],
            self.items_table.install_status["depend"])

        config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"] = sorted(all_items_to_install)

        self.sort_all_items_by_target_folder(consider_direct_sync=True)
        self.calc_iid_to_name_and_version()

    def calc_iid_to_name_and_version(self):
        self.items_table.set_name_and_version_for_active_iids()

    def resolve_special_build_in_iids(self, iids: List[str]):
        iids_set = set(iids)
        update_iids_set = set()
        special_build_in_iids = set(list(config_vars["SPECIAL_BUILD_IN_IIDS"]))
        found_special_build_in_iids = special_build_in_iids & set(iids)
        if len(found_special_build_in_iids) > 0:
            iids_set -= special_build_in_iids
            # repair also does update so it takes precedent over update
            if "__REPAIR_INSTALLED_ITEMS__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__REPAIR_INSTALLED_ITEMS__", detail_name='depends')
                iids_set.update(more_iids)
            elif "__UPDATE_INSTALLED_ITEMS__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__UPDATE_INSTALLED_ITEMS__", detail_name='depends')
                update_iids_set = set(more_iids)-iids_set

            if "__ALL_GUIDS_IID__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__ALL_GUIDS_IID__", detail_name='depends')
                iids_set.update(more_iids)

            if "__ALL_ITEMS_IID__" in found_special_build_in_iids:
                more_iids = self.items_table.get_resolved_details_value_for_active_iid(iid="__ALL_ITEMS_IID__", detail_name='depends')
                iids_set.update(more_iids)
        return list(iids_set), list(update_iids_set)
