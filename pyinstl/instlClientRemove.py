#!/usr/bin/env python3



import os

from configVar import var_stack
from .instlClient import InstlClient


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
        self.read_info_map_from_file(have_info_path)

        self.batch_accum.set_current_section('remove')
        self.batch_accum += self.platform_helper.progress("Starting remove")
        sorted_target_folder_list = sorted(self.installState.all_items_by_target_folder,
                                           key=lambda fold: var_stack.ResolveStrToStr(fold),
                                           reverse=True)
        # print(sorted_target_folder_list)
        self.accumulate_unique_actions('pre_remove', var_stack.ResolveVarToList("__MAIN_INSTALL_IIDS__"))

        for folder_name in sorted_target_folder_list:
            self.batch_accum += self.platform_helper.progress("Removing from {0}".format(folder_name))
            var_stack.set_var("__TARGET_DIR__").append(os.path.normpath(folder_name))
            items_in_folder = self.installState.all_items_by_target_folder[folder_name]
            self.batch_accum += self.platform_helper.new_line()

            self.accumulate_unique_actions('pre_remove_from_folder', items_in_folder)

            for IID in items_in_folder:
                with self.install_definitions_index[IID].push_var_stack_scope() as installi:
                    self.batch_accum += self.platform_helper.progress("Removing {installi.name}...".format(**locals()))
                    for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                        source = var_stack.ResolveVarToList(source_var)
                        self.batch_accum += self.platform_helper.progress("Removing {source[0]}...".format(**locals()))
                        self.batch_accum += var_stack.ResolveVarToList("iid_action_list_pre_remove_item", default=[])
                        self.create_remove_instructions_for_source(folder_name, source)
                        self.batch_accum += var_stack.ResolveVarToList("iid_action_list_post_remove_item", default=[])
                        self.batch_accum += self.platform_helper.progress("Remove {source[0]} done".format(**locals()))
                    self.batch_accum += self.platform_helper.progress("Remove {installi.name} done".format(**locals()))

            self.accumulate_unique_actions('post_remove_from_folder', items_in_folder)
            self.batch_accum += self.platform_helper.progress("Remove from {0} done".format(folder_name))

        self.accumulate_unique_actions('post_remove', var_stack.ResolveVarToList("__MAIN_INSTALL_IIDS__"))

    # create_remove_instructions_for_source:
    # Create instructions to remove a specific source from a specific target folder.
    # There can be 3 possibilities according to the value of the item's remove_item section:
    # No remove_item was specified in index.yaml - so the default action should be taken and all item's sources should be deleted.
    # Null remove_item was specified (remove_item: ~) - so nothing should be done.
    # Specific remove_item action specified - so specific action should be done.

    def create_remove_instructions_for_source(self, folder, source):
        """ source is a tuple (source_folder, tag), where tag is either !file, !files, !dir_cont or !dir """

        source_path, source_type = source[0], source[1]
        base_, leaf = os.path.split(source_path)
        to_remove_path = os.path.normpath(os.path.join(folder, leaf))

        remove_actions = var_stack.ResolveVarToList("iid_action_list_remove_item", default=[])
        if len(remove_actions) == 0:  # no specific actions were specified, so just remove the files
            if source_type == '!dir':  # remove whole folder
                remove_action = self.platform_helper.rmdir(to_remove_path, recursive=True)
                self.batch_accum += remove_action
            elif source_type == '!file':  # remove single file
                remove_action = self.platform_helper.rmfile(to_remove_path)
                self.batch_accum += remove_action
            elif source_type == '!dir_cont':  # remove all source's files and folders from a folder
                remove_items = self.info_map_table.get_items_in_dir(dir_path=source_path, levels_deep=1)
                remove_paths = self.original_names_from_wtars_names(item.path for item in remove_items)
                for remove_path in remove_paths:
                    base_, leaf = os.path.split(remove_path)
                    remove_full_path = os.path.normpath(os.path.join(folder, leaf))
                    remove_action = self.platform_helper.rm_file_or_dir(remove_full_path)
                    self.batch_accum += remove_action
            elif source_type == '!files':    # # remove all source's files from a folder
                remove_items = self.info_map_table.get_items_in_dir(dir_path=source_path, levels_deep=1)
                remove_paths = self.original_names_from_wtars_names(item.path for item in remove_items)
                for remove_path in remove_paths:
                    base_, leaf = os.path.split(remove_path)
                    remove_full_path = os.path.normpath(os.path.join(folder, leaf))
                    remove_action = self.platform_helper.rmfile(remove_full_path)
                    self.batch_accum += remove_action
        else:
            remove_actions = [_f for _f in remove_actions if _f]  # filter out None values
            self.batch_accum += remove_actions
