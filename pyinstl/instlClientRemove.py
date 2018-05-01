#!/usr/bin/env python3



import os

import utils
from configVar import var_stack
from .instlClient import InstlClient
from .batchAccumulator import BatchAccumulatorTransaction


class InstlClientRemove(InstlClient):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)

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

        have_info_path = var_stack.ResolveVarToStr("HAVE_INFO_MAP_PATH")
        if not os.path.isfile(have_info_path):
            have_info_path = var_stack.ResolveVarToStr("SITE_HAVE_INFO_MAP_PATH")
        with self.info_map_table.reading_files_context():
            self.read_info_map_from_file(have_info_path)
        self.calc_iid_to_name_and_version()

        self.batch_accum.set_current_section('remove')
        self.batch_accum += self.platform_helper.progress("Starting remove")
        sorted_target_folder_list = sorted(self.all_iids_by_target_folder,
                                           key=lambda fold: var_stack.ResolveStrToStr(fold),
                                           reverse=True)
        # print(sorted_target_folder_list)
        self.accumulate_unique_actions_for_active_iids('pre_remove', var_stack.ResolveVarToList("__FULL_LIST_OF_INSTALL_TARGETS__"))

        for folder_name in sorted_target_folder_list:
            with BatchAccumulatorTransaction(self.batch_accum) as folder_accum_transaction:
                self.batch_accum += self.platform_helper.new_line()
                self.create_remove_previous_sources_instructions_for_target_folder(folder_name)
                self.batch_accum += self.platform_helper.progress("Remove from folder {0}".format(folder_name))
                var_stack.set_var("__TARGET_DIR__").append(os.path.normpath(folder_name))
                items_in_folder = self.all_iids_by_target_folder[folder_name]

                folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('pre_remove_from_folder', items_in_folder)

                for IID in items_in_folder:
                    with BatchAccumulatorTransaction(self.batch_accum) as iid_accum_transaction:
                        name_for_iid = self.name_for_iid(iid=IID)
                        self.batch_accum += self.platform_helper.progress("Remove {name_for_iid}".format(**locals()))
                        sources_for_iid = self.items_table.get_sources_for_iid(IID)
                        resolved_sources_for_iid = [(var_stack.ResolveStrToStr(s[0]), s[1]) for s in sources_for_iid]
                        for source in resolved_sources_for_iid:
                            with BatchAccumulatorTransaction(self.batch_accum) as source_accum_transaction:
                                self.batch_accum += self.platform_helper.progress("Remove {source[0]}".format(**locals()))
                                self.batch_accum += self.items_table.get_resolved_details_value_for_active_iid(iid=IID, detail_name="pre_remove_item")
                                source_accum_transaction += self.create_remove_instructions_for_source(IID, folder_name, source)
                                iid_accum_transaction += source_accum_transaction.essential_action_counter
                                folder_accum_transaction += source_accum_transaction.essential_action_counter
                                self.batch_accum += self.items_table.get_resolved_details_value_for_active_iid(iid=IID, detail_name="post_remove_item")

                folder_accum_transaction += self.accumulate_unique_actions_for_active_iids('post_remove_from_folder', items_in_folder)

        self.accumulate_unique_actions_for_active_iids('post_remove', var_stack.ResolveVarToList("__FULL_LIST_OF_INSTALL_TARGETS__"))

    # create_remove_instructions_for_source:
    # Create instructions to remove a specific source from a specific target folder.
    # There can be 3 possibilities according to the value of the item's remove_item section:
    # No remove_item was specified in index.yaml - so the default action should be taken and all item's sources should be deleted.
    # Null remove_item was specified (remove_item: ~) - so nothing should be done.
    # Specific remove_item action specified - so specific action should be done.

    def create_remove_instructions_for_source(self, IID, folder, source):
        """ source is a tuple (source_folder, tag), where tag is either !file, !dir_cont or !dir """

        retVal = 0  # return the number of essential actions preformed e.g. not including progress, echo, etc
        source_path, source_type = source[0], source[1]
        base_, leaf = os.path.split(source_path)
        to_remove_path = os.path.normpath(os.path.join(folder, leaf))

        specific_remove_actions = self.items_table.get_details_for_active_iids('remove_item', unique_values=False, limit_to_iids=(IID,))

        if len(specific_remove_actions) == 0:  # no specific actions were specified, so just remove the files
            if source_type == '!dir':  # remove whole folder
                remove_action = self.platform_helper.rmdir(to_remove_path, recursive=True)
                self.batch_accum += remove_action
                retVal += 1
            elif source_type == '!file':  # remove single file
                remove_action = self.platform_helper.rmfile(to_remove_path)
                self.batch_accum += remove_action
                retVal += 1
            elif source_type == '!dir_cont':  # remove all source's files and folders from a folder
                remove_items = self.info_map_table.get_items_in_dir(dir_path=source_path, immediate_children_only=True)
                remove_paths = utils.original_names_from_wtars_names(item.path for item in remove_items)
                for remove_path in remove_paths:
                    base_, leaf = os.path.split(remove_path)
                    full_path_to_remove = os.path.normpath(os.path.join(folder, leaf))
                    self.batch_accum += self.platform_helper.rm_file_or_dir(full_path_to_remove)
                    retVal += 1
        else:
            # when an item should not be removed it will get such a detail:
            # remove_item: ~
            # this will cause specific_remove_actions list to be [None].
            # after filtering None values the list will be empty and remove actions will not be created
            specific_remove_actions = [_f for _f in specific_remove_actions if _f]  # filter out None values
            self.batch_accum += specific_remove_actions
            retVal += len(specific_remove_actions)
        return retVal
