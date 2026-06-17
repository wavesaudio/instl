#!/usr/bin/env python3.12
"""Wtar commands extracted verbatim from pyinstl/instlAdmin.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

import os
import re

import utils
from pybatch import *


class _WtarAdminMixin:

    def prepare_conditions_for_wtar(self):
        folder_wtar_regex_list = list(config_vars["FOLDER_WTAR_REGEX"])
        self.compiled_folder_wtar_regex = utils.compile_regex_list_ORed(folder_wtar_regex_list)

        # some folders should not be wtarred even if they pass 'FOLDER_WTAR_REGEX'.
        # if FOLDER_EXCLUDE_WTAR_REGEX was not found, folder_exclude_wtar_regex_list will default to a^
        # which will not exclude any folder
        folder_exclude_wtar_regex_list = config_vars.get("FOLDER_EXCLUDE_WTAR_REGEX", ['a^']).list()
        self.compiled_folder_exclude_wtar_regex = utils.compile_regex_list_ORed(folder_exclude_wtar_regex_list)

        file_wtar_regex_list = list(config_vars["FILE_WTAR_REGEX"])
        self.compiled_file_wtar_regex = utils.compile_regex_list_ORed(file_wtar_regex_list)

        self.min_file_size_to_wtar = int(config_vars["MIN_FILE_SIZE_TO_WTAR"])

        if "WTAR_BY_FILE_SIZE_EXCLUDE_REGEX" in config_vars:
            wtar_by_file_size_exclude_regex = list(config_vars["WTAR_BY_FILE_SIZE_EXCLUDE_REGEX"])
            self.compiled_wtar_by_file_size_exclude_regex = utils.compile_regex_list_ORed(wtar_by_file_size_exclude_regex)
        else:
            self.compiled_wtar_by_file_size_exclude_regex = re.compile(".+")

        self.already_wtarred_regex = re.compile(r"wtar(\.\w\w)?$")

    def should_wtar(self, dir_item: Path):
        _should_wtar = False
        _already_tarred = False
        dir_item_str = os.fspath(dir_item)
        try:
            if self.already_wtarred_regex.search(dir_item_str):
                _should_wtar = False
                _already_tarred = True
            elif dir_item.is_dir():
                if self.compiled_folder_wtar_regex.search(dir_item_str) \
                    and not self.compiled_folder_exclude_wtar_regex.search(dir_item_str):
                    # it's a folder matching one of the filters for wtarring a folder,
                    # but is not on the excludes filter
                    _should_wtar = True
                    _already_tarred = False
            elif dir_item.is_file():
                if self.compiled_file_wtar_regex.search(dir_item_str):
                    # it's a file matching one of the filters for wtarring a file
                    _should_wtar = True
                    _already_tarred = False
                elif dir_item.stat().st_size > self.min_file_size_to_wtar:
                    # it's a file whose size is big enough to require wtarring
                    if re.match(self.compiled_wtar_by_file_size_exclude_regex, dir_item_str):
                        _should_wtar = False
                        _already_tarred = False
                    else:
                        # but not a file whose name matching one of the filters for NOT wtarring
                        _should_wtar = True
                        _already_tarred = False
                else:
                    _should_wtar = False
                    _already_tarred = False
        except Exception:
            pass
        return _should_wtar, _already_tarred

    def do_wtar_staging_folder(self):
        self.batch_accum.set_current_section('admin')
        self.prepare_conditions_for_wtar()

        stage_folder = config_vars["STAGING_FOLDER"].Path()
        items_to_check = self.prepare_list_of_dirs_to_work_on(stage_folder)
        if tuple(items_to_check) == (stage_folder,):
            self.progress("wtar for the whole repository")
        else:
            self.progress("wtar limited to ", "; ".join([os.fspath(i) for i in items_to_check]))

        for a_folder in items_to_check:
            self.batch_accum += Unlock(a_folder, recursive=True)
            self.batch_accum += RmGlob(a_folder, '**/.DS_Store')
            self.batch_accum += RmGlob(a_folder, '**/*~*')
            self.batch_accum += Progress(f"delete ignored files in {a_folder}")

        total_items_to_tar = 0
        total_redundant_wtar_files = 0
        while len(items_to_check) > 0:
            item_to_check = items_to_check.pop(0)
            items_to_tar = list()
            items_to_delete = list()  # these are .wtar files for items that no longer need wtarring
            if not self.already_wtarred_regex.search(os.fspath(item_to_check)) and not item_to_check.is_symlink():

                # the item is not a wtar file, so whether it needs wtarring or not,
                # the old wtar parts, if any, should to be removed
                items_to_delete.extend(utils.find_wtarred_parts_of_original(item_to_check))

                # check if the item itself is candidate for wtarring
                to_tar, already_tarred = self.should_wtar(item_to_check)
                if to_tar:
                    items_to_tar.append(item_to_check)
                else:
                    # item_to_check does not need tarring, remove previous tars of this folder
                    # and recursively check child entries
                    if item_to_check.is_dir():
                        more_paths_to_check = [Path(ent) for ent in sorted(list(os.scandir(item_to_check)), key=lambda i: i.is_dir())]
                        items_to_check.extend(more_paths_to_check)

                if items_to_tar or items_to_delete:
                    total_items_to_tar += len(items_to_tar)

                    for item_to_delete in items_to_delete:
                        self.batch_accum += RmFile(item_to_delete)

                    for item_to_tar in items_to_tar:
                        self.batch_accum += Wtar(item_to_tar, split_threshold=self.min_file_size_to_wtar)
                        self.batch_accum += RmFileOrDir(item_to_tar)

        self.progress("found", total_items_to_tar, "to wtar")
        if total_redundant_wtar_files:
            self.progress(total_redundant_wtar_files, "redundant wtar files will be removed")

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()
