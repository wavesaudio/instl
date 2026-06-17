#!/usr/bin/env python3.12
"""Remove-previous-sources instruction behavior extracted verbatim from
pyinstl/instlClient.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import os
import logging
log = logging.getLogger()

import utils
from configVar import config_vars
from pybatch import *
from ..instlException import InstlFatalException


class _RemoveSourcesClientMixin:

    def create_remove_previous_sources_instructions_for_target_folder(self, target_folder_path):
        retVal = AnonymousAccum()
        target_folder_path_resolved = utils.ExpandAndResolvePath(config_vars.resolve_str(target_folder_path))
        if target_folder_path_resolved.is_dir():  # no need to remove previous sources if folder does not exist
            iids_in_folder = self.all_iids_by_target_folder[target_folder_path]
            previous_sources = self.items_table.get_details_and_tag_for_active_iids("previous_sources", unique_values=True, limit_to_iids=iids_in_folder)

            if len(previous_sources) > 0:
                with retVal.sub_accum(Cd(target_folder_path)) as remove_prev_section:
                    remove_prev_section += Progress(f"remove previous versions {target_folder_path}")

                    for previous_source in previous_sources:
                        remove_prev_section += self.create_remove_previous_sources_instructions_for_source(target_folder_path, previous_source)
        return retVal

    def create_remove_previous_sources_instructions_for_source(self, folder, source):
        """ source is a tuple (source_folder, tag), where tag is either !file, !dir_cont or !dir """

        retVal = AnonymousAccum()
        iid, source_path, source_type = source[0], source[1], source[2]
        if not source_path:
            log.warning(f"empty 'previous_sources' entry for item '{iid}'; "
                        f"skipping it (nothing to remove). Check the previous_sources section of '{iid}' in index.yaml.")
            return retVal

        to_remove_path = os.path.normpath(os.path.join(folder, source_path))

        match source_type:
            case '!dir':  # remove whole folder
                retVal += RmDir(to_remove_path)
            case '!file':  # remove single file
                retVal += RmFile(to_remove_path)
            case '!dir_cont':
                raise InstlFatalException(
                    f"Invalid index.yaml: item '{iid}' has a 'previous_sources' entry tagged !dir_cont,",
                    "which is not allowed for previous_sources (use !dir or !file instead).",
                    f"Offending source: '{source_path}'.")

        return retVal
