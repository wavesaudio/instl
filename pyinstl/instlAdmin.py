#!/usr/bin/env python3.6

import logging
log = logging.getLogger()

import os
import sys
import filecmp
import multiprocessing as mp
import time
import datetime
import re
import redis
import boto3
import threading

import utils
import aYaml
from .instlInstanceBase import InstlInstanceBase
from pybatch import *
from .instlException import InstlException


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


# noinspection PyPep8,PyPep8,PyPep8
class InstlAdmin(InstlInstanceBase):

    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.total_self_progress = 1000
        self.read_defaults_file(super().__thisclass__.__name__)
        self.fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')

    def get_default_out_file(self) -> None:
        if "__CONFIG_FILE__" in config_vars and '__MAIN_OUT_FILE__' not in config_vars:
            config_vars["__MAIN_OUT_FILE__"] = "$(__CONFIG_FILE__[0])-$(__MAIN_COMMAND__).$(BATCH_EXT)"

    def set_default_variables(self):
        if "__CONFIG_FILE__" in config_vars:
            for config_file in config_vars["__CONFIG_FILE__"].list():
                config_file_resolved = self.path_searcher.find_file(os.fspath(config_file), return_original_if_not_found=True)
                config_vars.setdefault("__CONFIG_FILE_PATH__", default=None).append(config_file_resolved)

                self.read_yaml_file(config_file_resolved)
            self.resolve_defined_paths()

    def do_command(self):
        self.set_default_variables()
        #self.platform_helper.num_items_for_progress_report = int(config_vars["LAST_PROGRESS"])
        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()

    def get_revision_range(self):
        revision_range_re = re.compile("""
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

    def raise_if_forbidden_file(self, item_to_check):
        if self.compiled_forbidden_file_regex.search(os.fspath(item_to_check)):
            raise InstlException(f"{item_to_check} has forbidden characters should not be committed to svn")

    def raise_if_forbidden_dir(self, item_to_check):
        if self.compiled_forbidden_folder_regex.search(os.fspath(item_to_check)):
            raise InstlException(f"{item_to_check} has forbidden characters should not be committed to svn")

    def do_stage2svn(self):
        self.batch_accum.set_current_section('admin')
        stage_folder = config_vars["STAGING_FOLDER"].Path()
        svn_folder = config_vars["SVN_CHECKOUT_FOLDER"].Path()

        self.compile_exclude_regexi()

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

        for svn_only_item in sorted(comparator.left_only):
            # copy items found in stage but not in svn
            stage_only_item_path = Path(comparator.left, svn_only_item)
            svn_item_path = Path(comparator.right, svn_only_item)
            if stage_only_item_path.is_symlink():
                raise InstlException(stage_only_item_path+" is a symlink which should not be committed to svn, run instl fix-symlinks and try again")
            elif stage_only_item_path.is_file():
                self.raise_if_forbidden_file(stage_only_item_path)

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
                self.raise_if_forbidden_dir(stage_only_item_path)
                # check that all items under a new folder pass the forbidden file/folder rule
                for root, dirs, files in os.walk(stage_only_item_path, followlinks=False):
                    for item in sorted(files):
                        self.raise_if_forbidden_file(item)
                    for item in sorted(dirs):
                        self.raise_if_forbidden_dir(item)

                self.batch_accum += CopyDirToDir(stage_only_item_path, comparator.right, hard_links=False, ignore_patterns=[".svn"], preserve_dest_files=False)
                self.batch_accum += Progress(f"copy dir {stage_only_item_path}")
            else:
                raise InstlException(stage_only_item_path+" not a file, dir or symlink, an abomination!")

        # copy changed items:

        do_not_copy_items = list()  # items that should not be copied even if different, there are items that are part of .wtar where
                                    # each part might be different but the contents are not. E.g. whe re-wtaring files where only
                                    # modification date has changed.
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
        for svn_only_item in sorted(comparator.right_only):
            if svn_only_item not in do_not_remove_items:
                item_to_remove = os.path.join(comparator.right, svn_only_item)
                self.batch_accum += SVNRemove(item_to_remove)

        # recurse to sub folders
        for sub_comparator in list(comparator.subdirs.values()):
            self.stage2svn_with_comparator(sub_comparator)

    def prepare_conditions_for_wtar(self):
        folder_wtar_regex_list = list(config_vars["FOLDER_WTAR_REGEX"])
        self.compiled_folder_wtar_regex = utils.compile_regex_list_ORed(folder_wtar_regex_list)
        file_wtar_regex_list = list(config_vars["FILE_WTAR_REGEX"])
        self.compiled_file_wtar_regex = utils.compile_regex_list_ORed(file_wtar_regex_list)

        self.min_file_size_to_wtar = int(config_vars["MIN_FILE_SIZE_TO_WTAR"])

        if "WTAR_BY_FILE_SIZE_EXCLUDE_REGEX" in config_vars:
            wtar_by_file_size_exclude_regex = list(config_vars["WTAR_BY_FILE_SIZE_EXCLUDE_REGEX"])
            self.compiled_wtar_by_file_size_exclude_regex = utils.compile_regex_list_ORed(wtar_by_file_size_exclude_regex)
        else:
            self.compiled_wtar_by_file_size_exclude_regex = re.compile(".+")

        self.already_wtarred_regex = re.compile("wtar(\.\w\w)?$")

    def should_wtar(self, dir_item: Path):
        _should_wtar = False
        _already_tarred = False
        try:
            if self.already_wtarred_regex.search(os.fspath(dir_item)):
                _should_wtar = False
                _already_tarred = True
            elif dir_item.is_dir():
                if self.compiled_folder_wtar_regex.search(os.fspath(dir_item)):
                    # it's a folder matching one of the filters for wtarring a folder
                    _should_wtar = True
                    _already_tarred = False
            elif dir_item.is_file():
                if self.compiled_file_wtar_regex.search(os.fspath(dir_item)):
                    # it's a file matching one of the filters for wtarring a file
                    _should_wtar = True
                    _already_tarred = False
                elif dir_item.stat().st_size > self.min_file_size_to_wtar:
                    # it's a file who's size is big enough to require wtarring
                    if re.match(self.compiled_wtar_by_file_size_exclude_regex, os.fspath(dir_item)):
                        _should_wtar = False
                        _already_tarred = False
                    else:
                         # but not a file who's name matching one of the filters for NOT wtarring
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

        out_file_path = os.fspath(config_vars["__MAIN_OUT_FILE__"])
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            aYaml.writeAsYaml(aYaml.YamlDumpWrap(depend_result, sort_mappings=True), out_file)
        self.progress("dependencies written to", out_file_path)

    def do_verify_repo(self):
        self.read_yaml_file(config_vars["STAGING_FOLDER_INDEX"].str())

        the_folder = config_vars["STAGING_FOLDER"].str()
        self.info_map_table.initialize_from_folder(the_folder)
        self.items_table.activate_all_oses()
        self.items_table.resolve_inheritance()

        self.verify_index_to_repo()

    def verify_index_to_repo(self):
        """ helper function for verify-repo and verify-index commands
            Assuming the index and info-map have already been read
            check the expect files from the index appear in the info-map
        """
        all_iids = sorted(self.items_table.get_all_iids())
        self.total_self_progress += len(all_iids)
        self.items_table.change_status_of_all_iids(1)

        problem_messages_by_iid = defaultdict(list)

        # check inherit
        self.progress("checking inheritance")
        missing_inheritees = self.items_table.get_missing_iids_from_details("inherit")
        for missing_inheritee in missing_inheritees:
            err_message = " ".join(("inherits from non existing", utils.quoteme_single(missing_inheritee[1])))
            problem_messages_by_iid[missing_inheritee[0]].append(err_message)

        # check depends
        self.progress("checking dependencies")
        missing_dependees = self.items_table.get_missing_iids_from_details("depends")
        for missing_dependee in missing_dependees:
            err_message = " ".join(("depends from non existing", utils.quoteme_single(missing_dependee[1])))
            problem_messages_by_iid[missing_dependee[0]].append(err_message)

        for iid in all_iids:
            self.progress("checking sources for", iid)

            # check sources
            source_and_tag_list = self.items_table.get_details_and_tag_for_active_iids("install_sources", unique_values=True, limit_to_iids=(iid,))

            for source in source_and_tag_list:
                source_path, source_type = source[0], source[1]
                num_files_for_source = self.info_map_table.mark_required_for_source(source_path, source_type)
                if num_files_for_source == 0:
                    err_message = " ".join(("source", utils.quoteme_single(source_path),"required by", iid, "does not have files"))
                    problem_messages_by_iid[iid].append(err_message)

            # check targets
            if len(source_and_tag_list) > 0:
                target_folders = set(self.items_table.get_resolved_details_value_for_active_iid(iid, "install_folders", unique_values=True))
                if len(target_folders) == 0:
                    err_message = " ".join(("iid", iid, "does not have target folder"))
                    problem_messages_by_iid[iid].append(err_message)

        self.progress("checking for cyclic dependencies")
        self.info_map_table.mark_required_completion()
        self.find_cycles()

        for iid in sorted(problem_messages_by_iid):
            self.progress(iid+":")
            for problem_message in sorted(problem_messages_by_iid[iid]):
                self.progress("   ", problem_message)

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
        self.compile_exclude_regexi()
        out_file_path = str(config_vars.get("__MAIN_OUT_FILE__", "stdout"))
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
                self.info_map_table.read_from_file(f2r)

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
        file_to_translate_path = config_vars["__MAIN_INPUT_FILE__"].Path()
        output_file_path = config_vars["__MAIN_OUT_FILE__"].Path()
        a_temp_file = tempfile.NamedTemporaryFile(mode='w', dir=output_file_path.parent, delete=False)
        try:
            num_translated_guids = self.translate_guids_in_file(file_to_translate_path, a_temp_file.name)
            os.replace(a_temp_file.name, output_file_path)
            self.progress(f"""{num_translated_guids} guids translated""")
        except Exception as ex:
            pass
        finally:
            try: os.unlink(a_temp_file.name)
            except: pass

    def translate_guids_in_file(self, in_file, out_file):
        num_translated_guids = 0
        iid_to_guid = dict((guid.lower(), iid) for iid, guid in self.items_table.get_all_iids_with_guids())
        guid_re = re.compile("""
                (?P<guid>[a-fA-F0-9]{8}
                (-[a-fA-F0-9]{4}){3}
                -[a-fA-F0-9]{12})
                """, re.VERBOSE)

        with open(in_file, "r") as rfd:
            with open(out_file, "w") as wfd:
                for line in rfd.readlines():
                    match = guid_re.search(line)
                    if match:
                        new_line = line.replace(match.group("guid"), f'{match.group("guid")}  # {iid_to_guid.get(match.group("guid").lower(), "?")}')
                        wfd.write(new_line)
                        num_translated_guids += 1
                    else:
                        wfd.write(line)
        return num_translated_guids

    def do_up2s3(self):
        repo_rev = int(config_vars['TARGET_REPO_REV'])
        self.up2s3_repo_rev(repo_rev, self.batch_accum)

    def up2s3_repo_rev(self, repo_rev, batch_accum):
        assert repo_rev >= int(config_vars['BASE_REPO_REV']), f"repo-rev({repo_rev}) < BASE_REPO_REV({int(config_vars['BASE_REPO_REV'])})"
        assert repo_rev >= int(config_vars['IGNORE_BELOW_REPO_REV']), f"repo-rev({repo_rev}) < IGNORE_BELOW_REPO_REV({int(config_vars['IGNORE_BELOW_REPO_REV'])})"
        assert repo_rev not in list(map(int, list(config_vars.get('IGNORE_SPECIFIC_REPO_REV', [])))), f"repo-rev({repo_rev}) is in IGNORE_SPECIFIC_REPO_REV"

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)
        try:
            r.set(config_vars["UPLOAD_REPO_REV_IN_PROGRESS_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str())

            config_vars['UP2S3_STATUS'] = "FAILED"
            config_vars['UP2S3_EXCEPTION'] = ""
            config_vars["REPO_REV"] = str(repo_rev)
            config_vars["__CURR_REPO_REV__"] = str(repo_rev)
            config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.repo_rev_to_folder_hierarchy(repo_rev)  # e.g. 345 -> 03/45

            checkout_url = str(config_vars['SVN_REPO_URL'])
            checkout_base_folder = Path(config_vars['UPLOAD_BASE_CHECKOUT_FOLDER'])
            checkout_folder_instl_folder_path = checkout_base_folder.joinpath("instl")
            checkout_folder_index_path = checkout_folder_instl_folder_path.joinpath("index.yaml")

            revision_folder_path = Path(config_vars["UPLOAD_REVISION_FOLDER"])
            revision_instl_folder_path = Path(config_vars["UPLOAD_REVISION_INSTL_FOLDER"])
            revision_instl_index_path = Path(config_vars["UPLOAD_REVISION_INDEX_FILE"])

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

            batch_accum += MakeDirs(revision_folder_path)  # create specific repo-rev folder
            batch_accum += MakeDirs(revision_instl_folder_path)  # create specific repo-rev instl folder
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
            batch_accum += CreateRepoRevFile()

            with batch_accum.sub_accum(Cd(revision_folder_path)) as sub_accum:
                sub_accum += Subprocess("aws", "s3", "sync", os.curdir, "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)", "--exclude", "*.DS_Store")
                repo_rev_file_path = config_vars["UPLOAD_REVISION_REPO_REV_FILE"].str()
                sub_accum += Subprocess("aws", "s3", "cp", repo_rev_file_path, "s3://$(S3_BUCKET_NAME)/admin/", "--content-type", 'text/plain')
            batch_accum += RmDirContents(revision_folder_path, exclude=['instl'])

            self.write_batch_file(batch_accum)
            if bool(config_vars["__RUN_BATCH__"]):
                self.run_batch_file()

            r.hset(config_vars["UPLOAD_REPO_REV_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["UPLOAD_REPO_REV_LAST_UPLOADED_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            config_vars['UP2S3_STATUS'] = "Completed"
        except Exception as ex:
            config_vars['UP2S3_EXCEPTION'] = f"{ex}"
            print(f"up2s3_repo_rev exception {ex}")
            raise
        finally:
            self.send_email_from_template_file(config_vars["UP2S3_EMAIL_TEMPLATE_PATH"].Path())
            r.set(config_vars["UPLOAD_REPO_REV_IN_PROGRESS_REDIS_KEY"].str(), "waiting...")

    def do_wait_on_action_trigger(self):

        sys.path.append(os.pardir)
        sys.path.append(f"{os.pardir}/{os.pardir}")
        from . import instl_own_main

        # config yaml such as stout-config.yaml with definitions needed for this funciton to work
        main_input_file = Path(config_vars["__CONFIG_FILE__"][0]).resolve()
        # other config files are assumed to exist below the folder where main_input_file is found
        main_config_folder = main_input_file.parent

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        # trigger_commit_redis_key: redis list of values like 'prod:V11:369' indicating a commit of repo-rev 369 for V11 on production happened
        trigger_commit_redis_key = config_vars['UPLOAD_REPO_REV_WAITING_LIST_REDIS_KEY'].str()

        # trigger_commit_redis_key: redis list of values like 'prod:V11:369' indicating request to activate of repo-rev 369 for V11 on production happened
        activate_repo_rev_waiting_list_redis_key = config_vars['ACTIVATE_REPO_REV_WAITING_LIST_REDIS_KEY'].str()

        # heartbeat_redis_key: regular time stamps will be send to this key
        heartbeat_redis_key = config_vars.get("HEARTBEAT_COUNTER_REDIS_KEY", "wv:instl:trigger:heartbeat").str()
        start_redis_heartbeat_thread(redis_host, redis_port, heartbeat_redis_key, 2.0)

        r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)
        trigger_keys_to_wait_on = (trigger_commit_redis_key, activate_repo_rev_waiting_list_redis_key)

        while True:
            log.info(f"wait on triggers: {redis_host}:{redis_port} {trigger_keys_to_wait_on}")
            poped = r.brpop(trigger_keys_to_wait_on, timeout=30)
            if poped is not None:
                key = str(poped[0])
                value = str(poped[1])

                log.info(f"popped key: {key}, value: {value}")
                if value == "stop":
                    log.info(f"received stop")
                    break
                elif value == "ping":
                    ping_redis_key = f"{key}:ping"
                    r.incr(ping_redis_key, 1)
                    log.info(f"ping incremented {ping_redis_key}")

                elif key in (trigger_commit_redis_key, activate_repo_rev_waiting_list_redis_key):
                    try:
                        instl_command_name = {trigger_commit_redis_key: "up2s3", activate_repo_rev_waiting_list_redis_key: "activate-repo-rev"}[key]
                        domain, major_version, repo_rev = value.split(":")
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
                        up2s3_process = mp.Process (target=instl_own_main,
                                                    name=f"{instl_command_name}_{domain}_{major_version}_{repo_rev}",
                                                    args=(str(config_vars["__INSTL_EXE_PATH__"]),
                                                          [instl_command_name,
                                                           "--config-file", os.fspath(work_config_file),
                                                           "--log", os.fspath(work_log_file),
                                                           "--run"]))

                        up2s3_process.start()
                        up2s3_process.join()

                    except Exception as ex:
                        log.info(f"Exception {ex} in {trigger_commit_redis_key} up2s3 of repo-rev {repo_rev}")
                else:
                    log.info(f"popped unknown key: {key}")

            time.sleep(2)
        log.info(f"stopped waiting on {trigger_keys_to_wait_on}")

    def do_activate_repo_rev(self):

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port
        r = redis.StrictRedis(host=redis_host, port=redis_port, charset="utf-8", decode_responses=True)

        try:
            r.set(config_vars["ACTIVATE_REPO_REV_IN_PROGRESS_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str())

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
            with open(copy_of_activated_repo_rev_file_path, "r") as rfd:
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
            r.set(config_vars["ACTIVATE_REPO_REV_IN_PROGRESS_REDIS_KEY"].str(), "waiting...")

    def get_work_folder(self):
        """ calculate the path of the work folder for specific repo_rev/major_version/domain
            create the folder
            assign the path to configVar
        """

        repo_rev_work_folder = self.repo_rev_to_folder_hierarchy(config_vars["TARGET_REPO_REV"])
        work_folder: Path = config_vars["UPLOAD_WORK_AREA"].Path().joinpath(config_vars["TARGET_DOMAIN"].str(), config_vars["TARGET_MAJOR_VERSION"].str(), repo_rev_work_folder)
        work_folder.mkdir(parents=True, exist_ok=True)
        return work_folder

    def send_email_from_template_file(self, path_to_template):
        work_folder = config_vars["TARGET_WORK_FOLDER"].Path()
        path_to_resolved = work_folder.joinpath(path_to_template.name)
        try:
            ResolveConfigVarsInFile(path_to_template, path_to_resolved)()
            utils.send_email_from_template_file(path_to_resolved)
        except Exception as ex:
            with open(path_to_resolved, "+w") as wfd:
                wfd.write(f"\nFailed to send email\n{ex}")
