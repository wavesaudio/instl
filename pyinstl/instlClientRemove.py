#!/usr/bin/env python3



import os

import utils
from configVar import config_vars
from .instlClient import InstlClient
from pybatch import *


class InstlClientRemove(InstlClient):
    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.read_defaults_file(super().__thisclass__.__name__)

    def do_remove(self):
        self.init_remove_vars()
        self.create_remove_instructions()

    def init_remove_vars(self):
        self.action_type_to_progress_message = {'pre_remove': "pre-remove step",
                                                'post_remove': "post-remove step",
                                                'pre_remove_from_folder': "pre-remove-from-folder step",
                                                'post_remove_from_folder': "post-remove-from-folder step",
                                                'pre_remove_item': "pre-delete step",
                                                'post_remove_item': "post-delete step"}

    def create_remove_instructions(self):

        have_info_path = config_vars["HAVE_INFO_MAP_PATH"].str()
        if not os.path.isfile(have_info_path):
            have_info_path = config_vars["SITE_HAVE_INFO_MAP_PATH"].str()
        self.info_map_table.read_from_file(have_info_path, disable_indexes_during_read=True)
        self.calc_iid_to_name_and_version()

        self.batch_accum.set_current_section('remove')
        self.batch_accum += Progress("Start remove")
        sorted_target_folder_list = sorted(self.all_iids_by_target_folder,
                                           key=lambda fold: config_vars.resolve_str(fold),
                                           reverse=True)
        # print(sorted_target_folder_list)
        self.accumulate_unique_actions_for_active_iids('pre_remove', list(config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"]))

        for folder_name in sorted_target_folder_list:
            with self.batch_accum.sub_accum(Section("Remove from folder", folder_name)) as folder_accum_transaction:
                folder_accum_transaction += self.create_remove_previous_sources_instructions_for_target_folder(folder_name)
                config_vars["__TARGET_DIR__"] = os.path.normpath(folder_name)
                items_in_folder = self.all_iids_by_target_folder[folder_name]

                folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('pre_remove_from_folder', items_in_folder)

                for IID in items_in_folder:
                    name_for_iid = self.name_for_iid(iid=IID)
                    with folder_accum_transaction.sub_accum(Section("Remove", name_for_iid)) as iid_accum_transaction:
                        sources_for_iid = self.items_table.get_sources_for_iid(IID)
                        resolved_sources_for_iid = [(config_vars.resolve_str(s[0]), s[1]) for s in sources_for_iid]
                        for source in resolved_sources_for_iid:
                            _, source_leaf = os.path.split(source[0])
                            with iid_accum_transaction.sub_accum(Section("Remove", source_leaf)) as source_accum_transaction:
                                source_accum_transaction += self.items_table.get_resolved_details_value_for_active_iid(iid=IID, detail_name="pre_remove_item")
                                source_accum_transaction += self.create_remove_instructions_for_source(IID, folder_name, source)
                                source_accum_transaction += self.items_table.get_resolved_details_value_for_active_iid(iid=IID, detail_name="post_remove_item")

                folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('post_remove_from_folder', items_in_folder)

        self.accumulate_unique_actions_for_active_iids('post_remove', list(config_vars["__FULL_LIST_OF_INSTALL_TARGETS__"]))

    # create_remove_instructions_for_source:
    # Create instructions to remove a specific source from a specific target folder.
    # There can be 3 possibilities according to the value of the item's remove_item section:
    # No remove_item was specified in index.yaml - so the default action should be taken and all item's sources should be deleted.
    # Null remove_item was specified (remove_item: ~) - so nothing should be done.
    # Specific remove_item action specified - so specific action should be done.

    def create_remove_instructions_for_source(self, IID, folder, source):
        """ source is a tuple (source_folder, tag), where tag is either !file, !dir_cont or !dir """

        retVal = []
        source_path, source_type = source[0], source[1]
        base_, leaf = os.path.split(source_path)
        to_remove_path = os.path.normpath(os.path.join(folder, leaf))

        specific_remove_actions = self.items_table.get_details_for_active_iids('remove_item', unique_values=False, limit_to_iids=(IID,))

        if len(specific_remove_actions) == 0:  # no specific actions were specified, so just remove the files
            if source_type == '!dir':  # remove whole folder
                retVal.append(RmDir(to_remove_path))
            elif source_type == '!file':  # remove single file
                retVal.append(RmFile(to_remove_path))
            elif source_type == '!dir_cont':  # remove all source's files and folders from a folder
                remove_items = self.info_map_table.get_items_in_dir(dir_path=source_path, immediate_children_only=True)
                remove_paths = utils.original_names_from_wtars_names(item.path for item in remove_items)
                for remove_path in remove_paths:
                    base_, leaf = os.path.split(remove_path)
                    full_path_to_remove = os.path.normpath(os.path.join(folder, leaf))
                    retVal.append(RmFileOrDir(full_path_to_remove))
        else:
            # when an item should not be removed it will get such a detail:
            # remove_item: ~
            # this will cause specific_remove_actions list to be [None].
            # after filtering None values the list will be empty and remove actions will not be created
            specific_remove_actions = [ShellCommand(_f, f"""'{to_remove_path}' remove action""") for _f in specific_remove_actions if _f]  # filter out None values
            retVal.extend(specific_remove_actions)
        return retVal
