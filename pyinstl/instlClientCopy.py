#!/usr/bin/env python2.7

from __future__ import print_function

import os
import logging

import svnTree
import utils
from configVar import var_stack


def do_copy(self):
    logging.info("Creating copy instructions")
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

def create_copy_instructions(self):
    self.have_map = svnTree.SVNTree()
    # read NEW_HAVE_INFO_MAP_PATH and not HAVE_INFO_MAP_PATH. Copy might be called after the sync batch file was created
    # but before it was executed.  HAVE_INFO_MAP_PATH is only created
    # when the sync batch file is executed.
    have_info_path = var_stack.resolve("$(NEW_HAVE_INFO_MAP_PATH)")
    self.have_map.read_info_map_from_file(have_info_path, a_format="text")

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
        items_in_folder = self.installState.install_items_by_target_folder[folder_name]
        logging.info("folder %s", var_stack.resolve(folder_name))
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.cd(folder_name)

        # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions('pre_copy_to_folder', items_in_folder)

        batch_accum_len_before = len(self.batch_accum)
        self.batch_accum += self.platform_helper.copy_tool.begin_copy_folder()
        for IID in items_in_folder:
            with self.install_definitions_index[IID] as installi:
                for source_var in var_stack.get_configVar_obj("iid_source_var_list"):
                    num_items_copied_to_folder += 1
                    source = var_stack.resolve_var_to_list(source_var)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_pre_copy_item")
                    self.create_copy_instructions_for_source(source, installi.name)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_post_copy_item")
        self.batch_accum += self.platform_helper.copy_tool.end_copy_folder()
        logging.info("... copy actions: %d", len(self.batch_accum) - batch_accum_len_before)

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
    for folder_name, items_in_folder in self.installState.no_copy_items_by_sync_folder.iteritems():

        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.cd(folder_name)
        self.batch_accum.indent_level += 1

        # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions('pre_copy_to_folder', items_in_folder)

        for IID in items_in_folder:
            with self.install_definitions_index[IID]:
                for source_var in var_stack.resolve_var_to_list_if_exists("iid_source_var_list"):
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
    for iid in self.installState.orphan_install_items:
        logging.info("Orphan item: %s", iid)
        self.batch_accum += self.platform_helper.echo("Don't know how to install " + iid)
    self.batch_accum += self.platform_helper.progress("Done copy")


