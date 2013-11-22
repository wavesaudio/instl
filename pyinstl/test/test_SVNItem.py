#!/usr/bin/env python2.7
from __future__ import print_function

from __future__ import print_function

import sys
import os
import unittest
import copy

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from aYaml.augmentedYaml import YamlDumpWrap, writeAsYaml
from svnItem import *
from svnTree import *

def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print ('%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0))
        return ret
    return wrap

def remove_sub_if_small_last_rev(svn_item):
    if svn_item.isFile():
        retVal = svn_item.last_rev() < 9
    elif svn_item.isDir():
        retVal = len(svn_item.subs()) == 0
    return retVal

item_list1 = [
            "Dir1, d, 17",
            "Dir1/File1.1, f, 15",
            "Dir1/File1.2, f, 16",
            "Dir1/File1.3, f, 17",

            "Dir2, d, 9",
            "Dir2/Dir2.1, d, 8",
            "Dir2/Dir2.1/File2.1.1, f, 8",
            "Dir2/Dir2.2, d, 5",
            "Dir2/Dir2.2/File2.2.1, fx, 5",
            "Dir2/Dir2.2/File2.2.2, f, 3",
            "Dir2/Dir2.3, d, 9",
            "Dir2/Dir2.3/File2.3.1, f, 7",
            "Dir2/Dir2.3/File2.3.2, fx, 9",
            "Dir2/Dir2.3/File2.3.3, f, 1",

            "Dir3, ds, 14",
            "Dir3/File3.1, f, 13",
            "Dir3/File3.2, f, 12",
            "Dir3/Dir3.1, d, 4",
            "Dir3/Dir3.1/File3.1.1, f, 2",
            "Dir3/Dir3.1/File3.1.2, fx, 4",
            "Dir3/Dir3.2, d, 14",
            "Dir3/Dir3.2/File3.2.1, f, 6",
            "Dir3/Dir3.2/File3.2.2, f, 10",
            "Dir3/Dir3.2/Dir3.2.1, d, 14",
            "Dir3/Dir3.2/Dir3.2.2, ds, 14"
            ]

item_list_need = [
            # same dir
            "Dir1, d, 17",
            "Dir1/File1.1, f, 15",
            "Dir1/File1.2, f, 16",
            "Dir1/File1.3, f, 17",

            "Dir2, d, 9",
            "Dir2/Dir2.1, d, 8",
            "Dir2/Dir2.1/File2.1.1, f, 8",
            "Dir2/Dir2.3, d, 9",
            "Dir2/Dir2.3/File2.3.1, f, 8",
            "Dir2/Dir2.3/File2.3.2, fx, 12",
            "Dir2/Dir2.3/File2.3.3, f, 1",

            "Dir3, ds, 16",
            "Dir3/File3.1, f, 13",
            "Dir3/File3.2, f, 12",
            "Dir3/Dir3.1, d, 4",
            "Dir3/Dir3.1/File3.1.2, fx, 5",
            "Dir3/Dir3.2, d, 14",
            "Dir3/Dir3.2/File3.2.1, f, 6",
            "TestDir, d, 15",
            "Dir3/Dir3.2/Dir3.2.2, ds, 14"
            ]

item_list_need_ref = [
            ("Dir1", "d", 17, 17),
            ("Dir1/File1.1", "f", 15, 15),
            ("Dir1/File1.2", "f", 16, 16),
            ("Dir1/File1.3", "f", 17, 17),

            ("Dir2", "d", 9, 9),
            ("Dir2/Dir2.1", "d", 8, 8),
            ("Dir2/Dir2.1/File2.1.1", "f", 8, 8),
            ("Dir2/Dir2.2", "d", 5, 5),
            ("Dir2/Dir2.2/File2.2.1", "fx", 5, 5),
            ("Dir2/Dir2.2/File2.2.2", "f", 3, 3),
            ("Dir2/Dir2.3", "d", 9, 9),
            ("Dir2/Dir2.3/File2.3.1", "f", 8, 7),
            ("Dir2/Dir2.3/File2.3.2", "fx", 12, 9),
            ("Dir2/Dir2.3/File2.3.3", "f", 1, 1),

            ("Dir3", "ds", 16, 14),
            ("Dir3/File3.1", "f", 13, 13),
            ("Dir3/File3.2", "f", 12, 12),
            ("Dir3/Dir3.1", "d", 4, 4),
            ("Dir3/Dir3.1/File3.1.1", "f", 2, 0),
            ("Dir3/Dir3.1/File3.1.2", "fx", 4, 5),
            ("Dir3/Dir3.2", "d", 14, 14),
            ("Dir3/Dir3.2/File3.2.1", "f", 6, 6),
            ("Dir3/Dir3.2/File3.2.2", "f", 10, 0),
            ("Dir3/Dir3.2/Dir3.2.1", "d", 14, 14),
            ("Dir3/Dir3.2/Dir3.2.2", "ds", 14, 14)
            ]


class TestSVNItem(unittest.TestCase):
    def setUp(self):
        ''' .
        '''
        self.maxDiff = None
    def tearDown(self):
        pass
    """
    """
    def test_recursive_remove_depth_first(self):
        svni1 = SVNItem("TestDir", "d", 15)
        for item in item_list1: svni1.new_item_from_str(item)
        list_before = [str(item) for item in svni1.walk_items()]
        svni1.recursive_remove_depth_first(remove_sub_if_small_last_rev)
        list_after  = [str(item) for item in svni1.walk_items()]
        self.assertNotEqual(list_before, list_after)

        item_list1_after_remove_ref = [
            "TestDir/Dir1, d, 17",
            "TestDir/Dir1/File1.1, f, 15",
            "TestDir/Dir1/File1.2, f, 16",
            "TestDir/Dir1/File1.3, f, 17",

            "TestDir/Dir2, d, 9",
            "TestDir/Dir2/Dir2.3, d, 9",
            "TestDir/Dir2/Dir2.3/File2.3.2, fx, 9",

            "TestDir/Dir3, ds, 14",
            "TestDir/Dir3/File3.1, f, 13",
            "TestDir/Dir3/File3.2, f, 12",
            "TestDir/Dir3/Dir3.2, d, 14",
            "TestDir/Dir3/Dir3.2/File3.2.2, f, 10",
            ]
        self.assertEqual(list_after, item_list1_after_remove_ref)

    def test_equal(self):
        svni1 = SVNItem("TestDir", "d", 15)
        svni2 = SVNItem("TestDir", "d", 15)
        svni3 = SVNItem("TestFile", "f", 15)
        self.assertEqual(svni1, svni2)
        self.assertNotEqual(svni1, svni3)
        svni1.new_item_at_path("file1", "f", 19)
        self.assertNotEqual(svni1, svni2)
        svni2.new_item_at_path("file1", "f", 19)
        self.assertEqual(svni1, svni2)
        svni1._add_sub_item(svni3)
        self.assertNotEqual(svni1, svni2)
        svni2._add_sub_item(copy.deepcopy(svni3))
        self.assertEqual(svni1, svni2)

    def test_looping(self):
        svni1 = SVNItem("TestDir", "d", 15)
        for item in item_list1: svni1.new_item_from_str(item)
        sub1 = svni1.get_item_at_path("Dir1")
        files, dirs = sub1.sorted_sub_items()
        # test item keys
        self.assertEqual([file.name() for file in files], sorted(["File1.1", "File1.2", "File1.3"]))

        sub3 = svni1.get_item_at_path("Dir3")
        files, dirs = sub3.sorted_sub_items()
        self.assertEqual([file.name() for file in files], sorted(["File3.1", "File3.2"]))
        self.assertEqual([dir.name() for dir in dirs], sorted(["Dir3.1", "Dir3.2"]))

    def test_deepcopy(self):
        svni1 = SVNItem("TestDir", "d", 15)
        for text_item in item_list1: svni1.new_item_from_str(text_item)
        svni2 = copy.deepcopy(svni1)
        self.assertEqual(svni1, svni2)

    def test_walk_items(self):
        """
        svni1 = SVNTree() #"TestDir", "d", 15
        for item in item_list1: svni1.new_item_from_str(item)
        svni1.write_to_file("/Users/shai/Desktop/test_walk_items.txt", in_format="text")

        all_items_list = []
        for item in svni1.walk_items(what="a"):
            all_items_list.append( (item.full_path(), item.flags(), item.last_rev()) )
        self.assertEqual(sorted(all_items_list), sorted(item_list1))

        all_files_list = []
        for afile in svni1.walk_items(what="f"):
            all_files_list.append(afile)
        self.assertEqual(sorted(all_files_list), sorted([item for item in item_list1 if "f" in item[1]]))

        all_dirs_list = []
        for adir in svni1.walk_items(what="d"):
            all_dirs_list.append(adir)
        self.assertEqual(sorted(all_dirs_list), sorted([item for item in item_list1 if "d" in item[1]]))
        """

    def test_add_sub_negative(self):
        svni1 = SVNItem("TestDir", "d", 15)
        # should throw when adding and hierarchy does not exist
        self.assertRaises(KeyError, svni1.new_item_at_path, "SubDir1/SubFile1", "f", 19)

        svni1.new_item_at_path("SubFile1", "f", 19)
        self.assertEqual(svni1.subs().keys(), ["SubFile1"])
        # should throw when adding and path has non leaf file
        self.assertRaises(ValueError, svni1.new_item_at_path, "SubFile1/SubFile2", "f", 19)

    def test_add_sub_positive(self):
        svni1 = SVNItem("TestDir", "d", 15)
        svni1.new_item_at_path("SubDir1", "d", 19)
        self.assertEqual(svni1.subs().keys(), ["SubDir1"])
        self.assertIsInstance(svni1.get_item_at_path("SubDir1"), SVNItem, msg="svn1.get_item_at_path should return SVNItem object")

        svni1.new_item_at_path("SubDir1/SubDir2", "d", 219)
        self.assertEqual(svni1.subs().keys(), ["SubDir1"])
        sub1 = svni1.get_item_at_path("SubDir1")
        self.assertIsInstance(sub1, SVNItem, msg="svn1.get_item_at_path should return SVNItem object")
        self.assertEqual(sub1.subs().keys(), ["SubDir2"])
        sub2 = sub1.get_item_at_path("SubDir2")
        self.assertIsInstance(sub2, SVNItem, msg="svn1.get_item_at_path should return SVNItem object")

        svni1.new_item_at_path("SubDirA", "d", 2195)
        self.assertEqual(sorted(svni1.subs().keys()), ["SubDir1", "SubDirA"])
        sub1 = svni1.get_item_at_path("SubDir1")
        self.assertIsInstance(sub1, SVNItem, msg="svn1.get_item_at_path should return SVNItem object")
        sub2 = svni1.get_item_at_path("SubDirA")
        self.assertIsInstance(sub2, SVNItem, msg="svn1.get_item_at_path should return SVNItem object")

    def test_add_sub_item_positive(self):
        ''' Check the internal function _add_sub_item where is should succeed '''
        svni1 = SVNItem("TestDir", "d", 15)
        svni2 = SVNItem("SubFile", "f", 1258)
        svni1._add_sub_item(svni2)
        self.assertEqual(svni1.subs().keys(), ["SubFile"])
        self.assertIsNone(svni1.get_item_at_path("kuku"), msg="svn1.get_item_at_path should return None for none existing item")
        self.assertIs(svni1.get_item_at_path("SubFile"), svni2, msg="svn1.get_item_at_path should return the same object given")
        svni1.new_item_at_path("SubDir", "d", 1258)
        self.assertEqual(sorted(svni1.subs().keys()), ["SubDir", "SubFile"])
        self.assertIsNone(svni1.get_item_at_path("kuku"), msg="svn1.get_item_at_path should return None for none existing item")
        self.assertIsInstance(svni1.get_item_at_path("SubDir"), SVNItem, msg="svn1.get_item_at_path should return SVNItem object")

    def test_add_sub_item_negative(self):
        ''' Check the internal function _add_sub_item where is should fail '''
        svni1 = SVNItem("TestDir", "f", 15)
        svni2 = SVNItem("SubFile", "f", 1258)
        self.assertRaises(ValueError, svni1._add_sub_item, svni2)
        self.assertRaises(ValueError, svni1.subs)
        self.assertRaises(ValueError, svni1.get_item_at_path, "SubFile")

    def test_other_flags_construction(self):
        ''' Construct SVNItem with some flags flag '''
        svni1 = SVNItem("TestFlags", "fx", 36)
        self.assertEqual(svni1.name(), "TestFlags")
        self.assertEqual(svni1.last_rev(), 36)
        self.assertTrue(svni1.isFile(), msg="SVNItem.isFile() should return True for file")
        self.assertFalse(svni1.isDir(), msg="SVNItem.isDir() should return False for directory")
        self.assertTrue(svni1.isExecutable(), msg="SVNItem.isExecutable() should return True for non-executable")
        self.assertFalse(svni1.isSymlink(), msg="SVNItem.isSymlink() should return False for non-symlink")
        self.assertRaises(ValueError, svni1.subs)
        self.assertRaises(ValueError, svni1.get_item_at_path, "kuku")
        svni2 = SVNItem("TestFlags", "ds", 36)
        self.assertEqual(svni2.name(), "TestFlags")
        self.assertFalse(svni2.isFile(), msg="SVNItem.isFile() should return False for directory")
        self.assertTrue(svni2.isDir(), msg="SVNItem.isDir() should return True for directory")
        self.assertFalse(svni2.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertTrue(svni2.isSymlink(), msg="SVNItem.isSymlink() should return True for non-symlink")
        self.assertEqual(svni2.subs(), {})
        self.assertIsNone(svni2.get_item_at_path("kuku"), "svn1.get_item_at_path should return None for none existing item")

    def test_dir_construction(self):
        ''' Construct SVNItem with directory flag '''
        svni1 = SVNItem("TestDir", "d", 15)
        self.assertEqual(svni1.name(), "TestDir")
        self.assertEqual(svni1.last_rev(), 15)
        self.assertFalse(svni1.isFile(), msg="SVNItem.isFile() should return False for directory")
        self.assertTrue(svni1.isDir(), msg="SVNItem.isDir() should return True for directory")
        self.assertFalse(svni1.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertFalse(svni1.isSymlink(), msg="SVNItem.isSymlink() should return False for non-symlink")
        self.assertEqual(svni1.subs(), {})
        self.assertIsNone(svni1.get_item_at_path("kuku"), msg="svn1.get_item_at_path should return None for none existing item")

    def test_file_construction(self):
        ''' Construct SVNItem with file flag '''
        svni1 = SVNItem("TestFile", "f", 17)
        self.assertEqual(svni1.name(), "TestFile")
        self.assertEqual(svni1.last_rev(), 17)
        self.assertEqual(str(svni1), "TestFile, f, 17")
        self.assertTrue(svni1.isFile(), msg="SVNItem.isFile() should return True for file")
        self.assertFalse(svni1.isDir(), msg="SVNItem.isDir() should return False for directory")
        self.assertFalse(svni1.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertRaises(ValueError, svni1.subs)
        self.assertRaises(ValueError, svni1.get_item_at_path, "kuku")
