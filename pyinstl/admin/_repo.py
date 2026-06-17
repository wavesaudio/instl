#!/usr/bin/env python3.12
"""Repository / staging / SVN / permissions commands extracted verbatim from
pyinstl/instlAdmin.py (fix-props, fix-symlinks, stage2svn, svn2stage, fix-perm
and their helpers).

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

import os
import filecmp

import utils
from pybatch import *
from ..instlException import InstlException


class _RepoAdminMixin:

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
                match item.isExecutable(), shouldBeExec:
                    case True, False:
                        repo_folder_accum += SVNDelProp('svn:executable', item.path)
                    case False, True:
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

    def should_file_be_exec(self, file_path):
        retVal = self.compiled_should_be_exec_regex.search(file_path)
        return retVal is not None

    def should_be_exec(self, item):
        retVal = item.isFile() and self.should_file_be_exec(item.path)
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
