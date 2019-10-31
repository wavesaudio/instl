#!/usr/bin/env python3.6


import sys
import os
from pathlib import Path
import unittest
import subprocess
import stat
import ctypes
import io
import contextlib
import filecmp
import random
import string
from collections import namedtuple

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum
from pybatch.copyBatchCommands import RsyncClone
from configVar import config_vars

current_os_names = utils.get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

config_vars["__CURRENT_OS_NAMES__"] = current_os_names


from .test_PythonBatchBase import *


class TestPythonBatchWtar(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_Wtar_Unwtar_repr(self):
        list_of_objs = list()
        list_of_objs.append(Wtar("/the/memphis/belle"))
        list_of_objs.append(Wtar("/the/memphis/belle", None))
        list_of_objs.append(Wtar("/the/memphis/belle", "robota"))
        list_of_objs.append(Unwtar("/the/memphis/belle"))
        list_of_objs.append(Unwtar("/the/memphis/belle", None))
        list_of_objs.append(Unwtar("/the/memphis/belle", "robota", no_artifacts=True))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_Wtar_Unwtar(self):
        folder_to_wtar = self.pbt.path_inside_test_folder("folder-to-wtar")
        folder_wtarred = self.pbt.path_inside_test_folder("folder-to-wtar.wtar")
        dummy_wtar_file_to_replace = self.pbt.path_inside_test_folder("dummy-wtar-file-to-replace.dummy")
        with open(dummy_wtar_file_to_replace, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(dummy_wtar_file_to_replace.exists(), f"{self.pbt.which_test}: {dummy_wtar_file_to_replace} should have been created")
        another_folder = self.pbt.path_inside_test_folder("another-folder")
        wtarred_in_another_folder = another_folder.joinpath("folder-to-wtar.wtar").resolve()

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(folder_to_wtar)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_wtar)) as cd_accum:
            cd_accum += Touch("dohickey")  # add one file with fixed (none random) name
            cd_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=4, num_files_per_dir=7, file_size=41)
            cd_accum += Wtar(folder_to_wtar)  # wtar next to the folder
            cd_accum += Wtar(folder_to_wtar, dummy_wtar_file_to_replace)  # wtar on replacing existing file
            cd_accum += MakeDir(another_folder)
            cd_accum += Wtar(folder_to_wtar, another_folder)  # wtar to a different folder
        self.pbt.exec_and_capture_output("wtar the folder")
        self.assertTrue(os.path.isfile(folder_wtarred), f"wtarred file was not found {folder_wtarred}")
        self.assertTrue(os.path.isfile(dummy_wtar_file_to_replace), f"dummy_wtar_file_to_replace file was not found {dummy_wtar_file_to_replace}")
        self.assertTrue(os.path.isfile(wtarred_in_another_folder), f"wtarred file in another folder was not found {wtarred_in_another_folder}")
        self.assertTrue(filecmp.cmp(folder_wtarred, dummy_wtar_file_to_replace), f"'{folder_wtarred}' and '{dummy_wtar_file_to_replace}' should be identical")
        self.assertTrue(filecmp.cmp(folder_wtarred, dummy_wtar_file_to_replace), f"'{folder_wtarred}' and '{dummy_wtar_file_to_replace}' should be identical")
        self.assertTrue(filecmp.cmp(folder_wtarred, wtarred_in_another_folder), f"'{folder_wtarred}' and '{wtarred_in_another_folder}' should be identical")

        unwtar_here = self.pbt.path_inside_test_folder("unwtar-here")
        unwtared_folder = unwtar_here.joinpath("folder-to-wtar").resolve()
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += Unwtar(folder_wtarred, unwtar_here)
        self.pbt.exec_and_capture_output("unwtar the folder")
        dir_wtar_unwtar_diff = filecmp.dircmp(folder_to_wtar, unwtared_folder, ignore=['.DS_Store'])
        self.assertTrue(is_identical_dircmp(dir_wtar_unwtar_diff), f"{self.pbt.which_test} : before wtar and after unwtar dirs are not the same")

    def test_Wzip_repr(self):
        list_of_objs = list()
        list_of_objs.append(Wzip("/the/memphis/belle"))
        list_of_objs.append(Wzip("/the/memphis/belle", None))
        list_of_objs.append(Wzip("/the/memphis/belle", "robota"))
        list_of_objs.append(Unwzip("/the/memphis/belle"))
        list_of_objs.append(Unwzip("/the/memphis/belle", None))
        list_of_objs.append(Unwzip("/the/memphis/belle", "robota"))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_Wzip(self):
        wzip_input = self.pbt.path_inside_test_folder("wzip_in")
        wzip_output = self.pbt.path_inside_test_folder("wzip_in.wzip")
        unwzip_target_folder = self.pbt.path_inside_test_folder("unwzip_target")
        unwzip_target_file = self.pbt.path_inside_test_folder("wzip_in")

        # create a file to zip
        with open(wzip_input, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(wzip_input.exists(), f"{self.pbt.which_test}: {wzip_input} should have been created")

        with self.pbt.batch_accum as batchi:
            batchi += Wzip(wzip_input)
        self.pbt.exec_and_capture_output("Wzip a file")
        self.assertTrue(wzip_output.exists(), f"{self.pbt.which_test}: {wzip_output} should exist after test")
        self.assertTrue(wzip_input.exists(), f"{self.pbt.which_test}: {wzip_input} should exist after test")

        with self.pbt.batch_accum as batchi:
            batchi += Unwzip(wzip_output, unwzip_target_folder)
        self.pbt.exec_and_capture_output("Unwzip a file")
        self.assertTrue(unwzip_target_folder.exists(), f"{self.pbt.which_test}: {unwzip_target_folder} should exist before test")
        self.assertTrue(unwzip_target_file.exists(), f"{self.pbt.which_test}: {unwzip_target_file} should exist before test")
        self.assertTrue(filecmp.cmp(wzip_input, unwzip_target_file), f"'{wzip_input}' and '{unwzip_target_file}' should be identical")
