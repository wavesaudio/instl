#!/usr/bin/env python3.9
import json
import logging
log = logging.getLogger()

import os
import sys
import traceback
import filecmp
import multiprocessing as mp
import time
import datetime
import re
import redis
import boto3
import threading
import io

from dataclasses import dataclass
import dictdiffer

import utils
import yaml
import aYaml
from .instlInstanceBase import InstlInstanceBase
from pybatch import *
from .instlException import InstlException
from configVar import ConfigVarYamlReader

def start_redis_heartbeat_thread(redis_host, redis_port, heartbeat_key, heartbeat_interval):
    """ start a daemon thread that will periodically set a redis key to a string containing the current date/time
        a daemon thread will stop when the application quits, so no need to join the thread
    """
    def heartbeat_redis(redis_host, redis_port, heartbeat_key, heartbeat_interval):
        try:
            r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)
            while True:
                now_time = time.time()
                r.set(heartbeat_key, str(datetime.datetime.fromtimestamp(now_time)))
                time_to_sleep = max(now_time + heartbeat_interval - time.time(), 0.01)
                #print(f"{now_time} {time_to_sleep}")
                time.sleep(time_to_sleep)
        except Exception as ex:
            print(f"Exception in heartbeat_redis {ex}")

    thread_name = "redis heartbeat"
    x = threading.Thread(target=heartbeat_redis, args=(redis_host, redis_port, heartbeat_key, heartbeat_interval), daemon=True, name=thread_name)
    x.start()


def smart_merge_dicts(by_os_dict):
    """ merge dicts by OS according to instl conventions
        by_os_dict is in the form {"Linux": {...}, "Mac": {...}, "Win": {...}}
        the dicts under by_os_dict are assumed to be different, if they are identical to begin with
        results are undefined
    """

    all_os_names = sorted(list(by_os_dict.keys()))
    merged = dict()
    for os_name in all_os_names:
        merged[os_name] = dict()

    # create a set of all top level keys
    all_keys = set()
    for os_name in all_os_names:
        all_keys.update(by_os_dict[os_name].keys())

    # items in already OS specific key should come from the corresponding os dict
    for os_name in all_os_names:
        if os_name in by_os_dict[os_name]:  # e.g "Mac" dict has a "Mac" key
            merged[os_name].update(by_os_dict[os_name][os_name])
            all_keys.remove(os_name)
    #print("all_keys", all_keys)

    # keys that are common to all oses
    keys_common_to_all_oses = all_keys.copy()
    for os_name in all_os_names:
        keys_common_to_all_oses.intersection_update(by_os_dict[os_name].keys())
    #print("keys_common_to_all_oses", keys_common_to_all_oses)
    keys_not_common_to_all_oses = all_keys - keys_common_to_all_oses
    #print("keys_not_common_to_all_oses", keys_not_common_to_all_oses)

    # separate keys_not_common_to_all_oses to those who are identical across all oses (keys_common_to_all_oses_with_same_value)
    # and those that are different between at least 2 oses (keys_common_to_all_oses_with_diff_value)
    keys_common_to_all_oses_with_same_value = set()
    keys_common_to_all_oses_with_diff_value = set()
    for key in keys_common_to_all_oses:
        # get a first one so we have something to compare against
        _curr = by_os_dict[all_os_names[0]][key]
        for os_name in all_os_names:
            _next = by_os_dict[os_name][key]
            if list(dictdiffer.diff(_curr, _next)):
                keys_common_to_all_oses_with_diff_value.add(key)
                break
            else:
                _curr = _next
        else:
            keys_common_to_all_oses_with_same_value.add(key)
    #print("keys_common_to_all_oses_with_same_value", keys_common_to_all_oses_with_same_value)
    #print("keys_common_to_all_oses_with_diff_value", keys_common_to_all_oses_with_diff_value)

    # all oses have these keys with same value, so assigned merged with a key/value from one of the oses
    for key in keys_common_to_all_oses_with_same_value:
        merged[key] = by_os_dict[all_os_names[0]][key]

    # all oses have these keys with different value, so assigned merged with a key/value from each of the oses
    for key in (keys_common_to_all_oses_with_diff_value | keys_not_common_to_all_oses):
        for os_name in all_os_names:
            if key in by_os_dict[os_name]:
                merged[os_name][key] = by_os_dict[os_name][key]

    # remove empty dicts
    all_oses = list(merged.keys())
    for os_name in all_oses:
        if not merged[os_name]:
            del merged[os_name]

    return merged

def dict_in_canonical_order(to_order, order=None, single_value=None):
    if order is None:
        order = []
    if single_value is None:
        single_value = []
    retVal = None
    if isinstance(to_order, str):
        retVal = to_order
    elif isinstance(to_order, collections.abc.Sequence):
        retVal = [dict_in_canonical_order(item) for item in to_order]
    elif isinstance(to_order, collections.abc.Mapping):
        retVal = collections.OrderedDict()
        names_in_order = list()
        names_from_node = [str(_key) for _key in to_order]
        for name in order:
            if name in names_from_node:
                names_in_order.append(name)
                names_from_node.remove(name)
        names_in_order.extend(names_from_node)  # add names in node that do not appear in order
        for name in names_in_order:
            value = to_order[name]
            if name in single_value and isinstance(value, collections.abc.Sequence) and 1 == len(value):
                value = value[0]
            retVal[name] = dict_in_canonical_order(value, order, single_value)
    else: # not sequence or mapping or string - assuming scalar
        retVal = to_order
    return retVal



