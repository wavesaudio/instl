#!/usr/bin/env python3.12
"""Sync-location / direct-sync resolution behavior extracted verbatim from
pyinstl/instlClient.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import os
import logging
log = logging.getLogger()

import utils
from configVar import config_vars
from pybatch import *


class _SyncLocationsClientMixin:

    def create_sync_folder_manifest_command(self, manifest_file_name_prefix: str, back_ground: bool=False):
        """ create batch commands to write a manifest of the sync folder to a file """
        retVal = AnonymousAccum()
        if 'SYNC_FOLDER_MANIFEST_FILE' in config_vars:  # sync folder manifest file should not be created twice
            return retVal
        which_folder_to_manifest = "$(COPY_SOURCES_ROOT_DIR)"
        output_file_name = manifest_file_name_prefix+"-sync-folder-manifest.txt"
        output_folder = None
        for param_to_extract_output_folder_from in ('ECHO_LOG_FILE', '__MAIN_INPUT_FILE__', '__MAIN_OUT_FILE__'):
            if config_vars.defined(param_to_extract_output_folder_from):
                log_file_path = str(config_vars[param_to_extract_output_folder_from])
                output_folder, _ = os.path.split(log_file_path)
                if os.path.isdir(output_folder):
                    break
                output_folder = None

        if output_folder is not None:
            config_vars['SYNC_FOLDER_MANIFEST_FILE'] = output_file_name
            output_file_path = Path(output_folder, output_file_name)
            retVal += RunInThread(Ls(which_folder_to_manifest, out_file=output_file_path), thread_name="list_sync_folder", daemon=True, ignore_all_errors=True)
        return retVal

    def get_direct_sync_status_from_indicator(self, direct_sync_indicator):
        retVal = False
        if direct_sync_indicator is not None:
            try:
                retVal = utils.str_to_bool_int(config_vars.resolve_str(direct_sync_indicator))
            except:
                pass
        return retVal

    def set_sync_locations_for_active_items(self):
        # get_sync_folders_and_sources_for_active_iids returns: [(iid, direct_sync_indicator, source, source_tag, install_folder),...]
        # direct_sync_indicator will be None unless the items has "direct_sync" section in index.yaml
        # source is the relative path as it appears in index.yaml
        # adjusted source is the source prefixed with $(SOURCE_PREFIX) -- it needed
        # source_tag is one of  '!dir', '!dir_cont', '!file'
        # install_folder is where the sources should be copied to OR, in case of direct syn where they should be synced to
        # install_folder will be None for those items that require only sync not copy (such as Icons)
        #
        # for each file item in the source this function will set the full path where to download the file: item.download_path
        # and the top folder common to all items in a single source: item.download_root
        sync_and_source = self.items_table.get_sync_folders_and_sources_for_active_iids()

        items_to_update = list()
        local_repo_sync_dir = os.fspath(config_vars["LOCAL_REPO_SYNC_DIR"])
        config_vars.setdefault("ALL_SYNC_DIRS", local_repo_sync_dir)
        for iid, direct_sync_indicator, source, source_tag, install_folder in sync_and_source:
            direct_sync = self.get_direct_sync_status_from_indicator(direct_sync_indicator)
            resolved_source_parts = source.split("/")
            if install_folder:
                resolved_install_folder = config_vars.resolve_str(install_folder)
            else:
                resolved_install_folder = install_folder

            match source_tag:
                case '!dir' | '!dir_cont':
                    if direct_sync:
                        # for direct-sync source, if one of the sources is Info.xml and it exists on disk AND source & file
                        # have the same checksum, then no sync is needed at all. All the above is not relevant in repair mode.
                        need_to_sync = True
                        if not self.update_mode:
                            info_xml_item = self.info_map_table.get_file_item("/".join((source, "Info.xml")))
                            if info_xml_item:
                                info_xml_of_target = config_vars.resolve_str("/".join((resolved_install_folder, resolved_source_parts[-1], "Info.xml")))
                                need_to_sync = not utils.check_file_checksum(info_xml_of_target, info_xml_item.checksum)
                        if need_to_sync:
                            config_vars["ALL_SYNC_DIRS"].append(resolved_install_folder)
                            item_paths = self.info_map_table.get_recursive_paths_in_dir(dir_path=source, what="any")
                            self.progress(f"mark for download {len(item_paths)} files of {iid}/{source}")
                            if source_tag == '!dir':
                                source_parent = "/".join(resolved_source_parts[:-1])
                                for item in item_paths:
                                    item_to_update = {"_id": item['_id'],
                                                    "download_path": config_vars.resolve_str("/".join((resolved_install_folder, item['path'][len(source_parent)+1:]))),
                                                    "download_root": config_vars.resolve_str("/".join((resolved_install_folder, resolved_source_parts[-1])))}
                                    items_to_update.append(item_to_update)
                            else:  # !dir_cont
                                source_parent = source
                                for item in item_paths:
                                    item_to_update = {"_id": item['_id'],
                                                    "download_path": config_vars.resolve_str("/".join((resolved_install_folder, item['path'][len(source_parent)+1:]))),
                                                    "download_root": resolved_install_folder}
                                    items_to_update.append(item_to_update)
                        else:
                            num_ignored_files = self.info_map_table.ignore_file_paths_of_dir(dir_path=source)
                            if num_ignored_files < 1:
                                num_ignored_files = ""  # sqlite curs.rowcount does not always returns the number of effected rows
                            self.progress(f"avoid download {num_ignored_files} files of {iid}, Info.xml has not changed")

                    else:
                        item_paths = self.info_map_table.get_recursive_paths_in_dir(dir_path=source)
                        self.progress(f"mark for download {len(item_paths)} files of {iid}/{source}")
                        for item in item_paths:
                            item_to_update = {"_id": item['_id'],
                                                    "download_path": config_vars.resolve_str("/".join((local_repo_sync_dir, item['path']))),
                                                    "download_root": None}
                            items_to_update.append(item_to_update)
                case '!file':
                    # if the file was wtarred and split it would have multiple items
                    items_for_file = self.info_map_table.get_required_paths_for_file(source)
                    self.progress(f"mark for download {len(items_for_file)} files of {iid}/{source}")
                    if direct_sync:
                        config_vars["ALL_SYNC_DIRS"].append(resolved_install_folder)
                        for item in items_for_file:
                            item_to_update = {"_id": item['_id'],
                                            "download_path": config_vars.resolve_str("/".join((resolved_install_folder, item['leaf']))),
                                            "download_root": config_vars.resolve_str(resolved_install_folder)}
                            items_to_update.append(item_to_update)
                    else:
                        for item in items_for_file:
                            item_to_update = {"_id": item['_id'],
                                            "download_path": config_vars.resolve_str("/".join((local_repo_sync_dir, item['path']))),
                                            "download_root": None}  # no need to set item.download_root here - it will not be used
                            items_to_update.append(item_to_update)

        self.info_map_table.update_downloads(items_to_update)
