#!/usr/bin/env python3.12
"""Installed-binaries version-check behavior extracted verbatim from
pyinstl/instlClient.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import logging
log = logging.getLogger()

import utils
from configVar import config_vars
from pybatch import *


class _BinariesClientMixin:

    def should_check_for_binary_versions(self):
        """ checking versions inside binaries is heavy task.
            should_check_for_binary_versions returns if it's needed.
            True value will be returned if check was explicitly requested
            or if update of installed items was requested
        """
        explicitly_asked_for_binaries_check = 'CHECK_BINARIES_VERSIONS' in config_vars
        update_was_requested = "__UPDATE_INSTALLED_ITEMS__" in config_vars.get("MAIN_INSTALL_TARGETS", []).list()
        retVal = explicitly_asked_for_binaries_check or update_was_requested
        return retVal

    def get_version_of_installed_binaries(self):
        # utils.add_to_actions_stack("getting version of installed binaries")
        binaries_version_list = list()
        try:

            ignore_regexes_filter = utils.check_binaries_versions_filter_with_ignore_regexes()

            if "CHECK_BINARIES_VERSION_FOLDER_EXCLUDE_REGEX" in config_vars:
                ignore_folder_regex_list = list(config_vars["CHECK_BINARIES_VERSION_FOLDER_EXCLUDE_REGEX"])
                ignore_regexes_filter.set_folder_ignore_regexes(ignore_folder_regex_list)

            if "CHECK_BINARIES_VERSION_FILE_EXCLUDE_REGEX" in config_vars:
                ignore_file_regex_list = list(config_vars["CHECK_BINARIES_VERSION_FILE_EXCLUDE_REGEX"])
                ignore_regexes_filter.set_file_ignore_regexes(ignore_file_regex_list)

            current_os = config_vars["__CURRENT_OS__"].str()
            path_to_search = list(config_vars.get('CHECK_BINARIES_VERSION_FOLDERS', []))
            for a_path in path_to_search:
                binaries_version_from_folder = utils.check_binaries_versions_in_folder(current_os, Path(a_path), ignore_regexes_filter)
                binaries_version_list.extend(binaries_version_from_folder)

            self.items_table.insert_binary_versions(binaries_version_list)

        except Exception as ex:
            log.warning(f"""exception while in check_binaries_versions {ex}""")
        return binaries_version_list
