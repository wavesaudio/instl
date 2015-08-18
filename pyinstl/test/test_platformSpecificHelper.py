#!/usr/bin/env python2.7
from __future__ import print_function

import unittest
import filecmp
import shutil
import random
import string
import inspect

from configVar import var_stack
from instlInstanceBase import PlatformSpecificHelperFactory
import utils


current_os_names = get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

def prepare_test_folder(folder_name):
    """ create a folder named test_platformSpecificHelper on the desktop.
        inside test_platformSpecificHelper create a folder named folder_name,
        but make sure it's empty.
    """
    desktop_folder = os.path.expanduser("~/Desktop")
    test_folder = os.path.join(desktop_folder, "test_platformSpecificHelper", folder_name)
    if os.path.isdir(test_folder):
        shutil.rmtree(test_folder)
    safe_makedirs(test_folder)
    return test_folder

def random_text(length=256):
    """ produce random text of printable characters. """
    retVal = "".join( [random.choice(string.printable) for i in xrange(length)] )
    return retVal

def random_file_name(name_len=32):
    """ produce random file name characters. """
    retVal = "".join( [random.choice(string.letters) for i in xrange(name_len)] )
    return retVal

def create_random_file(where, name_len=32, contents_len=256, ext=".txt"):
    """ create a file with random name and random contents in folder where. """
    file_name = random_file_name(name_len)
    if ext:
        file_name += ext
    file_path = os.path.join(where, file_name)
    file_contents = random_text(contents_len)
    with open(file_path, "w") as wfd:
        wfd.write(file_contents)
    return file_path

def create_random_files(where, num=32, name_len=32, contents_len=256):
    """ create some files with random name and random contents in folder where. """
    originals_file_paths = list()
    for i in xrange(num):
        file_path = create_random_file(where, name_len, contents_len)
        originals_file_paths.append(file_path)
    return originals_file_paths

