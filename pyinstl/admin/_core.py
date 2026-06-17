#!/usr/bin/env python3.12
"""Core InstlAdmin behavior (init, config-file reading, command dispatch and
small shared helpers) extracted verbatim from pyinstl/instlAdmin.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

import os
import re

import utils
from pybatch import *


class _CoreAdminMixin:

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
