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

    sorted_target_folder_list = sorted(self.installState.install_items_by_target_folder,
                                       key=lambda fold: var_stack.resolve(fold))

    # first create all target folders so to avoid dependency order problems such as creating links between folders
    if len(sorted_target_folder_list) > 0:
        self.batch_accum += self.platform_helper.progress("Creating folders...")
        for folder_name in sorted_target_folder_list:
            self.batch_accum += self.platform_helper.mkdir_with_owner(folder_name)
        self.batch_accum += self.platform_helper.progress("Create folders done")

    self.accumulate_unique_actions('pre_copy', self.installState.full_install_items)

    if 'Mac' in var_stack.resolve_to_list("$(__CURRENT_OS_NAMES__)") and 'Mac' in var_stack.resolve_to_list("$(TARGET_OS)"):
        self.pre_copy_mac_handling()

    for folder_name in sorted_target_folder_list:
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
                    source = var_stack.resolve_var_to_list(source_var)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_pre_copy_item")
                    self.create_copy_instructions_for_source(source)
                    self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_post_copy_item")
                    self.batch_accum += self.platform_helper.progress("Copy {installi.name}".format(**locals()))
        self.batch_accum += self.platform_helper.copy_tool.end_copy_folder()
        logging.info("... copy actions: %d", len(self.batch_accum) - batch_accum_len_before)

        self.batch_accum += self.platform_helper.progress("Expanding files...")
        self.batch_accum += self.platform_helper.unwtar_current_folder(no_artifacts=True)
        self.batch_accum += self.platform_helper.progress("Expand files done")

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
                    self.batch_accum += self.platform_helper.unwtar_something(to_untar)
                self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_pre_copy_item")
                self.batch_accum += var_stack.resolve_var_to_list_if_exists("iid_action_list_post_copy_item")

        # accumulate post_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions('post_copy_to_folder', items_in_folder)

        self.batch_accum += self.platform_helper.progress("{folder_name}".format(**locals()))
        self.batch_accum.indent_level -= 1

    self.accumulate_unique_actions('post_copy', self.installState.full_install_items)

    self.batch_accum.set_current_section('post-copy')
    self.batch_accum += self.platform_helper.copy_file_to_file("$(HAVE_INFO_MAP_PATH)", "$(SITE_HAVE_INFO_MAP_PATH)")

    self.platform_helper.copy_tool.finalize()

    self.create_require_file_instructions()

    # messages about orphan iids
    for iid in self.installState.orphan_install_items:
        logging.info("Orphan item: %s", iid)
        self.batch_accum += self.platform_helper.echo("Don't know how to install " + iid)
    self.batch_accum += self.platform_helper.progress("Done copy")


def create_copy_instructions_for_source(self, source):
    """ source is a tuple (source_path, tag), where tag is either !file or !dir """

    source_path = os.path.normpath("$(LOCAL_REPO_SYNC_DIR)/" + source[0])

    ignore_list = var_stack.resolve_to_list("$(COPY_IGNORE_PATTERNS)")

    if source[1] == '!file':  # get a single file, not recommended
        source_item = self.have_map.get_item_at_path(source[0])
        if source_item:
            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".",
                                                                                link_dest=True,
                                                                                ignore=ignore_list)
        else:
            source_folder, source_name = os.path.split(source[0])
            source_folder_item = self.have_map.get_item_at_path(source_folder)
            if source_folder_item:
                for wtar_item in source_folder_item.walk_items_with_filter(svnTree.WtarFilter(source_name), what="file"):
                    source_path = os.path.normpath("$(LOCAL_REPO_SYNC_DIR)/" + wtar_item.full_path())
                    self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".",
                                                                                        link_dest=True,
                                                                                        ignore=ignore_list)

    elif source[1] == '!dir_cont':  # get all files and folders from a folder
        self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(source_path, ".",
                                                                                    link_dest=True,
                                                                                    ignore=ignore_list,
                                                                                    preserve_dest_files=True)  # preserve files already in destination
    elif source[1] == '!files':  # get all files from a folder
        self.batch_accum += self.platform_helper.copy_tool.copy_dir_files_to_dir(source_path, ".",
                                                                                 link_dest=True,
                                                                                 ignore=ignore_list)
    else:  # !dir
        source_item = self.have_map.get_item_at_path(source[0])
        if source_item:
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path, ".",
                                                                               link_dest=True,
                                                                               ignore=ignore_list)
        else:
            source_folder, source_name = os.path.split(source[0])
            source_folder_item = self.have_map.get_item_at_path(source_folder)
            if source_folder_item:
                for wtar_item in source_folder_item.walk_items_with_filter(svnTree.WtarFilter(source_name), what="file"):
                    source_path = os.path.normpath("$(LOCAL_REPO_SYNC_DIR)/" + wtar_item.full_path())
                    self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_path, ".",
                                                                                        link_dest=True,
                                                                                        ignore=ignore_list)
    logging.debug("%s; (%s - %s)", source_path, var_stack.resolve(source_path), source[1])


# special handling when running on Mac OS
def pre_copy_mac_handling(self):
    num_files_to_set_exec = self.have_map.num_subs_in_tree(what="file",
                                                           predicate=lambda in_item: in_item.isExecutable())
    logging.info("Num files to set exec: %d", num_files_to_set_exec)
    if num_files_to_set_exec > 0:
        self.batch_accum += self.platform_helper.pushd("$(LOCAL_REPO_SYNC_DIR)")
        self.batch_accum += self.platform_helper.set_exec_for_folder(self.have_map.path_to_file)
        self.platform_helper.num_items_for_progress_report += num_files_to_set_exec
        self.batch_accum += self.platform_helper.progress("Set exec done")
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.popd()
