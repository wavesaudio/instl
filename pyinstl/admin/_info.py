#!/usr/bin/env python3.12
"""Miscellaneous info/inspection commands extracted verbatim from
pyinstl/instlAdmin.py (file-sizes, read-info-map, check-instl-folder-integrity,
translate-guids, short-index, dump-config-vars).

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
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
from ..instlInstanceBase import InstlInstanceBase
from pybatch import *
from ..instlException import InstlException
from configVar import ConfigVarYamlReader


class _InfoAdminMixin:

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
        guid_re = re.compile(r"""
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
