#!/usr/bin/env python3.6


import sys
import os
from pathlib import Path
from unittest import TestCase
import shutil
import stat
import ctypes
import io
import contextlib
import filecmp
import random
import string
from collections import namedtuple
import unittest

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum
from configVar import config_vars


from .test_PythonBatchBase import *


class TestPythonBatchMac(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    @unittest.skipUnless(running_on_Mac, "Mac only test")
    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def private_test_ConvertFolderOfSymlinks(self):
        """ to enable this test give a real path as folder_of_symlinks, preferably one with symlinks..."""

        folder_of_symlinks = Path("/Users/shai/Desktop/Tk.framework")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += CreateSymlinkFilesInFolder(folder_of_symlinks)
        self.pbt.exec_and_capture_output("test_ConvertFolderOfSymlinks_to_symlink_files")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += ResolveSymlinkFilesInFolder(folder_of_symlinks)
        self.pbt.exec_and_capture_output("test_ConvertFolderOfSymlinks_from_symlink_files")

    def test_MacDoc_repr(self):
        self.pbt.reprs_test_runner(MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True),
                                   MacDock("/Santa/Catalina/Island", "Santa Catalina Island", False),
                                   MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True, remove=True))

    def test_MacDoc_add_to_and_restart_dock(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(app_to_add_to_dock, restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_add_to_and_restart_dock")

    def test_MacDoc_remove_from_and_restart_dock(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(app_to_add_to_dock, remove=True, restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_remove_from_and_restart_dock")

    def test_MacDoc_add_to_and_restart_dock_separately(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(app_to_add_to_dock)
        self.pbt.batch_accum += MacDock(restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_add_to_and_restart_dock_separately")

    def test_MacDoc_remove_from_and_restart_dock_separately(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(app_to_add_to_dock, remove=True, restart_the_doc=False)
        self.pbt.batch_accum += MacDock(restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_remove_from_and_restart_dock_separately")

    def test_MacDoc_just_restart_dock(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_remove_from_dock")

    def test_CreateSymlink_repr(self):
        some_file_path = "/Pippi/Långstrump"
        some_symlink_path = "/Astrid/Anna/Emilia/Lindgren"
        self.pbt.reprs_test_runner(CreateSymlink(some_symlink_path, some_file_path))

    def test_CreateSymlink(self):
        a_file_to_symlink_to = self.pbt.path_inside_test_folder("a_file_to_symlink_to")
        symlink_to_a_file = self.pbt.path_inside_test_folder("symlink_to_a_file")
        relative_symlink_to_a_file = self.pbt.path_inside_test_folder("relative_symlink_to_a_file")
        a_folder_to_symlink_to = self.pbt.path_inside_test_folder("a_folder_to_symlink_to")
        symlink_to_a_folder = self.pbt.path_inside_test_folder("symlink_to_a_folder")
        relative_symlink_to_a_folder = self.pbt.path_inside_test_folder("relative_symlink_to_a_folder")

        self.pbt.batch_accum.clear(section_name="doit")
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as iSubSub:
            iSubSub += Touch(a_file_to_symlink_to)
            iSubSub += MakeDir(a_folder_to_symlink_to)
            iSubSub += CreateSymlink(symlink_to_a_file, a_file_to_symlink_to)
            iSubSub += CreateSymlink(symlink_to_a_folder, a_folder_to_symlink_to)
            iSubSub += CreateSymlink(relative_symlink_to_a_file, a_file_to_symlink_to.name)
            iSubSub += CreateSymlink(relative_symlink_to_a_folder, a_folder_to_symlink_to.name)
        self.pbt.exec_and_capture_output("CreateSymlink")

        self.assertFalse(os.path.islink(a_file_to_symlink_to), f"CreateSymlink {a_file_to_symlink_to} should be a file not a symlink")
        self.assertFalse(os.path.islink(a_folder_to_symlink_to), f"CreateSymlink {a_folder_to_symlink_to} should be a file not a symlink")
        self.assertTrue(os.path.islink(symlink_to_a_file), f"CreateSymlink {symlink_to_a_file} should be a symlink")
        self.assertTrue(os.path.islink(symlink_to_a_folder), f"CreateSymlink {symlink_to_a_folder} should be a symlink")
        self.assertTrue(os.path.islink(relative_symlink_to_a_file), f"CreateSymlink {relative_symlink_to_a_file} should be a symlink")
        self.assertTrue(os.path.islink(relative_symlink_to_a_folder), f"CreateSymlink {relative_symlink_to_a_folder} should be a symlink")

        # check the absolute symlinks
        a_file_original_from_symlink = os.readlink(symlink_to_a_file)
        a_folder_original_from_symlink = os.readlink(symlink_to_a_folder)
        self.assertTrue(a_file_to_symlink_to.samefile(a_file_original_from_symlink), f"symlink resolved to {a_file_original_from_symlink} not to {a_file_to_symlink_to} as expected")
        self.assertTrue(a_folder_to_symlink_to.samefile(a_folder_original_from_symlink), f"symlink resolved to {a_folder_original_from_symlink} not to {a_folder_to_symlink_to} as expected")

        # check the relative symlinks
        a_file_original_from_relative_symlink = self.pbt.path_inside_test_folder(os.readlink(relative_symlink_to_a_file), assert_not_exist=False)
        a_folder_original_from_relative_symlink = self.pbt.path_inside_test_folder(os.readlink(relative_symlink_to_a_folder), assert_not_exist=False)
        self.assertTrue(a_file_to_symlink_to.samefile(a_file_original_from_relative_symlink), f"symlink resolved to {a_file_original_from_relative_symlink} not to {a_file_to_symlink_to} as expected")
        self.assertTrue(a_folder_to_symlink_to.samefile(a_folder_original_from_relative_symlink), f"symlink resolved to {a_folder_original_from_relative_symlink} not to {a_folder_to_symlink_to} as expected")

    def test_SymlinkToSymlinkFile_repr(self):
        some_file_path = "/Pippi/Långstrump"
        self.pbt.reprs_test_runner(SymlinkToSymlinkFile(some_file_path))

    def test_SymlinkToSymlinkFileAndBack(self):
        """ since symlinks cannot be uploaded (or downloaded) to S3, instl replaces them with
            a .symlink file that contains the target of the original symlink.
            Before uploading SymlinkToSymlinkFile is called
            After downloading SymlinkFileToSymlink is called
        """
        SymlinkTestData = namedtuple('SymlinkTestData', ['original_to_symlink', 'symlink_to_a_original', 'symlink_file_of_original', 'relative_symlink_to_a_original', 'symlink_file_of_relative'])

        def create_symlink_test_data(name):
            """ a helper function to create paths to original, symlinks and symlink files"""
            original_to_symlink = self.pbt.path_inside_test_folder(name)

            symlink_to_a_original = self.pbt.path_inside_test_folder(f"symlink_of_{name}")
            relative_symlink_to_a_original = self.pbt.path_inside_test_folder(f"relative_symlink_of_{name}")

            symlink_file_of_original = Path(os.fspath(symlink_to_a_original)+".symlink")
            symlink_file_of_relative = Path(os.fspath(relative_symlink_to_a_original)+".symlink")

            return SymlinkTestData(original_to_symlink, symlink_to_a_original, symlink_file_of_original, relative_symlink_to_a_original, symlink_file_of_relative)

        file_symlink_test_data = create_symlink_test_data("a_file")
        folder_symlink_test_data = create_symlink_test_data("a_folder")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += Touch(file_symlink_test_data.original_to_symlink)
        self.pbt.batch_accum += MakeDir(folder_symlink_test_data.original_to_symlink)
        for test_data in file_symlink_test_data, folder_symlink_test_data:
            with self.pbt.batch_accum.sub_accum(CdStage(test_data.original_to_symlink.name, self.pbt.test_folder)) as symlink_test_accum:
                symlink_test_accum += CreateSymlink(test_data.symlink_to_a_original, test_data.original_to_symlink)                # symlink with full path
                symlink_test_accum += CreateSymlink(test_data.relative_symlink_to_a_original, test_data.original_to_symlink.name)  # symlink with relative path
                symlink_test_accum += SymlinkToSymlinkFile(test_data.symlink_to_a_original)
                symlink_test_accum += SymlinkToSymlinkFile(test_data.relative_symlink_to_a_original)

        self.pbt.exec_and_capture_output("SymlinkToSymlinkFile Creating symlink files")

        for test_data in file_symlink_test_data, folder_symlink_test_data:
            self.assertFalse(os.path.islink(test_data[0]), f"SymlinkToSymlinkFile {test_data.original_to_symlink} should be a file not a symlink")
            self.assertFalse(test_data.symlink_to_a_original.exists(), f"SymlinkToSymlinkFile {test_data.symlink_to_a_original} should have been erased")
            self.assertFalse(test_data.relative_symlink_to_a_original.exists(), f"SymlinkToSymlinkFile {test_data.relative_symlink_to_a_original} should have been erased")
            self.assertTrue(test_data.symlink_file_of_original.is_file(), f"SymlinkToSymlinkFile {test_data.symlink_file_of_original} should have been replaced by .symlink file")
            self.assertTrue(test_data.symlink_file_of_relative.is_file(), f"SymlinkToSymlinkFile {test_data.symlink_file_of_relative} should be replaced by .symlink file")

        return

        self.pbt.batch_accum.clear(section_name="doit")
        for test_data in file_symlink_test_data, folder_symlink_test_data:
            self.pbt.batch_accum += SymlinkFileToSymlink(test_data.symlink_file_of_original)
            self.pbt.batch_accum += SymlinkFileToSymlink(test_data.symlink_file_of_relative)
        self.pbt.exec_and_capture_output("SymlinkToSymlinkFile resolving symlink files")

        self.pbt.batch_accum.clear(section_name="doit")
        for test_data in file_symlink_test_data, folder_symlink_test_data:
            # check that the absolute and relative symlinks have been created
            self.assertTrue(test_data.symlink_to_a_original.is_symlink(), f"SymlinkToSymlinkFile {test_data.symlink_to_a_original} should have been created")
            self.assertTrue(test_data.relative_symlink_to_a_original.is_symlink(), f"SymlinkToSymlinkFile {test_data.relative_symlink_to_a_original} should have been created")

            # check that the absolute and relative symlinks files have been removed
            self.assertFalse(test_data.symlink_file_of_original.exists(), f"SymlinkToSymlinkFile {test_data.symlink_file_of_original} should have been erased")
            self.assertFalse(test_data.symlink_file_of_relative.exists(), f"SymlinkToSymlinkFile {test_data.symlink_file_of_relative} should have been erased")

            an_original_from_symlink = os.readlink(test_data.symlink_to_a_original)
            an_original_from_relative_symlink = os.readlink(test_data.relative_symlink_to_a_original)

            # check that the absolute and relative symlinks files point to the original
            self.assertTrue(test_data.original_to_symlink.samefile(an_original_from_symlink), f"symlink resolved to {an_original_from_symlink} not to {test_data.symlink_to_a_original} as expected")
            os.chdir(self.pbt.test_folder)  # so relative resolve of symlink will work
            self.assertTrue(test_data.original_to_symlink.samefile(an_original_from_relative_symlink), f"symlink resolved to {an_original_from_relative_symlink} not to {test_data.symlink_to_a_original} as expected")

    def test_SymlinkFileToSymlink_repr(self):
        some_file_path = "/Pippi/Långstrump.symlink"
        self.pbt.reprs_test_runner(SymlinkFileToSymlink(some_file_path))

    def test_SymlinkFileToSymlink(self):
        pass

    def test_CreateSymlinkFilesInFolder_repr(self):
        pass

    def test_CreateSymlinkFilesInFolder(self):
        pass

    def test_ResolveSymlinkFilesInFolder_repr(self):
        pass

    def test_ResolveSymlinkFilesInFolder(self):
        pass

    def test_RmSymlink_repr(self):
        self.pbt.reprs_test_runner(RmSymlink(r"/just/remove/me/already"))

    def test_RmSymlink(self):
        non_existing_path = self.pbt.path_inside_test_folder("non-existing-path")
        a_dir = self.pbt.path_inside_test_folder("some-dir")
        a_file = self.pbt.path_inside_test_folder("some-file")
        a_dir_symlink = self.pbt.path_inside_test_folder("some-dir-symlink")
        a_file_symlink = self.pbt.path_inside_test_folder("some-file-symlink")

        # create a file, a folder and symlinks to them
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(a_dir)
        self.pbt.batch_accum += Touch(a_file)
        self.pbt.batch_accum += CreateSymlink(a_dir_symlink, a_dir)
        self.pbt.batch_accum += CreateSymlink(a_file_symlink, a_file)
        self.pbt.exec_and_capture_output()
        self.assertFalse(non_existing_path.exists())
        self.assertTrue(a_dir.is_dir())
        self.assertTrue(a_file.is_file())
        self.assertTrue(a_dir_symlink.is_symlink())
        self.assertTrue(a_file_symlink.is_symlink())

        # remove everything with RmSymlink, but only the symlink should be actually removed
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += RmSymlink(non_existing_path)
        self.pbt.batch_accum += RmSymlink(a_dir)
        self.pbt.batch_accum += RmSymlink(a_file)
        self.pbt.batch_accum += RmSymlink(a_dir_symlink)
        self.pbt.batch_accum += RmSymlink(a_file_symlink)
        self.pbt.exec_and_capture_output()
        self.assertFalse(non_existing_path.exists())
        self.assertTrue(a_dir.is_dir())
        self.assertTrue(a_file.is_file())
        self.assertFalse(a_dir_symlink.exists())
        self.assertFalse(a_file_symlink.exists())

