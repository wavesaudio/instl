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


class TestPythonBatchMain(unittest.TestCase):
    def __init__(self, which_test="apple"):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_MakeDirs_0_repr(self):
        """ test that MakeDirs.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        mk_dirs_obj = MakeDirs("a/b/c", "jane/and/jane", remove_obstacles=True)
        mk_dirs_obj_recreated = eval(repr(mk_dirs_obj))
        self.assertEqual(mk_dirs_obj, mk_dirs_obj_recreated, "MakeDirs.repr did not recreate MakeDirs object correctly")

    def test_MakeDirs_1_simple(self):
        """ test MakeDirs. 2 dirs should be created side by side """
        dir_to_make_1 = self.pbt.test_folder.joinpath(self.pbt.which_test+"_1").resolve()
        dir_to_make_2 = self.pbt.test_folder.joinpath(self.pbt.which_test+"_2").resolve()
        self.assertFalse(dir_to_make_1.exists(), f"{self.pbt.which_test}: before test {dir_to_make_1} should not exist")
        self.assertFalse(dir_to_make_2.exists(), f"{self.pbt.which_test}: before test {dir_to_make_2} should not exist")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(dir_to_make_1, dir_to_make_2, remove_obstacles=True)
        self.pbt.batch_accum += MakeDirs(dir_to_make_1, remove_obstacles=False)  # MakeDirs twice should be OK

        self.pbt.exec_and_capture_output()

        self.assertTrue(dir_to_make_1.exists(), f"{self.pbt.which_test}: {dir_to_make_1} should exist")
        self.assertTrue(dir_to_make_2.exists(), f"{self.pbt.which_test}: {dir_to_make_2} should exist")

    def test_MakeDirs_2_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=True the file should be removed and directory created in it's place.
        """
        dir_to_make = self.pbt.path_inside_test_folder("file-that-should-be-dir")
        self.assertFalse(dir_to_make.exists(), f"{self.pbt.which_test}: {dir_to_make} should not exist before test")

        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.pbt.which_test}: {dir_to_make} should be a file before test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(dir_to_make, remove_obstacles=True)

        self.pbt.exec_and_capture_output()

        self.assertTrue(dir_to_make.is_dir(), f"{self.pbt.which_test}: {dir_to_make} should be a dir")

    def test_MakeDirs_3_no_remove_obstacles(self):
        """ test MakeDirs remove_obstacles parameter.
            A file is created and MakeDirs is called to create a directory on the same path.
            Since remove_obstacles=False the file should not be removed and FileExistsError raised.
        """
        dir_to_make = self.pbt.path_inside_test_folder("file-that-should-not-be-dir")
        self.assertFalse(dir_to_make.exists(), f"{self.pbt.which_test}: {dir_to_make} should not exist before test")

        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.pbt.which_test}: {dir_to_make} should be a file")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(dir_to_make, remove_obstacles=False)

        self.pbt.exec_and_capture_output(expected_exception=FileExistsError)

        self.assertTrue(dir_to_make.is_file(), f"{self.pbt.which_test}: {dir_to_make} should still be a file")

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
        file_to_chmod = self.pbt.path_inside_test_folder("file-to-chmod")
        touch(file_to_chmod)
        mod_before = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        os.chmod(file_to_chmod, Chmod.all_read)
        initial_mode = utils.unix_permissions_to_str(stat.S_IMODE(os.stat(file_to_chmod).st_mode))
        expected_mode = utils.unix_permissions_to_str(Chmod.all_read)
        self.assertEqual(initial_mode, expected_mode, f"{self.pbt.which_test}: failed to chmod on test file before tests: {initial_mode} != {expected_mode}")

        # change to rwxrwxrwx
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        if sys.platform == 'darwin':  # Adding executable bit for mac
            new_mode = stat.S_IMODE(new_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        new_mode_symbolic = 'a=rwx'
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.pbt.exec_and_capture_output("chmod_a=rwx")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.pbt.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # pass inappropriate symbolic mode should result in ValueError exception and permissions should remain
        new_mode_symbolic = 'a=rwi'  # i is not a legal mode
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.pbt.exec_and_capture_output("chmod_a=rwi", expected_exception=ValueError)

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.pbt.which_test}: mode should remain {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to rw-rw-rw-
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        new_mode_symbolic = 'a-x'
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

        self.pbt.exec_and_capture_output("chmod_a-x")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.pbt.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        if sys.platform == 'darwin':  # Windows doesn't have an executable bit, test is skipped
            # change to rwxrwxrw-
            new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IXUSR | stat.S_IXGRP)
            new_mode_symbolic = 'ug+x'
            self.pbt.batch_accum.clear()
            self.pbt.batch_accum += Chmod(file_to_chmod, new_mode_symbolic)

            self.pbt.exec_and_capture_output("chmod_ug+x")

            mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
            self.assertEqual(new_mode, mod_after, f"{self.pbt.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

        # change to r--r--r--
        new_mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(file_to_chmod, 'u-wx')
        self.pbt.batch_accum += Chmod(file_to_chmod, 'g-wx')
        self.pbt.batch_accum += Chmod(file_to_chmod, 'o-wx')

        self.pbt.exec_and_capture_output("chmod_a-wx")

        mod_after = stat.S_IMODE(os.stat(file_to_chmod).st_mode)
        self.assertEqual(new_mode, mod_after, f"{self.pbt.which_test}: failed to chmod to {utils.unix_permissions_to_str(new_mode)} got {utils.unix_permissions_to_str(mod_after)}")

    def test_Chmod_recursive(self):
        """ test Chmod recursive
            A file is created and it's permissions are changed several times
        """
        if sys.platform == 'win32':
            return
        folder_to_chmod = self.pbt.path_inside_test_folder("folder-to-chmod")

        initial_mode = Chmod.all_read_write
        initial_mode_str = "a+rw"
        # create the folder
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(folder_to_chmod)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_chmod)) as cd_accum:
            cd_accum += Touch("hootenanny")  # add one file with fixed (none random) name
            cd_accum += MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41)
            cd_accum += Chmod(path=folder_to_chmod, mode=initial_mode_str, recursive=True)
        self.pbt.exec_and_capture_output("create the folder")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, initial_mode, Chmod.all_read_write_exec))

        # change to rwxrwxrwx
        new_mode_symbolic = 'a=rwx'
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.pbt.exec_and_capture_output("chmod a=rwx")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, Chmod.all_read_write_exec, Chmod.all_read_write_exec))

        # pass inappropriate symbolic mode should result in ValueError exception and permissions should remain
        new_mode_symbolic = 'a=rwi'  # i is not a legal mode
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.pbt.exec_and_capture_output("chmod invalid", expected_exception=subprocess.CalledProcessError)

        # change to r-xr-xr-x
        new_mode_symbolic = 'a-w'
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.pbt.exec_and_capture_output("chmod a-w")

        self.assertTrue(compare_chmod_recursive(folder_to_chmod, Chmod.all_read_exec, Chmod.all_read_exec))

        # change to rwxrwxrwx so folder can be deleted
        new_mode_symbolic = 'a+rwx'
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(folder_to_chmod, new_mode_symbolic, recursive=True)

        self.pbt.exec_and_capture_output("chmod restore perm")

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
        dir_to_make = self.pbt.path_inside_test_folder("cd-here")
        file_to_touch = dir_to_make.joinpath("touch-me").resolve()
        self.assertFalse(file_to_touch.exists(), f"{self.pbt.which_test}: before test {file_to_touch} should not exist")

        cwd_before = os.getcwd()
        self.assertNotEqual(dir_to_make, cwd_before, f"{self.pbt.which_test}: before test {dir_to_make} should not be current working directory")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(dir_to_make, remove_obstacles=False)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_make)) as sub_bc:
            sub_bc += Touch(file_to_touch.name)  # file's path is relative!

        self.pbt.exec_and_capture_output()

        self.assertTrue(file_to_touch.exists(), f"{self.pbt.which_test}: touched file was not created {file_to_touch}")

        cwd_after = os.getcwd()
        # cwd should be back to where it was
        self.assertEqual(cwd_before, cwd_after, "{self.pbt.which_test}: cd has not restored the current working directory was: {cwd_before}, now: {cwd_after}")

    def test_ChFlags_repr(self):
        chflags_obj = ChFlags("/a/file/to/change", "uchg")
        chflags_obj_recreated = eval(repr(chflags_obj))
        self.assertEqual(chflags_obj, chflags_obj_recreated, "ChFlags.repr did not recreate ChFlags object correctly")

    def test_ChFlags(self):
        test_file = self.pbt.path_inside_test_folder("chflags-me")
        self.assertFalse(test_file.exists(), f"{self.pbt.which_test}: {test_file} should not exist before test")

        self.pbt.batch_accum.clear()
        # On Windows, we must hide the file last or we won't be able to change additional flags
        self.pbt.batch_accum += Touch(test_file)
        self.pbt.batch_accum += ChFlags(test_file, "locked")
        self.pbt.batch_accum += ChFlags(test_file, "hidden")

        self.pbt.exec_and_capture_output("hidden_locked")

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

        self.pbt.batch_accum.clear()
        # On Windows, we must first unhide the file before we can change additional flags
        self.pbt.batch_accum += ChFlags(test_file, "nohidden")   # so file can be seen
        self.pbt.batch_accum += Unlock(test_file)                # so file can be erased

        self.pbt.exec_and_capture_output("nohidden")

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
        source_file = self.pbt.path_inside_test_folder("source-file.txt")
        self.assertFalse(source_file.exists(), f"{self.pbt.which_test}: {source_file} should not exist before test")
        target_file = self.pbt.path_inside_test_folder("target-file.txt")
        self.assertFalse(target_file.exists(), f"{self.pbt.which_test}: {target_file} should not exist before test")

        content_1 = ''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(124))
        content_2 = ''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase) for i in range(125))
        with open(source_file, "w") as wfd:
            wfd.write(content_1)
        with open(target_file, "w") as wfd:
            wfd.write(content_2)

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += AppendFileToFile(source_file, target_file)

        self.pbt.exec_and_capture_output()

        with open(target_file, "r") as rfd:
            concatenated_content = rfd.read()

        expected_content = content_2+content_1
        self.assertEqual(concatenated_content, expected_content)

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
        folder_to_wtar = self.pbt.path_inside_test_folder("folder-to-wtar")
        folder_wtarred = self.pbt.path_inside_test_folder("folder-to-wtar.wtar")
        dummy_wtar_file_to_replace = self.pbt.path_inside_test_folder("dummy-wtar-file-to-replace.dummy")
        with open(dummy_wtar_file_to_replace, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(dummy_wtar_file_to_replace.exists(), f"{self.pbt.which_test}: {dummy_wtar_file_to_replace} should have been created")
        another_folder = self.pbt.path_inside_test_folder("another-folder")
        wtarred_in_another_folder = another_folder.joinpath("folder-to-wtar.wtar").resolve()

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(folder_to_wtar)
        with self.pbt.batch_accum.sub_accum(Cd(folder_to_wtar)) as cd_accum:
            cd_accum += Touch("dohickey")  # add one file with fixed (none random) name
            cd_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=4, num_files_per_dir=7, file_size=41)
            cd_accum += Wtar(folder_to_wtar)  # wtar next to the folder
            cd_accum += Wtar(folder_to_wtar, dummy_wtar_file_to_replace)  # wtar on replacing existing file
            cd_accum += MakeDirs(another_folder)
            cd_accum += Wtar(folder_to_wtar, another_folder)  # wtar to a different folder
        self.pbt.exec_and_capture_output("wtar the folder")
        self.assertTrue(os.path.isfile(folder_wtarred), f"wtarred file was not found {folder_wtarred}")
        self.assertTrue(os.path.isfile(dummy_wtar_file_to_replace), f"dummy_wtar_file_to_replace file was not found {dummy_wtar_file_to_replace}")
        self.assertTrue(os.path.isfile(wtarred_in_another_folder), f"wtarred file in another folder was not found {wtarred_in_another_folder}")
        self.assertTrue(filecmp.cmp(folder_wtarred, dummy_wtar_file_to_replace), f"'{folder_wtarred}' and '{dummy_wtar_file_to_replace}' should be identical")
        self.assertTrue(filecmp.cmp(folder_wtarred, dummy_wtar_file_to_replace), f"'{folder_wtarred}' and '{dummy_wtar_file_to_replace}' should be identical")
        self.assertTrue(filecmp.cmp(folder_wtarred, wtarred_in_another_folder), f"'{folder_wtarred}' and '{wtarred_in_another_folder}' should be identical")

        unwtar_here = self.pbt.path_inside_test_folder("unwtar-here")
        unwtared_folder = unwtar_here.joinpath("folder-to-wtar").resolve()
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Unwtar(folder_wtarred, unwtar_here)
        self.pbt.exec_and_capture_output("unwtar the folder")
        dir_wtar_unwtar_diff = filecmp.dircmp(folder_to_wtar, unwtared_folder, ignore=['.DS_Store'])
        self.assertTrue(is_identical_dircmp(dir_wtar_unwtar_diff), f"{self.pbt.which_test} : before wtar and after unwtar dirs are not the same")

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
        folder_to_list = self.pbt.path_inside_test_folder("folder-to-list")
        list_out_file = self.pbt.path_inside_test_folder("list-output")

        # create the folder, with sub folder and one known file
        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as cd1_accum:
             cd1_accum += MakeDirs(folder_to_list)
             with cd1_accum.sub_accum(Cd(folder_to_list)) as cd2_accum:
                cd2_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=2, num_files_per_dir=8, file_size=41)
             cd1_accum += Ls(folder_to_list, out_file="list-output")
        self.pbt.exec_and_capture_output("ls folder")
        self.assertTrue(os.path.isdir(folder_to_list), f"{self.pbt.which_test} : folder to list was not created {folder_to_list}")
        self.assertTrue(os.path.isfile(list_out_file), f"{self.pbt.which_test} : list_out_file was not created {list_out_file}")

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
        wzip_input = self.pbt.path_inside_test_folder("wzip_in")
        self.assertFalse(wzip_input.exists(), f"{self.pbt.which_test}: {wzip_input} should not exist before test")
        wzip_output = self.pbt.path_inside_test_folder("wzip_in.wzip")
        self.assertFalse(wzip_output.exists(), f"{self.pbt.which_test}: {wzip_output} should not exist before test")

        unwzip_target_folder = self.pbt.path_inside_test_folder("unwzip_target")
        self.assertFalse(unwzip_target_folder.exists(), f"{self.pbt.which_test}: {unwzip_target_folder} should not exist before test")
        unwzip_target_file = self.pbt.path_inside_test_folder("wzip_in")
        self.assertFalse(unwzip_target_file.exists(), f"{self.pbt.which_test}: {unwzip_target_file} should not exist before test")

        # create a file to zip
        with open(wzip_input, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(wzip_input.exists(), f"{self.pbt.which_test}: {wzip_input} should have been created")

        with self.pbt.batch_accum as batchi:
            batchi += Wzip(wzip_input)
        self.pbt.exec_and_capture_output("Wzip a file")
        self.assertTrue(wzip_output.exists(), f"{self.pbt.which_test}: {wzip_output} should exist after test")
        self.assertTrue(wzip_input.exists(), f"{self.pbt.which_test}: {wzip_input} should exist after test")

        with self.pbt.batch_accum as batchi:
            batchi += Unwzip(wzip_output, unwzip_target_folder)
        self.pbt.exec_and_capture_output("Unwzip a file")
        self.assertTrue(unwzip_target_folder.exists(), f"{self.pbt.which_test}: {unwzip_target_folder} should exist before test")
        self.assertTrue(unwzip_target_file.exists(), f"{self.pbt.which_test}: {unwzip_target_file} should exist before test")
        self.assertTrue(filecmp.cmp(wzip_input, unwzip_target_file), f"'{wzip_input}' and '{unwzip_target_file}' should be identical")

    def test_Essentiality(self):
        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Stage("redundant section")) as redundant_accum:
            redundant_accum += Echo("redundant echo")
        self.assertEqual(self.pbt.batch_accum.total_progress_count(), 0, f"{self.pbt.which_test}: a Stage with only echo should discarded")
        with self.pbt.batch_accum.sub_accum(Stage("redundant section")) as redundant_accum:
            redundant_accum += Wzip("dummy no real path")
        self.assertGreater(self.pbt.batch_accum.total_progress_count(), 0, f"{self.pbt.which_test}: a Stage with essential command should not discarded")

    def test_RaiseException_repr(self):
        the_exception = ValueError
        the_message = "just a dummy exception"
        re_obj = RaiseException(the_exception, the_message)
        re_obj_recreated = eval(repr(re_obj))
        self.assertEqual(re_obj, re_obj_recreated, "RaiseException.repr (1) did not recreate RsyncClone object correctly")

    def test_RaiseException(self):
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += RaiseException(ValueError, "la la la")
        self.pbt.exec_and_capture_output(expected_exception=ValueError)

    def test_If_repr(self):
        the_condition = True
        obj = If(the_condition, if_true=Touch("hootenanny"), if_false=Touch("hootebunny"))
        if_repr = repr(obj)
        print(if_repr)
        obj_recreated = eval(if_repr)
        self.assertEqual(obj, obj_recreated, "If.repr (1) did not recreate If object correctly")

        obj = If(Path("/mama/mia/here/i/go/again").exists(), if_true=Touch("hootenanny"), if_false=Touch("hootebunny"))
        if_repr = repr(obj)
        print(if_repr)
        obj_recreated = eval(if_repr)
        self.assertEqual(obj, obj_recreated, "If.repr (1) did not recreate If object correctly")

    def test_IfFileExist(self):
        file_that_should_exist = self.pbt.path_inside_test_folder("should_exist")
        self.assertFalse(file_that_should_exist.exists(), f"{self.pbt.which_test}: {file_that_should_exist} should not exist before test")
        file_that_should_not_exist = self.pbt.path_inside_test_folder("should_not_exist")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not exist before test")
        file_touched_if_exist = self.pbt.path_inside_test_folder("touched_if_exist")
        self.assertFalse(file_touched_if_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_exist} should not exist before test")
        file_touched_if_not_exist = self.pbt.path_inside_test_folder("touched_if_not_exist")
        self.assertFalse(file_touched_if_not_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_not_exist} should not exist before test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Touch(file_that_should_exist)
        self.pbt.batch_accum += If(IsFile(file_that_should_exist), if_true=Touch(file_touched_if_exist), if_false=Touch(file_that_should_not_exist))
        self.pbt.batch_accum += If(IsFile(file_that_should_not_exist), if_true=Touch(file_that_should_not_exist), if_false=Touch(file_touched_if_not_exist))

        self.pbt.exec_and_capture_output()
        self.assertTrue(file_that_should_exist.exists(), f"{self.pbt.which_test}: {file_that_should_exist} should have been created")
        self.assertTrue(file_touched_if_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_exist} should have been created")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not have been created")
        self.assertTrue(file_touched_if_not_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_not_exist} should have been created")
