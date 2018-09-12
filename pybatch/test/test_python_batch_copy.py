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

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum
from configVar import config_vars


from testPythonBatch import *


class TestPythonBatchCopy(TestPythonBatch):
    def __init__(self, which_test="pineapple"):
        super().__init__(which_test)

    def test_RsyncClone(self):
        """ test RsyncClone (with/without using rsync's link_dest option)
            a directory is created and filled with random files and folders.
            This directory is copied and both source and targets dirs are compared to make sure they are the same.

            without hard links:
                Folder structure and files should be identical

            with hard links:
                - All mirrored files should have the same inode number - meaning they are hard links to
            the same file.

                - Currently this test fails for unknown reason. The rsync command does not create hard links.
            The exact same rsync command when ran for terminal creates the hard links. So I assume the
            rsync command is correct but running it from python changes something.

        """
        dir_to_copy_from = self.path_inside_test_folder("copy-src")
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")

        dir_to_copy_to_no_hard_links = self.path_inside_test_folder("copy-target-no-hard-links")
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.path_inside_test_folder("copy-target-with-hard-links")
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        dir_to_copy_to_with_ignore = self.path_inside_test_folder("copy-target-with-ignore")
        self.assertFalse(dir_to_copy_to_with_ignore.exists(), f"{self.which_test}: {dir_to_copy_to_with_ignore} should not exist before test")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_copy_from)
        with self.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
        self.batch_accum += RsyncClone(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.batch_accum += RsyncClone(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        file_names_to_ignore = ["hootenanny"]
        self.batch_accum += RsyncClone(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=file_names_to_ignore)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.which_test} (with hard links): source and target files are not hard links to the same file")
        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, file_names_to_ignore)

    def test_CopyDirToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        ong = CopyDirToDir(dir_from, dir_to, hard_links=False)
        ong_repr = repr(ong)
        ong_recreated = eval(ong_repr)
        self.assertEqual(ong, ong_recreated, "CopyDirToDir.repr did not recreate CopyDirToDir object correctly")

    def test_MoveDirToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        ong = MoveDirToDir(dir_from, dir_to, ignore_if_not_exist=False)
        ong_repr = repr(ong)
        ong_recreated = eval(ong_repr)
        self.assertEqual(ong, ong_recreated, "MoveDirToDir.repr did not recreate MoveDirToDir object correctly")

    def test_CopyDirToDir(self):
        """ test CopyDirToDir (with/without using hard links)
            a directory is created and filled with random files and folders.
            This directory is copied and both source and targets dirs are compared to make sure they are the same.

            without hard links:
                Folder structure and files should be identical

            with hard links:
                - All mirrored files should have the same inode number - meaning they are hard links to
            the same file.
        """
        dir_to_copy_from = self.path_inside_test_folder("copy-src")
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")

        dir_to_copy_to_no_hard_links = self.path_inside_test_folder("copy-target-no-hard-links")
        copied_dir_no_hard_links = dir_to_copy_to_no_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.path_inside_test_folder("copy-target-with-hard-links")
        copied_dir_with_hard_links = dir_to_copy_to_with_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        dir_to_copy_to_with_ignore = self.path_inside_test_folder("copy-target-with-ignore")
        copied_dir_with_ignore = dir_to_copy_to_with_ignore.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_with_ignore.exists(), f"{self.which_test}: {dir_to_copy_to_with_ignore} should not exist before test")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_copy_from)
        with self.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
        self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        filen_names_to_ignore = ["hootenanny"]
        self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=filen_names_to_ignore)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.which_test} (with hard links): source and target files are not hard links to the same file")
        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, filen_names_to_ignore)

    def test_CopyDirContentsToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        cdctd_obj = CopyDirContentsToDir(dir_from, dir_to, link_dest=True)
        cdctd_obj_recreated = eval(repr(cdctd_obj))
        self.assertEqual(cdctd_obj, cdctd_obj_recreated, "CopyDirContentsToDir.repr did not recreate CopyDirContentsToDir object correctly")

    def test_CopyDirContentsToDir(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contents
            should be copied - not the source dir itself.
        """
        dir_to_copy_from = self.path_inside_test_folder("copy-src")
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")

        dir_to_copy_to_no_hard_links = self.path_inside_test_folder("copy-target-no-hard-links")
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.path_inside_test_folder("copy-target-with-hard-links")
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        dir_to_copy_to_with_ignore = self.path_inside_test_folder("copy-target-with-ignore")
        self.assertFalse(dir_to_copy_to_with_ignore.exists(), f"{self.which_test}: {dir_to_copy_to_with_ignore} should not exist before test")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_copy_from)
        with self.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
        self.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        filen_names_to_ignore = ["hootenanny"]
        self.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=filen_names_to_ignore)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.which_test} (with hard links): source and target files are not hard  links to the same file")

        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, filen_names_to_ignore)

    def test_CopyFileToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        cftd_obj = CopyFileToDir(dir_from, dir_to, hard_links=False)
        cftd_obj_recreated = eval(repr(cftd_obj))
        self.assertEqual(cftd_obj, cftd_obj_recreated, "CopyFileToDir.repr did not recreate CopyFileToDir object correctly")

    def test_CopyFileToDir(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contains
            one file that is copied by it's full path.
        """
        file_name = "hootenanny"
        dir_to_copy_from = self.path_inside_test_folder("copy-src")
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")
        file_to_copy = dir_to_copy_from.joinpath(file_name).resolve()

        dir_to_copy_to_no_hard_links = self.path_inside_test_folder("copy-target-no-hard-links")
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.path_inside_test_folder("copy-target-with-hard-links")
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_copy_from)
        self.batch_accum += MakeDirs(dir_to_copy_to_no_hard_links)
        with self.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch(file_name)  # add one file
        self.batch_accum += CopyFileToDir(file_to_copy, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.batch_accum += CopyFileToDir(file_to_copy, dir_to_copy_to_with_hard_links, hard_links=True)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.which_test} (with hard links): source and target files are not hard links to the same file")

    def test_CopyFileToFile_repr(self):
        dir_from = r"\p\o\i"
        cftf_obj = CopyFileToFile(dir_from, "/sugar/man", hard_links=False, copy_owner=True)
        cftf_obj_recreated = eval(repr(cftf_obj))
        self.assertEqual(cftf_obj, cftf_obj_recreated, "CopyFileToFile.repr did not recreate CopyFileToFile object correctly")

    def test_CopyFileToFile(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contains
            one file that is copied by it's full path and target is a full path to a file.
        """
        file_name = "hootenanny"
        dir_to_copy_from = self.path_inside_test_folder("copy-src")
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")
        file_to_copy = dir_to_copy_from.joinpath(file_name).resolve()

        target_dir_no_hard_links = self.path_inside_test_folder("target_dir_no_hard_links")
        self.assertFalse(target_dir_no_hard_links.exists(), f"{self.which_test}: {target_dir_no_hard_links} should not exist before test")
        target_file_no_hard_links = target_dir_no_hard_links.joinpath(file_name).resolve()

        target_dir_with_hard_links = self.path_inside_test_folder("target_dir_with_hard_links")
        self.assertFalse(target_dir_with_hard_links.exists(), f"{self.which_test}: {target_dir_with_hard_links} should not exist before test")
        target_file_with_hard_links = target_dir_with_hard_links.joinpath(file_name).resolve()

        target_dir_with_different_name = self.path_inside_test_folder("target_dir_with_different_name")
        self.assertFalse(target_dir_with_different_name.exists(), f"{self.which_test}: {target_dir_with_different_name} should not exist before test")
        target_file_different_name_without_hard_links = target_dir_with_different_name.joinpath("Scrooge").resolve()
        target_file_different_name_with_hard_links = target_dir_with_different_name.joinpath("Ebenezer").resolve()

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_copy_from)
        self.batch_accum += MakeDirs(target_dir_no_hard_links)
        self.batch_accum += MakeDirs(target_dir_with_hard_links)
        with self.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch(file_name)  # add one file
        self.batch_accum += CopyFileToFile(file_to_copy, target_file_no_hard_links, hard_links=False)
        self.batch_accum += CopyFileToFile(file_to_copy, target_file_with_hard_links, hard_links=True)
        self.batch_accum += CopyFileToFile(file_to_copy, target_file_different_name_without_hard_links, hard_links=False)
        self.batch_accum += CopyFileToFile(file_to_copy, target_file_different_name_with_hard_links, hard_links=True)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, target_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.which_test}  (no hard links): source and target dirs are not the same")

        dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, target_dir_with_hard_links)
        self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.which_test}  (with hard links): source and target files are not hard links to the same file")

        self.assertTrue(filecmp.cmp(file_to_copy, target_file_different_name_without_hard_links))
        self.assertTrue(is_same_inode(file_to_copy, target_file_different_name_with_hard_links))

    def test_MoveDirToDir(self):
        """ test MoveDirToDir (with/without using hard links)
            a directory is created and filled with random files and folders.
            This directory is copied and both source and targets dirs are compared to make sure they are the same.

            without hard links:
                Folder structure and files should be identical

            with hard links:
                - All mirrored files should have the same inode number - meaning they are hard links to
            the same file.

            In order to be able to check the copy the test first copy from one folder to the second and then moves the second to a third folder
        """
        dir_to_copy_from = self.path_inside_test_folder("copy-src")
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")

        dir_to_copy_to_no_hard_links = self.path_inside_test_folder("copy-target-no-hard-links")
        copied_dir_no_hard_links = dir_to_copy_to_no_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_move_to_no_hard_links = self.path_inside_test_folder("move-target-no-hard-links")
        moved_dir_no_hard_links = dir_to_move_to_no_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_move_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_move_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.path_inside_test_folder("copy-target-with-hard-links")
        copied_dir_with_hard_links = dir_to_copy_to_with_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        dir_to_move_to_with_hard_links = self.path_inside_test_folder("move-target-with-hard-links")
        moved_dir_with_hard_links = dir_to_move_to_with_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_move_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_move_to_with_hard_links} should not exist before test")

        dir_to_copy_to_with_ignore = self.path_inside_test_folder("copy-target-with-ignore")
        copied_dir_with_ignore = dir_to_copy_to_with_ignore.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_with_ignore.exists(), f"{self.which_test}: {dir_to_copy_to_with_ignore} should not exist before test")

        dir_to_move_to_with_ignore = self.path_inside_test_folder("move-target-with-ignore")
        moved_dir_with_ignore = dir_to_move_to_with_ignore.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_move_to_with_ignore.exists(), f"{self.which_test}: {dir_to_move_to_with_ignore} should not exist before test")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_copy_from)
        with self.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
        self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        self.batch_accum += MoveDirToDir(copied_dir_no_hard_links, dir_to_move_to_no_hard_links, hard_links=False)

        self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        self.batch_accum += MoveDirToDir(copied_dir_with_hard_links, dir_to_move_to_with_hard_links, hard_links=True)

        file_names_to_ignore = ["hootenanny"]
        self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=file_names_to_ignore)
        self.batch_accum += MoveDirToDir(copied_dir_with_ignore, dir_to_move_to_with_ignore, hard_links=False)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, moved_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.which_test} (no hard links): source and target dirs are not the same")

        dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, moved_dir_with_hard_links)
        self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.which_test} (with hard links): source and target files are not hard links to the same file")

        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, moved_dir_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, moved_dir_with_ignore)
