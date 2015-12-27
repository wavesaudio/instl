#!/usr/bin/env python2.7

from __future__ import print_function

import os

import svnTree
import utils
from configVar import var_stack
from functools import reduce


def do_copy(self):
    self.init_copy_vars()
    self.create_copy_instructions()


def init_copy_vars(self):
    self.action_type_to_progress_message = {'pre_copy': "pre-install step",
                                            'post_copy': "post-install step",
                                            'pre_copy_to_folder': "pre-copy step",
                                            'post_copy_to_folder': "post-copy step"}
    self.bytes_to_copy = 0
    self.wtar_ratio = 1.3 # ratio between wtar file and it's uncompressed contents
    if "WTAR_RATIO" in var_stack:
        self.wtar_ratio = float(var_stack.resolve("$(WTAR_RATIO)"))
    self.is_wtar_item = svnTree.WtarFilter() # will return true for any wtar file
    self.calc_user_cache_dir_var() # this will set USER_CACHE_DIR if it was not explicitly defined
    self.ignore_list = var_stack.resolve_to_list("$(COPY_IGNORE_PATTERNS)")


def create_copy_instructions(self):
    # read HAVE_INFO_MAP_FOR_COPY which is be default HAVE_INFO_MAP_PATH.
    # Copy might be called after the sync batch file was created
    # but before it was executed in which case HAVE_INFO_MAP_FOR_COPY will be defined to NEW_HAVE_INFO_MAP_PATH.
    have_info_path = var_stack.resolve("$(HAVE_INFO_MAP_FOR_COPY)")
    self.info_map_table.read_from_file(have_info_path, a_format="text")

    # copy and actions instructions for sources
    self.batch_accum.set_current_section('copy')
    self.batch_accum += self.platform_helper.progress("Starting copy from $(LOCAL_REPO_SYNC_DIR)")

    self.accumulate_unique_actions('pre_copy', self.installState.full_install_items)

    sorted_target_folder_list = sorted(self.installState.install_items_by_target_folder,
                                       key=lambda fold: var_stack.resolve(fold))

    # first create all target folders so to avoid dependency order problems such as creating links between folders
    if len(sorted_target_folder_list) > 0:
        self.batch_accum += self.platform_helper.progress("Creating folders...")
        for folder_name in sorted_target_folder_list:
            self.batch_accum += self.platform_helper.mkdir_with_owner(folder_name)
        self.batch_accum += self.platform_helper.progress("Create folders done")

    if 'Mac' in var_stack.resolve_to_list("$(__CURRENT_OS_NAMES__)") and 'Mac' in var_stack.resolve_to_list("$(TARGET_OS)"):
        self.pre_copy_mac_handling()

    for folder_name in sorted_target_folder_list:
        num_items_copied_to_folder = 0
        items_in_folder = sorted(self.installState.install_items_by_target_folder[folder_name])
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.cd(folder_name)

        # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions('pre_copy_to_folder', items_in_folder)

        batch_accum_len_before = len(self.batch_accum)
        self.batch_accum += self.platform_helper.copy_tool.begin_copy_folder()
        for IID in items_in_folder:
            with self.install_definitions_index[IID] as installi:
                for source_var in sorted(var_stack.get_configVar_obj("iid_source_var_list")):
                    num_items_copied_to_folder += 1
                    source = var_stack.resolve_var_to_list(source_var)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_pre_copy_item")
                    self.create_copy_instructions_for_source(source, installi.name)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_post_copy_item")
        self.batch_accum += self.platform_helper.copy_tool.end_copy_folder()

        # only if items were actually copied there's need to (Mac only) resolve symlinks
        if num_items_copied_to_folder > 0:
            if 'Mac' in var_stack.resolve_to_list("$(__CURRENT_OS_NAMES__)") and 'Mac' in var_stack.resolve_to_list("$(TARGET_OS)"):
                self.batch_accum += self.platform_helper.progress("Resolving symlinks...")
                self.batch_accum += self.platform_helper.resolve_symlink_files()
                self.batch_accum += self.platform_helper.progress("Resolve symlinks done")

        # accumulate post_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions('post_copy_to_folder', items_in_folder)

        self.batch_accum.indent_level -= 1

    # actions instructions for sources that do not need copying, here folder_name is the sync folder
    for folder_name in sorted(self.installState.no_copy_items_by_sync_folder.keys()):
        items_in_folder = self.installState.no_copy_items_by_sync_folder[folder_name]
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.cd(folder_name)
        self.batch_accum.indent_level += 1

        # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions('pre_copy_to_folder', items_in_folder)

        for IID in sorted(items_in_folder):
            with self.install_definitions_index[IID]:
                for source_var in sorted(var_stack.resolve_var_to_list_if_exists("iid_source_var_list")):
                    source = var_stack.resolve_var_to_list(source_var)
                    source_folder, source_name = os.path.split(source[0])
                    to_untar = os.path.join(folder_name, source_name)
                    self.batch_accum += self.platform_helper.unwtar_something(to_untar, no_artifacts=True)
                self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_pre_copy_item")
                self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_post_copy_item")

        # accumulate post_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions('post_copy_to_folder', items_in_folder)

        self.batch_accum += self.platform_helper.progress("{folder_name}".format(**locals()))
        self.batch_accum.indent_level -= 1

    print(self.bytes_to_copy, "bytes to copy")

    self.accumulate_unique_actions('post_copy', self.installState.full_install_items)

    self.batch_accum.set_current_section('post-copy')
    # Copy have_info file to "site" (e.g. /Library/Application support/... or c:\ProgramData\...)
    # for reference. But when preparing offline installers the site location is the same as the sync location
    # so copy should be avoided.
    if var_stack.resolve("$(HAVE_INFO_MAP_PATH)") != var_stack.resolve("$(SITE_HAVE_INFO_MAP_PATH)"):
        self.batch_accum += self.platform_helper.mkdir_with_owner("$(SITE_REPO_BOOKKEEPING_DIR)")
        self.batch_accum += self.platform_helper.copy_file_to_file("$(HAVE_INFO_MAP_PATH)", "$(SITE_HAVE_INFO_MAP_PATH)")

    self.platform_helper.copy_tool.finalize()

    self.create_require_file_instructions()

    # messages about orphan iids
    for iid in sorted(self.installState.orphan_install_items):
        self.batch_accum += self.platform_helper.echo("Don't know how to install " + iid)
    self.batch_accum += self.platform_helper.progress("Done copy")


