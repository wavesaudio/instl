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
        self.which_test = which_test.lstrip("test_")
        self.test_folder = pathlib.Path(__file__).joinpath("..", "..", "..").resolve().joinpath("python_batch_test_results", which_test)
        self.stdout_capture = io.StringIO()  # to capture the output of exec calls

    def setUp(self):
        """ for each test create it's own test sub-folder"""
        if self.test_folder.exists():
            shutil.rmtree(str(self.test_folder))  # make sure the folder is erased
        self.test_folder.mkdir(parents=True, exist_ok=False)

    def tearDown(self):
        pass

    def write_file_in_test_folder(self, file_name, contents):
        with open(self.test_folder.joinpath(file_name), "w") as wfd:
            wfd.write(contents)

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

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make_1), str(dir_to_make_2), remove_obstacles=True)
            bc += MakeDirs(str(dir_to_make_1), remove_obstacles=False)  # MakeDirs twice should be OK
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        self.assertTrue(dir_to_make_1.exists(), f"{self.which_test}: {dir_to_make_1} should exist")
        self.assertTrue(dir_to_make_2.exists(), f"{self.which_test}: {dir_to_make_2} should exist")

    def test_MakeDirs_2_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=True the file should be removed and directory created in it's place.
        """
        dir_to_make = self.test_folder.joinpath("file-that-should-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{self.which_test}: {dir_to_make} should not exist before test")

        touch(str(dir_to_make))
        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should be a file before test")

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=True)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(dir_to_make.is_dir(), f"{self.which_test}: {dir_to_make} should be a dir")

    def test_MakeDirs_3_no_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=False the file should not be removed and FileExistsError raised.
        """
        dir_to_make = self.test_folder.joinpath("file-that-should-not-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{self.which_test}: {dir_to_make} should not exist before test")

        touch(str(dir_to_make))
        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should be a file")

        bc_ = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=False)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            with self.assertRaises(FileExistsError, msg="should raise FileExistsError") as context:
                ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should still be a file")

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
        self.assertEqual(initial_mode, expected_mode, f"{self.which_test}: failed to chmod on test file before tests: {initial_mode} != {expected_mode}")

        # change to rwxrwxrwx
        bc = None
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        with BatchCommandAccum() as bc:
            bc += Chmod(str(file_to_chmod), new_mode)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to rw-rw-rw-
        bc = None
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        with BatchCommandAccum() as bc:
            bc += Chmod(str(file_to_chmod), new_mode)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to r--r--r--
        bc = None
        new_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        with BatchCommandAccum() as bc:
            bc += Chmod(str(file_to_chmod), new_mode)
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

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
        self.assertNotEqual(str(dir_to_make), cwd_before, f"{self.which_test}: before test {dir_to_make} should not be current working directory")

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=False)
            with bc.sub_section(Cd(str(dir_to_make))) as sub_bc:
                sub_bc += Touch("touch-me")  # file's path is relative!
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

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

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += Touch("hootenanny")  # add one file with fixed (none random) name
                bc += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
            bc += CopyDirToDir(str(dir_to_copy_from), str(dir_to_copy_to_no_hard_links), link_dest=False)
            bc += CopyDirToDir(str(dir_to_copy_from), str(dir_to_copy_to_with_hard_links), link_dest=True)

        bc_repr = repr(bc)
        #with capture_stdout(self.stdout_capture):
        ops = exec(f"""{bc_repr}""", globals(), locals())

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, copied_dir_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test} (no hard links): source and target dirs are not the same")

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

        bc = None
        with BatchCommandAccum() as bc:
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += Touch("hootenanny")  # add one file with fixed (none random) name
                bc += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
            bc += CopyDirContentsToDir(str(dir_to_copy_from), str(dir_to_copy_to_no_hard_links), link_dest=False)
            bc += CopyDirContentsToDir(str(dir_to_copy_from), str(dir_to_copy_to_with_hard_links), link_dest=True)

        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test} (no hard links): source and target dirs are not the same")

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

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += Touch("hootenanny")  # add one file
            bc += CopyFileToDir(str(file_to_copy), str(dir_to_copy_to_no_hard_links), link_dest=False)
            bc += CopyFileToDir(str(file_to_copy), str(dir_to_copy_to_with_hard_links), link_dest=True)

        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test} (no hard links): source and target dirs are not the same")

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

        dir_to_copy_to_no_hard_links = self.test_folder.joinpath("copy-target-no-hard-links").resolve()
        self.assertFalse(dir_to_copy_to_no_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_no_hard_links} should not exist before test")
        target_file_no_hard_links = dir_to_copy_to_no_hard_links.joinpath(file_name).resolve()

        dir_to_copy_to_with_hard_links = self.test_folder.joinpath("copy-target-with-hard-links").resolve()
        self.assertFalse(dir_to_copy_to_with_hard_links.exists(), f"{self.which_test}: {dir_to_copy_to_with_hard_links} should not exist before test")
        target_file_with_hard_links = dir_to_copy_to_with_hard_links.joinpath(file_name).resolve()

        bc = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_copy_from))
            with bc.sub_section(Cd(str(dir_to_copy_from))) as sub_bc:
                bc += Touch("hootenanny")  # add one file
            bc += CopyFileToFile(str(file_to_copy), str(target_file_no_hard_links), link_dest=False)
            bc += CopyFileToFile(str(file_to_copy), str(target_file_with_hard_links), link_dest=True)

        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        dir_comp_no_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_no_hard_links)
        self.assertTrue(is_identical_dircmp(dir_comp_no_hard_links), "{self.which_test}  (no hard links): source and target dirs are not the same")

        dir_comp_with_hard_links = filecmp.dircmp(dir_to_copy_from, dir_to_copy_to_with_hard_links)
        self.assertTrue(is_hard_linked(dir_comp_with_hard_links), "{self.which_test}  (with hard links): source and target files are not hard links to the same file")

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

    def test_ChFlags(self):
        flags = {"hidden": stat.UF_HIDDEN,
                 "uchg": stat.UF_IMMUTABLE}
        test_file = self.test_folder.joinpath("chflags-me").resolve()
        self.assertFalse(test_file.exists(), f"{self.which_test}: {test_file} should not exist before test")

        bc = None
        with BatchCommandAccum() as bc:
            bc += Touch(str(test_file))
            bc += ChFlags(str(test_file), "hidden")
            bc += ChFlags(str(test_file), "uchg")
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(test_file.exists())

        files_flags = os.stat(str(test_file)).st_flags
        self.assertEqual((files_flags & flags['hidden']), flags['hidden'])
        self.assertEqual((files_flags & flags['uchg']), flags['uchg'])

        with BatchCommandAccum() as bc:
            bc += Unlock(str(test_file))                # so file can be erased
            bc += ChFlags(str(test_file), "nohidden")   # so file can be seen
        bc_repr = repr(bc)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        files_flags = os.stat(str(test_file)).st_flags
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

        with BatchCommandAccum() as bc:
            bc += AppendFileToFile(str(source_file), str(target_file))
        bc_repr = repr(bc)
        self.write_file_in_test_folder("batch.py", bc_repr)
        with capture_stdout(self.stdout_capture):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        self.write_file_in_test_folder("batch_output.txt", self.stdout_capture.getvalue())

        with open(target_file, "r") as rfd:
            concatenated_content = rfd.read()

        expected_content = content_2+content_1
        self.assertEqual(concatenated_content, expected_content)

if __name__ == '__main__':
    unittest.main()
