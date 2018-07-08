#!/usr/bin/env python3.6


import sys
import os
import pathlib
import unittest
import shutil
import stat
import io
import contextlib
import filecmp
import random
import string
import subprocess

import utils
from pybatch import *
from pybatch import BatchCommandAccum


@contextlib.contextmanager
def capture_stdout(in_new_stdout=None):
    old_stdout = sys.stdout
    if in_new_stdout is None:
        new_stdout = io.StringIO()
    else:
        new_stdout = in_new_stdout
    sys.stdout = new_stdout
    yield new_stdout
    new_stdout.seek(0)
    sys.stdout = old_stdout


def explain_dict_diff(d1, d2):
    keys1 = set(d1.keys())
    keys2 = set(d2.keys())
    if keys1 != keys2:
        print("keys in d1 not in d2", keys1-keys2)
        print("keys in d2 not in d1", keys2-keys1)
    else:
        for k in keys1:
            if d1[k] != d2[k]:
                print(f"d1['{k}']({d1[k]}) != d2['{k}']({d2[k]})")


def is_identical_dircmp(a_dircmp: filecmp.dircmp):
    """ filecmp.dircmp does not have straight forward way to ask are directories the same?
        is_identical_dircmp attempts to fill this gap
    """
    retVal = len(a_dircmp.left_only) == 0 and len(a_dircmp.right_only) == 0 and len(a_dircmp.diff_files) == 0
    if retVal:
        for sub_dircmp in a_dircmp.subdirs.values():
            retVal = is_identical_dircmp(sub_dircmp)
            if not retVal:
                break
    return retVal


def is_hard_linked(a_dircmp: filecmp.dircmp):
    """ check that all same_files are hard link of each other"""
    retVal = True
    for a_file in a_dircmp.same_files:
        left_file = os.path.join(a_dircmp.left, a_file)
        right_file = os.path.join(a_dircmp.right, a_file)
        retVal = os.stat(left_file)[stat.ST_INO] == os.stat(right_file)[stat.ST_INO]
        if not retVal:
            break
        retVal = os.stat(left_file)[stat.ST_NLINK] == os.stat(right_file)[stat.ST_NLINK] == 2
        if not retVal:
            break
    if retVal:
        for sub_dircmp in a_dircmp.subdirs.values():
            retVal = is_hard_linked(sub_dircmp)
            if not retVal:
                break
    return retVal


def compare_chmod_recursive(folder_path, expected_file_mode, expected_dir_mode):
    root_mode = stat.S_IMODE(os.stat(folder_path).st_mode)
    if root_mode != expected_dir_mode:
        return False
    for root, dirs, files in os.walk(folder_path, followlinks=False):
        for item in files:
            item_path = os.path.join(root, item)
            item_mode = stat.S_IMODE(os.stat(item_path).st_mode)
            if item_mode != expected_file_mode:
                return False
        for item in dirs:
            item_path = os.path.join(root, item)
            item_mode = stat.S_IMODE(os.stat(item_path).st_mode)
            if item_mode != expected_dir_mode:
                return False
    return True