def calc_size_of_file_item(self, a_file_item):
    """ for use with builtin function reduce to calculate the unwtarred size of a file """
    if a_file_item.is_wtar_file():
        item_size = int(float(a_file_item.size) * self.wtar_ratio)
    else:
        item_size = a_file_item.size
    return item_size


def create_copy_instructions_for_file(self, source_path, name_for_progress_message):
    source_items = self.info_map_table.get_required_for_file(source_path)
    first_wtar_item = None
    for source_item in source_items:
        source_item_path = os.path.normpath("$(LOCAL_REPO_SYNC_DIR)/" + source_item.path)
        self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_item_path, ".",
                                                                            link_dest=True,
                                                                            ignore=self.ignore_list)
        self.bytes_to_copy += self.calc_size_of_file_item(source_item)
        if source_item.is_first_wtar_file():
            first_wtar_item = source_item
    self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))
    if first_wtar_item:
        self.batch_accum += self.platform_helper.unwtar_something(first_wtar_item.name(), no_artifacts=True)
        self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))


def create_copy_instructions_for_dir_cont(self, source_path, name_for_progress_message):
    self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(source_path, ".",
                                                                                link_dest=True,
                                                                                ignore=self.ignore_list,
                                                                                preserve_dest_files=True)  # preserve files already in destination
    self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))

    source_items = self.info_map_table.get_files_in_dir(source_path)
    num_items_to_unwtar = 0
    for source_item in source_items:
        self.bytes_to_copy += self.calc_size_of_file_item(source_item)
        if source_item.is_wtar_file():
            num_items_to_unwtar += 1
    if num_items_to_unwtar > 0:
        self.batch_accum += self.platform_helper.unwtar_something(".", no_artifacts=True)
        self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))


def create_copy_instructions_for_files(self, source_path, name_for_progress_message):
    self.batch_accum += self.platform_helper.copy_tool.copy_dir_files_to_dir(source_path, ".",
                                                                             link_dest=True,
                                                                             ignore=self.ignore_list)
    self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))

    source_items = self.info_map_table.get_files_in_dir(source_path, levels_deep=1)
    num_items_to_unwtar = 0
    for source_item in source_items:
        self.bytes_to_copy += self.calc_size_of_file_item(source_item)
        if source_item.is_first_wtar_file():
            self.batch_accum += self.platform_helper.unwtar_something(source_item.name(), no_artifacts=True)
            self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))


def create_copy_instructions_for_dir(self, source_path, name_for_progress_message):
    dir_item = self.info_map_table.get_dir_item(source_path)
    if dir_item is not None:
        self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path, ".",
                                                                           link_dest=True,
                                                                           ignore=self.ignore_list)
        self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))
        source_items = self.info_map_table.get_files_in_dir(source_path)
        num_items_to_unwtar = 0
        for source_item in source_items:
            self.bytes_to_copy += self.calc_size_of_file_item(source_item)
            if source_item.is_wtar_file():
                num_items_to_unwtar += 1
        if num_items_to_unwtar > 0:
            self.batch_accum += self.platform_helper.unwtar_something(".", no_artifacts=True)
            self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))
    else:
        # it might be a dir that was wtarred
        self.create_copy_instructions_for_file(source_path, name_for_progress_message)


def create_copy_instructions_for_source(self, source, name_for_progress_message):
    """ source is a tuple (source_path, tag), where tag is either !file or !dir
    """

    if source[1] == '!file':  # get a single file
        self.create_copy_instructions_for_file(source[0], name_for_progress_message)
    elif source[1] == '!dir_cont':  # get all files and folders from a folder
        self.create_copy_instructions_for_dir_cont(source[0], name_for_progress_message)
    elif source[1] == '!files':  # get all files from a folder
        self.create_copy_instructions_for_files(source[0], name_for_progress_message)
    elif source[1] == '!dir':  # !dir
        self.create_copy_instructions_for_dir(source[0], name_for_progress_message)
    else:
        raise ValueError("unknown source type "+source[1]+" for "+source[0])


# special handling when running on Mac OS
def pre_copy_mac_handling(self):
    required_and_exec = self.info_map_table.get_required_exec()
    num_files_to_set_exec = len(required_and_exec)
    if num_files_to_set_exec > 0:
        self.batch_accum += self.platform_helper.set_exec_for_folder(self.have_map.path_to_file)
        self.batch_accum += self.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
        self.platform_helper.num_items_for_progress_report += num_files_to_set_exec
        self.batch_accum += self.platform_helper.progress("Set exec done")
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.popd()
