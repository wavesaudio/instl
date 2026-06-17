#!/usr/bin/env python3.12
"""require.yaml handling and previous-state preservation behavior extracted
verbatim from pyinstl/instlClient.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
from collections import defaultdict
import logging
log = logging.getLogger()

from configVar import config_vars
from configVar import main_input_file_path
from pybatch import *


class _RequireClientMixin:

    def read_previous_requirements(self):
        require_file_path = config_vars["SITE_REQUIRE_FILE_PATH"].Path()
        with Chmod(require_file_path, "a+rw", ignore_all_errors=True) as chmoder:
            chmoder()
        try:
            self.read_yaml_file(require_file_path, ignore_if_not_exist=True)
        except Exception as ex:
            log.warning(f"Exception reading {require_file_path}: {ex}")
            renamed_require_file_path = Path(require_file_path.parent, config_vars.resolve_str("$(SITE_REQUIRE_FILE_NAME).failed_to_read"))
            try:
                require_file_path.rename(renamed_require_file_path)
                log.warning(f"moved require.yaml to {renamed_require_file_path}")
            except Exception as ex_in_ex:
                log.warning(f"failed to moved require.yaml to {renamed_require_file_path}: {ex_in_ex}")
                # no need to do anything else if renaming failed

    def create_require_file_instructions(self):
        # write the require file as it should look after copy is done
        old_require_file_path = config_vars["OLD_SITE_REQUIRE_FILE_PATH"].Path()
        current_require_file_path = config_vars["SITE_REQUIRE_FILE_PATH"].Path()
        new_require_file_path = config_vars["NEW_SITE_REQUIRE_FILE_PATH"].Path()

        self.batch_accum += Chmod(old_require_file_path, "a+rw", ignore_all_errors=True)
        self.batch_accum += Chmod(current_require_file_path, "a+rw", ignore_all_errors=True)
        self.batch_accum += CopyFileToFile(current_require_file_path, old_require_file_path, ignore_if_not_exist=True, hard_links=False, copy_owner=True)

        require_yaml = self.repr_require_for_yaml()
        if require_yaml:
            MakeDir(new_require_file_path.parent, remove_obstacles=True, chowner=True, recursive_chmod=False, own_progress_count=0)()
            self.write_require_file(new_require_file_path, require_yaml)
            # Copy the new require file over the old one, if copy fails the old file remains.
            self.batch_accum += Chmod(new_require_file_path, "a+rw", ignore_all_errors=True)
            self.batch_accum += CopyFileToFile(new_require_file_path, current_require_file_path, hard_links=False, copy_owner=True)
            self.batch_accum += Chmod(current_require_file_path, "a+rw", ignore_all_errors=True)
        else:   # remove previous require.yaml since the new one does not contain anything
            self.batch_accum += RmFile(current_require_file_path)

    def repr_require_for_yaml(self):
        translate_detail_names = {'require_version': 'version', 'require_guid': 'guid'}
        retVal = defaultdict(dict)
        require_details = self.items_table.get_details_by_name_for_all_iids("require_%")

        # translate each row to a dict, to help debug, since sqlite3.row does not show fields in Pycharm debugger
        for require_detail in [dict(rd) for rd in require_details]:

            # get the translated detail_name (which is the original detail_name if detail_name is not in translate_detail_names)
            detail_name_translated = translate_detail_names.get(require_detail['detail_name'], require_detail['detail_name'])

            # do not include any details originating from auxiliary IIDs such as UNINSTALL_AS_PLUGIN, such details could have
            # been written to previous require.yaml due to a bug in index.yaml
            # do not include details guids that are not from original_iid, again to overcome bugs.
            if require_detail['original_iid'] in self.auxiliary_iids or \
                    (detail_name_translated == 'guid' and require_detail['original_iid'] != require_detail['owner_iid']):
                continue

            # this will create the item_dict in retVal if it does not already exist
            item_dict = retVal[require_detail['owner_iid']]

            # if this is the first encounter of this detail_name, create a set to hold the values
            # a set is used to avoid duplicate values
            if detail_name_translated not in item_dict:
                item_dict[detail_name_translated] = set()

            # add the deatil to the set
            item_dict[detail_name_translated].add(require_detail['detail_value'])

        for item in retVal.values():
            for k, v in item.items():
                item[k] = sorted(list(v))  # turn the set into a sorted list
        return retVal

    def save_previous_state(self):
        current_require_file_path = config_vars["SITE_REQUIRE_FILE_PATH"].Path()
        new_require_file_path = config_vars["NEW_SITE_REQUIRE_FILE_PATH"].Path()
        main_input_file = main_input_file_path()

        save_require_before_file_path = main_input_file.parent.joinpath(main_input_file.stem + "_require_before.yaml")
        save_require_after_file_path = main_input_file.parent.joinpath(main_input_file.stem + "_require_after.yaml")

        self.batch_accum += CopyFileToFile(current_require_file_path, save_require_before_file_path, ignore_if_not_exist=True, hard_links=False, copy_owner=True)
        self.batch_accum += CopyFileToFile(new_require_file_path, save_require_after_file_path, ignore_if_not_exist=True, hard_links=False, copy_owner=True)
