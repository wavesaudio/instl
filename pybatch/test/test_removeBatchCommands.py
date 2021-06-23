#!/usr/bin/env python3.9


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

running_on_Mac = sys.platform == 'darwin'
running_on_Win = sys.platform == 'win32'


from .test_PythonBatchBase import *


class TestPythonBatchRemove(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_RmFile_repr(self):
        self.pbt.reprs_test_runner(RmFile(r"\just\remove\me\already"))

    def test_RmFile(self):
        file_actually_a_folder = self.pbt.path_inside_test_folder("file_actually_a_folder")
        self.assertFalse(file_actually_a_folder.exists(), f"file exists '{file_actually_a_folder}'")
        file_not_existing = self.pbt.path_inside_test_folder("file_not_existing")
        self.assertFalse(file_not_existing.exists(), f"file exists '{file_not_existing}'")
        file_easy_to_remove = self.pbt.path_inside_test_folder("file_easy_to_remove")
        self.assertFalse(file_easy_to_remove.exists(), f"file exists '{file_easy_to_remove}'")

        if running_on_Mac:
            file_no_permissions = self.pbt.path_inside_test_folder("file_no_permissions")
            self.assertFalse(file_no_permissions.exists(), f"file exists '{file_no_permissions}'")
        file_locked = self.pbt.path_inside_test_folder("file_locked")
        self.assertFalse(file_locked.exists(), f"file exists '{file_locked}'")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(file_actually_a_folder)
        self.pbt.batch_accum += Touch(file_easy_to_remove)
        if running_on_Mac:
            self.pbt.batch_accum += Touch(file_no_permissions)
            self.pbt.batch_accum += Chmod(file_no_permissions, "a-w")
        self.pbt.batch_accum += Touch(file_locked)
        self.pbt.batch_accum += ChFlags(file_locked,'locked')
        self.pbt.exec_and_capture_output("create files to remove")
        self.assertTrue(file_actually_a_folder.exists(), f"folder was not created '{file_actually_a_folder}'")
        self.assertTrue(file_easy_to_remove.exists(), f"file was not created '{file_easy_to_remove}'")
        if running_on_Mac:
            self.assertTrue(file_no_permissions.exists(), f"file was not created '{file_no_permissions}'")
        self.assertTrue(file_locked.exists(), f"file was not created '{file_locked}'")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += RmFile(file_actually_a_folder)
        self.pbt.batch_accum += RmFile(file_not_existing)
        self.pbt.batch_accum += RmFile(file_easy_to_remove)
        if running_on_Mac:
            self.pbt.batch_accum += RmFile(file_no_permissions)
        self.pbt.batch_accum += RmFile(file_locked)
        self.pbt.exec_and_capture_output("remove files")
        self.assertFalse(file_easy_to_remove.exists(), f"file was not removed '{file_easy_to_remove}'")
        if running_on_Mac:
            self.assertFalse(file_no_permissions.exists(), f"file was not removed '{file_no_permissions}'")
        self.assertFalse(file_locked.exists(), f"file was not removed '{file_locked}'")

    def test_RmDir_repr(self):
       self.pbt.reprs_test_runner(RmDir(r"\just\remove\me\already"))

    def test_RmDir(self):
        # some files to be removed as if they were a folder
        files_map = {name: self.pbt.path_inside_test_folder(name) for name in ("file_pretending_to_be_a_folder", "file_pretending_to_be_a_folder_no_permissions", "file_pretending_to_be_a_folder_locked")}
        for _file_path in files_map.values():
            self.assertFalse(_file_path.exists(), f"file already exists '{_file_path}'")

        # some folders to be removed
        folder_not_existing = self.pbt.path_inside_test_folder("folder_not_existing")
        folders_map = {name: self.pbt.path_inside_test_folder(name) for name in ("folder_easy_to_remove", "folder_no_permissions", "folder_locked")}
        if not running_on_Mac:
            folders_map.pop("folder_no_permissions")
        for _folder_path in folders_map.values():
            self.assertFalse(_folder_path.exists(), f"file already exists '{_folder_path}'")

        self.pbt.batch_accum.clear(section_name="doit")
        for _file_path in files_map.values():
            self.pbt.batch_accum += Touch(_file_path)
        if running_on_Mac:
            self.pbt.batch_accum += Chmod(files_map["file_pretending_to_be_a_folder_no_permissions"], "a=r")
        self.pbt.batch_accum += ChFlags(files_map["file_pretending_to_be_a_folder_locked"], 'locked')

        for _folder_path in folders_map.values():
            self.pbt.batch_accum += MakeDir(_folder_path)
        if running_on_Mac:
            self.pbt.batch_accum += Chmod(folders_map["folder_no_permissions"], "a=r")
        self.pbt.batch_accum += ChFlags(folders_map["folder_locked"],'locked')
        self.pbt.batch_accum += MakeDir(folder_not_existing)
        self.pbt.exec_and_capture_output("create files and folders to remove")

        # check that all files and folders were created
        for _folder_path in itertools.chain(folders_map.values(), files_map.values()):
            self.assertTrue(_folder_path.exists(), f"folder/file already exists '{_folder_path}'")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += RmDir(folder_not_existing)
        for _folder_path in itertools.chain(folders_map.values(), files_map.values()):
            self.pbt.batch_accum += RmDir(_folder_path)
        self.pbt.exec_and_capture_output("remove folders")

        for _folder_path in itertools.chain(folders_map.values(), files_map.values()):
            self.assertFalse(_folder_path.exists(), f"folder/file still exists '{_folder_path}'")

    def test_RmFileOrDir_repr(self):
        self.pbt.reprs_test_runner(RmFileOrDir(r"/just/remove/me/already"))

    def test_RmFileOrDir(self):
        pass

    def test_remove(self):
        """ Create a folder and fill it with random files.
            1st try to remove the folder with RmFile which should fail and raise exception
            2nd try to remove the folder with RmDir which should work
        """
        dir_to_remove = self.pbt.path_inside_test_folder("remove-me")
        self.assertFalse(dir_to_remove.exists())

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(dir_to_remove)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_remove)) as sub_bc:
            sub_bc += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
        self.pbt.batch_accum += RmFile(dir_to_remove)  # RmFile should not remove a folder
        self.pbt.exec_and_capture_output(expected_exception=PermissionError)
        self.assertTrue(dir_to_remove.exists())

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += RmDir(dir_to_remove)
        self.pbt.exec_and_capture_output()
        self.assertFalse(dir_to_remove.exists())

    def test_RemoveEmptyFolders_repr(self):
        with self.assertRaises(TypeError):
            obj = RemoveEmptyFolders()

        list_of_objs = list()
        list_of_objs.append(RemoveEmptyFolders("/per/pen/di/cular"))
        list_of_objs.append(RemoveEmptyFolders("/per/pen/di/cular", files_to_ignore=[]))
        list_of_objs.append(RemoveEmptyFolders("/per/pen/di/cular", files_to_ignore=['async', 'await']))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_RemoveEmptyFolders(self):
        folder_to_remove = self.pbt.path_inside_test_folder("folder-to-remove")
        file_to_stay = folder_to_remove.joinpath("paramedic")

        # create the folder, with sub folder and one known file
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(folder_to_remove)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_remove)) as cd_accum:
            cd_accum += Touch(file_to_stay.name)
            cd_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=2, num_files_per_dir=0, file_size=41)
        self.pbt.exec_and_capture_output("create empty folders")
        self.assertTrue(os.path.isdir(folder_to_remove), f"{self.pbt.which_test} : folder to remove was not created {folder_to_remove}")
        self.assertTrue(os.path.isfile(file_to_stay), f"{self.pbt.which_test} : file_to_stay was not created {file_to_stay}")

        # remove empty folders, top folder and known file should remain
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += RemoveEmptyFolders(folder_to_remove, files_to_ignore=['.DS_Store'])
        # removing non existing folder should not be a problem
        self.pbt.batch_accum += RemoveEmptyFolders("kajagogo", files_to_ignore=['.DS_Store'])
        self.pbt.exec_and_capture_output("remove almost empty folders")
        self.assertTrue(os.path.isdir(folder_to_remove), f"{self.pbt.which_test} : folder was removed although it had a legit file {folder_to_remove}")
        self.assertTrue(os.path.isfile(file_to_stay), f"{self.pbt.which_test} : file_to_stay was removed {file_to_stay}")

        # remove empty folders, with known file ignored - so to folder should be removed
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += RemoveEmptyFolders(folder_to_remove, files_to_ignore=['.DS_Store', "parame.+"])
        self.pbt.exec_and_capture_output("remove empty folders")
        self.assertFalse(os.path.isdir(folder_to_remove), f"{self.pbt.which_test} : folder was not removed {folder_to_remove}")
        self.assertFalse(os.path.isfile(file_to_stay), f"{self.pbt.which_test} : file_to_stay was not removed {file_to_stay}")

    def test_RmGlob_repr(self):
        self.pbt.reprs_test_runner(RmGlob("/lo/lla/pa/loo/za", "*.pendicular"))

    def test_RmGlob(self):
        folder_to_glob = self.pbt.path_inside_test_folder("folder-to-glob")

        pattern = "?b*.k*"
        files_that_should_be_removed = ["abc.kif", "cba.kmf"]
        files_that_should_not_be_removed = ["acb.kof", "bac.kaf", "bca.kuf", "cab.kef"]

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(folder_to_glob)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_glob)) as cd_accum:
            for f in files_that_should_be_removed + files_that_should_not_be_removed:
                cd_accum += Touch(f)

        self.pbt.batch_accum += RmGlob(os.fspath(folder_to_glob), pattern)
        self.pbt.exec_and_capture_output()

        for f in files_that_should_be_removed:
            fp = Path(folder_to_glob, f)
            self.assertFalse(fp.is_file(), f"{self.pbt.which_test} : file was not removed {fp}")

        for f in files_that_should_not_be_removed:
            fp = Path(folder_to_glob, f)
            self.assertTrue(fp.is_file(), f"{self.pbt.which_test} : file was removed {fp}")

    def test_RmGlobs_repr(self):
        list_of_objs = list()
        list_of_objs.append(RmGlobs("/lo/lla/pa/loo/za"))
        list_of_objs.append(RmGlobs("/lo/lla/pa/loo/za", "*.pendicular"))
        list_of_objs.append(RmGlobs("/lo/lla/pa/loo/za", "*.pendicular", "i*regular.??"))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_RmGlobs(self):
        folder_to_glob = self.pbt.path_inside_test_folder("folder-to-glob")

        patterns = "?b*.k*", "*mama*"
        files_that_should_be_removed = ["abc.kif", "cba.kmf", "hi-mama", "mama-hi", "mama"]
        files_that_should_not_be_removed = ["acb.kof", "bac.kaf", "bca.kuf", "cab.kef", "big-mami"]

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(folder_to_glob)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_glob)) as cd_accum:
            for f in files_that_should_be_removed + files_that_should_not_be_removed:
                cd_accum += Touch(f)

        self.pbt.batch_accum += RmGlobs(os.fspath(folder_to_glob), *patterns)
        self.pbt.exec_and_capture_output()

        for f in files_that_should_be_removed:
            fp = Path(folder_to_glob, f)
            self.assertFalse(fp.is_file(), f"{self.pbt.which_test} : file was not removed {fp}")

        for f in files_that_should_not_be_removed:
            fp = Path(folder_to_glob, f)
            self.assertTrue(fp.is_file(), f"{self.pbt.which_test} : file was removed {fp}")

    def test_RmDirContents_repr(self):
        list_of_objs = list()
        list_of_objs.append(RmDirContents("/lo/lla/pa/loo/za"))
        list_of_objs.append(RmDirContents("/lo/lla/pa/loo/za", ["pendicular"]))
        list_of_objs.append(RmDirContents("/lo/lla/pa/loo/za", ["*.pendicular", "i*regular.??"]))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_RmDirContents(self):
        folder_to_clear = self.pbt.path_inside_test_folder("folder-to-clear")

        files_that_should_be_removed = ["abc.kif", "cba.kmf", "hi-mama", "mama-hi", "mama"]
        files_that_should_not_be_removed = ["acb.kof", "bac.kaf", "bca.kuf", "cab.kef", "big-mami"]

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(folder_to_clear)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_clear)) as cd_accum:
            for f in files_that_should_be_removed + files_that_should_not_be_removed:
                cd_accum += Touch(f)

        self.pbt.batch_accum += RmDirContents(os.fspath(folder_to_clear), exclude=files_that_should_not_be_removed)
        self.pbt.exec_and_capture_output()

        for f in files_that_should_be_removed:
            fp = Path(folder_to_clear, f)
            self.assertFalse(fp.is_file(), f"{self.pbt.which_test} : file was not removed {fp}")

        for f in files_that_should_not_be_removed:
            fp = Path(folder_to_clear, f)
            self.assertTrue(fp.is_file(), f"{self.pbt.which_test} : file was removed {fp}")