# noinspection PyPep8,PyPep8,PyPep8
class InstlAdmin(InstlInstanceBase):

    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.total_self_progress = 1000
        self.read_defaults_file(super().__thisclass__.__name__)
        self.fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')
        self.config_vars_stack_size_before_reading_config_files = None
        self.wait_info_counter = 0  # incremented when printing wait info
        self.compile_exclude_regexi()

    def get_default_out_file(self) -> None:
        if "__CONFIG_FILE__" in config_vars and '__MAIN_OUT_FILE__' not in config_vars:
            config_vars["__MAIN_OUT_FILE__"] = "$(__CONFIG_FILE__[0])-$(__MAIN_COMMAND__).$(BATCH_EXT)"

    def read_config_files(self, reset_previous=False):
        if reset_previous:
            config_vars.resize_stack(self.config_vars_stack_size_before_reading_config_files)
        self.config_vars_stack_size_before_reading_config_files = config_vars.stack_size()

        config_vars.push_scope()
        if "__CONFIG_FILE__" in config_vars:
            for config_file in config_vars["__CONFIG_FILE__"].list():
                config_file_resolved = self.path_searcher.find_file(os.fspath(config_file), return_original_if_not_found=True)
                config_vars.setdefault("__CONFIG_FILE_PATH__", default=None).append(config_file_resolved)

                self.read_yaml_file(config_file_resolved)
            self.resolve_defined_paths()

    def set_default_variables(self):
        self.read_config_files()

    def do_command(self):
        self.set_default_variables()
        #self.platform_helper.num_items_for_progress_report = int(config_vars["LAST_PROGRESS"])
        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()

    def get_revision_range(self):
        revision_range_re = re.compile(r"""
                                (?P<min_rev>\d+)
                                (:
                                (?P<max_rev>\d+)
                                )?
                                """, re.VERBOSE)
        min_rev = 0
        max_rev = 1
        match = revision_range_re.match(config_vars["REPO_REV"].str())
        if match:
            min_rev += int(match['min_rev'])
            if match['max_rev']:
                max_rev += int(match['max_rev'])
            else:
                max_rev += min_rev
        return min_rev, max_rev

    def get_last_repo_rev(self):
        repo_url = config_vars["SVN_REPO_URL"].str()
        with SVNLastRepoRev(url=repo_url, reply_config_var="__LAST_REPO_REV__") as lrr:
            lrr()
        retVal = int(config_vars["__LAST_REPO_REV__"])
        return retVal

    def do_fix_props(self):
        self.batch_accum.set_current_section('admin')
        repo_folder = config_vars["SVN_CHECKOUT_FOLDER"].Path()
        work_folder_path = repo_folder.parent

        PythonBatchCommandBase.ignore_progress = True
        with Cd(repo_folder) as cd_repo_folder:
            self.progress(cd_repo_folder.progress_msg())
            cd_repo_folder()

            props_file = work_folder_path.joinpath("svn-proplist-for-fix-props.txt")
            self.progress(f"get svn proplist to {props_file}")
            with SVNPropList(out_file=props_file) as props_getter:
                self.progress(props_getter.progress_msg_self())
                props_getter()

            info_file = work_folder_path.joinpath("svn-info-for-fix-props.txt")
            self.progress(f"get svn info to {info_file}")
            with SVNInfo(out_file=info_file) as info_getter:
                self.progress(info_getter.progress_msg_self())
                info_getter()

        with SVNInfoReader(info_file, format='info') as info_reader:
            self.progress(info_reader.progress_msg_self())
            info_reader()

        with SVNInfoReader(props_file, format='props') as props_reader:
            self.progress(props_reader.progress_msg_self())
            props_reader()
        PythonBatchCommandBase.ignore_progress = False

        should_be_exec_regex_list = list(config_vars["EXEC_PROP_REGEX"])
        self.compiled_should_be_exec_regex = utils.compile_regex_list_ORed(should_be_exec_regex_list)

        with self.batch_accum.sub_accum(Cd(repo_folder)) as repo_folder_accum:
            for item in self.info_map_table.get_items(what="any"):
                shouldBeExec = self.should_be_exec(item)
                for extra_prop in item.extra_props_list():
                    repo_folder_accum += SVNDelProp("svn:"+extra_prop, item.path)
                if item.isExecutable() and not shouldBeExec:
                    repo_folder_accum += SVNDelProp('svn:executable', item.path)
                elif not item.isExecutable() and shouldBeExec:
                    repo_folder_accum += SVNSetProp('svn:executable', 'yes', item.path)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def is_file_exec(self, file_path):
        file_mode = stat.S_IMODE(os.stat(file_path).st_mode)
        exec_mode = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        retVal = (file_mode & exec_mode) != 0
        return retVal

    def do_fix_symlinks(self):
        self.batch_accum.set_current_section('admin')

        stage_folder = config_vars["STAGING_FOLDER"].Path()
        folders_to_check = self.prepare_list_of_dirs_to_work_on(stage_folder)
        if tuple(folders_to_check) == (stage_folder,):
            self.progress("fix-symlink for the whole repository")
        else:
            self.progress("fix-symlink limited to ", "; ".join([os.fspath(i) for i in folders_to_check]))

        for folder_to_check in folders_to_check:
            self.batch_accum += CreateSymlinkFilesInFolder(folder_to_check)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def compile_exclude_regexi(self):
        forbidden_folder_regex_list = list(config_vars["FOLDER_EXCLUDE_REGEX"])
        self.compiled_forbidden_folder_regex = utils.compile_regex_list_ORed(forbidden_folder_regex_list)
        forbidden_file_regex_list = list(config_vars["FILE_EXCLUDE_REGEX"])
        self.compiled_forbidden_file_regex = utils.compile_regex_list_ORed(forbidden_file_regex_list)

    def is_forbidden_file(self, item_to_check):
        return bool(self.compiled_forbidden_file_regex.search(os.fspath(item_to_check)))

    def raise_if_forbidden_file(self, item_to_check):
        if self.is_forbidden_file(item_to_check):
            raise InstlException(f"{item_to_check} is on forbidden file list and should not be committed to svn")

    def is_forbidden_dir(self, item_to_check):
        return bool(self.compiled_forbidden_folder_regex.search(os.fspath(item_to_check)))

    def raise_if_forbidden_dir(self, item_to_check):
        if self.is_forbidden_dir(item_to_check):
            raise InstlException(f"{item_to_check} is on forbidden folders list and  should not be committed to svn")

    def do_stage2svn(self):
        self.batch_accum.set_current_section('admin')
        stage_folder = config_vars["STAGING_FOLDER"].Path()
        svn_folder = config_vars["SVN_CHECKOUT_FOLDER"].Path()

        stage_folder_svn_folder_pairs = []
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            self.progress("stage2svn limited to:")
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                stage_path = Path(stage_folder, limit)
                svn_path = Path(svn_folder, limit)
                stage_folder_svn_folder_pairs.append((stage_path, svn_path))
        else:
            self.progress("stage2svn for the whole repository:")
            stage_folder_svn_folder_pairs.append((stage_folder, svn_folder))

        for pair in stage_folder_svn_folder_pairs:
            self.progress(f"    {pair[0]} -> {pair[1]}")
            self.raise_if_forbidden_dir(pair[0])

        self.batch_accum += Unlock(stage_folder, recursive=True)
        self.batch_accum += Cd(svn_folder)
        for pair in stage_folder_svn_folder_pairs:
            # compare stage to svn folder
            comparator = filecmp.dircmp(pair[0], pair[1], ignore=[".svn", ".DS_Store", "Icon\015"])
            # create copy instructions with compare results
            self.stage2svn_with_comparator(comparator)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def stage2svn_with_comparator(self, comparator):
        """ create stage to svn copy instructions for comparator
            we cannot just use CopyDirToDir since there are some caveats and exceptions
        """
        do_not_remove_items = list()

        # items found in stage folder but not in svn folder
        for stage_only_item in sorted(comparator.left_only):
            stage_only_item_path = Path(comparator.left, stage_only_item)
            svn_item_path = Path(comparator.right, stage_only_item)
            if stage_only_item_path.is_symlink():
                raise InstlException(stage_only_item_path+" is a symlink which should not be committed to svn, run instl fix-symlinks and try again")
            elif stage_only_item_path.is_file():
                if self.is_forbidden_file(stage_only_item_path):
                    self.progress(f"skipping forbidden file {stage_only_item_path}")
                    continue

                # if stage file is .wtar.aa file but there is an identical .wtar on the right - do not add.
                # this is done to help transitioning to single wtar files to be .wtar.aa without forcing the users
                # to download again just because extension changed.
                copy_and_add_file = True
                if stage_only_item_path.name.endswith(".wtar.aa"):
                    svn_item_path_without_aa = Path(os.fspath(svn_item_path)[:-3])
                    if svn_item_path_without_aa.is_file():
                        stage_file_checksum = utils.get_wtar_total_checksum(stage_only_item_path)
                        svn_file_checksum = utils.get_wtar_total_checksum(svn_item_path_without_aa)
                        if stage_file_checksum == svn_file_checksum:
                            copy_and_add_file = False
                            do_not_remove_items.append(svn_item_path_without_aa.name)

                if copy_and_add_file:
                    self.batch_accum += CopyFileToDir(stage_only_item_path, comparator.right, hard_links=False, ignore_patterns=[".svn"])
                    # tell svn about new items, svn will not accept 'add' for changed items
                    self.batch_accum += SVNAdd(svn_item_path)
                else:
                    self.batch_accum += Progress(f"not adding {stage_only_item_path} because {svn_item_path_without_aa} exists and is identical")

            elif stage_only_item_path.is_dir():
                if self.is_forbidden_dir(stage_only_item_path):
                    self.progress(f"skipping forbidden folder {stage_only_item_path}")
                    continue
                # check that all items under a new folder pass the forbidden file/folder rule
                for root, dirs, files in os.walk(stage_only_item_path, followlinks=False):
                    for item in sorted(files):
                        self.raise_if_forbidden_file(item)
                    for item in sorted(dirs):
                        self.raise_if_forbidden_dir(item)

                self.batch_accum += CopyDirToDir(stage_only_item_path, comparator.right, hard_links=False, ignore_patterns=[".svn"], preserve_dest_files=False)
                self.batch_accum += SVNAdd(svn_item_path)
            else:
                raise InstlException(stage_only_item_path+" not a file, dir or symlink, an abomination!")

        # copy changed items:

        do_not_copy_items = list()
        # items that should not be copied even if different.
        # There are items that are part of .wtar where
        # each part might be different but the contents are not.
        # E.g. when re-wtaring files where only modification date has changed.
        for diff_item in sorted(comparator.diff_files):
            copy_file = diff_item not in do_not_copy_items
            left_item_path = Path(comparator.left, diff_item)
            svn_item_path = Path(comparator.right, diff_item)
            if left_item_path.is_symlink():
                raise InstlException(left_item_path+" is a symlink which should not be committed to svn, run instl fix-symlinks and try again")
            elif left_item_path.is_file():
                self.raise_if_forbidden_file(left_item_path)

                if utils.is_first_wtar_file(diff_item):
                    stage_file_checksum = utils.get_wtar_total_checksum(left_item_path)
                    _checksum = utils.get_wtar_total_checksum(svn_item_path)
                    if stage_file_checksum == _checksum:
                        copy_file = False
                        split_wtar_files = utils.find_split_files(left_item_path)
                        do_not_copy_items.extend([split_wtar_file.name for split_wtar_file in split_wtar_files])

                if copy_file:
                    self.batch_accum += CopyFileToDir(left_item_path, comparator.right, hard_links=False, ignore_patterns=[".svn"])
                else:
                    self.batch_accum += Progress(f"identical {left_item_path}")
            else:
                raise InstlException(left_item_path+" not a different file or symlink, an abomination!")

        # removed items:
        for stage_only_item in sorted(comparator.right_only):
            if stage_only_item not in do_not_remove_items:
                item_to_remove = os.path.join(comparator.right, stage_only_item)
                self.batch_accum += SVNRemove(item_to_remove)

        # recurse to sub folders
        for sub_comparator in list(comparator.subdirs.values()):
            self.stage2svn_with_comparator(sub_comparator)

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

    def do_svn2stage(self):
        self.batch_accum.set_current_section('admin')
        self.get_default_out_file()
        stage_folder = config_vars["STAGING_FOLDER"].Path()
        svn_folder = config_vars["SVN_CHECKOUT_FOLDER"].Path()
        checkout_url = config_vars["SVN_REPO_URL"].str()

        # --limit command line option might have been specified
        limit_info_list = []
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                limit_info_list.append((limit, svn_folder.joinpath(limit), stage_folder.joinpath(limit)))
        else:
            limit_info_list.append(("", svn_folder, stage_folder))

        if svn_folder.is_dir():
            with self.batch_accum.sub_accum(Cd(svn_folder)) as suba:
                suba += SVNCleanup()

        for limit_info in limit_info_list:
            limit_checkout_url = checkout_url
            if limit_info[0] != "":
                limit_checkout_url += "/" + limit_info[0]
            self.batch_accum += SVNCheckout(url=limit_checkout_url, working_copy_path=limit_info[1], depth="infinity")
            self.batch_accum += CopyDirContentsToDir(limit_info[1], limit_info[2], hard_links=False, ignore_patterns=[".svn", ".DS_Store"], delete_extraneous_files=True)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def do_verify_index(self):
        self.read_yaml_file(config_vars["__MAIN_INPUT_FILE__"].Path())
        self.info_map_table.read_from_file(config_vars["FULL_INFO_MAP_FILE_PATH"].Path(), disable_indexes_during_read=True)
        self.verify_actions()
        self.verify_index_to_repo()

    def do_depend(self):
        from . import installItemGraph

        self.read_yaml_file(os.fspath(config_vars["__MAIN_INPUT_FILE__"]))
        self.items_table.activate_all_oses()
        self.items_table.resolve_inheritance()
        depend_result = defaultdict(dict)
        graph = installItemGraph.create_dependencies_graph(self.items_table)
        all_iids = self.items_table.get_all_iids()
        cache_for_needs = dict()
        for IID in all_iids:
            depend_result[IID]['depends'] = self.needs(IID, set(all_iids), cache_for_needs)
            if not depend_result[IID]['depends']:
                depend_result[IID]['depends'] = None   # so '~' is displayed instead of []

            depend_result[IID]['needed_by'] = self.needed_by(IID, graph)
            if not depend_result[IID]['needed_by']:
                depend_result[IID]['needed_by'] = None # so '~' is displayed instead of []

        out_file_path = config_vars.get("__MAIN_OUT_FILE__", None).Path()
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            aYaml.writeAsYaml(aYaml.YamlDumpWrap(depend_result, sort_mappings=True), out_file)
        self.progress("dependencies written to", out_file_path)

    def do_verify_repo(self):
        self.read_yaml_file(config_vars["STAGING_FOLDER_INDEX"].str())

        the_folder = config_vars["STAGING_FOLDER"].str()
        self.info_map_table.initialize_from_folder(the_folder, progress_callback=self.progress)
        self.items_table.activate_all_oses()
        problem_messages_by_iid = defaultdict(list)
        self.verify_inheritance(problem_messages_by_iid)  # must be done before resolve_inheritance
        self.verify_dependencies(problem_messages_by_iid) # must be done before resolve_inheritance
        if problem_messages_by_iid:
            self.print_problem_messages(problem_messages_by_iid)
            self.progress(" >>> cannot continue checking - THESE ISSUES MUST BE FIXED <<<")
            raise AssertionError(f"Found {len(problem_messages_by_iid)} missing inherit/depends")
        else:
            self.items_table.resolve_inheritance()
            self.verify_actions(problem_messages_by_iid)
            self.verify_index_to_repo(problem_messages_by_iid)

    def verify_inheritance(self, problem_messages_by_iid):
        # check inherit
        self.progress("checking inheritance")
        missing_inheritees = self.items_table.get_missing_iids_from_details("inherit")
        for missing_inheritee in missing_inheritees:
            err_message = f"inherits from non existing '{missing_inheritee[1]}'"
            problem_messages_by_iid[missing_inheritee[0]].append(err_message)

    def verify_dependencies(self, problem_messages_by_iid):
        # check depends
        self.progress("checking dependencies")
        missing_dependees = self.items_table.get_missing_iids_from_details("depends")
        for missing_dependee in missing_dependees:
            err_message = f"depends on non existing '{missing_dependee[1]}'"
            problem_messages_by_iid[missing_dependee[0]].append(err_message)

    def print_problem_messages(self, problem_messages_by_iid):
        if problem_messages_by_iid:
            for iid in sorted(problem_messages_by_iid):
                self.progress(iid + ":")
                for problem_message in sorted(problem_messages_by_iid[iid]):
                    self.progress("   ", problem_message)
        else:
            self.progress(f"No problems found")

    def verify_index_to_repo(self, problem_messages_by_iid=None):
        """ helper function for verify-repo and verify-index commands
            Assuming the index and info-map have already been read
            check the expect files from the index appear in the info-map
        """

        no_target_folder_ok = config_vars.get("NO_TARGET_FOLDER_OK", []).list()
        common_name_ok = config_vars.get("COMMON_NAME_OK", []).list()
        no_files_or_folders_ok = config_vars.get("NO_FILES_OR_FOLDERS_OK", []).list()

        all_iids = sorted(self.items_table.get_all_iids())
        self.total_self_progress += len(all_iids)
        self.items_table.change_status_of_all_iids(1)

        if problem_messages_by_iid is None:
            problem_messages_by_iid = defaultdict(list)

        names_to_iids = defaultdict(list)
        for iid in all_iids:
            self.progress("checking sources for", iid)

            name = self.items_table.get_details_for_active_iids("name", unique_values=True, limit_to_iids=[iid])
            if name:
                names_to_iids[name[0]].append(iid)

            # check sources
            source_and_tag_list = self.items_table.get_details_and_tag_for_active_iids("install_sources", unique_values=True, limit_to_iids=(iid,))
            for source in source_and_tag_list:
                iid, source_path, source_type = source[0], source[1], source[2]
                num_files_for_source = self.info_map_table.mark_required_for_source(source_path, source_type)
                if num_files_for_source == 0:
                    case_insensitive_items = self.info_map_table.get_any_item_recursive(source_path, case_sensitive=False)
                    if iid not in no_files_or_folders_ok:
                        err_message = f"""source, '{source_path}' required by {iid}, does not have any files or folders"""
                        if case_insensitive_items:
                            err_message += f"""\nthere are some files/folders with similar name but different case:\n{[s.path for s in case_insensitive_items]}"""
                        problem_messages_by_iid[iid].append(err_message)

            # check previous sources
            previous_sources = self.items_table.get_details_and_tag_for_active_iids("previous_sources", unique_values=True)
            for previous_source in previous_sources:
                iid, previous_source_path, source_type = previous_source[0], previous_source[1], previous_source[2]
                if not previous_source_path:
                    err_message = f"previous source for {iid} is empty"
                    problem_messages_by_iid[iid].append(err_message)
                if source_type not in ("!dir", "!file"):
                    err_message = f"previous source for {iid} has type {source_type}, should be !file or !dir"
                    problem_messages_by_iid[iid].append(err_message)

            # check targets
            if len(source_and_tag_list) > 0:
                target_folders = set(self.items_table.get_resolved_details_value_for_active_iid(iid, "install_folders", unique_values=True))
                if len(target_folders) == 0 and iid not in no_target_folder_ok:
                    err_message = f"iid {iid}, does not have target folder"
                    problem_messages_by_iid[iid].append(err_message)

        for name, iids in names_to_iids.items():
            if len(iids) > 1:
                err_message = f"name '{name}', is common to {len(iids)} iids: {iids}"
                for iid in iids:
                    if iid not in common_name_ok:
                        problem_messages_by_iid[iid].append(err_message)

        self.progress("checking for cyclic dependencies")
        self.info_map_table.mark_required_completion()
        self.find_cycles()

        self.print_problem_messages(problem_messages_by_iid)

        self.progress("index:", len(all_iids), "iids")
        num_files = self.info_map_table.num_items("all-files")
        num_dirs = self.info_map_table.num_items("all-dirs")
        num_required_files = self.info_map_table.num_items("required-files")
        num_required_dirs = self.info_map_table.num_items("required-dirs")
        self.progress("info map:", num_files, "files in", num_dirs, "folders")
        self.progress("info map:", num_required_files, "required files, ", num_required_dirs, "required folders")

        unrequired_files = self.info_map_table.get_unrequired_items(what="file")
        self.progress("unrequired files:")
        [self.progress("    ", f.path) for f in unrequired_files]
        unrequired_dirs = self.info_map_table.get_unrequired_items(what="dir")
        self.progress("unrequired dirs:")
        [self.progress("    ", d.path) for d in unrequired_dirs]

    def should_file_be_exec(self, file_path):
        retVal = self.compiled_should_be_exec_regex.search(file_path)
        return retVal is not None

    def should_be_exec(self, item):
        retVal = item.isFile() and self.should_file_be_exec(item.path)
        return retVal

    def prepare_list_of_dirs_to_work_on(self, top_folder: Path):
        """ Some command can operate on a subset of folders inside the main folder.
            If __LIMIT_COMMAND_TO__ is defined join top_folder to each item in __LIMIT_COMMAND_TO__.
            otherwise return top_folder.
        """
        retVal = list()
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                retVal.append(top_folder.joinpath(limit))
        else:
            retVal.append(top_folder)
        return retVal

    def do_fix_perm(self):
        self.batch_accum.set_current_section('admin')
        should_be_exec_regex_list = list(config_vars["EXEC_PROP_REGEX"])
        self.compiled_should_be_exec_regex = utils.compile_regex_list_ORed(should_be_exec_regex_list)

        files_that_should_not_be_exec = list()
        files_that_must_be_exec = list()

        stage_folder = config_vars["STAGING_FOLDER"].Path()
        folders_to_check = self.prepare_list_of_dirs_to_work_on(stage_folder)
        for folder_to_check in folders_to_check:
            self.batch_accum += Unlock(folder_to_check, recursive=True)
            for root, dirs, files in os.walk(folder_to_check, followlinks=False):
                for a_file in files:
                    item_path = os.path.join(root, a_file)
                    if self.compiled_forbidden_file_regex.search(os.fspath(item_path)):
                        # removing forbidden files should be done by addin RmFile to self.batch_accum, thus:
                        # self.batch_accum += RmFile(item_path)
                        # however MacOS Icon files have \r characters which ii failed to print properly
                        # to the batch file. Therefor they are deleted immediately here:
                        os.unlink(item_path)
                    else:
                        file_is_exec = self.is_file_exec(item_path)
                        file_should_be_exec = self.should_file_be_exec(item_path)
                        if file_is_exec != file_should_be_exec:
                            if file_should_be_exec:
                                self.batch_accum += Chmod(item_path, "a+x")
                                files_that_must_be_exec.append(item_path)
                            else:
                                self.batch_accum += Chmod(item_path, "a-x")
                                files_that_should_not_be_exec.append(item_path)

            self.batch_accum += Chmod(folder_to_check, mode="a+rw,+X", recursive=True)  # "-R a+rw,+X"

        if len(files_that_should_not_be_exec) > 0:
            self.progress(f"Exec bit will be removed from the {len(files_that_should_not_be_exec)} following files")
            for a_file in files_that_should_not_be_exec:
                self.progress("   ", a_file)

        if len(files_that_must_be_exec) > 0:
            self.progress(f"Exec bit will be added to the {len(files_that_must_be_exec)} following files")
            for a_file in files_that_must_be_exec:
                self.progress("   ", a_file)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def do_file_sizes(self):
        out_file_path = config_vars.get("__MAIN_OUT_FILE__", None).Path()
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            what_to_scan = config_vars["__MAIN_INPUT_FILE__"].Path()
            if what_to_scan.is_file():
                file_size = what_to_scan.stat().st_size
                print(f"{what_to_scan}, {file_size}", file=out_file)
            else:
                if not self.compiled_forbidden_folder_regex.search(os.fspath(what_to_scan)):
                    for root, dirs, files in utils.excluded_walk(what_to_scan, file_exclude_regex=self.compiled_forbidden_file_regex, dir_exclude_regex=self.compiled_forbidden_folder_regex, followlinks=False):
                        for a_file in files:
                            full_path = Path(root, a_file)
                            file_size = full_path.stat().st_size
                            partial_path = full_path.relative_to(what_to_scan)
                            print(f"{partial_path}, {file_size}", file=out_file)

    def do_read_info_map(self):
        files_to_read = list(config_vars["__MAIN_INPUT_FILE__"])
        with self.info_map_table.reading_files_context():
            for f2r in files_to_read:
                self.info_map_table.read_from_file(f2r, progress_callback=self.progress)

    def do_check_instl_folder_integrity(self):
        instl_folder_path = config_vars["__MAIN_INPUT_FILE__"].Path()
        index_path = instl_folder_path.joinpath("index.yaml")
        self.read_yaml_file(index_path)
        main_info_map_path = instl_folder_path.joinpath("info_map.txt")
        self.info_map_table.read_from_file(main_info_map_path)
        instl_folder_path_parts = os.path.normpath(instl_folder_path).split(os.path.sep)
        revision_folder_name = instl_folder_path_parts[-2]
        revision_file_path = instl_folder_path.joinpath("V9_repo_rev.yaml."+revision_folder_name)
        if not revision_file_path.is_file():
            self.progress("file not found", revision_file_path)
        self.read_yaml_file(revision_file_path)
        index_checksum = utils.get_file_checksum(index_path)
        if config_vars["INDEX_CHECKSUM"].str() != index_checksum:
            self.progress(f"""bad index checksum expected: {config_vars["INDEX_CHECKSUM"]}, actual: {index_checksum}""")

        main_info_map_checksum = utils.get_file_checksum(main_info_map_path)
        if config_vars["INFO_MAP_CHECKSUM"].str() != main_info_map_checksum:
            self.progress(f"""bad info_map.txt checksum expected: {config_vars["INFO_MAP_CHECKSUM"]}, actual: {main_info_map_checksum}""")

        self.items_table.activate_all_oses()
        all_info_maps = self.items_table.get_detail_values_by_name_for_all_iids("info_map")
        all_instl_folder_items = self.info_map_table.get_file_items_of_dir('instl')
        for item in all_instl_folder_items:
            if item.leaf in all_info_maps:
                info_map_full_path = instl_folder_path.joinpath(item.leaf)
                info_map_checksum = utils.get_file_checksum(info_map_full_path)
                if item.checksum != info_map_checksum:
                    self.progress(f"""bad {item.leaf} checksum expected: {item.checksum}, actual: {info_map_checksum}""")

    def do_translate_guids(self):

        input_path = config_vars["__MAIN_INPUT_FILE__"].Path()
        files_to_translate_path = list()
        if input_path.is_dir():
            for root, dirs, files in os.walk(input_path):
                for f in files:
                    if not f.startswith("."):
                        files_to_translate_path.append(Path(root, f))
                    else:
                        print(f"{f} is hidden")
        else:
            files_to_translate_path.append(input_path)

        for f in files_to_translate_path:
            a_temp_file = f.parent.joinpath(f.name+".tmp")
            try:
                num_translated_guids = self.translate_guids_in_file(f, a_temp_file)
                if num_translated_guids > 0:
                    modificatio_times = f.stat().st_atime_ns, f.stat().st_mtime_ns
                    os.rename(a_temp_file, f)
                    # restore modification time so files will keep relative modification time, so we can know when the file was created
                    os.utime(f, ns=modificatio_times)
                self.progress(f"""{f}: {num_translated_guids} guids translated""")
            except Exception as ex:
                pass
            finally:
                try: os.unlink(a_temp_file)
                except: pass

    def translate_guids_in_file(self, in_file, out_file):
        num_translated_guids = 0
        guid_to_iid = dict((guid.lower(), iid) for iid, guid in self.items_table.get_all_iids_with_guids())
        guid_re = re.compile("""
                (?P<guid>[a-fA-F0-9]{8}
                (-[a-fA-F0-9]{4}){3}
                -[a-fA-F0-9]{12})
                """, re.VERBOSE)

        with utils.utf8_open_for_read(in_file, "r") as rfd:
            with utils.utf8_open_for_write(out_file, "w") as wfd:
                for line in rfd.readlines():
                    match = guid_re.search(line)
                    if match:
                        the_iid = guid_to_iid.get(match.group("guid").lower(), "?")
                        if the_iid not in line:  # if not already translated
                            new_line = line.replace(match.group("guid"), f'{match.group("guid")}  # {the_iid}')
                            wfd.write(new_line)
                            num_translated_guids += 1
                    else:
                        wfd.write(line)
        return num_translated_guids

    def do_up2s3(self):
        repo_rev = int(config_vars['TARGET_REPO_REV'])
        self.up2s3_repo_rev(repo_rev, self.batch_accum)

    def do_up_short_index(self):
        repo_rev = int(config_vars['TARGET_REPO_REV'])
        self.up_short_index_repo_rev(repo_rev, self.batch_accum)

    def up_short_index_repo_rev(self, repo_rev, batch_accum):
        assert repo_rev >= int(config_vars['BASE_REPO_REV']), f"repo-rev({repo_rev}) < BASE_REPO_REV({int(config_vars['BASE_REPO_REV'])})"
        assert repo_rev >= int(config_vars['IGNORE_BELOW_REPO_REV']), f"repo-rev({repo_rev}) < IGNORE_BELOW_REPO_REV({int(config_vars['IGNORE_BELOW_REPO_REV'])})"
        assert repo_rev not in list(map(int, list(config_vars.get('IGNORE_SPECIFIC_REPO_REV', [])))), f"repo-rev({repo_rev}) is in IGNORE_SPECIFIC_REPO_REV"

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)
        try:

            config_vars['UP_SHORT_INDEX_STATUS'] = "FAILED"
            config_vars['UP_SHORT_INDEX_EXCEPTION'] = ""
            config_vars["REPO_REV"] = str(repo_rev)
            config_vars["__CURR_REPO_REV__"] = str(repo_rev)
            config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.info_map_table.repo_rev_to_folder_hierarchy(repo_rev)  # e.g. 345 -> 03/45

            revision_folder_path = Path(config_vars["UPLOAD_REVISION_FOLDER"])
            if not revision_folder_path.is_dir():
                raise FileNotFoundError(f"revision folder does not exist {revision_folder_path}")

            revision_instl_index_path = Path(config_vars["UPLOAD_REVISION_INDEX_FILE"])
            checkout_folder_short_index_path = Path(config_vars["UPLOAD_REVISION_SHORT_INDEX_FILE"])

            batch_accum.set_current_section('admin')
            # checkout specific repo-rev to base folder
            # full checkout might take a long time so checking out to base folder, if done in repo-rev order
            # will only get the files of that repo-rev instead of the whole repository

            skip_some_actions = False  # to save time during debugging

            batch_accum += IndexYamlReader(revision_instl_index_path)
            batch_accum += ShortIndexYamlCreator(checkout_folder_short_index_path)
            base_rev = int(config_vars["BASE_REPO_REV"])
            if base_rev > 0:
                batch_accum += SetBaseRevision(base_rev)
            batch_accum += CreateRepoRevFile()

            if not skip_some_actions:
                with batch_accum.sub_accum(Cd(revision_folder_path)) as sub_accum:
                    sub_accum += Subprocess("aws", "s3", "cp", os.fspath(checkout_folder_short_index_path), "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/"+checkout_folder_short_index_path.name, "--content-type", 'text/plain')
                    repo_rev_file_path = config_vars["UPLOAD_REVISION_REPO_REV_FILE"].Path()
                    sub_accum += Subprocess("aws", "s3", "cp", os.fspath(repo_rev_file_path), "s3://$(S3_BUCKET_NAME)/admin/"+repo_rev_file_path.name, "--content-type", 'text/plain')
                    sub_accum += Subprocess("aws", "s3", "cp", os.fspath(repo_rev_file_path), "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/"+repo_rev_file_path.name, "--content-type", 'text/plain')

            self.write_batch_file(batch_accum)
            if bool(config_vars["__RUN_BATCH__"]):
                self.run_batch_file()

            r.hset(config_vars["UPLOAD_SHORT_INDEX_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["UPLOAD_SHORT_INDEX_LAST_UPLOADED_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            config_vars['UP_SHORT_INDEX_STATUS'] = "Completed"
        except Exception as ex:
            config_vars['UP_SHORT_INDEX_EXCEPTION'] = f"{ex}"
            print(f"up_short_index_repo_rev exception {ex}")
            raise
        finally:
            self.send_email_from_template_file(config_vars["SHORT_INDEX_EMAIL_TEMPLATE_PATH"].Path())

    def up2s3_repo_rev(self, repo_rev, batch_accum):
        assert repo_rev >= int(config_vars['BASE_REPO_REV']), f"repo-rev({repo_rev}) < BASE_REPO_REV({int(config_vars['BASE_REPO_REV'])})"
        assert repo_rev >= int(config_vars['IGNORE_BELOW_REPO_REV']), f"repo-rev({repo_rev}) < IGNORE_BELOW_REPO_REV({int(config_vars['IGNORE_BELOW_REPO_REV'])})"
        assert repo_rev not in list(map(int, list(config_vars.get('IGNORE_SPECIFIC_REPO_REV', [])))), f"repo-rev({repo_rev}) is in IGNORE_SPECIFIC_REPO_REV"

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)
        try:

            config_vars['UP2S3_STATUS'] = "FAILED"
            config_vars['UP2S3_EXCEPTION'] = ""
            config_vars["REPO_REV"] = str(repo_rev)
            config_vars["__CURR_REPO_REV__"] = str(repo_rev)
            config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.info_map_table.repo_rev_to_folder_hierarchy(repo_rev)  # e.g. 345 -> 03/45

            checkout_url = str(config_vars['SVN_REPO_URL'])
            checkout_base_folder = Path(config_vars['UPLOAD_BASE_CHECKOUT_FOLDER'])
            checkout_folder_instl_folder_path = checkout_base_folder.joinpath("instl")
            checkout_folder_index_path = checkout_folder_instl_folder_path.joinpath("index.yaml")

            revision_folder_path = Path(config_vars["UPLOAD_REVISION_FOLDER"])
            revision_instl_folder_path = Path(config_vars["UPLOAD_REVISION_INSTL_FOLDER"])
            revision_instl_index_path = Path(config_vars["UPLOAD_REVISION_INDEX_FILE"])

            checkout_folder_short_index_path = revision_instl_folder_path.joinpath("short-index.yaml")
            info_map_info_path = revision_instl_folder_path.joinpath("info_map.info")
            info_map_props_path = revision_instl_folder_path.joinpath("info_map.props")
            info_map_file_sizes_path = revision_instl_folder_path.joinpath("info_map.file-sizes")
            full_info_map_file_path = revision_instl_folder_path.joinpath(str(config_vars['FULL_INFO_MAP_FILE_NAME']))

            batch_accum.set_current_section('admin')
            # checkout specific repo-rev to base folder
            # full checkout might take a long time so checking out to base folder, if done in repo-rev order
            # will only get the files of that repo-rev instead of the whole repository

            skip_some_actions = False  # to save time during debugging

            if checkout_base_folder.is_dir():   # check if folder is indeed svn checkout folder
                if checkout_base_folder.joinpath(".svn").is_dir():
                    batch_accum += SVNCleanup(working_copy_path=checkout_base_folder, skip_action=skip_some_actions, stderr_means_err=False)
                else:
                    shutil.rmtree(checkout_base_folder)

            batch_accum += SVNCheckout(url=checkout_url, working_copy_path=checkout_base_folder, repo_rev=repo_rev, skip_action=skip_some_actions, stderr_means_err=False)

            batch_accum += MakeDir(revision_folder_path)  # create specific repo-rev folder
            batch_accum += MakeDir(revision_instl_folder_path)  # create specific repo-rev instl folder
            with batch_accum.sub_accum(Cd(checkout_base_folder)) as sub_accum:
                sub_accum += SVNInfo(url=".", out_file=info_map_info_path, skip_action=skip_some_actions, stderr_means_err=False)
                sub_accum += SVNPropList(url=".", out_file=info_map_props_path, skip_action=skip_some_actions, stderr_means_err=False)
                sub_accum += FileSizes(folder_to_scan=checkout_base_folder, out_file=info_map_file_sizes_path, skip_action=skip_some_actions)

            batch_accum += IndexYamlReader(checkout_folder_index_path)
            batch_accum += SVNInfoReader(info_map_info_path, format='info', disable_indexes_during_read=True)
            batch_accum += SVNInfoReader(info_map_props_path, format='props')
            batch_accum += SVNInfoReader(info_map_file_sizes_path, format='file-sizes')
            base_rev = int(config_vars["BASE_REPO_REV"])
            if base_rev > 0:
                batch_accum += SetBaseRevision(base_rev)

            # copy all (and only) the files from repo-rev
            batch_accum += CopySpecificRepoRev(checkout_base_folder, revision_folder_path, repo_rev, skip_action=skip_some_actions)
            # also copy the whole instl folder
            batch_accum += CopyDirToDir(checkout_folder_instl_folder_path, revision_folder_path, delete_extraneous_files=False)

            batch_accum += InfoMapFullWriter(full_info_map_file_path, in_format='text')
            batch_accum += InfoMapSplitWriter(revision_instl_folder_path, in_format='text')
            batch_accum += Wzip(revision_instl_index_path)
            batch_accum += ShortIndexYamlCreator(checkout_folder_short_index_path)
            batch_accum += CreateRepoRevFile()

            with batch_accum.sub_accum(Cd(revision_folder_path)) as sub_accum:
                sub_accum += Subprocess("aws", "s3", "sync", os.curdir, "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)", "--exclude", "*.DS_Store")
                repo_rev_file_path = config_vars["UPLOAD_REVISION_REPO_REV_FILE"].Path()
                sub_accum += Subprocess("aws", "s3", "cp", os.fspath(repo_rev_file_path), "s3://$(S3_BUCKET_NAME)/admin/"+repo_rev_file_path.name, "--content-type", 'text/plain')
            batch_accum += RmDirContents(revision_folder_path, exclude=['instl'])

            self.write_batch_file(batch_accum)
            if bool(config_vars["__RUN_BATCH__"]):
                self.run_batch_file()

            r.hset(config_vars["UPLOAD_REPO_REV_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["UPLOAD_REPO_REV_LAST_UPLOADED_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            r.hset(config_vars["UPLOAD_SHORT_INDEX_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["UPLOAD_SHORT_INDEX_LAST_UPLOADED_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            config_vars['UP2S3_STATUS'] = "Completed"
        except Exception as ex:
            config_vars['UP2S3_EXCEPTION'] = f"{ex}"
            print(f"up2s3_repo_rev exception {ex}")
            raise
        finally:
            self.send_email_from_template_file(config_vars["UP2S3_EMAIL_TEMPLATE_PATH"].Path())

    def report_instl_info_to_redis(self, redis_instance):
        instl_info_redis_key = config_vars.get("INSTL_INFO_REDIS_KEY", None).str()
        if instl_info_redis_key:
            instl_info_dict = dict()
            instl_info_dict["version"] = self.get_version_str(short=True)
            instl_info_dict["version string"] = self.get_version_str(short=False)
            instl_info_dict["path"] = config_vars["__INSTL_EXE_PATH__"].str()
            instl_info_dict["python version"] = config_vars["__PYTHON_VERSION__"].str()
            instl_info_dict["current os"] = config_vars["__CURRENT_OS__"].str()
            redis_instance.hmset(instl_info_redis_key, instl_info_dict)

    def print_wait_on_action_trigger_info(self, _redis_host, _redis_port, _waiting_list_redis_key):
        if self.wait_info_counter == 0:
            log.info(f"{self.get_version_str(short=False)}")
            log.info(f"wait on redis list: {_redis_host}:{_redis_port} {_waiting_list_redis_key}")
            log.info(f"to upload: lpush {_waiting_list_redis_key} upload:domain:version:repo-rev (e.g. upload:test:V10:333)")
            log.info(f"to create and upload only short index: lpush {_waiting_list_redis_key} short-index:domain:version:repo-rev (e.g. short-index:test:V12:17)")
            log.info(f"to activate: lpush {_waiting_list_redis_key} activate:domain:version:repo-rev (e.g. activate:test:V10:333)")

            log.info(f"special values: lpush {_waiting_list_redis_key} stop|ping|reload-config-files")

        self.wait_info_counter += 1
        self.wait_info_counter = self.wait_info_counter % 30

    def do_wait_on_action_trigger(self):

        sys.path.append(os.pardir)
        sys.path.append(f"{os.pardir}/{os.pardir}")
        from .instl_main import instl_own_main

        # config yaml such as stout-config.yaml with definitions needed for this function to work
        main_input_file = Path(config_vars["__CONFIG_FILE__"][0]).resolve()
        # other config files are assumed to exist below the folder where main_input_file is found
        main_config_folder = main_input_file.parent

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        waiting_list_redis_key = config_vars['WAITING_LIST_REDIS_KEY'].str()

        # heartbeat_redis_key: regular time stamps will be send to this key
        heartbeat_redis_key = config_vars.get("HEARTBEAT_COUNTER_REDIS_KEY", None).str()
        if heartbeat_redis_key:
            start_redis_heartbeat_thread(redis_host, redis_port, heartbeat_redis_key, 2.0)

        r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)
        self.report_instl_info_to_redis(r)
        trigger_keys_to_wait_on = (waiting_list_redis_key,)
        while True:
            self.print_wait_on_action_trigger_info(redis_host, redis_port, waiting_list_redis_key)
            r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), "waiting...")
            poped = r.brpop(trigger_keys_to_wait_on, timeout=30)
            if poped is not None:
                key = str(poped[0])
                value = str(poped[1])
                r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), value)

                log.info(f"popped key: {key}, value: {value}")
                if value == "stop":
                    log.info(f"received stop")
                    break
                elif value == "ping":
                    ping_redis_key = f"{key}:ping"
                    r.incr(ping_redis_key, 1)
                    log.info(f"ping incremented {ping_redis_key}")
                elif value == "reload-config-files":
                    log.info(f"reloading config files {config_vars['__CONFIG_FILE__'].list()}")
                    self.read_config_files(reset_previous=True)
                else:
                    with config_vars.push_scope_context(use_cache=True):
                        try:
                            what_to_do, domain, major_version, repo_rev = value.split(":")
                            instl_command_name = {'upload': "up2s3", 'up2s3': "up2s3", 'activate': "activate-repo-rev", "short-index": "up-short-index" }[what_to_do.lower()]
                            config_vars["TARGET_DOMAIN"] = domain
                            config_vars["TARGET_MAJOR_VERSION"] = major_version
                            config_vars["TARGET_REPO_REV"] = repo_rev
                            log.info(f"{key} triggered domain: {domain} major_version: {major_version} repo-rev {repo_rev}")
                            config_vars["TARGET_WORK_FOLDER"] = self.get_work_folder()

                            domain_major_version_config_folder = main_config_folder.joinpath(domain, major_version)
                            domain_major_version_config_file = domain_major_version_config_folder.joinpath("config.yaml")
                            up2s3_yaml_dict = {
                                "__include__": [os.fspath(domain_major_version_config_file),
                                                os.fspath(main_input_file)],
                                'TARGET_DOMAIN': domain,
                                'TARGET_MAJOR_VERSION': major_version,
                                'TARGET_REPO_REV': repo_rev,
                                'TARGET_WORK_FOLDER': config_vars["TARGET_WORK_FOLDER"].str(),
                            }
                            define_dict = aYaml.YamlDumpDocWrap(up2s3_yaml_dict,
                                                                '!define', "definitions",
                                                                explicit_start=True, sort_mappings=False)

                            work_config_file = config_vars["TARGET_WORK_FOLDER"].Path().joinpath(f"{instl_command_name}_{domain}_{major_version}_{repo_rev}.yaml")
                            with utils.utf8_open_for_write(work_config_file, "w") as wfd:
                                aYaml.writeAsYaml(define_dict, wfd)

                            work_log_file = config_vars["TARGET_WORK_FOLDER"].Path().joinpath(f"{instl_command_name}_{domain}_{major_version}_{repo_rev}.log")
                            log_files = config_vars.get("OPEN_LOG_FILES", []).list()
                            log_files.append(work_log_file)
                            log_files = [os.fspath(log_file) for log_file in log_files]
                            mp_context = mp.get_context("spawn")
                            up2s3_process = mp_context.Process (target=instl_own_main,
                                                        name=f"{instl_command_name}_{domain}_{major_version}_{repo_rev}",
                                                        args=([str(config_vars["__INSTL_EXE_PATH__"]),
                                                              instl_command_name,
                                                               "--config-file", os.fspath(work_config_file),
                                                               "--log", *log_files,
                                                               "--db", ":file:",    # let instl will decide where the db file is placed
                                                               "--run"],))

                            up2s3_process.start()
                            up2s3_process.join()

                        except Exception as ex:
                            log.info(f"Exception {ex} while handling {key} {value}")

            r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), "waiting...")
            time.sleep(2)
        log.info(f"stopped waiting on {trigger_keys_to_wait_on}")
        r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), "stopped")

    def do_activate_repo_rev(self):

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port
        r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)

        try:

            config_vars['ACTIVATE_STATUS'] = "FAILED"
            config_vars['ACTIVATE_EXCEPTION'] = ""

            s3_resource = boto3.resource('s3')
            bucket_name = str(config_vars["S3_BUCKET_NAME"])
            repo_rev_file_specific_name = str(config_vars["REPO_REV_FILE_SPECIFIC_NAME"])  # file name for a specific repo-rev file e.g. V9_repo_rev.yaml.236
            repo_rev_file_specific_key = f"admin/{repo_rev_file_specific_name}"

            repo_rev_file_activated_name = str(config_vars["REPO_REV_FILE_BASE_NAME"])  # file name for activated repo-rev file e.g. V9_repo_rev.yaml
            repo_rev_file_activated_key = f"admin/{repo_rev_file_activated_name}"

            # find if the specific file exists in the admin folder of the bucket
            def is_file_in_s3(_s3_resource, _bucket_name, path_in_bucket):
                retVal = False
                try:
                    ls_response = _s3_resource.meta.client.list_objects_v2(Bucket=_bucket_name, Prefix=path_in_bucket)
                    list_of_files = ls_response['Contents']
                    for file in list_of_files:
                        if file["Key"] == path_in_bucket:
                            retVal = True
                            break
                except Exception:
                    pass
                return retVal

            if not is_file_in_s3(s3_resource, bucket_name, repo_rev_file_specific_key):
                raise FileNotFoundError(f"{repo_rev_file_specific_key} was not found in bucket {bucket_name}")

            # now copy the specific file to be the activated file, this is done directly on s3
            s3_resource.meta.client.copy({'Bucket': bucket_name, 'Key': repo_rev_file_specific_key},
                                         Bucket=bucket_name, Key=repo_rev_file_activated_key)
            log.info(f"activated repo-rev {config_vars['TARGET_REPO_REV']} for {config_vars['TARGET_MAJOR_VERSION']} on {config_vars['TARGET_DOMAIN']}")

            if not is_file_in_s3(s3_resource, bucket_name, repo_rev_file_activated_key):
                raise FileNotFoundError(f"{repo_rev_file_activated_key} was not found in bucket {bucket_name}")

            target_domain = config_vars["TARGET_DOMAIN"].str()
            major_version = config_vars["TARGET_MAJOR_VERSION"].str()
            target_repo_rev = config_vars["TARGET_REPO_REV"].int()
            work_folder = config_vars["TARGET_WORK_FOLDER"].Path()

            # download the activated file to the work folder for reference
            copy_of_activated_repo_rev_file_path = config_vars.resolve_str(f"{work_folder}/$(REPO_REV_FILE_BASE_NAME)")
            s3_resource.meta.client.download_file(Bucket=bucket_name, Key=repo_rev_file_activated_key, Filename=copy_of_activated_repo_rev_file_path)
            log.info(f"downloaded activated repo-rev file to {copy_of_activated_repo_rev_file_path}")
            with utils.utf8_open_for_read(copy_of_activated_repo_rev_file_path, "r") as rfd:
                repo_rev_file_text = rfd.read()
                match = re.search(r"^REPO_REV:\s+(?P<target_repo_rev>\d+)", repo_rev_file_text, flags=re.MULTILINE)
                if match:
                    actual_activated_repo_rev_from_s3 = int(match.group('target_repo_rev'))
                    if actual_activated_repo_rev_from_s3 == target_repo_rev:
                        log.info(f"verified activated repo-rev for {target_domain} {major_version} is {actual_activated_repo_rev_from_s3}")
                    else:
                        raise ValueError(f"activated repo-rev for {target_domain} {major_version} is {actual_activated_repo_rev_from_s3} not {target_repo_rev}")
                else:
                    raise ValueError(f"regex could find 'REPO_REV:' in {copy_of_activated_repo_rev_file_path}")

            r.hset(config_vars["ACTIVATE_REPO_REV_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["ACTIVATE_REPO_REV_CURRENT_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            config_vars['ACTIVATE_STATUS'] = "Completed"

        except Exception as ex:
            config_vars['ACTIVATE_EXCEPTION'] = f"{ex}"
            print(f"do_activate_repo_rev exception {ex}")
            raise
        finally:
            self.send_email_from_template_file(config_vars["ACTIVATE_REPO_REV_EMAIL_TEMPLATE_PATH"].Path())

    def get_work_folder(self):
        """ calculate the path of the work folder for specific repo_rev/major_version/domain
            create the folder
            assign the path to configVar
        """

        repo_rev_work_folder = self.info_map_table.repo_rev_to_folder_hierarchy(config_vars["TARGET_REPO_REV"])
        work_folder: Path = config_vars["UPLOAD_WORK_AREA"].Path().joinpath(config_vars["TARGET_DOMAIN"].str(), config_vars["TARGET_MAJOR_VERSION"].str(), repo_rev_work_folder)
        with MakeDir(work_folder, report_own_progress=False) as md:
            md()
        return work_folder

    def send_email_from_template_file(self, path_to_template):
        work_folder = config_vars["TARGET_WORK_FOLDER"].Path()
        path_to_resolved = work_folder.joinpath(path_to_template.name)
        try:
            ResolveConfigVarsInFile(path_to_template, path_to_resolved)()
            utils.send_email_from_template_file(path_to_resolved)
        except Exception as ex:
            with open(path_to_resolved, "a") as wfd:
                wfd.write(f"\nFailed to send email\n{traceback.format_exc()}")

    def do_short_index(self):
        config_vars['__SILENT__'] = True  # disable InstlClientReport from doing output since ShortIndexYamlCreator already does that
        in_file_path = config_vars["__MAIN_INPUT_FILE__"].Path()
        with IndexYamlReader(in_file_path, report_own_progress=False) as yaml_reader:
            yaml_reader()
        out_file_path = config_vars.get("__MAIN_OUT_FILE__", None).Path()
        with ShortIndexYamlCreator(out_file_path, report_own_progress=False) as short_creator:
            short_creator()

    def do_dump_config_vars(self):
        if "__MAIN_INPUT_FILE__" in config_vars:
            self.read_yaml_file(config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True))

        output_file = config_vars.get("__MAIN_OUT_FILE__", None).Path(resolve=True)
        with open(output_file, "w") as wfd:
            wfd.write("--- !define\n")
            for identifier in config_vars.keys():
                the_config_var = config_vars[identifier]
                if len(the_config_var) > 1:
                    wfd.write(f"{identifier}: [{', '.join(the_config_var.list())}]")
                else:
                    wfd.write(f"{identifier}: {the_config_var}")
                if the_config_var.raw() != the_config_var.str():
                    wfd.write(f"  # {the_config_var.raw()}")
                wfd.write("\n")

    def do_collect_manifests(self):
        @dataclass
        class ManifestItem:
            """ holds one IID collected from manifest.yaml files"""
            iid: str
            manifest_node: dict
            origin_path: Path
            top_level_tag: str = None  # Mac/Win/Common

        yaml_keys_order = config_vars["INDEX_YAML_CANONICAL_KEY_ORDER"].list()
        yaml_single_value_keys = config_vars["INDEX_YAML_SINGLE_VALUE_KEYS"].list()

        class ManifestYamlReader(ConfigVarYamlReader):
            """ overrides ConfigVarYamlReader to read manifest.yaml files
            """
            def __init__(self, config_vars):
                super().__init__(config_vars)
                self.manifest_nodes = defaultdict(list)

            def init_specific_doc_readers(self):
                ConfigVarYamlReader.init_specific_doc_readers(self)
                self.specific_doc_readers["__no_tag__"] = self.manifest_node_reader
                self.specific_doc_readers["__unknown_tag__"] = self.manifest_node_reader

            def manifest_node_reader(self, the_node, *args, **kwargs):
                for a_node_name, a_node_value in the_node.items():
                    yaml_node_as_dict = aYaml.nodeToPy(a_node_value, order=yaml_keys_order, single_value=yaml_single_value_keys, preserve_tags=True)
                    top_level_tag = kwargs.get("top_level_tag", None)
                    item = ManifestItem(a_node_name, yaml_node_as_dict, self.file_read_stack[-1], top_level_tag)
                    self.manifest_nodes[a_node_name].append(item)

        folders_to_search_for_manifests = [Path(f) for f in config_vars["COLLECT_MANIFESTS_DIR"].list()]
        reader = ManifestYamlReader(config_vars)
        num_files = 0
        for manifests_folder in folders_to_search_for_manifests:
            for top_level_dir in sorted(manifests_folder.glob("*")):
                if top_level_dir.is_dir() and not top_level_dir.name.startswith('.'):
                    top_level_tag = top_level_dir.name
                    for root, dirs, files in os.walk(top_level_dir, followlinks=False):
                        dirs.sort()  # to be idempotent, so folders will always be scanned in the same order
                        for a_file in sorted(files):
                            a_file_path = Path(root, a_file)
                            if a_file_path.name.endswith("manifest.yaml") and not a_file_path.name.startswith("."):
                                print(a_file_path)
                                reader.read_yaml_file(a_file_path, top_level_tag=top_level_tag)
                                num_files += 1
                # add manifest.yaml's if they are on the top level too
                # not sure is top_level_tag will be appropriate
                elif top_level_dir.is_file() and top_level_dir.name.endswith("manifest.yaml") and not top_level_dir.name.startswith("."):
                    top_level_tag = manifests_folder.name
                    print(top_level_dir)
                    reader.read_yaml_file(top_level_dir, top_level_tag=top_level_tag)
                    num_files += 1

        manifest_nodes = reader.manifest_nodes
        num_singles = 0
        num_duplicates = 0
        num_different = 0
        diffs_dict = dict()
        filtered_manifest_nodes = {key: value for key, value in manifest_nodes.items() if key.endswith("_IID")}

        for iid, content_list in filtered_manifest_nodes.items():
            if len(content_list) == 1:
                num_singles += 1
                content_list[0].top_level_tag = "Common"
            elif len(content_list) == 2:
                num_duplicates += 1
                the_diff = list(dictdiffer.diff(content_list[0].manifest_node, content_list[1].manifest_node, ignore=['top_level_tag']))
                if the_diff:
                    num_different += 1
                    # they are different so merge them
                    merged = smart_merge_dicts({content_list[0].top_level_tag: content_list[0].manifest_node,
                                       content_list[1].top_level_tag: content_list[1].manifest_node})
                    merged = dict_in_canonical_order(merged, order=yaml_keys_order, single_value=yaml_single_value_keys)

                    content_list[0].manifest_node = merged
                    content_list[0].top_level_tag = "Common"
                    print(f"unified {iid}")
                else:
                    # they are the same so take the first one
                    content_list[0].top_level_tag = "Common"
                del content_list[1]
            else:
                print(f"IID {iid} found in more than 2 files")
                for item in content_list:
                    print(f"    {item.origin_path}")
                filtered_manifest_nodes[iid].clear()

        print(f"scanned {num_files}, found {len(filtered_manifest_nodes)} distinct IIDs")
        print(f"{num_singles} singles, {num_duplicates} duplicates, {num_different} dup and different")

        all_manifests = {"Common": dict(), "Mac": dict(), "Win": dict()}
        for iid, content_list in filtered_manifest_nodes.items():
            for contents in content_list:
                all_manifests[contents.top_level_tag][iid] = contents.manifest_node

        collect_manifests_results_path = config_vars["COLLECT_MANIFESTS_RESULTS_PATH"].Path()

        if "__OUTPUT_FORMAT__" in config_vars:
            config_vars["COLLECT_MANIFESTS_FORMAT"] = "$(__OUTPUT_FORMAT__)"
        output_format = config_vars.get("COLLECT_MANIFESTS_FORMAT", "yaml").str()
        if "yaml" == output_format:
            self.write_collected_manifests_yaml(collect_manifests_results_path, all_manifests)
        elif "json" == output_format:
            self.write_collected_manifests_json(collect_manifests_results_path, all_manifests)

    def write_collected_manifests_yaml(self, out_manifests_file, all_manifests):
        with open(out_manifests_file, "w") as wfd:
            try:
                base_index_path = config_vars["COLLECT_MANIFESTS_BASE_INDEX"].Path()
                wfd.write(base_index_path.read_text())  # copy the index_base.yaml verbatim
            except:
                pass
            wfd.write("\n# below are IIDs collected from manifest.yaml files\n\n")
            if all_manifests["Common"]:
                aYaml.writeAsYaml(aYaml.YamlDumpDocWrap(all_manifests["Common"], tag="!index", sort_mappings=True),
                                  wfd, top_level_blank_line=True)
            if all_manifests["Mac"]:
                aYaml.writeAsYaml(aYaml.YamlDumpDocWrap(all_manifests["Mac"], tag="!index_Mac", sort_mappings=True),
                                  wfd,
                                  top_level_blank_line=True)
            if all_manifests["Win"]:
                aYaml.writeAsYaml(aYaml.YamlDumpDocWrap(all_manifests["Win"], tag="!index_Win", sort_mappings=True),
                                  wfd,
                                  top_level_blank_line=True)
        print(f"collected manifests written to: {out_manifests_file}")

    def write_collected_manifests_json(self, out_manifests_file, all_manifests):
        item_list = list()
        for section, mani_list in all_manifests.items():
            for iid, a_node in mani_list.items():
                item = {"IID": iid}
                if not a_node:
                    print(f"no node for iid {iid}")
                    continue
                if 'name' in a_node:
                    item['name'] = a_node['name']
                if 'version' in a_node:
                    item['version'] = a_node['version']
                if 'guid' in a_node:
                    item['guid'] = a_node['guid']
                item_list.append(item)
                if 'depends' in a_node:
                    depends = [{'IID': iid} for iid in a_node['depends']]
                    item['_children'] = depends

        with open(out_manifests_file, "w") as wfd:
            wfd.write(json.dumps(item_list, indent=1, default=utils.extra_json_serializer))
