#!/usr/bin/env python3.6


import sys
import os
from pathlib import Path
import unittest
import shutil
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


from testPythonBatch import *


class TestPythonBatchRemove(unittest.TestCase):
    def __init__(self, which_test="apple"):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_RmFile_repr(self):
        rmfile_obj = RmFile(r"\just\remove\me\already")
        rmfile_obj_recreated = eval(repr(rmfile_obj))
        self.assertEqual(rmfile_obj, rmfile_obj_recreated, "RmFile.repr did not recreate RmFile object correctly")

    def test_RmDir_repr(self):
        rmfile_obj = RmDir(r"\just\remove\me\already")
        rmfile_obj_recreated = eval(repr(rmfile_obj))
        self.assertEqual(rmfile_obj, rmfile_obj_recreated, "RmDir.repr did not recreate RmDir object correctly")

    def test_remove(self):
        """ Create a folder and fill it with random files.
            1st try to remove the folder with RmFile which should fail and raise exception
            2nd try to remove the folder with RmDir which should work
        """
        dir_to_remove = self.pbt.path_inside_test_folder("remove-me")
        self.assertFalse(dir_to_remove.exists())

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(dir_to_remove)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_remove)) as sub_bc:
            sub_bc += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
        self.pbt.batch_accum += RmFile(dir_to_remove)  # RmFile should not remove a folder
        self.pbt.exec_and_capture_output(expected_exception=PermissionError)
        self.assertTrue(dir_to_remove.exists())

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += RmDir(dir_to_remove)
        self.pbt.exec_and_capture_output()
        self.assertFalse(dir_to_remove.exists())

    def test_RemoveEmptyFolders_repr(self):
        with self.assertRaises(TypeError):
            ref_obj = RemoveEmptyFolders()

        ref_obj = RemoveEmptyFolders("/per/pen/di/cular")
        ref_obj_recreated =eval(repr(ref_obj))
        self.assertEqual(ref_obj, ref_obj_recreated, "RemoveEmptyFolders.repr did not recreate MacDoc object correctly")

        ref_obj = RemoveEmptyFolders("/per/pen/di/cular", [])
        ref_obj_recreated =eval(repr(ref_obj))
        self.assertEqual(ref_obj, ref_obj_recreated, "RemoveEmptyFolders.repr did not recreate MacDoc object correctly")

        ref_obj = RemoveEmptyFolders("/per/pen/di/cular", ['async', 'await'])
        ref_obj_recreated =eval(repr(ref_obj))
        self.assertEqual(ref_obj, ref_obj_recreated, "RemoveEmptyFolders.repr did not recreate MacDoc object correctly")

    def test_RemoveEmptyFolders(self):
        folder_to_remove = self.pbt.path_inside_test_folder("folder-to-remove")
        file_to_stay = folder_to_remove.joinpath("paramedic")

        # create the folder, with sub folder and one known file
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(folder_to_remove)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_remove)) as cd_accum:
            cd_accum += Touch(file_to_stay.name)
            cd_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=2, num_files_per_dir=0, file_size=41)
        self.pbt.exec_and_capture_output("create empty folders")
        self.assertTrue(os.path.isdir(folder_to_remove), f"{self.pbt.which_test} : folder to remove was not created {folder_to_remove}")
        self.assertTrue(os.path.isfile(file_to_stay), f"{self.pbt.which_test} : file_to_stay was not created {file_to_stay}")

        # remove empty folders, top folder and known file should remain
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += RemoveEmptyFolders(folder_to_remove, files_to_ignore=['.DS_Store'])
        # removing non existing folder should not be a problem
        self.pbt.batch_accum += RemoveEmptyFolders("kajagogo", files_to_ignore=['.DS_Store'])
        self.pbt.exec_and_capture_output("remove almost empty folders")
        self.assertTrue(os.path.isdir(folder_to_remove), f"{self.pbt.which_test} : folder was removed although it had a legit file {folder_to_remove}")
        self.assertTrue(os.path.isfile(file_to_stay), f"{self.pbt.which_test} : file_to_stay was removed {file_to_stay}")

        # remove empty folders, with known file ignored - so to folder should be removed
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += RemoveEmptyFolders(folder_to_remove, files_to_ignore=['.DS_Store', "paramedic"])
        self.pbt.exec_and_capture_output("remove empty folders")
        self.assertFalse(os.path.isdir(folder_to_remove), f"{self.pbt.which_test} : folder was not removed {folder_to_remove}")
        self.assertFalse(os.path.isfile(file_to_stay), f"{self.pbt.which_test} : file_to_stay was not removed {file_to_stay}")