def create_copy_instructions_for_source(self, source, name_for_progress_message):
    """ source is a tuple (source_path, tag), where tag is either !file or !dir
    """

    # return True if name is a wtar file (.w) or the first file of a split wtar (.wtar.aa)
    def is_first_wtar_file(name):
        retVal = name.endswith(".wtar") or name.endswith(".wtar.aa")
        return retVal

    def calc_size_of_file_item(old_total, a_file_item):
        """ for use with builtin function reduce to calculate the unwtarred size of a file """
        if self.is_wtar_item(a_file_item):
            item_size = int(float(a_file_item.safe_size) * self.wtar_ratio)
        else:
            item_size = a_file_item.safe_size
        return old_total + item_size

    source_item = self.have_map.get_item_at_path(source[0])
    source_path = os.path.normpath("$(LOCAL_REPO_SYNC_DIR)/" + source[0])

    ignore_list = var_stack.resolve_to_list("$(COPY_IGNORE_PATTERNS)")

    if source[1] == '!file':  # get a single file
        if source_item:
            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".",
                                                                                link_dest=True,
                                                                                ignore=ignore_list)
            self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))
            self.bytes_to_copy += source_item.safe_size
        else: # not in map, might be wtarred
            source_folder, source_name = os.path.split(source[0])
            source_folder_item = self.have_map.get_item_at_path(source_folder)
            if source_folder_item:
                first_wtar_item = None
                for wtar_item in source_folder_item.walk_items_with_filter(svnTree.WtarFilter(source_name), what="file"):
                    if is_first_wtar_file(wtar_item.name):
                        first_wtar_item = wtar_item
                    source_path = os.path.normpath("$(LOCAL_REPO_SYNC_DIR)/" + wtar_item.full_path())
                    self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".",
                                                                                        link_dest=True,
                                                                                        ignore=ignore_list)
                    self.bytes_to_copy += int(float(wtar_item.safe_size) * self.wtar_ratio)
                self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))
                if first_wtar_item:
                    self.batch_accum += self.platform_helper.unwtar_something(first_wtar_item.name, no_artifacts=True)
                    self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))

    elif source[1] == '!dir_cont':  # get all files and folders from a folder
        self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(source_path, ".",
                                                                                    link_dest=True,
                                                                                    ignore=ignore_list,
                                                                                    preserve_dest_files=True)  # preserve files already in destination
        self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))

        self.bytes_to_copy += reduce(calc_size_of_file_item, source_item.walk_items(what="file"), 0)
        file_list, dir_list = source_item.sorted_sub_items()
        num_items_to_unwtar = 0
        for file_item in file_list:
            if is_first_wtar_file(file_item.name):
                self.batch_accum += self.platform_helper.unwtar_something(file_item.name, no_artifacts=True)
                num_items_to_unwtar += 1
        for dir_item in dir_list:
            num_wtar_files_in_dir_item = len(list(dir_item.walk_items_with_filter(svnTree.WtarFilter(), what="file")))
            if num_wtar_files_in_dir_item > 0:
                self.batch_accum += self.platform_helper.unwtar_something(dir_item.name, no_artifacts=True)
                num_items_to_unwtar += 1
        if num_items_to_unwtar > 0:
            self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))

    elif source[1] == '!files':  # get all files from a folder
        self.batch_accum += self.platform_helper.copy_tool.copy_dir_files_to_dir(source_path, ".",
                                                                                 link_dest=True,
                                                                                 ignore=ignore_list)
        self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))
        file_list, dir_list = source_item.sorted_sub_items()
        self.bytes_to_copy += reduce(calc_size_of_file_item, file_list, 0)
        file_list, dir_list = source_item.sorted_sub_items()
        num_items_to_unwtar = 0
        for file_item in file_list:
            if is_first_wtar_file(file_item.name):
                self.batch_accum += self.platform_helper.unwtar_something(file_item.name, no_artifacts=True)
                num_items_to_unwtar += 1
        if num_items_to_unwtar > 0:
            self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))

    else:  # !dir
        if source_item:
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path, ".",
                                                                               link_dest=True,
                                                                               ignore=ignore_list)
            self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))
            self.bytes_to_copy += reduce(calc_size_of_file_item, source_item.walk_items(what="file"), 0)
            num_wtar_files_in_source = len(list(source_item.walk_items_with_filter(svnTree.WtarFilter(), what="file")))
            if num_wtar_files_in_source > 0:
                self.batch_accum += self.platform_helper.unwtar_something(source_item.name, no_artifacts=True)
                self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))
        else:
            source_folder, source_name = os.path.split(source[0])
            source_folder_item = self.have_map.get_item_at_path(source_folder)
            if source_folder_item:
                first_wtar_item = None
                for wtar_item in source_folder_item.walk_items_with_filter(svnTree.WtarFilter(source_name), what="file"):
                    if is_first_wtar_file(wtar_item.name):
                        first_wtar_item = wtar_item
                    source_path = os.path.normpath("$(LOCAL_REPO_SYNC_DIR)/" + wtar_item.full_path())
                    self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".",
                                                                                        link_dest=True,
                                                                                        ignore=ignore_list)
                    self.batch_accum += self.platform_helper.progress("Copy {name_for_progress_message}".format(**locals()))
                    self.bytes_to_copy += int(float(wtar_item.safe_size) * self.wtar_ratio)
                if first_wtar_item:
                    self.batch_accum += self.platform_helper.unwtar_something(first_wtar_item.name, no_artifacts=True)
                    self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message}".format(**locals()))
    logging.debug("%s; (%s - %s)", source_path, var_stack.resolve(source_path), source[1])


# special handling when running on Mac OS
def pre_copy_mac_handling(self):
    num_files_to_set_exec = self.have_map.num_subs_in_tree(what="file",
                                                           predicate=lambda in_item: in_item.isExecutable())
    logging.info("Num files to set exec: %d", num_files_to_set_exec)
    if num_files_to_set_exec > 0:
        self.batch_accum += self.platform_helper.set_exec_for_folder(self.have_map.path_to_file)
        self.batch_accum += self.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
        self.platform_helper.num_items_for_progress_report += num_files_to_set_exec
        self.batch_accum += self.platform_helper.progress("Set exec done")
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.popd()