class TestPlatformSpecificHelper(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        var_stack.set_var("__CURRENT_OS__").append(os_family_name)
        var_stack.set_var("__CURRENT_OS_SECOND_NAME__").append(os_second_name)

    def setUp(self):
        """ .
        """
        self.ps_helper = PlatformSpecificHelperFactory(os_family_name, None)
        self.ps_helper.init_copy_tool()

    def tearDown(self):
        del self.ps_helper

    def check_indoes_Equal(self, left_dir, right_dir, test_name, report=None):
        """ compare two folders that should have the same hard-linked files.
            if any two files have the same name but different inodes,
            report and return False
        """
        retVal = True
        if report is None:
            report = list()
        comperer = filecmp.dircmp(left_dir, right_dir)
        if comperer.left_only:
            retVal = False
            report.append( (left_dir+" only files:",) )
            for lfile in comperer.left_only:
                report.append( (lfile, os.stat(os.path.join(left_dir, lfile)).st_ino) )
            report.append((".",))
        if comperer.right_only:
            retVal = False
            report.append( (right_dir+" only files:",) )
            for lfile in comperer.right_only:
                report.append( (lfile, os.stat(os.path.join(right_dir, lfile)).st_ino) )
            report.append((".",))

        if comperer.common_files:
            report.append(("common files in "+os.path.basename(left_dir)+"/"+os.path.basename(right_dir),) )
            for cfile in comperer.common_files:
                linode = os.stat(os.path.join(left_dir, cfile)).st_ino
                rinode = os.stat(os.path.join(right_dir, cfile)).st_ino
                if linode == rinode:
                    report.append( (cfile, linode, "==", rinode) )
                else:
                    retVal = False
                    report.append( (cfile, linode, "!=", rinode) )
        elif comperer.left_only or comperer.right_only:
            retVal = False
            report.append( ("no common files",) )
            report.append((".",))

        for cdir in comperer.common_dirs:
            self.check_indoes_Equal(os.path.join(left_dir, cdir),
                                     os.path.join(right_dir, cdir),
                                     test_name,
                                     report)
        if not retVal:
            print(test_name)
            col_format = gen_col_format(max_widths(report))
            for res_line in report:
                print(col_format[len(res_line)].format(*res_line))
            print(".")
        return retVal

    def check_indoes_NotEqual(self, left_dir, right_dir, test_name, report=None):
        """ compare two folders that should have the same non-hard-linked files.
            if any two files have the same name and same inodes,
            report and return False
        """
        retVal = True
        if report is None:
            report = list()
        comperer = filecmp.dircmp(left_dir, right_dir)
        if comperer.left_only:
            retVal = False
            report.append( (left_dir+" only files:",) )
            for lfile in comperer.left_only:
                report.append( (lfile, os.stat(os.path.join(left_dir, lfile)).st_ino) )
            report.append((".",))
        if comperer.right_only:
            retVal = False
            report.append( (right_dir+" only files:",) )
            for lfile in comperer.right_only:
                report.append( (lfile, os.stat(os.path.join(right_dir, lfile)).st_ino) )
            report.append((".",))

        if comperer.common_files:
            report.append( ("common files in "+os.path.basename(left_dir)+"/"+os.path.basename(right_dir),) )
            for cfile in comperer.common_files:
                linode = os.stat(os.path.join(left_dir, cfile)).st_ino
                rinode = os.stat(os.path.join(right_dir, cfile)).st_ino
                if linode == rinode:
                    retVal = False
                    report.append( (cfile, linode, "==", rinode) )
                else:
                    report.append( (cfile, linode, "!=", rinode) )
        elif comperer.left_only or comperer.right_only:
            retVal = False
            report.append( ("no common files",) )
            report.append((".",))

        for cdir in comperer.common_dirs:
            self.check_indoes_NotEqual(os.path.join(left_dir, cdir),
                                     os.path.join(right_dir, cdir),
                                     test_name,
                                     report)
        if not retVal:
            print(test_name)
            col_format = gen_col_format(max_widths(report))
            for res_line in report:
                print(col_format[len(res_line)].format(*res_line))
            print(".")
        return retVal

    def test_copy_dir_to_dir_with_hard_links(self):
        """ copy a complete folder into another, with hard-linking,
            files' inodes should be the same."""

        test_folder = prepare_test_folder("test copy dir to dir with hard links")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        originals_file_paths = create_random_files(originals_folder)
        sub_originals_folder = safe_makedirs(os.path.join(test_folder, "originals", "sub-originals"))
        originals_file_paths.extend(create_random_files(sub_originals_folder))
        safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-empty"))
        sub_sub_originals_folder_full = safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-full"))
        originals_file_paths.extend(create_random_files(sub_sub_originals_folder_full))

        hard_links_folder = safe_makedirs(os.path.join(test_folder, "hard-links"))
        results_folder = os.path.join(hard_links_folder, "originals")

        # copy without hard-links, file contents should be the same. files' inodes should be different.
        copy_command = self.ps_helper.copy_tool.copy_dir_to_dir(originals_folder, hard_links_folder, link_dest=True)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)

        self.assertTrue(self.check_indoes_Equal(originals_folder, results_folder, inspect.stack()[0][3]))

    def test_copy_dir_to_dir_no_hard_links(self):
        """ copy a complete folder into another, without hard-linking,
            file contents should be the same. files' inodes should be different."""

        test_folder = prepare_test_folder("test copy dir to dir no hard links")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        originals_file_paths = create_random_files(originals_folder)
        sub_originals_folder = safe_makedirs(os.path.join(test_folder, "originals", "sub-originals"))
        originals_file_paths.extend(create_random_files(sub_originals_folder))
        safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-empty"))
        sub_sub_originals_folder_full = safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-full"))
        originals_file_paths.extend(create_random_files(sub_sub_originals_folder_full))

        copies_folder = safe_makedirs(os.path.join(test_folder, "copies"))
        results_folder = os.path.join(copies_folder, "originals")

        # copy without hard-links, file contents should be the same. files' inodes should be different.
        copy_command = self.ps_helper.copy_tool.copy_dir_to_dir(originals_folder, copies_folder, link_dest=False)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)

        self.assertTrue(self.check_indoes_NotEqual(originals_folder, results_folder, inspect.stack()[0][3]))

    def test_copy_dir_contents_to_dir_with_hard_links(self):
        """ copy files and folders in one folder to another, with hard-linking,
            files' inodes should be the same."""

        test_folder = prepare_test_folder("test copy dir contents to dir with hard links")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        originals_file_paths = create_random_files(originals_folder)
        sub_originals_folder = safe_makedirs(os.path.join(test_folder, "originals", "sub-originals"))
        originals_file_paths.extend(create_random_files(sub_originals_folder))
        safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-empty"))
        sub_sub_originals_folder_full = safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-full"))
        originals_file_paths.extend(create_random_files(sub_sub_originals_folder_full))

        hard_links_folder = safe_makedirs(os.path.join(test_folder, "hard_links"))

        # copy without hard-links, file contents should be the same. files' inodes should be different.
        copy_command = self.ps_helper.copy_tool.copy_dir_contents_to_dir(originals_folder, hard_links_folder, link_dest=True)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)

        self.assertTrue(self.check_indoes_Equal(originals_folder, hard_links_folder, inspect.stack()[0][3]))

    def test_copy_dir_contents_to_dir_no_hard_links(self):
        """ copy files and folders in one folder to another, without hard-linking,
            file contents should be the same. files' inodes should be different."""

        test_folder = prepare_test_folder("test copy dir contents to dir no hard links")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        originals_file_paths = create_random_files(originals_folder)
        sub_originals_folder = safe_makedirs(os.path.join(test_folder, "originals", "sub-originals"))
        originals_file_paths.extend(create_random_files(sub_originals_folder))
        safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-empty"))
        sub_sub_originals_folder_full = safe_makedirs(os.path.join(test_folder, "originals", "sub-sub-originals-full"))
        originals_file_paths.extend(create_random_files(sub_sub_originals_folder_full))

        copies_folder = safe_makedirs(os.path.join(test_folder, "copies"))

        # copy without hard-links, file contents should be the same. files' inodes should be different.
        copy_command = self.ps_helper.copy_tool.copy_dir_contents_to_dir(originals_folder, copies_folder, link_dest=False)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)

        self.assertTrue(self.check_indoes_NotEqual(originals_folder, copies_folder, inspect.stack()[0][3]))

    def test_files_to_dir_copy_no_hard_links(self):
        """ copy files in one folder to another, without hard-linking,
            file contents should be the same. files' inodes should be different."""

        test_folder = prepare_test_folder("test files to dir copy no hard links")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        copies_folder = safe_makedirs(os.path.join(test_folder, "copies"))

        originals_file_paths = create_random_files(originals_folder)

        # copy without hard-links, file contents should be the same. files' inodes should be different.
        copy_command = self.ps_helper.copy_tool.copy_dir_files_to_dir(originals_folder, copies_folder, link_dest=False)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)

        copies_file_paths = []
        for file_path in originals_file_paths:
            folder, file_name = os.path.split(file_path)
            copies_file_paths.append(os.path.join(copies_folder, file_name))

        for copied_file_path in copies_file_paths:
            self.assertTrue(os.path.isfile(copied_file_path))

        comperer = filecmp.dircmp(originals_folder, copies_folder)
        self.assertEqual(comperer.left_only, [], "Some files where not copied: {comperer.left_only}".format(**locals()))
        self.assertEqual(comperer.right_only, [], "Extra files where copied: {comperer.right_only}".format(**locals()))
        match, mismatch, errors = filecmp.cmpfiles(originals_folder, copies_folder, comperer.common, shallow=False)
        self.assertEqual(errors, [], "some files are missing {errors}".format(**locals()))
        self.assertEqual(mismatch, [], "some files are different {mismatch}".format(**locals()))
        self.assertTrue(self.check_indoes_NotEqual(originals_folder, copies_folder, inspect.stack()[0][3]))

    def test_files_to_dir_copy_with_hard_links(self):
        """ copy files in one folder to another, with hard-linking,
            files' inodes should be the same."""

        test_folder = prepare_test_folder("test files to dir copy with hard links")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        hard_links_folder = safe_makedirs(os.path.join(test_folder, "hard-links"))

        originals_file_paths = create_random_files(originals_folder)

        copy_command = self.ps_helper.copy_tool.copy_dir_files_to_dir(originals_folder, hard_links_folder, link_dest=True)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)

        hard_link_file_paths = []
        for file_path in originals_file_paths:
            folder, file_name = os.path.split(file_path)
            hard_link_file_paths.append(os.path.join(hard_links_folder, file_name))

        for hard_link_file_path in hard_link_file_paths:
            self.assertTrue(os.path.isfile(hard_link_file_path))

        comperer = filecmp.dircmp(originals_folder, hard_links_folder)
        self.assertEqual(comperer.left_only,  [], "Some files where not copied: {comperer.left_only}".format(**locals()))
        self.assertEqual(comperer.right_only, [], "Extra files where copied: {comperer.right_only}".format(**locals()))
        match, mismatch, errors = filecmp.cmpfiles(originals_folder, hard_links_folder, comperer.common, shallow=False)
        self.assertEqual(errors, [], "some files are missing {errors}".format(**locals()))
        self.assertEqual(mismatch, [], "some files are different {mismatch}".format(**locals()))
        self.assertTrue(self.check_indoes_Equal(originals_folder, hard_links_folder, inspect.stack()[0][3]))


    def test_file_to_dir_copy_no_hard_link(self):
        """ copy single file in one folder to another, without hard-linking,
            file contents should be the same. files' inodes should be different."""
        test_folder = prepare_test_folder("test file to file copy no hard link")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        copies_folder = safe_makedirs(os.path.join(test_folder, "copies"))

        file_to_copy = create_random_file(originals_folder)
        _, copied_file = os.path.split(file_to_copy)
        copied_file = os.path.join(copies_folder, copied_file)

        copy_command = self.ps_helper.copy_tool.copy_file_to_dir(file_to_copy, copies_folder, link_dest=False)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)
        self.assertTrue(os.path.isfile(copied_file))
        self.assertTrue(filecmp.cmp(file_to_copy, copied_file, shallow=False), "{copied_file} file is different from expected {file_to_copy}".format(**locals()))
        self.assertTrue(self.check_indoes_NotEqual(originals_folder, copies_folder, inspect.stack()[0][3]))

    def test_file_to_dir_copy_with_hard_link(self):
        """ copy single file in one folder to another, with hard-linking,
            files' inodes should be the same."""

        test_folder = prepare_test_folder("test file to file copy with hard link")
        originals_folder = safe_makedirs(os.path.join(test_folder, "originals"))
        hard_link_folder = safe_makedirs(os.path.join(test_folder, "hard-link"))

        file_to_copy = create_random_file(originals_folder)
        _, hard_link_file = os.path.split(file_to_copy)
        hard_link_file = os.path.join(hard_link_folder, hard_link_file)

        copy_command = self.ps_helper.copy_tool.copy_file_to_dir(file_to_copy, hard_link_folder, link_dest=True)
        subprocess.check_output(copy_command, stdin=None, stderr=None, shell=True, universal_newlines=False)
        self.assertTrue(os.path.isfile(hard_link_file))
        self.assertTrue(filecmp.cmp(file_to_copy, hard_link_file, shallow=False), "{hard_link_file} file is different from expected {file_to_copy}".format(**locals()))
        self.assertTrue(self.check_indoes_Equal(originals_folder, hard_link_folder, inspect.stack()[0][3]))
