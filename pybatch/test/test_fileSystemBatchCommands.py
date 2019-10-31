#!/usr/bin/env python3.6


import sys
import os
from pathlib import Path
import unittest
import subprocess
import stat
import ctypes
import math
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


from .test_PythonBatchBase import *


class TestPythonBatchFileSystem(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_NewMakeDir_repr(self):
        self.pbt.reprs_test_runner(MakeDir('rumba'),
                                   MakeDir('pumba', remove_obstacles=False),
                                   MakeDir('pumba', remove_obstacles=True),
                                   MakeDir('pumba', chowner=False),
                                   MakeDir('pumba', chowner=True),
                                   MakeDir('pumba', remove_obstacles=False, chowner=False),
                                   MakeDir('pumba', remove_obstacles=True, chowner=False),
                                   MakeDir('pumba', remove_obstacles=False, chowner=True),
                                   MakeDir('pumba', remove_obstacles=True, chowner=True),
                                   )

    def test_MakeDir_1_simple(self):
        """ test MakeDir. 2 dirs should be created side by side """
        dir_to_make_1 = self.pbt.path_inside_test_folder(self.pbt.which_test+"_1")
        dir_to_make_2 = self.pbt.path_inside_test_folder(self.pbt.which_test+"_2")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDir(dir_to_make_1, remove_obstacles=True)
        self.pbt.batch_accum += MakeDir(dir_to_make_2, remove_obstacles=True)
        self.pbt.batch_accum += MakeDir(dir_to_make_1, remove_obstacles=False)  # MakeDir twice should be OK

        self.pbt.exec_and_capture_output()

        self.assertTrue(dir_to_make_1.exists(), f"{self.pbt.which_test}: {dir_to_make_1} should exist")
        self.assertTrue(dir_to_make_2.exists(), f"{self.pbt.which_test}: {dir_to_make_2} should exist")

    def test_MakeDir_2_remove_obstacles(self):
        """ test MakeDir remove_obstacles parameter.
            A file is created and MakeDir is called to create a directory on the same path.
            Since remove_obstacles=True the file should be removed and directory created in it's place.
        """
        dir_to_make = self.pbt.path_inside_test_folder("file-that-should-be-dir")
        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.pbt.which_test}: {dir_to_make} should be a file before test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDir(dir_to_make, remove_obstacles=True)

        self.pbt.exec_and_capture_output()

        self.assertTrue(dir_to_make.is_dir(), f"{self.pbt.which_test}: {dir_to_make} should be a dir")

    def test_MakeDir_3_no_remove_obstacles(self):
        """ test MakeDir remove_obstacles parameter.
            A file is created and MakeDir is called to create a directory on the same path.
            Since remove_obstacles=False the file should not be removed and FileExistsError raised.
        """
        dir_to_make = self.pbt.path_inside_test_folder("file-that-should-not-be-dir")
        touch(dir_to_make)
        self.assertTrue(dir_to_make.is_file(), f"{self.pbt.which_test}: {dir_to_make} should be a file")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDir(dir_to_make, remove_obstacles=False)

        self.pbt.exec_and_capture_output(expected_exception=FileExistsError)

        self.assertTrue(dir_to_make.is_file(), f"{self.pbt.which_test}: {dir_to_make} should still be a file")

    def test_Touch_repr(self):
        self.pbt.reprs_test_runner(Touch("/f/g/h"))

    def test_Cd_repr(self):
        self.pbt.reprs_test_runner(Cd("a/b/c"))

    def test_Cd_and_Touch(self):
        """ test Cd and Touch
            A directory is created and Cd is called to make it the current working directory.
            Inside a file is created ('touched'). After that current working directory should return
            to it's initial value
        """
        dir_to_make = self.pbt.path_inside_test_folder("cd-here")
        file_to_touch = dir_to_make.joinpath("touch-me").resolve()
        cwd_before = os.getcwd()
        self.assertNotEqual(dir_to_make, cwd_before, f"{self.pbt.which_test}: before test {dir_to_make} should not be current working directory")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDir(dir_to_make, remove_obstacles=False)
        with self.pbt.batch_accum.sub_accum(Cd(dir_to_make)) as sub_bc:
            sub_bc += Touch(file_to_touch.name)  # file's path is relative!

        self.pbt.exec_and_capture_output()

        self.assertTrue(file_to_touch.exists(), f"{self.pbt.which_test}: touched file was not created {file_to_touch}")

        cwd_after = os.getcwd()
        # cwd should be back to where it was
        self.assertEqual(cwd_before, cwd_after, "{self.pbt.which_test}: cd has not restored the current working directory was: {cwd_before}, now: {cwd_after}")

    def test_Cd_fail(self):
        just_a_folder = self.pbt.path_inside_test_folder("just-a-folder")
        self.assertFalse(just_a_folder.exists())
        non_existing_dir = self.pbt.path_inside_test_folder("directory-should-not-exists")
        self.assertFalse(non_existing_dir.exists())
        dir_but_actualy_file = self.pbt.path_inside_test_folder("actualy-a-file")
        self.assertFalse(dir_but_actualy_file.exists())
        no_permissions_folder = self.pbt.path_inside_test_folder("no-permissions-folder")
        self.assertFalse(no_permissions_folder.exists())

        # normal cd no fail expected
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDir(just_a_folder)
        self.pbt.batch_accum += Cd(just_a_folder)
        self.pbt.exec_and_capture_output("cd")

        # cd to non existing dir FileNotFoundError expected
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Cd(non_existing_dir)
        self.pbt.exec_and_capture_output("cd to non-existing folder", expected_exception=FileNotFoundError)

        # cd to a file NotADirectoryError expected
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Touch(dir_but_actualy_file)
        self.pbt.batch_accum += Cd(dir_but_actualy_file)
        self.pbt.exec_and_capture_output("cd to file", expected_exception=NotADirectoryError)

        # cd with no permissions PermissionError expected
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDir(no_permissions_folder)
        self.pbt.batch_accum += Chmod(no_permissions_folder, mode="a-x")
        self.pbt.batch_accum += Cd(no_permissions_folder)
        self.pbt.exec_and_capture_output("cd with no permissions", expected_exception=PermissionError)

        # restore permissions so test folder can be deleted
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(no_permissions_folder, mode="a+x")
        self.pbt.exec_and_capture_output("restore permissions")

    def test_CdStage_repr(self):
        list_of_title_lists = ((), ("t1",), ("t2", "t3"))
        self.pbt.reprs_test_runner(*(CdStage("a good stage", "/a/file/to/change", *title_list) for title_list in list_of_title_lists ))

    def test_CdStage(self):
        pass

    def test_ChFlags_repr(self):
        list_of_reprs = list()
        list_of_flag_lists = (("hidden",), ("hidden", "locked"))

        for flag_list in list_of_flag_lists:
            list_of_reprs.append(ChFlags("/a/file/to/change", *flag_list))
        for flag_list in list_of_flag_lists:
            list_of_reprs.append(ChFlags("/a/file/to/change", *flag_list, recursive=True))
        for flag_list in list_of_flag_lists:
            list_of_reprs.append(ChFlags("/a/file/to/change", *flag_list, ignore_all_errors=True))
        for flag_list in list_of_flag_lists:
            list_of_reprs.append(ChFlags("/a/file/to/change", *flag_list, ignore_all_errors=True, recursive=True))

        self.pbt.reprs_test_runner(*list_of_reprs)

        with self.assertRaises(AssertionError):
            obj = ChFlags("/a/file/to/change", "hidden", "momo")

    def test_ChFlags_and_Unlock(self):
        test_file = self.pbt.path_inside_test_folder("chflags-me")

        self.pbt.batch_accum.clear()
        # On Windows, we must hide the file last or we won't be able to change additional flags
        self.pbt.batch_accum += Touch(test_file)
        self.pbt.batch_accum += ChFlags(test_file, "locked", "hidden")

        self.pbt.exec_and_capture_output("hidden_locked")

        self.assertTrue(test_file.exists())

        flags = {"hidden": stat.UF_HIDDEN,
                 "locked": stat.UF_IMMUTABLE}
        if sys.platform == 'darwin':
            files_flags = os.stat(test_file).st_flags
            self.assertEqual((files_flags & flags['hidden']), flags['hidden'])
            self.assertEqual((files_flags & flags['locked']), flags['locked'])
        elif sys.platform == 'win32':
            self.assertTrue(self.is_hidden(test_file))
            self.assertFalse(os.access(test_file, os.W_OK))

        self.pbt.batch_accum.clear()
        # On Windows, we must first unhide the file before we can change additional flags
        self.pbt.batch_accum += ChFlags(test_file, "nohidden")   # so file can be seen
        self.pbt.batch_accum += Unlock(test_file)                # so file can be deleted, Unlock is alias for ChFlags(..., "unlocked")

        self.pbt.exec_and_capture_output("nohidden_nolocked")

        if sys.platform == 'darwin':
            files_flags = os.stat(test_file).st_flags
            self.assertEqual((files_flags & flags['locked']), 0)
            self.assertEqual((files_flags & flags['hidden']), 0)
        elif sys.platform == 'win32':
            self.assertFalse(self.is_hidden(test_file))
            self.assertTrue(os.access(test_file, os.W_OK))

    @classmethod
    def is_hidden(cls, filepath):
        name = os.path.basename(os.path.abspath(filepath))
        return name.startswith('.') or cls.has_hidden_attribute(filepath)

    @classmethod
    def has_hidden_attribute(cls, filepath):
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(filepath))
            assert attrs != -1
            result = bool(attrs & 2)
        except (AttributeError, AssertionError):
            result = False
        return result

    def test_AppendFileToFile_repr(self):
        self.pbt.reprs_test_runner(AppendFileToFile("/a/file/to/append", "/a/file/to/appendee"))

    def test_AppendFileToFile(self):
        source_file = self.pbt.path_inside_test_folder("source-file.txt")
        target_file = self.pbt.path_inside_test_folder("target-file.txt")

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

    def test_Chown_repr(self):
        self.pbt.reprs_test_runner(Chown("/a/file/to/append", 123, 456),
                                   Chown("/a/file/to/append", None, 456),
                                   Chown("/a/file/to/append", 123, None),
                                   Chown("/a/file/to/append", None, None))

    def test_Chown(self):
        user_id = 502
        group_id = 20
        file_to_chown: Path = self.pbt.path_inside_test_folder("chown-this-file")
        self.assertFalse(file_to_chown.exists(), f"file exists '{file_to_chown}'")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Touch(file_to_chown)
        self.pbt.batch_accum += Chmod(file_to_chown, "a+rw")
        self.pbt.batch_accum += Chown(file_to_chown,user_id=user_id, group_id=group_id)
        self.pbt.exec_and_capture_output("chown")

        file_stat = file_to_chown.stat()
        self.assertEqual(file_stat.st_uid, user_id, f"user should be {user_id} not {file_stat.st_uid}")
        self.assertEqual(file_stat.st_gid, group_id, f"user should be {group_id} not {file_stat.st_gid}")


    def test_Chmod_repr(self):
        new_mode = stat.S_IMODE(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        self.pbt.reprs_test_runner(Chmod("a/b/c", new_mode, recursive=True), Chmod("a/b/c", new_mode, recursive=False))

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
        self.pbt.batch_accum += MakeDir(folder_to_chmod)
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

    def test_ChmodAndChown_repr(self):
        pass

    def test_ChmodAndChown(self):
        pass

    def test_Ls_repr(self):
        self.pbt.reprs_test_runner(Ls('rumba', out_file="empty.txt"),
                                   Ls("/per/pen/di/cular", out_file="perpendicular_ls.txt", ls_format='abc'),
                                   Ls("/Gina/Lollobrigida", out_file="Lollobrigida.txt"))

    def test_Ls(self):
        folder_to_list = self.pbt.path_inside_test_folder("folder-to-list")
        list_out_file = self.pbt.path_inside_test_folder("list-output")

        # create the folder, with sub folder and one known file
        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as cd1_accum:
             cd1_accum += MakeDir(folder_to_list)
             with cd1_accum.sub_accum(Cd(folder_to_list)) as cd2_accum:
                cd2_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=2, num_files_per_dir=8, file_size=41)
             cd1_accum += Ls(folder_to_list, out_file="list-output")
        self.pbt.exec_and_capture_output("ls folder")
        self.assertTrue(os.path.isdir(folder_to_list), f"{self.pbt.which_test} : folder to list was not created {folder_to_list}")
        self.assertTrue(os.path.isfile(list_out_file), f"{self.pbt.which_test} : list_out_file was not created {list_out_file}")

    def test_Essentiality(self):
        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Stage("redundant section")) as redundant_accum:
            redundant_accum += Echo("redundant echo")
        self.assertEqual(self.pbt.batch_accum.total_progress_count(), 0, f"{self.pbt.which_test}: a Stage with only echo should discarded")
        with self.pbt.batch_accum.sub_accum(Stage("redundant section")) as redundant_accum:
            redundant_accum += Wzip("dummy no real path")
        self.assertGreater(self.pbt.batch_accum.total_progress_count(), 0, f"{self.pbt.which_test}: a Stage with essential command should not discarded")

    def test_FileSizes_repr(self):
        self.pbt.reprs_test_runner(FileSizes('rumba', out_file="empty.txt"))

    def test_FileSizes(self):
        folder_to_list = self.pbt.path_inside_test_folder("folder-to-list")
        random_data_file_1 = (self.pbt.path_inside_test_folder("random_data_file_1"), 999)
        random_data_file_2 = (self.pbt.path_inside_test_folder("random_data_file_2"), 888)
        list_file = self.pbt.path_inside_test_folder("list_file")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeRandomDataFile(random_data_file_1[0], random_data_file_1[1])
        self.pbt.batch_accum += MakeRandomDataFile(random_data_file_2[0], random_data_file_2[1])
        self.pbt.batch_accum += FileSizes(folder_to_list, out_file=list_file)
        self.pbt.exec_and_capture_output()

    def test_MakeRandomDataFile_repr(self):
        self.pbt.reprs_test_runner(MakeRandomDataFile('rumba', file_size=1234))
        with self.assertRaises(ValueError):
            MakeRandomDataFile('rumba', file_size=-123)

    def test_MakeRandomDataFile(self):
        random_data_file_1: Path = (self.pbt.path_inside_test_folder("random_data_file_1"), 1799)
        random_data_file_zero = (self.pbt.path_inside_test_folder("random_data_file_zero"), 0)

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeRandomDataFile(random_data_file_1[0], random_data_file_1[1])
        self.pbt.batch_accum += MakeRandomDataFile(random_data_file_zero[0], random_data_file_zero[1])
        self.pbt.exec_and_capture_output()
        self.assertEqual(random_data_file_1[1], os.path.getsize(random_data_file_1[0]))
        self.assertEqual(random_data_file_zero[1], os.path.getsize(random_data_file_zero[0]))

    def test_SplitJoinFile_repr(self):
        self.pbt.reprs_test_runner(SplitFile('rumba', 7000),
                                   SplitFile('pumba', 8000, remove_original=False),
                                   SplitFile('dima', 9000, remove_original=True),
                                   JoinFile('rumba.aa'),
                                   JoinFile('pumba.aa', remove_parts=False),
                                   JoinFile('dima.aa', remove_parts=True))

    def test_SplitJoinFile(self):
        file_size = 15
        part_size = 5
        expected_num_parts = (file_size // part_size) + (1 if file_size % part_size > 0 else 0)
        expected_part_size = math.ceil(file_size / expected_num_parts)

        file_to_split: Path = (self.pbt.path_inside_test_folder("file_to_split"))
        file_to_split_before: Path = (self.pbt.path_inside_test_folder("file_to_split.before"))
        first_split_file: Path = (self.pbt.path_inside_test_folder("file_to_split.aa"))

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeRandomDataFile(file_to_split, file_size)
        self.pbt.batch_accum += SplitFile(file_to_split, part_size, remove_original=False)
        self.pbt.batch_accum += CopyFileToFile(file_to_split, file_to_split_before)
        self.pbt.batch_accum += RmFile(file_to_split)
        self.pbt.batch_accum += JoinFile(first_split_file, remove_parts=False)
        self.pbt.exec_and_capture_output()

        are_files_the_same = filecmp.cmp(file_to_split_before, file_to_split, shallow=False)
        self.assertTrue(are_files_the_same, f"{self.pbt.which_test}: before split and after join fies are not the same")

    def test_something(self):
        the_file = "C:\\ProgramData\\Waves Audio\\Central\\V10\\new_require.yaml"
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Chmod(the_file, "ugo+rw")
        self.pbt.exec_and_capture_output()

