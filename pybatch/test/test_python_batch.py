#!/usr/bin/env python3.6


import sys
import os
import pathlib
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


def is_identical_dircomp_with_ignore(a_dircmp: filecmp.dircmp, filen_names_to_ignore):
    '''A non recusive function that tests that two folders are the same, but testing that the ignore list has been ignored (and not copied to trg folder)'''
    return a_dircmp.left_only == filen_names_to_ignore and len(a_dircmp.right_only) == 0 and len(a_dircmp.diff_files) == 0


def is_same_inode(file_1, file_2):
    retVal = os.stat(file_1)[stat.ST_INO] == os.stat(file_2)[stat.ST_INO]
    return retVal


def is_hard_linked(a_dircmp: filecmp.dircmp):
    """ check that all same_files are hard link of each other"""
    retVal = True
    for a_file in a_dircmp.same_files:
        left_file = os.path.join(a_dircmp.left, a_file)
        right_file = os.path.join(a_dircmp.right, a_file)
        retVal = is_same_inode(left_file, right_file)
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


def is_hidden(filepath):
    name = os.path.basename(os.path.abspath(filepath))
    return name.startswith('.') or has_hidden_attribute(filepath)


def has_hidden_attribute(filepath):
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(filepath))
        assert attrs != -1
        result = bool(attrs & 2)
    except (AttributeError, AssertionError):
        result = False
    return result


main_test_folder_name = "python_batch_test_results"