class TestPythonBatch(unittest.TestCase):
    def __init__(self, which_test="banana"):
        super().__init__(which_test)
        self.which_test = which_test.lstrip("test_")
        self.test_folder = pathlib.Path(__file__).joinpath("..", "..", "..").resolve().joinpath("python_batch_test_results", self.which_test)
        self.batch_accum = BatchCommandAccum()
        self.sub_test_counter = 0

    def setUp(self):
        """ for each test create it's own test sub-folder"""
        if self.test_folder.exists():
            for root, dirs, files in os.walk(str(self.test_folder)):
                for d in dirs:
                    os.chmod(os.path.join(root, d), stat.S_IWUSR)
                for f in files:
                    os.chmod(os.path.join(root, f), stat.S_IWUSR)
            shutil.rmtree(self.test_folder)  # make sure the folder is erased
        self.test_folder.mkdir(parents=True, exist_ok=False)

    def tearDown(self):
        pass

    def write_file_in_test_folder(self, file_name, contents):
        with open(self.test_folder.joinpath(file_name), "w") as wfd:
            wfd.write(contents)

    def exec_and_capture_output(self, test_name=None, expected_exception=None):
        self.sub_test_counter += 1
        if test_name is None:
            test_name = self.which_test
        test_name = f"{self.sub_test_counter}_{test_name}"

        bc_repr = repr(self.batch_accum)
        self.write_file_in_test_folder(test_name+".py", bc_repr)
        stdout_capture = io.StringIO()
        with capture_stdout(stdout_capture):
            if not expected_exception:
                ops = exec(f"""{bc_repr}""", globals(), locals())
            else:
                with self.assertRaises(expected_exception):
                    ops = exec(f"""{bc_repr}""", globals(), locals())

        self.write_file_in_test_folder(test_name+"_output.txt", stdout_capture.getvalue())

    def test_MakeDirs_0_repr(self):
        """ test that MakeDirs.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        mk_dirs_obj = MakeDirs("a/b/c", "jane/and/jane", remove_obstacles=True)
        mk_dirs_obj_recreated = eval(repr(mk_dirs_obj))
        self.assertEqual(mk_dirs_obj, mk_dirs_obj_recreated, "MakeDirs.repr did not recreate MakeDirs object correctly")

    def test_MakeDirs_1_simple(self):
        """ test MakeDirs. 2 dirs should be created side by side """
        dir_to_make_1 = self.test_folder.joinpath(self.which_test+"_1").resolve()
        dir_to_make_2 = self.test_folder.joinpath(self.which_test+"_2").resolve()
        self.assertFalse(dir_to_make_1.exists(), f"{self.which_test}: before test {dir_to_make_1} should not exist")
        self.assertFalse(dir_to_make_2.exists(), f"{self.which_test}: before test {dir_to_make_2} should not exist")

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_make_1, dir_to_make_2, remove_obstacles=True)
            self.batch_accum += MakeDirs(dir_to_make_1, remove_obstacles=False)  # MakeDirs twice should be OK

        self.exec_and_capture_output()

        self.assertTrue(dir_to_make_1.exists(), f"{self.which_test}: {dir_to_make_1} should exist")
        self.assertTrue(dir_to_make_2.exists(), f"{self.which_test}: {dir_to_make_2} should exist")

    def test_MakeDirs_2_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=True the file should be removed and directory created in it's place.
        """
        dir_to_make = self.test_folder.joinpath("file-that-should-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{self.which_test}: {dir_to_make} should not exist before test")

        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should be a file before test")

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_make, remove_obstacles=True)

        self.exec_and_capture_output()

        self.assertTrue(dir_to_make.is_dir(), f"{self.which_test}: {dir_to_make} should be a dir")

    def test_MakeDirs_3_no_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=False the file should not be removed and FileExistsError raised.
        """
        dir_to_make = self.test_folder.joinpath("file-that-should-not-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{self.which_test}: {dir_to_make} should not exist before test")

        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should be a file")

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_make, remove_obstacles=False)

        self.exec_and_capture_output(expected_exception=FileExistsError)

        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should still be a file")

    def test_Chmod_non_recursive(self):
        """ test Chmod
            A file is created and it's permissions are changed several times
        """
        # TODO: Add test for symbolic links
        file_to_chmod = self.test_folder.joinpath("file-to-chmod").resolve()
        touch(file_to_chmod)
        mod_before = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        os.chmod(file_to_chmod, Chmod.all_read)
        initial_mode = utils.unix_permissions_to_str(stat.S_IMODE(os.stat(file_to_chmod).st_mode))
        expected_mode = utils.unix_permissions_to_str(Chmod.all_read)
        self.assertEqual(initial_mode, expected_mode, f"{self.which_test}: failed to chmod on test file before tests: {initial_mode} != {expected_mode}")

        # change to rwxrwxrwx
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        if sys.platform == 'darwin':  # Adding executable bit for mac
            new_mode = stat.S_IMODE(new_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        new_mode_symbolic = 'a=rwx'
        with self.batch_accum:
            self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.exec_and_capture_output("chmod_a=rwx")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # pass inappropriate symbolic mode should result in ValueError exception and permissions should remain
        new_mode_symbolic = 'a=rwi'  # i is not a legal mode
        with self.batch_accum:
            self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.exec_and_capture_output("chmod_a=rwi", expected_exception=ValueError)

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: mode should remain {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to rw-rw-rw-
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        new_mode_symbolic = 'a-x'
        with self.batch_accum:
            self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.exec_and_capture_output("chmod_a-x")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        if sys.platform == 'darwin':  # Windows doesn't have an executable bit, test is skipped
            # change to rwxrwxrw-
            new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IXUSR | stat.S_IXGRP)
            new_mode_symbolic = 'ug+x'
            with self.batch_accum:
                self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

            self.exec_and_capture_output("chmod_ug+x")

            mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
            self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to r--r--r--
        new_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        with self.batch_accum:
            self.batch_accum += Chmod(file_to_chmod, 'u-wx')
            self.batch_accum += Chmod(file_to_chmod, 'g-wx')
            self.batch_accum += Chmod(file_to_chmod, 'o-wx')

        self.exec_and_capture_output("chmod_a-wx")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

    def test_Chmod_recursive(self):
        """ test Chmod recursive
            A file is created and it's permissions are changed several times
        """
        folder_to_chmod = self.test_folder.joinpath("folder-to-chmod").resolve()

        initial_mode = Chmod.all_read_write
        initial_mode_str = "a+rw"
        # create the folder
        with self.batch_accum:
             self.batch_accum += MakeDirs(folder_to_chmod)
             with self.batch_accum.adjuvant(Cd(folder_to_chmod)):
                self.batch_accum += Touch("hootenanny")  # add one file with fixed (none random) name
                self.batch_accum += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
                self.batch_accum += Chmod(path=folder_to_chmod, mode=initial_mode_str, recursive=True)
        self.exec_and_capture_output("create the folder")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, initial_mode, Chmod.all_read_write_exec))

        # change to rwxrwxrwx
        new_mode_symbolic = 'a=rwx'
        with self.batch_accum:
            self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod a=rwx")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, Chmod.all_read_write_exec, Chmod.all_read_write_exec))

        # pass inappropriate symbolic mode should result in ValueError exception and permissions should remain
        new_mode_symbolic = 'a=rwi'  # i is not a legal mode
        with self.batch_accum:
            self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod invalid", expected_exception=subprocess.CalledProcessError)

        # change to r-xr-xr-x
        new_mode_symbolic = 'a-w'
        with self.batch_accum:
            self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod a-w")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, Chmod.all_read_exec, Chmod.all_read_exec))

        # change to rwxrwxrwx so folder can be deleted
        new_mode_symbolic = 'a+rwx'
        with self.batch_accum:
            self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod restore perm")

    def test_Cd_and_Touch_1(self):
        """ test Cd and Touch
            A directory is created and Cd is called to make it the current working directory.
            Inside a file is created ('touched'). After that current working directory should return
            to it's initial value
        """
        dir_to_make = self.test_folder.joinpath("cd-here").resolve()
        file_to_touch = dir_to_make.joinpath("touch-me").resolve()
        self.assertFalse(file_to_touch.exists(), f"{self.which_test}: before test {file_to_touch} should not exist")

        cwd_before = os.getcwd()
        self.assertNotEqual(dir_to_make, cwd_before, f"{self.which_test}: before test {dir_to_make} should not be current working directory")

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_make, remove_obstacles=False)
            with self.batch_accum.adjuvant(Cd(dir_to_make)) as sub_bc:
                sub_bc += Touch("touch-me")  # file's path is relative!

        self.exec_and_capture_output()

        self.assertTrue(file_to_touch.exists(), f"{self.which_test}: touched file was not created {file_to_touch}")

        cwd_after = os.getcwd()
        # cwd should be back to where it was
        self.assertEqual(cwd_before, cwd_after, "{self.which_test}: cd has not restored the current working directory was: {cwd_before}, now: {cwd_after}")

    def test_CopyDirToDir(self):
        """ test CopyDirToDir (with/without using rsync's link_dest option)
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
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")

        dir_to_copy_to_no_hard_links = self.test_folder.joinpath("copy-target-no-hard-links").resolve()
        copied_dir_no_hard_links = dir_to_copy_to_no_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.test_folder.joinpath("copy-target-with-hard-links").resolve()
        copied_dir_with_hard_links = dir_to_copy_to_with_hard_links.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_copy_from)
            with self.batch_accum.adjuvant(Cd(dir_to_copy_from)) as sub_bc:
                self.batch_accum += Touch("hootenanny")  # add one file with fixed (none random) name
                self.batch_accum += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
            self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, link_dest=False)
            if sys.platform == 'darwin':
                self.batch_accum += CopyDirToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, link_dest=True)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), "{self.which_test} (with hard links): source and target files are not hard links to the same file")

    def test_CopyDirContentsToDir(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contents
            should be copied - not the source dir itself.
        """
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")

        dir_to_copy_to_no_hard_links = self.test_folder.joinpath("copy-target-no-hard-links").resolve()
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.test_folder.joinpath("copy-target-with-hard-links").resolve()
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_copy_from)
            with self.batch_accum.adjuvant(Cd(dir_to_copy_from)) as sub_bc:
                self.batch_accum += Touch("hootenanny")  # add one file with fixed (none random) name
                self.batch_accum += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
            self.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_no_hard_links, link_dest=False)
            if sys.platform == 'darwin':
                self.batch_accum += CopyDirContentsToDir(dir_to_copy_from, dir_to_copy_to_with_hard_links, link_dest=True)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), "{self.which_test} (with hard links): source and target files are not hard links to the same file")

    def test_CopyFileToDir(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contains
            one file that is copied by it's full path.
        """
        file_name = "hootenanny"
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")
        file_to_copy = dir_to_copy_from.joinpath(file_name).resolve()

        dir_to_copy_to_no_hard_links = self.test_folder.joinpath("copy-target-no-hard-links").resolve()
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")

        dir_to_copy_to_with_hard_links = self.test_folder.joinpath("copy-target-with-hard-links").resolve()
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_copy_from)
            self.batch_accum += MakeDirs(dir_to_copy_to_no_hard_links)
            with self.batch_accum.adjuvant(Cd(dir_to_copy_from)) as sub_bc:
                self.batch_accum += Touch("hootenanny")  # add one file
            self.batch_accum += CopyFileToDir(file_to_copy, dir_to_copy_to_no_hard_links, link_dest=False)
            if sys.platform == 'darwin':
                self.batch_accum += CopyFileToDir(file_to_copy, dir_to_copy_to_with_hard_links, link_dest=True)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test} (no hard links): source and target dirs are not the same")

        if sys.platform == 'darwin':
            dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
            self.assertTrue(is_hard_linked(dir_comp_with_hard_links), "{self.which_test} (with hard links): source and target files are not hard links to the same file")

    def test_CopyFileToFile(self):
        """ see doc string for test_CopyDirToDir, with the difference that the source dir contains
            one file that is copied by it's full path and target is a full path to a file.
        """
        file_name = "hootenanny"
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_from.exists(), f"{self.which_test}: {dir_to_copy_from} should not exist before test")
        file_to_copy = dir_to_copy_from.joinpath(file_name).resolve()

        target_dir_no_hard_links = self.test_folder.joinpath("target_dir_no_hard_links").resolve()
        self.assertFalse(target_dir_no_hard_links.exists(), f"{self.which_test}: {target_dir_no_hard_links} should not exist before test")
        target_file_no_hard_links = target_dir_no_hard_links.joinpath(file_name).resolve()

        target_dir_with_hard_links = self.test_folder.joinpath("target_dir_with_hard_links").resolve()
        self.assertFalse(target_dir_with_hard_links.exists(), f"{self.which_test}: {target_dir_with_hard_links} should not exist before test")
        target_file_with_hard_links = target_dir_with_hard_links.joinpath(file_name).resolve()

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_copy_from)
            self.batch_accum += MakeDirs(target_dir_no_hard_links)
            self.batch_accum += MakeDirs(target_dir_with_hard_links)
            with self.batch_accum.adjuvant(Cd(dir_to_copy_from)) as sub_bc:
                self.batch_accum += Touch("hootenanny")  # add one file
            self.batch_accum += CopyFileToFile(file_to_copy, target_file_no_hard_links, link_dest=False)
            self.batch_accum += CopyFileToFile(file_to_copy, target_file_with_hard_links, link_dest=True)

        self.exec_and_capture_output()

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, target_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test}  (no hard links): source and target dirs are not the same")

        dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, target_dir_with_hard_links)
        self.assertTrue(is_hard_linked(dir_comp_with_hard_links), "{self.which_test}  (with hard links): source and target files are not hard links to the same file")

    def test_remove(self):
        """ Create a folder and fill it with random files.
            1st try to remove the folder with RmFile which should fail and raise exception
            2nd try to remove the folder with RmDir which should work
        """
        dir_to_remove = self.test_folder.joinpath("remove-me").resolve()
        self.assertFalse(dir_to_remove.exists())

        with self.batch_accum:
            self.batch_accum += MakeDirs(dir_to_remove)
            with self.batch_accum.adjuvant(Cd(dir_to_remove)) as sub_bc:
                self.batch_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
            self.batch_accum += RmFile(dir_to_remove)  # RmFile should not remove a folder
        self.exec_and_capture_output(expected_exception=PermissionError)
        self.assertTrue(dir_to_remove.exists())

        with self.batch_accum:
            self.batch_accum += RmDir(dir_to_remove)
        self.exec_and_capture_output()
        self.assertFalse(dir_to_remove.exists())

    def test_ChFlags(self):
        flags = {"hidden": stat.UF_HIDDEN,
                 "uchg": stat.UF_IMMUTABLE}
        test_file = self.test_folder.joinpath("chflags-me").resolve()
        self.assertFalse(test_file.exists(), f"{self.which_test}: {test_file} should not exist before test")

        with self.batch_accum:
            self.batch_accum += Touch(test_file)
            self.batch_accum += ChFlags(test_file, "hidden")
            self.batch_accum += ChFlags(test_file, "uchg")

        self.exec_and_capture_output("hidden_uchg")

        self.assertTrue(test_file.exists())

        files_flags = os.stat(test_file).st_flags
        self.assertEqual((files_flags & flags['hidden']), flags['hidden'])
        self.assertEqual((files_flags & flags['uchg']), flags['uchg'])

        with self.batch_accum:
            self.batch_accum += Unlock(test_file)                # so file can be erased
            self.batch_accum += ChFlags(test_file, "nohidden")   # so file can be seen

        self.exec_and_capture_output("nohidden")

        files_flags = os.stat(test_file).st_flags
        self.assertEqual((files_flags & flags['uchg']), 0)
        self.assertEqual((files_flags & flags['hidden']), 0)

    def test_AppendFileToFile(self):
        source_file = self.test_folder.joinpath("source-file.txt").resolve()
        self.assertFalse(source_file.exists(), f"{self.which_test}: {source_file} should not exist before test")
        target_file = self.test_folder.joinpath("target-file.txt").resolve()
        self.assertFalse(target_file.exists(), f"{self.which_test}: {target_file} should not exist before test")

        content_1 = ''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(124))
        content_2 = ''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(125))
        with open(source_file, "w") as wfd:
            wfd.write(content_1)
        with open(target_file, "w") as wfd:
            wfd.write(content_2)

        with self.batch_accum:
            self.batch_accum += AppendFileToFile(source_file, target_file)

        self.exec_and_capture_output()

        with open(target_file, "r") as rfd:
            concatenated_content = rfd.read()

        expected_content = content_2+content_1
        self.assertEqual(concatenated_content, expected_content)

    def test_ShellShellCommands(self):
        batches_dir = self.test_folder.joinpath("batches").resolve()
        self.assertFalse(batches_dir.exists(), f"{self.which_test}: {batches_dir} should not exist before test")

        if sys.platform == 'darwin':
            geronimo = ["ls /Users/shai/Desktop >> ~/Desktop/batches/geronimo.txt",
                        """[ -f "/Users/shai/Desktop/batches/geronimo.txt" ] && echo "g e r o n i m o" >> /Users/shai/Desktop/batches/geronimo.txt"""]
        else:
            geronimo = [r"dir C:\Program Files\Git >> %userprofile%\desktop\geronimo.txt",
                        ]

        with self.batch_accum:
            self.batch_accum += VarAssign("geronimo", geronimo)
            self.batch_accum += MakeDirs(batches_dir)
            self.batch_accum += ShellCommands(dir=batches_dir, var_name="geronimo")

        self.exec_and_capture_output()



if __name__ == '__main__':
    unittest.main()
