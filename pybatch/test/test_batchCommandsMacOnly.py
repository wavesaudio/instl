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


from test_PythonBatchBase import *


class TestPythonBatchMac(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def private_test_ConvertFolderOfSymlinks(self):
        """ to enable this test give a real path as folder_of_symlinks, preferably one with symlinks..."""

        if sys.platform != 'darwin':
            return

        folder_of_symlinks = Path("/Users/shai/Desktop/Tk.framework")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += CreateSymlinkFilesInFolder(folder_of_symlinks)
        self.pbt.exec_and_capture_output("test_ConvertFolderOfSymlinks_to_symlink_files")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += ResolveSymlinkFilesInFolder(folder_of_symlinks)
        self.pbt.exec_and_capture_output("test_ConvertFolderOfSymlinks_from_symlink_files")

    def test_MacDoc_repr(self):
        obj = MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"MacDoc.repr did not recreate MacDoc object correctly: {diff_explanation}")

        obj = MacDock("/Santa/Catalina/Island", "Santa Catalina Island", False)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"MacDoc.repr did not recreate MacDoc object correctly: {diff_explanation}")

        obj = MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True, remove=True)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"MacDoc.repr did not recreate MacDoc object correctly: {diff_explanation}")

    def test_MacDoc(self):
        if sys.platform == "darwin":
            pass  # who do we check this?

    def test_CreateSymlink_repr(self):

        if sys.platform != 'darwin':
            return

        some_file_path = "/Pippi/Långstrump"
        some_symlink_path = "/Astrid/Anna/Emilia/Lindgren"
        obj = CreateSymlink(some_symlink_path, some_file_path)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"CreateSymlink.repr did not recreate CreateSymlink object correctly: {diff_explanation}")

    def test_CreateSymlink(self):

        if sys.platform != 'darwin':
            return

        a_file_to_symlink = self.pbt.path_inside_test_folder("symlink_me_file")
        symlink_to_a_file = self.pbt.path_inside_test_folder("symlink_of_a_file")
        relative_symlink_to_a_file = self.pbt.path_inside_test_folder("relative_symlink_of_a_file")
        a_folder_to_symlink = self.pbt.path_inside_test_folder("symlink_me_folder")
        symlink_to_a_folder = self.pbt.path_inside_test_folder("symlink_of_a_folder")
        relative_symlink_to_a_folder = self.pbt.path_inside_test_folder("relative_symlink_of_a_folder")

        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as iSubSub:
            iSubSub += Touch(a_file_to_symlink)
            iSubSub += MakeDirs(a_folder_to_symlink)
            iSubSub += CreateSymlink(symlink_to_a_file, a_file_to_symlink)
            iSubSub += CreateSymlink(symlink_to_a_folder, a_folder_to_symlink)
            iSubSub += CreateSymlink(relative_symlink_to_a_file, a_file_to_symlink.name)
            iSubSub += CreateSymlink(relative_symlink_to_a_folder, a_folder_to_symlink.name)
        self.pbt.exec_and_capture_output("CreateSymlink")

        self.assertFalse(os.path.islink(a_file_to_symlink), f"CreateSymlink {a_file_to_symlink} should be a file not a symlink")
        self.assertFalse(os.path.islink(a_folder_to_symlink), f"CreateSymlink {a_folder_to_symlink} should be a file not a symlink")
        self.assertTrue(os.path.islink(symlink_to_a_file), f"CreateSymlink {symlink_to_a_file} should be a symlink")
        self.assertTrue(os.path.islink(symlink_to_a_folder), f"CreateSymlink {symlink_to_a_folder} should be a symlink")
        self.assertTrue(os.path.islink(relative_symlink_to_a_file), f"CreateSymlink {relative_symlink_to_a_file} should be a symlink")
        self.assertTrue(os.path.islink(relative_symlink_to_a_folder), f"CreateSymlink {relative_symlink_to_a_folder} should be a symlink")

        # check the absolute symlinks
        a_file_original_from_symlink = os.readlink(symlink_to_a_file)
        a_folder_original_from_symlink = os.readlink(symlink_to_a_folder)
        self.assertTrue(a_file_to_symlink.samefile(a_file_original_from_symlink), f"symlink resolved to {a_file_original_from_symlink} not to {a_file_to_symlink} as expected")
        self.assertTrue(a_folder_to_symlink.samefile(a_folder_original_from_symlink), f"symlink resolved to {a_folder_original_from_symlink} not to {a_folder_to_symlink} as expected")

        # check the relative symlinks
        a_file_original_from_relative_symlink = self.pbt.path_inside_test_folder(os.readlink(relative_symlink_to_a_file))
        a_folder_original_from_relative_symlink = self.pbt.path_inside_test_folder(os.readlink(relative_symlink_to_a_folder))
        self.assertTrue(a_file_to_symlink.samefile(a_file_original_from_relative_symlink), f"symlink resolved to {a_file_original_from_relative_symlink} not to {a_file_to_symlink} as expected")
        self.assertTrue(a_folder_to_symlink.samefile(a_folder_original_from_relative_symlink), f"symlink resolved to {a_folder_original_from_relative_symlink} not to {a_folder_to_symlink} as expected")

    def test_SymlinkToSymlinkFile_repr(self):

        if sys.platform != 'darwin':
            return

        some_file_path = "/Pippi/Långstrump"
        obj = SymlinkToSymlinkFile(some_file_path)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"SymlinkToSymlinkFile.repr did not recreate SymlinkToSymlinkFile object correctly: {diff_explanation}")

    def test_SymlinkToSymlinkFileAndBack(self):
        """ since symlinks cannot be uploaded (or downloaded) to S3, instl replaces them with
            a .symlink file that contains the target of the original symlink.
            Before uploading SymlinkToSymlinkFile is called
            After downloading SymlinkFileToSymlink is called
        """

        if sys.platform != 'darwin':
            return

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

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Touch(file_symlink_test_data.original_to_symlink)
        self.pbt.batch_accum += MakeDirs(folder_symlink_test_data.original_to_symlink)
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

        self.pbt.batch_accum.clear()
        for test_data in file_symlink_test_data, folder_symlink_test_data:
            self.pbt.batch_accum += SymlinkFileToSymlink(test_data.symlink_file_of_original)
            self.pbt.batch_accum += SymlinkFileToSymlink(test_data.symlink_file_of_relative)
        self.pbt.exec_and_capture_output("SymlinkToSymlinkFile resolving symlink files")

        self.pbt.batch_accum.clear()
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

        if sys.platform != 'darwin':
            return

        some_file_path = "/Pippi/Långstrump.symlink"
        obj = SymlinkFileToSymlink(some_file_path)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"SymlinkToSymlinkFile.repr did not resolve SymlinkToSymlinkFile object correctly: {diff_explanation}")

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


