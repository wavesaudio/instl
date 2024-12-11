#!/usr/bin/env python3.12

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


class TestPythonBatchCopy(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_RsyncClone_repr(self):
        list_of_objs = list()
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        list_of_objs.append(RsyncClone(dir_from, dir_to))
        list_of_objs.append(RsyncClone(dir_from, dir_to, symlinks_as_symlinks=False,
                 ignore_patterns=['*.a', 'b.*'],
                 hard_links=False,
                 ignore_dangling_symlinks=True,
                 delete_extraneous_files=True,
                 verbose=17,
                 dry_run=True))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_RsyncClone(self):
        """ test RsyncClone (with/without using rsync's hard_links option)
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
        dir_to_copy_from = self.pbt.path_inside_test_folder("copy-resource_source_file")
        dir_to_copy_to_no_hard_links = self.pbt.path_inside_test_folder("copy-target-no-hard-links")
        dir_to_copy_to_with_hard_links = self.pbt.path_inside_test_folder("copy-target-with-hard-links")
        dir_to_copy_to_with_ignore = self.pbt.path_inside_test_folder("copy-target-with-ignore")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(dir_to_copy_from)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=5, num_dirs_per_level=3, num_files_per_dir=5, file_size=413)
        self.pbt.batch_accum += RsyncClone(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.pbt.batch_accum += RsyncClone(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        file_names_to_ignore = ["hootenanny"]
        self.pbt.batch_accum += RsyncClone(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=file_names_to_ignore)

        self.pbt.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.pbt.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.pbt.which_test} (with hard links): source and target files are not hard links to the same file")
        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, file_names_to_ignore)

    def test_CopyDirToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        self.pbt.reprs_test_runner(CopyDirToDir(dir_from, dir_to, hard_links=False))

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
        dir_to_copy_from = self.pbt.path_inside_test_folder("copy-resource_source_file")

        dir_to_copy_to_no_hard_links = self.pbt.path_inside_test_folder("copy-target-no-hard-links")
        copied_dir_no_hard_links = dir_to_copy_to_no_hard_links.joinpath("copy-resource_source_file").resolve()

        dir_to_copy_to_with_hard_links = self.pbt.path_inside_test_folder("copy-target-with-hard-links")
        copied_dir_with_hard_links = dir_to_copy_to_with_hard_links.joinpath("copy-resource_source_file").resolve()

        dir_to_copy_to_with_ignore = self.pbt.path_inside_test_folder("copy-target-with-ignore")
        copied_dir_with_ignore = dir_to_copy_to_with_ignore.joinpath("copy-resource_source_file").resolve()

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(dir_to_copy_from)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=5, num_dirs_per_level=3, num_files_per_dir=5, file_size=413)

        self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        file_names_to_ignore = ["hootenanny"]
        self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=file_names_to_ignore)

        self.pbt.exec_and_capture_output("target-not-exist")

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.pbt.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.pbt.which_test} (with hard links): source and target files are not hard links to the same file")
        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, file_names_to_ignore)

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum.set_current_section("prepare")

        self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        file_names_to_ignore = ["hootenanny"]
        self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=file_names_to_ignore)

        self.pbt.exec_and_capture_output("target-exist")

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.pbt.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.pbt.which_test} (with hard links): source and target files are not hard links to the same file")
        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, file_names_to_ignore)

    def test_MoveDirToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        self.pbt.reprs_test_runner(MoveDirToDir(dir_from, dir_to, ignore_if_not_exist=False))

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
        dir_to_copy_from = self.pbt.path_inside_test_folder("copy-resource_source_file")

        dir_to_copy_to_no_hard_links = self.pbt.path_inside_test_folder("copy-target-no-hard-links")
        copied_dir_no_hard_links = dir_to_copy_to_no_hard_links.joinpath("copy-resource_source_file").resolve()

        dir_to_move_to_no_hard_links = self.pbt.path_inside_test_folder("move-target-no-hard-links")
        moved_dir_no_hard_links = dir_to_move_to_no_hard_links.joinpath("copy-resource_source_file").resolve()

        dir_to_copy_to_with_hard_links = self.pbt.path_inside_test_folder("copy-target-with-hard-links")
        copied_dir_with_hard_links = dir_to_copy_to_with_hard_links.joinpath("copy-resource_source_file").resolve()

        dir_to_move_to_with_hard_links = self.pbt.path_inside_test_folder("move-target-with-hard-links")
        moved_dir_with_hard_links = dir_to_move_to_with_hard_links.joinpath("copy-resource_source_file").resolve()

        dir_to_copy_to_with_ignore = self.pbt.path_inside_test_folder("copy-target-with-ignore")
        copied_dir_with_ignore = dir_to_copy_to_with_ignore.joinpath("copy-resource_source_file").resolve()

        dir_to_move_to_with_ignore = self.pbt.path_inside_test_folder("move-target-with-ignore")
        moved_dir_with_ignore = dir_to_move_to_with_ignore.joinpath("copy-resource_source_file").resolve()

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(dir_to_copy_from)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=5, num_dirs_per_level=3, num_files_per_dir=5, file_size=413)
        self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        self.pbt.batch_accum += MoveDirToDir(copied_dir_no_hard_links, dir_to_move_to_no_hard_links, hard_links=False)

        self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        self.pbt.batch_accum += MoveDirToDir(copied_dir_with_hard_links, dir_to_move_to_with_hard_links, hard_links=True)

        file_names_to_ignore = ["hootenanny"]
        self.pbt.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=file_names_to_ignore)
        self.pbt.batch_accum += MoveDirToDir(copied_dir_with_ignore, dir_to_move_to_with_ignore, hard_links=False)

        self.pbt.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, moved_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.pbt.which_test} (no hard links): source and target dirs are not the same")

        dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, moved_dir_with_hard_links)
        self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.pbt.which_test} (with hard links): source and target files are not hard links to the same file")

        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, moved_dir_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, moved_dir_with_ignore)

    def test_CopyDirContentsToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        self.pbt.reprs_test_runner(CopyDirContentsToDir(dir_from, dir_to, hard_links=True))

    def test_CopyDirContentsToDir(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contents
            should be copied - not the source dir itself.
        """
        dir_to_copy_from = self.pbt.path_inside_test_folder("copy-resource_source_file")
        dir_to_copy_to_no_hard_links = self.pbt.path_inside_test_folder("copy-target-no-hard-links")
        dir_to_copy_to_with_hard_links = self.pbt.path_inside_test_folder("copy-target-with-hard-links")
        dir_to_copy_to_with_ignore = self.pbt.path_inside_test_folder("copy-target-with-ignore")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(dir_to_copy_from)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch("hootenanny")  # add one file with fixed (none random) name
            sub_bc += MakeRandomDirs(num_levels=5, num_dirs_per_level=3, num_files_per_dir=5, file_size=413)
        self.pbt.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.pbt.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, hard_links=True)
        filen_names_to_ignore = ["hootenanny"]
        self.pbt.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_with_ignore, ignore_patterns=filen_names_to_ignore)

        self.pbt.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.pbt.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.pbt.which_test} (with hard links): source and target files are not hard  links to the same file")

        dir_comp_with_ignore = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_ignore)
        is_identical_dircomp_with_ignore(dir_comp_with_ignore, filen_names_to_ignore)

    def test_MoveDirContentsToDir_repr(self):
        pass

    def test_MoveDirContentsToDir(self):
        pass

    def test_CopyFileToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        self.pbt.reprs_test_runner(CopyFileToDir(dir_from, dir_to, hard_links=False))

    def test_CopyFileToDir(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contains
            one file that is copied by it's full path.
        """
        file_name = "hootenanny"
        dir_to_copy_from = self.pbt.path_inside_test_folder("copy-resource_source_file")
        file_to_copy = dir_to_copy_from.joinpath(file_name).resolve()
        dir_to_copy_to_no_hard_links = self.pbt.path_inside_test_folder("copy-target-no-hard-links")
        dir_to_copy_to_with_hard_links = self.pbt.path_inside_test_folder("copy-target-with-hard-links")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(dir_to_copy_from)
        self.pbt.batch_accum += MakeDir(dir_to_copy_to_no_hard_links)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch(file_name)  # add one file
        self.pbt.batch_accum += CopyFileToDir(file_to_copy, dir_to_copy_to_no_hard_links, hard_links=False)
        if sys.platform == 'darwin':
            self.pbt.batch_accum += CopyFileToDir(file_to_copy, dir_to_copy_to_with_hard_links, hard_links=True)

        self.pbt.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.pbt.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.pbt.which_test} (with hard links): source and target files are not hard links to the same file")

    def test_MoveFileToDir_repr(self):
        pass

    def test_MoveFileToDir(self):
        pass

    def test_CopyFileToFile_repr(self):
        dir_from = r"\p\o\i"
        self.pbt.reprs_test_runner(CopyFileToFile(dir_from, "/sugar/man", hard_links=False, copy_owner=True))

    def test_CopyFileToFile(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contains
            one file that is copied by it's full path and target is a full path to a file.
        """
        file_name = "hootenanny"
        dir_to_copy_from = self.pbt.path_inside_test_folder("copy-resource_source_file")
        file_to_copy = dir_to_copy_from.joinpath(file_name).resolve()
        target_dir_no_hard_links = self.pbt.path_inside_test_folder("target_dir_no_hard_links")
        target_file_no_hard_links = target_dir_no_hard_links.joinpath(file_name).resolve()
        target_dir_with_hard_links = self.pbt.path_inside_test_folder("target_dir_with_hard_links")
        target_file_with_hard_links = target_dir_with_hard_links.joinpath(file_name).resolve()
        target_dir_with_different_name = self.pbt.path_inside_test_folder("target_dir_with_different_name")
        target_file_different_name_without_hard_links = target_dir_with_different_name.joinpath("Scrooge").resolve()
        target_file_different_name_with_hard_links = target_dir_with_different_name.joinpath("Ebenezer").resolve()

        self.pbt.batch_accum.clear(section_name="doit")

        self.pbt.batch_accum += MakeDir(dir_to_copy_from)
        self.pbt.batch_accum += MakeDir(target_dir_no_hard_links)
        self.pbt.batch_accum += MakeDir(target_dir_with_hard_links)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_copy_from)) as sub_bc:
            sub_bc += Touch(file_name)  # add one file
        self.pbt.batch_accum += CopyFileToFile(file_to_copy, target_file_no_hard_links, hard_links=False)
        self.pbt.batch_accum += CopyFileToFile(file_to_copy, target_file_with_hard_links, hard_links=True)
        self.pbt.batch_accum += CopyFileToFile(file_to_copy, target_file_different_name_without_hard_links, hard_links=False)
        self.pbt.batch_accum += CopyFileToFile(file_to_copy, target_file_different_name_with_hard_links, hard_links=True)

        self.pbt.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, target_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), f"{self.pbt.which_test}  (no hard links): source and target dirs are not the same")

        dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, target_dir_with_hard_links)
        self.assertTrue(is_hard_linked(dir_comp_with_hard_links), f"{self.pbt.which_test}  (with hard links): source and target files are not hard links to the same file")

        self.assertTrue(filecmp.cmp(file_to_copy, target_file_different_name_without_hard_links))
        self.assertTrue(is_same_inode(file_to_copy, target_file_different_name_with_hard_links))

    def test_MoveFileToFile_repr(self):
        pass

    def test_MoveFileToFile(self):
        file_name = "hootenanny"
        dir_to_copy_from = self.pbt.path_inside_test_folder("source_dir")
        dir_to_copy_to = self.pbt.path_inside_test_folder("target_dir")
        source_file = dir_to_copy_from.joinpath(file_name).resolve()
        target_file = dir_to_copy_to.joinpath(file_name).resolve()

        # create source file
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(dir_to_copy_from)
        self.pbt.batch_accum += Touch(source_file)
        self.pbt.exec_and_capture_output()
        self.assertTrue(source_file.is_file())
        self.assertFalse(target_file.is_file())

        # move file to target folder
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MoveFileToFile(source_file, target_file)
        self.pbt.exec_and_capture_output()
        self.assertFalse(source_file.is_file())
        self.assertTrue(target_file.is_file())

        # move file target file to itself, this should leave the file as is
        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MoveFileToFile(target_file, target_file)
        self.pbt.exec_and_capture_output()
        self.assertTrue(target_file.is_file())

    def test_CopyGlobToDir_repr(self):
        self.pbt.reprs_test_runner(CopyGlobToDir("/a/b/c", "/x/y/z", "*.banana"),
                                   CopyGlobToDir("/a/b/c", "/x/y/z", "*.banana", hard_links=False, copy_owner=True))

    def test_CopyGlobToDir(self):

        files_to_copy = (
            self.pbt.path_inside_test_folder("chimi/chury/a.banana"),
            self.pbt.path_inside_test_folder("chimi/chury/b.banana"),
            self.pbt.path_inside_test_folder("chimi/chury/c.banana"),
        )

        files_not_to_copy = (
            self.pbt.path_inside_test_folder("chimi/d.banana"),
            self.pbt.path_inside_test_folder("chimi/chury/cofix/e.banana"),
            self.pbt.path_inside_test_folder("chimi/chury/f.banana/g.ananas"),
        )

        target_dir = self.pbt.path_inside_test_folder("some bananas")
        glob_pattern = "*/*/*.banana"

        self.pbt.batch_accum.clear(section_name="doit")
        for file_to_create in files_to_copy + files_not_to_copy:
            self.pbt.batch_accum += Touch(file_to_create)
        self.pbt.batch_accum += CopyGlobToDir(glob_pattern, self.pbt.test_folder, target_dir)
        self.pbt.exec_and_capture_output()

        for copied_file in target_dir.glob('*'):
            print(copied_file)

    def test_BreakHardLinkUsingEnvironmentVars(self):
        original_file = self.pbt.path_inside_test_folder("original")
        linked_file = self.pbt.path_inside_test_folder("linked")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += Touch(original_file)
        self.pbt.batch_accum += CopyFileToFile(original_file, linked_file, hard_links=True)

        self.pbt.exec_and_capture_output("create hard link")
        self.assertEqual(original_file.stat().st_ino, linked_file.stat().st_ino, f"after creating hard-link files do not have not same inode")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += EnvironVarAssign("linked_file_path", os.fspath(linked_file))
        self.pbt.batch_accum += EnvironVarAssign("temp_file_path", "${linked_file_path}" + "." + str(os.getpid()))
        self.pbt.batch_accum += MoveFileToFile(linked_file, "${temp_file_path}", hard_links=False)
        self.pbt.batch_accum += MoveFileToFile("${temp_file_path}", linked_file)

        self.pbt.exec_and_capture_output("break hard link")
        self.assertNotEqual(original_file.stat().st_ino, linked_file.stat().st_ino, f"after breaking hard-link files still have not same inode")

    def test_BreakHardLinkUsingBreakHardLink(self):
        original_file = self.pbt.path_inside_test_folder("original")
        linked_file = self.pbt.path_inside_test_folder("linked")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += Touch(original_file)
        self.pbt.batch_accum += CopyFileToFile(original_file, linked_file, hard_links=True)

        self.pbt.exec_and_capture_output("create hard link")
        self.assertEqual(original_file.stat().st_ino, linked_file.stat().st_ino, f"after creating hard-link files do not have not same inode")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += BreakHardLink(linked_file)

        self.pbt.exec_and_capture_output("break hard link")
        self.assertNotEqual(original_file.stat().st_ino, linked_file.stat().st_ino, f"after breaking hard-link files still have not same inode")
