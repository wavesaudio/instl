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

import utils
from pybatch import *


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
    for a_file in a_dircmp.same_files:
        left_file = os.path.join(a_dircmp.left, a_file)
        right_file = os.path.join(a_dircmp.right, a_file)
        retVal = os.stat(left_file)[stat.ST_INO] == os.stat(right_file)[stat.ST_INO]
        #if not retVal:
        #    break
        retVal = os.stat(left_file)[stat.ST_NLINK] == os.stat(right_file)[stat.ST_NLINK] == 2
        if not retVal:
            break
    if retVal:
        for sub_dircmp in a_dircmp.subdirs.values():
            retVal = is_hard_linked(sub_dircmp)
            if not retVal:
                break
    return retVal


class TestPythonBatch(unittest.TestCase):
    def __init__(self, which_test="banana"):
        super().__init__(which_test)
        self.which_test = which_test
        self.test_folder = pathlib.Path(__file__).joinpath("..", "..", "..").resolve().joinpath("python_batch_test_results", which_test)
        self.stdout_capture = io.StringIO()  # to capture the output of exec calls

    def setUp(self):
        """ for each test create it's own test sub-folder"""
        if self.test_folder.exists():
            shutil.rmtree(str(self.test_folder))  # make sure the folder is erased
        self.test_folder.mkdir(parents=True, exist_ok=False)

    def tearDown(self):
        pass

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
        self.assertFalse(dir_to_make_1.exists())
        self.assertFalse(dir_to_make_2.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make_1), str(dir_to_make_2), remove_obstacles=True)
            bc += MakeDirs(str(dir_to_make_1), remove_obstacles=False)  # MakeDirs twice should be OK
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        self.assertTrue(dir_to_make_1.is_dir())
        self.assertTrue(dir_to_make_2.is_dir())

    def test_MakeDirs_2_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=True the file should be removed and directory created in it's place.
        """
        dir_to_make = self.test_folder.joinpath("file-that-should-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{dir_to_make} should not exist at the start ot the test")

        touch(str(dir_to_make))
        self.assertTrue(dir_to_make.is_file(), f"{dir_to_make} should be a file at this stage")

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=True)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(dir_to_make.is_dir(), f"{dir_to_make} should be a dir at this stage")

    def test_MakeDirs_3_no_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=False the file should not be removed and FileExistsError raised.
        """
        dir_to_make = self.test_folder.joinpath("file-that-should-not-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{dir_to_make} should not exist at the start ot the test")

        touch(str(dir_to_make))
        self.assertTrue(dir_to_make.is_file(), f"{dir_to_make} should be a file at this stage")

        bc_ = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=False)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            with self.assertRaises(FileExistsError, msg="should raise FileExistsError") as context:
                ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(dir_to_make.is_file(), f"{dir_to_make} should still be a file")

    def test_Chmod_1(self):
        """ test Chmod
            A file is created and it's permissions are changed 3 times
        """
        file_to_chmod = self.test_folder.joinpath("file-to-chmod").resolve()
        touch(str(file_to_chmod))
        mod_before = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        os.chmod(file_to_chmod, Chmod.all_read)
        initial_mode = utils.unix_permissions_to_str(stat.S_IMODE(os.stat(file_to_chmod).st_mode))
        expected_mode = utils.unix_permissions_to_str(Chmod.all_read)
        self.assertEqual(initial_mode, expected_mode, f"failed to chmod on test file before tests: {initial_mode} != {expected_mode}")

        # change to rwxrwxrwx
        bc = None
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        with BatchCommandAccum() as bc:
            bc += Chmod(str(file_to_chmod), new_mode)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to rw-rw-rw-
        bc = None
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        with BatchCommandAccum() as bc:
            bc += Chmod(str(file_to_chmod), new_mode)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to r--r--r--
        bc = None
        new_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        with BatchCommandAccum() as bc:
            bc += Chmod(str(file_to_chmod), new_mode)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

    def test_Cd_and_Touch_1(self):
        """ test Cd and Touch
            A directory is created and Cd is called to make it the current working directory.
            Inside a file is created ('touched'). After that current working directory should return
            to it's initial value
        """
        dir_to_make = self.test_folder.joinpath("cd-here").resolve()
        file_to_touch = dir_to_make.joinpath("touch-me").resolve()
        self.assertFalse(file_to_touch.exists())

        cwd_before = os.getcwd()
        self.assertNotEqual(str(dir_to_make), cwd_before)

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=False)
            with bc.sub_section(Cd(str(dir_to_make))) as sub_bc:
                sub_bc += Touch("touch-me")  # file's path is relative!
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        self.assertTrue(file_to_touch.exists(), f"touched file was not created {file_to_touch}")

        cwd_after = os.getcwd()
        # cwd should be back to where it was
        self.assertEqual(cwd_before, cwd_after, "cd has not restored the current working directory was: {cwd_before}, now: {cwd_after}")

    def test_CopyDirToDir_no_hard_links(self):
        """ test CopyDirToDir (without using rsync's link_dest)
            a directory is created and filled with random files and folders.
            This directory is copied and both are compared to make sure they are the same.
        """
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        dir_to_copy_to = self.test_folder.joinpath("copy-target").resolve()
        copied_dir = dir_to_copy_to.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_from.exists())
        self.assertFalse(dir_to_copy_to.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
            bc += CopyDirToDir(str(dir_to_copy_from), str(dir_to_copy_to))

        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        dir_comp = filecmp.dircmp(dir_to_copy_from, copied_dir)

        self.assertTrue(is_identical_dircmp(dir_comp), "test_CopyDirToDir: source and target dirs are not the same")

    def test_CopyDirToDir_with_hard_links(self):
        """ test CopyDirToDir (with using rsync's link_dest)
            a directory is created and filled with random files and folders.
            This directory is copied and both are compared to make sure they are the same.
            All mirrored files should have the same inode number - meaning they are hard links to
            the same file.
        """
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        dir_to_copy_to = self.test_folder.joinpath("copy-target").resolve()
        copied_dir = dir_to_copy_to.joinpath("copy-src").resolve()
        self.assertFalse(dir_to_copy_from.exists())
        self.assertFalse(dir_to_copy_to.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
            bc += CopyDirToDir(str(dir_to_copy_from), str(dir_to_copy_to), link_dest=True)

        bc_repr = repr(bc)
        #with capture_stdout(self.stdout_capture):
        ops = exec(f"""{bc_repr}""", globals(), locals())

        dir_comp = filecmp.dircmp(dir_to_copy_from, copied_dir)

        self.assertTrue(is_identical_dircmp(dir_comp), "test_CopyDirToDir: source and target dirs are not the same")
        self.assertTrue(is_hard_linked(dir_comp), "test_CopyDirToDir: source and target files are not hard links to the same file")

    def test_CopyDirContentsToDir(self):
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        dir_to_copy_to = self.test_folder.joinpath("copy-target").resolve()
        copied_dir = dir_to_copy_to
        self.assertFalse(dir_to_copy_from.exists())
        self.assertFalse(dir_to_copy_to.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
            bc += CopyDirContentsToDir(str(dir_to_copy_from), str(dir_to_copy_to))

        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        dir_comp = filecmp.dircmp(dir_to_copy_from, copied_dir)

        self.assertTrue(is_identical_dircmp(dir_comp), "test_CopyDirToDir: source and target dirs are not the same")

    def test_CopyFileToDir(self):
        file_name = ''.join(random.choice(string.ascii_lowercase) for i in range(8))
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        dir_to_copy_to = self.test_folder.joinpath("copy-target").resolve()
        source_file = dir_to_copy_from.joinpath(file_name)
        target_file = dir_to_copy_to.joinpath(file_name)
        self.assertFalse(dir_to_copy_from.exists())
        self.assertFalse(dir_to_copy_to.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += Touch(file_name)
            bc += CopyFileToDir(str(source_file), str(dir_to_copy_to))

        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        self.assertTrue(target_file.is_file(), f"test_CopyFileToDir: target file '{target_file}' not found")
        self.assertTrue(filecmp.cmp(str(source_file), str(target_file), shallow=False), "test_CopyFileToDir: source and target are not the same")

    def test_CopyFileToFile(self):
        file_name = ''.join(random.choice(string.ascii_lowercase) for i in range(8))
        dir_to_copy_from = self.test_folder.joinpath("copy-src").resolve()
        dir_to_copy_to = self.test_folder.joinpath("copy-target").resolve()
        source_file = dir_to_copy_from.joinpath(file_name)
        target_file = dir_to_copy_to.joinpath(file_name)
        self.assertFalse(dir_to_copy_from.exists())
        self.assertFalse(dir_to_copy_to.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            bc += MakeDirs(str(dir_to_copy_to))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += Touch(file_name)
            bc += CopyFileToFile(str(source_file), str(target_file))

        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        self.assertTrue(target_file.is_file(), f"test_CopyFileToDir: target file '{target_file}' not found")
        self.assertTrue(filecmp.cmp(str(source_file), str(target_file), shallow=False), "test_CopyFileToDir: source and target are not the same")

    def test_remove(self):
        dir_to_remove = self.test_folder.joinpath("remove-me").resolve()
        self.assertFalse(dir_to_remove.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_remove))
            with bc.sub_section(Cd(str(dir_to_remove))) as sub_bc:
                bc += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
            bc += RmFile(str(dir_to_remove))  # RmFile should not remove a folder
        bc_repr = repr(bc)
        with self.assertRaises(PermissionError, msg="should raise PermissionError") as context:
            ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(dir_to_remove.exists())

        bc = None
        with BatchCommandAccum() as bc:
            bc += RmDir(str(dir_to_remove))
        bc_repr = repr(bc)
        ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertFalse(dir_to_remove.exists())


if __name__ == '__main__':
    unittest.main()
