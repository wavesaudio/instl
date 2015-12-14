#!/usr/bin/env python3



import os

import svnTree
from configVar import var_stack


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
    self.have_map = svnTree.SVNTree()

    have_info_path = var_stack.resolve("$(HAVE_INFO_MAP_PATH)")
    if not os.path.isfile(have_info_path):
        have_info_path = var_stack.resolve("$(SITE_HAVE_INFO_MAP_PATH)")
    self.have_map.read_info_map_from_file(have_info_path, a_format="text")

    self.batch_accum.set_current_section('remove')
    self.batch_accum += self.platform_helper.progress("Starting remove")
    sorted_target_folder_list = sorted(self.installState.install_items_by_target_folder,
                                       key=lambda fold: var_stack.resolve(fold),
                                       reverse=True)
    # print(sorted_target_folder_list)
    self.accumulate_unique_actions('pre_remove', self.installState.full_install_items)

    for folder_name in sorted_target_folder_list:
        var_stack.set_var("__TARGET_DIR__").append(os.path.normpath(folder_name))
        items_in_folder = self.installState.install_items_by_target_folder[folder_name]
        self.batch_accum += self.platform_helper.new_line()

        self.accumulate_unique_actions('pre_remove_from_folder', items_in_folder)

        for IID in items_in_folder:
            with self.install_definitions_index[IID] as installi:
                for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                    source = var_stack.resolve_var_to_list(source_var)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_pre_remove_item")
                    self.create_remove_instructions_for_source(folder_name, source)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_post_remove_item")
                    self.batch_accum += self.platform_helper.progress("Remove {installi.name}".format(**locals()))

        self.accumulate_unique_actions('post_remove_from_folder', items_in_folder)

    self.accumulate_unique_actions('post_remove', self.installState.full_install_items)


# create_remove_instructions_for_source:
# Create instructions to remove a specific source from a specific target folder.
# There can be 3 possibilities according to the value of the item's remove_item section:
# No remove_item was specified - so all item's sources should be deleted.
# Null remove_item was specified (remove_item: ~) - so nothing should be done.
# Specific remove_item action specified - so specific action should be done.

def create_remove_instructions_for_source(self, folder, source):
    """ source is a tuple (source_folder, tag), where tag is either !file or !dir """

    base_, leaf = os.path.split(source[0])
    to_remove_path = os.path.normpath(os.path.join(folder, leaf))

    remove_actions = var_stack.resolve_var_to_list_if_exists("iid_action_list_remove_item")
    if len(remove_actions) == 0:
        if source[1] == '!dir':  # remove whole folder
            remove_action = self.platform_helper.rmdir(to_remove_path, recursive=True)
            self.batch_accum += remove_action
        elif source[1] == '!file':  # remove single file
            remove_action = self.platform_helper.rmfile(to_remove_path)
            self.batch_accum += remove_action
        elif source[1] == '!dir_cont':  # remove all source's files and folders from a folder
            source_folder_info_map_item = self.have_map.get_item_at_path(source[0])
            # avoid removing items that were not installed,
            # could happen because install dependencies are not always the same as remove dependencies.
            if source_folder_info_map_item is not None:
                file_list, folder_list = source_folder_info_map_item.sorted_sub_items()
                unwtared_file_name_list = self.replace_wtar_names_with_real_names(file_item.name for file_item in file_list)
                for sub_file_name in unwtared_file_name_list:
                    to_remove_path = os.path.normpath(os.path.join(folder, sub_file_name))
                    remove_action = self.platform_helper.rm_file_or_dir(to_remove_path)
                    self.batch_accum += remove_action
                for sub_folder in folder_list:
                    to_remove_path = os.path.normpath(os.path.join(folder, sub_folder.name))
                    remove_action = self.platform_helper.rmdir(to_remove_path, recursive=True)
                    self.batch_accum += remove_action
        elif source[1] == '!files':    # # remove all source's files from a folder
            source_folder_info_map_item = self.have_map.get_item_at_path(source[0])
            # avoid removing items that were not installed,
            # could happen because install dependencies are not always the same as remove dependencies.
            if source_folder_info_map_item is not None:
                file_list, folder_list = source_folder_info_map_item.sorted_sub_items()
                unwtared_file_name_list = self.replace_wtar_names_with_real_names(file_item.name for file_item in file_list)
                for sub_file_name in unwtared_file_name_list:
                    to_remove_path = os.path.normpath(os.path.join(folder, sub_file_name))
                    remove_action = self.platform_helper.rm_file_or_dir(to_remove_path)
                    self.batch_accum += remove_action
    else:
        remove_actions = [_f for _f in remove_actions if _f]  # filter out None values
        self.batch_accum += remove_actions