class TestPythonBatch(unittest.TestCase):
    def __init__(self, which_test="banana"):
        super().__init__(which_test)
        self.which_test = which_test.lstrip("test_")
        self.test_folder = pathlib.Path(__file__).joinpath(os.pardir, os.pardir, os.pardir).resolve().joinpath(main_test_folder_name, self.which_test)
        self.batch_accum: PythonBatchCommandAccum = PythonBatchCommandAccum()
        self.sub_test_counter = 0

    def setUp(self):
        """ for each test create it's own test sub-fold"""
        if self.test_folder.exists():
            for root, dirs, files in os.walk(str(self.test_folder)):
                for d in dirs:
                    os.chmod(os.path.join(root, d), Chmod.all_read_write_exec)
                for f in files:
                    os.chmod(os.path.join(root, f), Chmod.all_read_write)
            shutil.rmtree(self.test_folder)  # make sure the folder is erased
        self.test_folder.mkdir(parents=True, exist_ok=False)
        self.batch_accum.set_current_section("pre")

    def tearDown(self):
        pass

    def path_inside_test_folder(self, name):
        return self.test_folder.joinpath(name).resolve()

    def write_file_in_test_folder(self, file_name, contents):
        with open(self.path_inside_test_folder(file_name), "w") as wfd:
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
                try:
                    ops = exec(f"""{bc_repr}""", globals(), locals())
                except SyntaxError:
                    print(f"> > > > SyntaxError in {test_name}")
                    raise
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

        self.batch_accum.clear()
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
        dir_to_make = self.path_inside_test_folder("file-that-should-be-dir")
        self.assertFalse(dir_to_make.exists(), f"{self.which_test}: {dir_to_make} should not exist before test")

        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should be a file before test")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_make, remove_obstacles=True)

        self.exec_and_capture_output()

        self.assertTrue(dir_to_make.is_dir(), f"{self.which_test}: {dir_to_make} should be a dir")

    def test_MakeDirs_3_no_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=False the file should not be removed and FileExistsError raised.
        """
        dir_to_make = self.path_inside_test_folder("file-that-should-not-be-dir")
        self.assertFalse(dir_to_make.exists(), f"{self.which_test}: {dir_to_make} should not exist before test")

        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should be a file")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_make, remove_obstacles=False)

        self.exec_and_capture_output(expected_exception=FileExistsError)

        self.assertTrue(dir_to_make.is_file(), f"{self.which_test}: {dir_to_make} should still be a file")

    def test_Chmod_repr(self):
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        chmod_obj = Chmod("a/b/c", new_mode, recursive=False)
        chmod_obj_recreated = eval(repr(chmod_obj))
        self.assertEqual(chmod_obj, chmod_obj_recreated, "Chmod.repr did not recreate Chmod object correctly (mode is int)")

        new_mode = "a-rw"
        chmod_obj = Chmod("a/b/c", new_mode, recursive=False)
        chmod_obj_recreated = eval(repr(chmod_obj))
        self.assertEqual(chmod_obj, chmod_obj_recreated, "Chmod.repr did not recreate Chmod object correctly (mode is symbolic)")

    def test_Chmod_non_recursive(self):
        """ test Chmod
            A file is created and it's permissions are changed several times
        """
        # TODO: Add test for symbolic links
        file_to_chmod = self.path_inside_test_folder("file-to-chmod")
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
        self.batch_accum.clear()
        self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.exec_and_capture_output("chmod_a=rwx")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # pass inappropriate symbolic mode should result in ValueError exception and permissions should remain
        new_mode_symbolic = 'a=rwi'  # i is not a legal mode
        self.batch_accum.clear()
        self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.exec_and_capture_output("chmod_a=rwi", expected_exception=ValueError)

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: mode should remain {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to rw-rw-rw-
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        new_mode_symbolic = 'a-x'
        self.batch_accum.clear()
        self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.exec_and_capture_output("chmod_a-x")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        if sys.platform == 'darwin':  # Windows doesn't have an executable bit, test is skipped
            # change to rwxrwxrw-
            new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IXUSR | stat.S_IXGRP)
            new_mode_symbolic = 'ug+x'
            self.batch_accum.clear()
            self.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

            self.exec_and_capture_output("chmod_ug+x")

            mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
            self.assertEqual(new_mode, mod_after, f"{self.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to r--r--r--
        new_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        self.batch_accum.clear()
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
        if sys.platform == 'win32':
            return
        folder_to_chmod = self.path_inside_test_folder("folder-to-chmod")

        initial_mode = Chmod.all_read_write
        initial_mode_str = "a+rw"
        # create the folder
        self.batch_accum.clear()
        self.batch_accum += MakeDirs(folder_to_chmod)
        with self.batch_accum.sub_accum(Cd(folder_to_chmod)) as cd_accum:
            cd_accum += Touch("hootenanny")  # add one file with fixed (none random) name
            cd_accum += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
            cd_accum += Chmod(path=folder_to_chmod, mode=initial_mode_str, recursive=True)
        self.exec_and_capture_output("create the folder")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, initial_mode, Chmod.all_read_write_exec))

        # change to rwxrwxrwx
        new_mode_symbolic = 'a=rwx'
        self.batch_accum.clear()
        self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod a=rwx")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, Chmod.all_read_write_exec, Chmod.all_read_write_exec))

        # pass inappropriate symbolic mode should result in ValueError exception and permissions should remain
        new_mode_symbolic = 'a=rwi'  # i is not a legal mode
        self.batch_accum.clear()
        self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod invalid", expected_exception=subprocess.CalledProcessError)

        # change to r-xr-xr-x
        new_mode_symbolic = 'a-w'
        self.batch_accum.clear()
        self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod a-w")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, Chmod.all_read_exec, Chmod.all_read_exec))

        # change to rwxrwxrwx so folder can be deleted
        new_mode_symbolic = 'a+rwx'
        self.batch_accum.clear()
        self.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.exec_and_capture_output("chmod restore perm")

    def test_Cd_repr(self):
        cd_obj = Cd("a/b/c")
        cd_obj_recreated = eval(repr(cd_obj))
        self.assertEqual(cd_obj, cd_obj_recreated, "Cd.repr did not recreate Cd object correctly")

    def test_Touch_repr(self):
        touch_obj = Touch("/f/g/h")
        touch_obj_recreated = eval(repr(touch_obj))
        self.assertEqual(touch_obj, touch_obj, "Touch.repr did not recreate Touch object correctly")

    def test_Cd_and_Touch_1(self):
        """ test Cd and Touch
            A directory is created and Cd is called to make it the current working directory.
            Inside a file is created ('touched'). After that current working directory should return
            to it's initial value
        """
        dir_to_make = self.path_inside_test_folder("cd-here")
        file_to_touch = dir_to_make.joinpath("touch-me").resolve()
        self.assertFalse(file_to_touch.exists(), f"{self.which_test}: before test {file_to_touch} should not exist")

        cwd_before = os.getcwd()
        self.assertNotEqual(dir_to_make, cwd_before, f"{self.which_test}: before test {dir_to_make} should not be current working directory")

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_make, remove_obstacles=False)
        with self.batch_accum.sub_accum(Cd(dir_to_make)) as sub_bc:
            sub_bc += Touch(file_to_touch.name)  # file's path is relative!

        self.exec_and_capture_output()

        self.assertTrue(file_to_touch.exists(), f"{self.which_test}: touched file was not created {file_to_touch}")

        cwd_after = os.getcwd()
        # cwd should be back to where it was
        self.assertEqual(cwd_before, cwd_after, "{self.which_test}: cd has not restored the current working directory was: {cwd_before}, now: {cwd_after}")

    def test_CopyDirToDir_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        cdtd_obj = CopyDirToDir(dir_from, dir_to, hard_links=False)
        cdtd_obj_repr = repr(cdtd_obj)
        cdtd_obj_recreated = eval(cdtd_obj_repr)
        self.assertEqual(cdtd_obj, cdtd_obj_recreated, "CopyDirToDir.repr did not recreate CopyDirToDir object correctly")

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
        dir_to_remove = self.path_inside_test_folder("remove-me")
        self.assertFalse(dir_to_remove.exists())

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(dir_to_remove)
        with self.batch_accum.sub_accum(Cd(dir_to_remove)) as sub_bc:
            sub_bc += MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41)
        self.batch_accum += RmFile(dir_to_remove)  # RmFile should not remove a folder
        self.exec_and_capture_output(expected_exception=PermissionError)
        self.assertTrue(dir_to_remove.exists())

        self.batch_accum.clear()
        self.batch_accum += RmDir(dir_to_remove)
        self.exec_and_capture_output()
        self.assertFalse(dir_to_remove.exists())

    def test_ChFlags_repr(self):
        chflags_obj = ChFlags("/a/file/to/change", "uchg")
        chflags_obj_recreated = eval(repr(chflags_obj))
        self.assertEqual(chflags_obj, chflags_obj_recreated, "ChFlags.repr did not recreate ChFlags object correctly")

    def test_ChFlags(self):
        test_file = self.path_inside_test_folder("chflags-me")
        self.assertFalse(test_file.exists(), f"{self.which_test}: {test_file} should not exist before test")

        self.batch_accum.clear()
        # On Windows, we must hide the file last or we won't be able to change additional flags
        self.batch_accum += Touch(test_file)
        self.batch_accum += ChFlags(test_file, "locked")
        self.batch_accum += ChFlags(test_file, "hidden")

        self.exec_and_capture_output("hidden_locked")

        self.assertTrue(test_file.exists())

        flags = {"hidden": stat.UF_HIDDEN,
                 "locked": stat.UF_IMMUTABLE}
        if sys.platform == 'darwin':
            files_flags = os.stat(test_file).st_flags
            self.assertEqual((files_flags & flags['hidden']), flags['hidden'])
            self.assertEqual((files_flags & flags['locked']), flags['locked'])
        elif sys.platform == 'win32':
            self.assertTrue(is_hidden(test_file))
            self.assertFalse(os.access(test_file, os.W_OK))

        self.batch_accum.clear()
        # On Windows, we must first unhide the file before we can change additional flags
        self.batch_accum += ChFlags(test_file, "nohidden")   # so file can be seen
        self.batch_accum += Unlock(test_file)                # so file can be erased

        self.exec_and_capture_output("nohidden")

        if sys.platform == 'darwin':
            files_flags = os.stat(test_file).st_flags
            self.assertEqual((files_flags & flags['locked']), 0)
            self.assertEqual((files_flags & flags['hidden']), 0)
        elif sys.platform == 'win32':
            self.assertFalse(is_hidden(test_file))
            self.assertTrue(os.access(test_file, os.W_OK))

    def test_AppendFileToFile_repr(self):
        aftf_obj = AppendFileToFile("/a/file/to/append", "/a/file/to/appendee")
        aftf_obj_recreated = eval(repr(aftf_obj))
        self.assertEqual(aftf_obj, aftf_obj_recreated, "AppendFileToFile.repr did not recreate AppendFileToFile object correctly")

    def test_AppendFileToFile(self):
        source_file = self.path_inside_test_folder("source-file.txt")
        self.assertFalse(source_file.exists(), f"{self.which_test}: {source_file} should not exist before test")
        target_file = self.path_inside_test_folder("target-file.txt")
        self.assertFalse(target_file.exists(), f"{self.which_test}: {target_file} should not exist before test")

        content_1 = ''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(124))
        content_2 = ''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(125))
        with open(source_file, "w") as wfd:
            wfd.write(content_1)
        with open(target_file, "w") as wfd:
            wfd.write(content_2)

        self.batch_accum.clear()
        self.batch_accum += AppendFileToFile(source_file, target_file)

        self.exec_and_capture_output()

        with open(target_file, "r") as rfd:
            concatenated_content = rfd.read()

        expected_content = content_2+content_1
        self.assertEqual(concatenated_content, expected_content)

    def test_ShellCommands_repr(self):
        # ShellCommands.repr() cannot replicate it's original construction exactly
        # therefor the usual repr tests do not apply
        pass

    def test_ShellCommands(self):
        batches_dir = self.path_inside_test_folder("batches")
        self.assertFalse(batches_dir.exists(), f"{self.which_test}: {batches_dir} should not exist before test")

        if sys.platform == 'darwin':
            geronimo = [f"""ls /Users/shai/Desktop >> "{os.fspath(batches_dir)}/geronimo.txt\"""",
                        f"""[ -f "{os.fspath(batches_dir)}/geronimo.txt" ] && echo "g e r o n i m o" >> {os.fspath(batches_dir)}/geronimo.txt"""]
        else:

            # geronimo = [r"SET",]
            geronimo = [r"dir %appdata% >> %appdata%\geronimo.txt",
                        r"dir %userprofile%\desktop >> %userprofile%\desktop\geronimo.txt",
                        r"cmd /C dir %userprofile%\desktop >> %userprofile%\desktop\geronimo.txt",
                        r"cmd /C dir %userprofile%\desktop",]

        self.batch_accum.clear()
        #self.batch_accum += ConfigVarAssign("geronimo", *geronimo)
        self.batch_accum += MakeDirs(batches_dir)
        self.batch_accum += ShellCommands(shell_commands_list=geronimo, message="testing ShellCommands")

        self.exec_and_capture_output()

    def test_ParallelRun_repr(self):
        pr_obj = ParallelRun("/rik/ya/vik", True)
        pr_obj_recreated = eval(repr(pr_obj))
        self.assertEqual(pr_obj, pr_obj_recreated, "ParallelRun.repr did not recreate ParallelRun object correctly")

    def test_ParallelRun_shell(self):
        test_file = self.path_inside_test_folder("list-of-runs")
        self.assertFalse(test_file.exists(), f"{self.which_test}: {test_file} should not exist before test")
        ls_output = self.path_inside_test_folder("ls.out.txt")
        self.assertFalse(ls_output.exists(), f"{self.which_test}: {ls_output} should not exist before test")
        ps_output = self.path_inside_test_folder("ps.out.txt")
        self.assertFalse(ps_output.exists(), f"{self.which_test}: {ps_output} should not exist before test")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the ls\n""")
                wfd.write(f"""ls -l . > ls.out.txt\n""")
                wfd.write(f"""# meanwhile, do the ps\n""")
                wfd.write(f"""ps -x > ps.out.txt\n""")

        self.batch_accum.clear()
        with self.batch_accum.sub_accum(Cd(self.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, True)

        self.exec_and_capture_output()
        self.assertTrue(ls_output.exists(), f"{self.which_test}: {ls_output} was not created")
        self.assertTrue(ps_output.exists(), f"{self.which_test}: {ps_output} was not created")

    def test_ParallelRun_shell_bad_exit(self):
        test_file = self.path_inside_test_folder("list-of-runs")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the some good\n""")
                wfd.write(f"""true\n""")
                wfd.write(f"""# while also doing some bad\n""")
                wfd.write(f"""false\n""")

        self.batch_accum.clear()
        with self.batch_accum.sub_accum(Cd(self.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, True)

        self.exec_and_capture_output(expected_exception=SystemExit)

    def test_ParallelRun_no_shell(self):
        test_file = self.path_inside_test_folder("list-of-runs")
        self.assertFalse(test_file.exists(), f"{self.which_test}: {test_file} should not exist before test")

        zip_input = self.path_inside_test_folder("zip_in")
        self.assertFalse(zip_input.exists(), f"{self.which_test}: {zip_input} should not exist before test")
        zip_output = self.path_inside_test_folder("zip_in.bz2")
        self.assertFalse(zip_output.exists(), f"{self.which_test}: {zip_output} should not exist before test")
        zip_input_copy = self.path_inside_test_folder("zip_in.copy")
        self.assertFalse(zip_input_copy.exists(), f"{self.which_test}: {zip_input_copy} should not exist before test")

        # create a file to zip
        with open(zip_input, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(zip_input.exists(), f"{self.which_test}: {zip_input} should have been created")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the zip\n""")
                wfd.write(f"""bzip2 --compress {zip_input}\n""")
                wfd.write(f'''# also run some random program\n''')
                wfd.write(f'''bison --version\n''')

        self.batch_accum.clear()
        with self.batch_accum.sub_accum(Cd(self.test_folder)) as sub_bc:
            # save a copy of the input file
            sub_bc += CopyFileToFile(zip_input, zip_input_copy)
            # zip the input file, bzip2 will remove it
            sub_bc += ParallelRun(test_file, False)

        self.exec_and_capture_output()
        self.assertFalse(zip_input.exists(), f"{self.which_test}: {zip_input} should have been erased by bzip2")
        self.assertTrue(zip_output.exists(), f"{self.which_test}: {zip_output} should have been created by bzip2")
        self.assertTrue(zip_input_copy.exists(), f"{self.which_test}: {zip_input_copy} should have been copied")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the unzip\n""")
                # unzip the zipped file an keep the
                wfd.write(f"""bzip2 --decompress --keep {zip_output}\n""")
                wfd.write(f'''# also run some random program\n''')
                wfd.write(f'''bison --version\n''')

        self.batch_accum.clear()
        with self.batch_accum.sub_accum(Cd(self.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, False)

        self.exec_and_capture_output()
        self.assertTrue(zip_input.exists(), f"{self.which_test}: {zip_input} should have been created by bzip2")
        self.assertTrue(zip_output.exists(), f"{self.which_test}: {zip_output} should not have been erased by bzip2")
        self.assertTrue(zip_input_copy.exists(), f"{self.which_test}: {zip_input_copy} should remain")

        self.assertTrue(filecmp.cmp(zip_input, zip_input_copy), f"'{zip_input}' and '{zip_input_copy}' should be identical")

    def test_Wtar_Unwtar_repr(self):
        wtar_obj = Wtar("/the/memphis/belle")
        wtar_obj_recreated = eval(repr(wtar_obj))
        self.assertEqual(wtar_obj, wtar_obj_recreated, "Wtar.repr did not recreate Wtar object correctly")

        wtar_obj = Wtar("/the/memphis/belle", None)
        wtar_obj_recreated = eval(repr(wtar_obj))
        self.assertEqual(wtar_obj, wtar_obj_recreated, "Wtar.repr did not recreate Wtar object correctly")

        wtar_obj = Wtar("/the/memphis/belle", "robota")
        wtar_obj_recreated = eval(repr(wtar_obj))
        self.assertEqual(wtar_obj, wtar_obj_recreated, "Wtar.repr did not recreate Wtar object correctly")

        unwtar_obj = Unwtar("/the/memphis/belle")
        unwtar_obj_recreated = eval(repr(unwtar_obj))
        self.assertEqual(unwtar_obj, unwtar_obj_recreated, "Unwtar.repr did not recreate Unwtar object correctly")

        unwtar_obj = Unwtar("/the/memphis/belle", None)
        unwtar_obj_recreated = eval(repr(unwtar_obj))
        self.assertEqual(unwtar_obj, unwtar_obj_recreated, "Unwtar.repr did not recreate Unwtar object correctly")

        unwtar_obj = Unwtar("/the/memphis/belle", "robota", no_artifacts=True)
        unwtar_obj_recreated = eval(repr(unwtar_obj))
        self.assertEqual(unwtar_obj, unwtar_obj_recreated, "Unwtar.repr did not recreate Unwtar object correctly")

    def test_Wtar_Unwtar(self):
        folder_to_wtar = self.path_inside_test_folder("folder-to-wtar")
        folder_wtarred = self.path_inside_test_folder("folder-to-wtar.wtar")
        dummy_wtar_file_to_replace = self.path_inside_test_folder("dummy-wtar-file-to-replace.dummy")
        with open(dummy_wtar_file_to_replace, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(dummy_wtar_file_to_replace.exists(), f"{self.which_test}: {dummy_wtar_file_to_replace} should have been created")
        another_folder = self.path_inside_test_folder("another-folder")
        wtarred_in_another_folder = another_folder.joinpath("folder-to-wtar.wtar").resolve()

        self.batch_accum.clear()
        self.batch_accum += MakeDirs(folder_to_wtar)
        with self.batch_accum.sub_accum(Cd(folder_to_wtar)) as cd_accum:
            cd_accum += Touch("dohickey")  # add one file with fixed (none random) name
            cd_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=4, num_files_per_dir=7, file_size=41)
            cd_accum += Wtar(folder_to_wtar)  # wtar next to the folder
            cd_accum += Wtar(folder_to_wtar, dummy_wtar_file_to_replace)  # wtar on replacing existing file
            cd_accum += MakeDirs(another_folder)
            cd_accum += Wtar(folder_to_wtar, another_folder)  # wtar to a different folder
        self.exec_and_capture_output("wtar the folder")
        self.assertTrue(os.path.isfile(folder_wtarred), f"wtarred file was not found {folder_wtarred}")
        self.assertTrue(os.path.isfile(dummy_wtar_file_to_replace), f"dummy_wtar_file_to_replace file was not found {dummy_wtar_file_to_replace}")
        self.assertTrue(os.path.isfile(wtarred_in_another_folder), f"wtarred file in another folder was not found {wtarred_in_another_folder}")
        self.assertTrue(filecmp.cmp(folder_wtarred, dummy_wtar_file_to_replace), f"'{folder_wtarred}' and '{dummy_wtar_file_to_replace}' should be identical")
        self.assertTrue(filecmp.cmp(folder_wtarred, dummy_wtar_file_to_replace), f"'{folder_wtarred}' and '{dummy_wtar_file_to_replace}' should be identical")
        self.assertTrue(filecmp.cmp(folder_wtarred, wtarred_in_another_folder), f"'{folder_wtarred}' and '{wtarred_in_another_folder}' should be identical")

        unwtar_here = self.path_inside_test_folder("unwtar-here")
        unwtared_folder = unwtar_here.joinpath("folder-to-wtar").resolve()
        self.batch_accum.clear()
        self.batch_accum += Unwtar(folder_wtarred, unwtar_here)
        self.exec_and_capture_output("unwtar the folder")
        dir_wtar_unwtar_diff = filecmp.dircmp(folder_to_wtar, unwtared_folder, ignore=['.DS_Store'])
        self.assertTrue(is_identical_dircmp(dir_wtar_unwtar_diff), f"{self.which_test} : before wtar and after unwtar dirs are not the same")

    def test_WinShortcut_repr(self):
        if sys.platform == "win32":
            win_shortcut_obj = WinShortcut("/the/memphis/belle", "/go/to/hell")
            win_shortcut_obj_recreated = eval(repr(win_shortcut_obj))
            self.assertEqual(win_shortcut_obj, win_shortcut_obj_recreated, "WinShortcut.repr did not recreate WinShortcut object correctly")

            win_shortcut_obj = WinShortcut("/the/memphis/belle", "/go/to/hell", False)
            win_shortcut_obj_recreated = eval(repr(win_shortcut_obj))
            self.assertEqual(win_shortcut_obj, win_shortcut_obj_recreated, "WinShortcut.repr did not recreate WinShortcut object correctly")

            win_shortcut_obj = WinShortcut("/the/memphis/belle", "/go/to/hell", run_as_admin=True)
            win_shortcut_obj_recreated = eval(repr(win_shortcut_obj))
            self.assertEqual(win_shortcut_obj, win_shortcut_obj_recreated, "WinShortcut.repr did not recreate WinShortcut object correctly")

    def test_WinShortcut(self):
        if sys.platform == "win32":
            pass  # TBD on windows

    def test_MacDoc_repr(self):
        if sys.platform == "darwin":
            mac_dock_obj = MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True)
            mac_dock_obj_recreated = eval(repr(mac_dock_obj))
            self.assertEqual(mac_dock_obj, mac_dock_obj_recreated, "MacDoc.repr did not recreate MacDoc object correctly")

            mac_dock_obj = MacDock("/Santa/Catalina/Island", "Santa Catalina Island", False)
            mac_dock_obj_recreated = eval(repr(mac_dock_obj))
            self.assertEqual(mac_dock_obj, mac_dock_obj_recreated, "MacDoc.repr did not recreate MacDoc object correctly")

            mac_dock_obj = MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True, remove=True)
            mac_dock_obj_recreated = eval(repr(mac_dock_obj))
            self.assertEqual(mac_dock_obj, mac_dock_obj_recreated, "MacDoc.repr did not recreate MacDoc object correctly")

    def test_MacDoc(self):
        if sys.platform == "darwin":
            pass  # who do we check this?

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
        folder_to_remove = self.path_inside_test_folder("folder-to-remove")
        file_to_stay = folder_to_remove.joinpath("paramedic")

        # create the folder, with sub folder and one known file
        self.batch_accum.clear()
        self.batch_accum += MakeDirs(folder_to_remove)
        with self.batch_accum.sub_accum(Cd(folder_to_remove)) as cd_accum:
            cd_accum += Touch(file_to_stay.name)
            cd_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=2, num_files_per_dir=0, file_size=41)
        self.exec_and_capture_output("create empty folders")
        self.assertTrue(os.path.isdir(folder_to_remove), f"{self.which_test} : folder to remove was not created {folder_to_remove}")
        self.assertTrue(os.path.isfile(file_to_stay), f"{self.which_test} : file_to_stay was not created {file_to_stay}")

        # remove empty folders, top folder and known file should remain
        self.batch_accum.clear()
        self.batch_accum += RemoveEmptyFolders(folder_to_remove, files_to_ignore=['.DS_Store'])
        # removing non existing folder should not be a problem
        self.batch_accum += RemoveEmptyFolders("kajagogo", files_to_ignore=['.DS_Store'])
        self.exec_and_capture_output("remove almost empty folders")
        self.assertTrue(os.path.isdir(folder_to_remove), f"{self.which_test} : folder was removed although it had a legit file {folder_to_remove}")
        self.assertTrue(os.path.isfile(file_to_stay), f"{self.which_test} : file_to_stay was removed {file_to_stay}")

        # remove empty folders, with known file ignored - so to folder should be removed
        self.batch_accum.clear()
        self.batch_accum += RemoveEmptyFolders(folder_to_remove, files_to_ignore=['.DS_Store', "paramedic"])
        self.exec_and_capture_output("remove empty folders")
        self.assertFalse(os.path.isdir(folder_to_remove), f"{self.which_test} : folder was not removed {folder_to_remove}")
        self.assertFalse(os.path.isfile(file_to_stay), f"{self.which_test} : file_to_stay was not removed {file_to_stay}")

    def test_Ls_repr(self):
        with self.assertRaises(AssertionError):
            ref_obj = Ls([])

        ls_obj = Ls('', out_file="empty.txt")
        ls_obj_recreated = eval(repr(ls_obj))
        self.assertEqual(ls_obj, ls_obj_recreated, "Ls.repr did not recreate Ls object correctly")

        ls_obj = Ls("/per/pen/di/cular", out_file="perpendicular_ls.txt", ls_format='abc')
        ls_obj_recreated = eval(repr(ls_obj))
        self.assertEqual(ls_obj, ls_obj_recreated, "Ls.repr did not recreate Ls object correctly")

        ls_obj = Ls("/Gina/Lollobrigida", r"C:\Users\nira\AppData\Local\Waves Audio\instl\Cache/instl/V10", out_file="Lollobrigida.txt")
        ls_obj_recreated = eval(repr(ls_obj))
        self.assertEqual(ls_obj, ls_obj_recreated, "Ls.repr did not recreate Ls object correctly")

    def test_Ls(self):
        folder_to_list = self.path_inside_test_folder("folder-to-list")
        list_out_file = self.path_inside_test_folder("list-output")

        # create the folder, with sub folder and one known file
        self.batch_accum.clear()
        with self.batch_accum.sub_accum(Cd(self.test_folder)) as cd1_accum:
             cd1_accum += MakeDirs(folder_to_list)
             with cd1_accum.sub_accum(Cd(folder_to_list)) as cd2_accum:
                cd2_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=2, num_files_per_dir=8, file_size=41)
             cd1_accum += Ls(folder_to_list, out_file="list-output")
        self.exec_and_capture_output("ls folder")
        self.assertTrue(os.path.isdir(folder_to_list), f"{self.which_test} : folder to list was not created {folder_to_list}")
        self.assertTrue(os.path.isfile(list_out_file), f"{self.which_test} : list_out_file was not created {list_out_file}")

    def test_Wzip_repr(self):
        wzip_obj = Wzip("/the/memphis/belle")
        wzip_obj_recreated = eval(repr(wzip_obj))
        self.assertEqual(wzip_obj, wzip_obj_recreated, "Wzip.repr did not recreate Wzip object correctly")

        wzip_obj = Wzip("/the/memphis/belle", None)
        wzip_obj_recreated = eval(repr(wzip_obj))
        self.assertEqual(wzip_obj, wzip_obj_recreated, "Wzip.repr did not recreate Wzip object correctly")

        wzip_obj = Wzip("/the/memphis/belle", "robota")
        wzip_obj_recreated = eval(repr(wzip_obj))
        self.assertEqual(wzip_obj, wzip_obj_recreated, "Wzip.repr did not recreate Wzip object correctly")

        unwzip_obj = Unwzip("/the/memphis/belle")
        unwzip_obj_recreated = eval(repr(unwzip_obj))
        self.assertEqual(unwzip_obj, unwzip_obj_recreated, "Unwzip.repr did not recreate Unwzip object correctly")

        unwzip_obj = Unwzip("/the/memphis/belle", None)
        unwzip_obj_recreated = eval(repr(unwzip_obj))
        self.assertEqual(unwzip_obj, unwzip_obj_recreated, "Unwzip.repr did not recreate Unwzip object correctly")

        unwzip_obj = Unwzip("/the/memphis/belle", "robota")
        unwzip_obj_recreated = eval(repr(unwzip_obj))
        self.assertEqual(wzip_obj, wzip_obj_recreated, "Wzip.repr did not recreate Wzip object correctly")

    def test_Wzip(self):
        wzip_input = self.path_inside_test_folder("wzip_in")
        self.assertFalse(wzip_input.exists(), f"{self.which_test}: {wzip_input} should not exist before test")
        wzip_output = self.path_inside_test_folder("wzip_in.wzip")
        self.assertFalse(wzip_output.exists(), f"{self.which_test}: {wzip_output} should not exist before test")

        unwzip_target_folder = self.path_inside_test_folder("unwzip_target")
        self.assertFalse(unwzip_target_folder.exists(), f"{self.which_test}: {unwzip_target_folder} should not exist before test")
        unwzip_target_file = self.path_inside_test_folder("wzip_in")
        self.assertFalse(unwzip_target_file.exists(), f"{self.which_test}: {unwzip_target_file} should not exist before test")

        # create a file to zip
        with open(wzip_input, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(wzip_input.exists(), f"{self.which_test}: {wzip_input} should have been created")

        with self.batch_accum as batchi:
            batchi += Wzip(wzip_input)
        self.exec_and_capture_output("Wzip a file")
        self.assertTrue(wzip_output.exists(), f"{self.which_test}: {wzip_output} should exist after test")
        self.assertTrue(wzip_input.exists(), f"{self.which_test}: {wzip_input} should exist after test")

        with self.batch_accum as batchi:
            batchi += Unwzip(wzip_output, unwzip_target_folder)
        self.exec_and_capture_output("Unwzip a file")
        self.assertTrue(unwzip_target_folder.exists(), f"{self.which_test}: {unwzip_target_folder} should exist before test")
        self.assertTrue(unwzip_target_file.exists(), f"{self.which_test}: {unwzip_target_file} should exist before test")
        self.assertTrue(filecmp.cmp(wzip_input, unwzip_target_file), f"'{wzip_input}' and '{unwzip_target_file}' should be identical")

    def test_Curl_repr(self):
        url_from = r"http://www.google.com"
        file_to = "/q/w/r"
        curl_path = 'curl'
        if sys.platform == 'win32':
            curl_path = r'C:\Program Files (x86)\Waves Central\WavesLicenseEngine.bundle\Contents\Win32\curl.exe'
        curl_obj = CUrl(url_from, file_to, curl_path)
        curl_obj_recreated = eval(repr(curl_obj))
        self.assertEqual(curl_obj, curl_obj_recreated, "CUrl.repr did not recreate CUrl object correctly")

    def test_Curl_download(self):
        sample_file = pathlib.Path(__file__).joinpath('../test_data/curl_sample.txt').resolve()
        with open(sample_file, 'r') as stream:
            test_data = stream.read()
        url_from = 'https://www.sample-videos.com/text/Sample-text-file-10kb.txt'
        to_path = self.path_inside_test_folder("curl")
        curl_path = 'curl'
        if sys.platform == 'win32':
            curl_path = r'C:\Program Files (x86)\Waves Central\WavesLicenseEngine.bundle\Contents\Win32\curl.exe'
        os.makedirs(to_path, exist_ok=True)
        downloaded_file = os.path.join(to_path, 'Sample.txt')
        with self.batch_accum as batchi:
            batchi += CUrl(url_from, downloaded_file, curl_path)
        self.exec_and_capture_output("Download file")
        with open(downloaded_file, 'r') as stream:
            downloaded_data = stream.read()
        self.assertEqual(test_data, downloaded_data)

    def test_Essentiality(self):
        self.batch_accum.clear()
        with self.batch_accum.sub_accum(Section("redundant section")) as redundant_accum:
            redundant_accum += Echo("redundant echo")
        self.assertEqual(self.batch_accum.total_progress_count(), 0, f"{self.which_test}: a Section with only echo should discarded")
        with self.batch_accum.sub_accum(Section("redundant section")) as redundant_accum:
            redundant_accum += Wzip("dummy no real path")
        self.assertGreater(self.batch_accum.total_progress_count(), 0, f"{self.which_test}: a Section with essential command should not discarded")

    def test_CreateSymlink_repr(self):

        if sys.platform != 'darwin':
            return

        some_file_path = "/Pippi/Långstrump"
        some_symlink_path = "/Astrid/Anna/Emilia/Lindgren"
        create_symlink_obj = CreateSymlink(some_symlink_path, some_file_path)
        create_symlink_obj_recreated = eval(repr(create_symlink_obj))
        self.assertEqual(create_symlink_obj, create_symlink_obj_recreated, "CreateSymlink.repr did not recreate CreateSymlink object correctly")

    def test_CreateSymlink(self):

        if sys.platform != 'darwin':
            return

        a_file_to_symlink = self.path_inside_test_folder("symlink_me_file")
        symlink_to_a_file = self.path_inside_test_folder("symlink_of_a_file")
        relative_symlink_to_a_file = self.path_inside_test_folder("relative_symlink_of_a_file")
        a_folder_to_symlink = self.path_inside_test_folder("symlink_me_folder")
        symlink_to_a_folder = self.path_inside_test_folder("symlink_of_a_folder")
        relative_symlink_to_a_folder = self.path_inside_test_folder("relative_symlink_of_a_folder")

        self.batch_accum.clear()
        self.batch_accum += Touch(a_file_to_symlink)
        self.batch_accum += MakeDirs(a_folder_to_symlink)
        self.batch_accum += CreateSymlink(symlink_to_a_file, a_file_to_symlink)
        self.batch_accum += CreateSymlink(symlink_to_a_folder, a_folder_to_symlink)
        self.batch_accum += CreateSymlink(relative_symlink_to_a_file, a_file_to_symlink.name)
        self.batch_accum += CreateSymlink(relative_symlink_to_a_folder, a_folder_to_symlink.name)
        self.exec_and_capture_output("CreateSymlink")

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
        a_file_original_from_relative_symlink = self.path_inside_test_folder(os.readlink(relative_symlink_to_a_file))
        a_folder_original_from_relative_symlink = self.path_inside_test_folder(os.readlink(relative_symlink_to_a_folder))
        self.assertTrue(a_file_to_symlink.samefile(a_file_original_from_relative_symlink), f"symlink resolved to {a_file_original_from_relative_symlink} not to {a_file_to_symlink} as expected")
        self.assertTrue(a_folder_to_symlink.samefile(a_folder_original_from_relative_symlink), f"symlink resolved to {a_folder_original_from_relative_symlink} not to {a_folder_to_symlink} as expected")

    def test_SymlinkToSymlinkFile_repr(self):

        if sys.platform != 'darwin':
            return

        some_file_path = "/Pippi/Långstrump"
        create_symlink_obj = SymlinkToSymlinkFile(some_file_path)
        create_symlink_obj_recreated = eval(repr(create_symlink_obj))
        self.assertEqual(create_symlink_obj, create_symlink_obj_recreated, "SymlinkToSymlinkFile.repr did not recreate SymlinkToSymlinkFile object correctly")

    def test_SymlinkFileToSymlink_repr(self):

        if sys.platform != 'darwin':
            return

        some_file_path = "/Pippi/Långstrump.symlink"
        resolve_symlink_obj = SymlinkFileToSymlink(some_file_path)
        resolve_symlink_obj_reresolved = eval(repr(resolve_symlink_obj))
        self.assertEqual(resolve_symlink_obj, resolve_symlink_obj_reresolved, "SymlinkToSymlinkFile.repr did not reresolve SymlinkToSymlinkFile object correctly")

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
            original_to_symlink = self.path_inside_test_folder(name)

            symlink_to_a_original = self.path_inside_test_folder(f"symlink_of_{name}")
            relative_symlink_to_a_original = self.path_inside_test_folder(f"relative_symlink_of_{name}")

            symlink_file_of_original = pathlib.Path(os.fspath(symlink_to_a_original)+".symlink")
            symlink_file_of_relative = pathlib.Path(os.fspath(relative_symlink_to_a_original)+".symlink")

            return SymlinkTestData(original_to_symlink, symlink_to_a_original, symlink_file_of_original, relative_symlink_to_a_original, symlink_file_of_relative)

        file_symlink_test_data = create_symlink_test_data("a_file")
        folder_symlink_test_data = create_symlink_test_data("a_folder")

        self.batch_accum.clear()
        self.batch_accum += Touch(file_symlink_test_data.original_to_symlink)
        self.batch_accum += MakeDirs(folder_symlink_test_data.original_to_symlink)
        for test_data in file_symlink_test_data, folder_symlink_test_data:
            with self.batch_accum.sub_accum(Section(test_data.original_to_symlink.name)) as symlink_test_accum:
                symlink_test_accum += CreateSymlink(test_data.symlink_to_a_original, test_data.original_to_symlink)                # symlink with full path
                symlink_test_accum += CreateSymlink(test_data.relative_symlink_to_a_original, test_data.original_to_symlink.name)  # symlink with relative path
                symlink_test_accum += SymlinkToSymlinkFile(test_data.symlink_to_a_original)
                symlink_test_accum += SymlinkToSymlinkFile(test_data.relative_symlink_to_a_original)

        self.exec_and_capture_output("SymlinkToSymlinkFile Creating symlink files")

        for test_data in file_symlink_test_data, folder_symlink_test_data:
            self.assertFalse(os.path.islink(test_data[0]), f"SymlinkToSymlinkFile {test_data.original_to_symlink} should be a file not a symlink")
            self.assertFalse(test_data.symlink_to_a_original.exists(), f"SymlinkToSymlinkFile {test_data.symlink_to_a_original} should have been erased")
            self.assertFalse(test_data.relative_symlink_to_a_original.exists(), f"SymlinkToSymlinkFile {test_data.relative_symlink_to_a_original} should have been erased")
            self.assertTrue(test_data.symlink_file_of_original.is_file(), f"SymlinkToSymlinkFile {test_data.symlink_file_of_original} should be replaced by .symlink file")
            self.assertTrue(test_data.symlink_file_of_relative.is_file(), f"SymlinkToSymlinkFile {test_data.symlink_file_of_relative} should be replaced by .symlink file")
        for test_data in file_symlink_test_data, folder_symlink_test_data:
            self.batch_accum += SymlinkFileToSymlink(test_data.symlink_file_of_original)
            self.batch_accum += SymlinkFileToSymlink(test_data.symlink_file_of_relative)
        self.exec_and_capture_output("SymlinkToSymlinkFile resolving symlink files")

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
            os.chdir(self.test_folder)  # so relative resolve of symlink will work
            self.assertTrue(test_data.original_to_symlink.samefile(an_original_from_relative_symlink), f"symlink resolved to {an_original_from_relative_symlink} not to {test_data.symlink_to_a_original} as expected")

    def private_test_ConvertFolderOfSymlinks(self):
        """ to enable this test give a real path as folder_of_symlinks, preferably one with symlinks..."""

        if sys.platform != 'darwin':
            return

        folder_of_symlinks = pathlib.Path("/Users/shai/Desktop/Tk.framework")

        self.batch_accum.clear()
        self.batch_accum += CreateSymlinkFilesInFolder(folder_of_symlinks)
        self.exec_and_capture_output("test_ConvertFolderOfSymlinks_to_symlink_files")

        self.batch_accum.clear()
        self.batch_accum += ResolveSymlinkFilesInFolder(folder_of_symlinks)
        self.exec_and_capture_output("test_ConvertFolderOfSymlinks_from_symlink_files")

    def test_RsyncClone_repr(self):
        dir_from = r"\p\o\i"
        dir_to = "/q/w/r"
        cdtd_obj = RsyncClone(dir_from, dir_to)
        cdtd_obj_recreated = eval(repr(cdtd_obj))
        self.assertEqual(cdtd_obj, cdtd_obj_recreated, "RsyncClone.repr (1) did not recreate RsyncClone object correctly")

        cdtd_obj = RsyncClone(dir_from, dir_to, symlinks_as_symlinks=False,
                 ignore_patterns=['*.a', 'b.*'],
                 hard_links=False,
                 ignore_dangling_symlinks=True,
                 delete_extraneous_files=True,
                 verbose=17,
                 dry_run=True)
        print(repr(cdtd_obj))
        cdtd_obj_recreated = eval(repr(cdtd_obj))
        self.assertEqual(cdtd_obj, cdtd_obj_recreated, "RsyncClone.repr (2) did not recreate RsyncClone object correctly")

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

    def test_RaiseException_repr(self):
        the_exception = ValueError
        the_message = "just a dummy exception"
        re_obj = RaiseException(the_exception, the_message)
        re_obj_recreated = eval(repr(re_obj))
        self.assertEqual(re_obj, re_obj_recreated, "RaiseException.repr (1) did not recreate RsyncClone object correctly")

    def test_RaiseException(self):
        self.batch_accum.clear()
        self.batch_accum += RaiseException(ValueError, "la la la")
        self.exec_and_capture_output(expected_exception=ValueError)


if __name__ == '__main__':
    test_folder = pathlib.Path(__file__).joinpath(os.pardir, os.pardir, os.pardir).resolve().joinpath(main_test_folder_name)
    shutil.rmtree(test_folder)

    unittest.main()
