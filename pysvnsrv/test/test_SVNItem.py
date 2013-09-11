#!/usr/bin/env python2.7
from __future__ import print_function

from __future__ import print_function

import sys
import os
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from aYaml.augmentedYaml import YamlDumpWrap, writeAsYaml
from svnItem import *

def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print ('%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0))
        return ret
    return wrap

class TestSVNItem(unittest.TestCase):

    def setUp(self):
        """ .
        """
        pass
    def tearDown(self):
        pass
    
    def test_walk_items(self):
        item_list = [
                    ("Dir1", "d", 14),
                    ("Dir1/File1.1", "f", 14),
                    ("Dir1/File1.2", "f", 14),
                    ("Dir1/File1.3", "f", 14),
                    ("Dir2", "d", 14),
                    ("Dir2/Dir2.1", "d", 14),
                    ("Dir2/Dir2.1/File2.1.1", "f", 14),
                    ("Dir2/Dir2.2", "d", 14),
                    ("Dir2/Dir2.2/File2.2.1", "fx", 14),
                    ("Dir2/Dir2.2/File2.2.2", "f", 14),
                    ("Dir2/Dir2.3", "d", 14),
                    ("Dir2/Dir2.3/File2.3.1", "f", 14),
                    ("Dir2/Dir2.3/File2.3.2", "fx", 14),
                    ("Dir2/Dir2.3/File2.3.3", "f", 14),
                    ("Dir3", "ds", 14),
                    ("Dir3/File3.1", "f", 14),
                    ("Dir3/File3.2", "f", 14),
                    ("Dir3/Dir3.1", "d", 14),
                    ("Dir3/Dir3.1/File3.1.1", "f", 14),
                    ("Dir3/Dir3.1/File3.1.2", "fx", 14),
                    ("Dir3/Dir3.2", "d", 14),
                    ("Dir3/Dir3.2/File3.2.1", "f", 14),
                    ("Dir3/Dir3.2/File3.2.2", "f", 14),
                    ("Dir3/Dir3.2/Dir3.2.1", "d", 14),
                    ("Dir3/Dir3.2/Dir3.2.2", "ds", 14)
                    ]
        svni1 = SVNItem("TestDir", "d", 15)
        for item in item_list:
            svni1.add_sub(*item)
        
        all_items_list = []    
        for item in svni1.walk_items(what="a"):
            all_items_list.append(item)
        self.assertEqual(all_items_list, item_list)
        
        all_files_list = []    
        for file in svni1.walk_items(what="f"):
            all_files_list.append(file)
        self.assertEqual(all_files_list, [item for item in item_list if "f" in item[1]])

        all_dirs_list = []    
        for dir in svni1.walk_items(what="d"):
            all_dirs_list.append(dir)
        self.assertEqual(all_dirs_list, [item for item in item_list if "d" in item[1]])
                
    def test_add_sub_negative(self):
        svni1 = SVNItem("TestDir", "d", 15)
        flat1 = SVNItemFlat("SubDir1/SubFile1", "f", 19)
        # should throw when adding and hierarchy does not exist
        self.assertRaises(KeyError, svni1.add_sub, *flat1)
        
        flat2 = SVNItemFlat("SubFile1", "f", 19)
        svni1.add_sub(*flat2)
        self.assertEqual(svni1.sub_names(), ["SubFile1"])
        flat3 = SVNItemFlat("SubFile1/SubFile2", "f", 19)
        # should throw when adding and path has non leaf file
        self.assertRaises(ValueError, svni1.add_sub, *flat3)

    def test_add_sub_positive(self):
        svni1 = SVNItem("TestDir", "d", 15)
        flat1 = SVNItemFlat("SubDir1", "d", 19)
        svni1.add_sub(*flat1)
        self.assertEqual(svni1.sub_names(), ["SubDir1"])
        self.assertIsInstance(svni1.get_sub("SubDir1"), SVNItem, msg="svn1.get_sub should return SVNItem object")
        
        flat2 = SVNItemFlat("SubDir1/SubDir2", "d", 219)
        svni1.add_sub(*flat2)
        self.assertEqual(svni1.sub_names(), ["SubDir1"])
        sub1 = svni1.get_sub("SubDir1/SubDir2")
        self.assertIsInstance(sub1, SVNItem, msg="svn1.get_sub should return SVNItem object")
        self.assertEqual(sub1.sub_names(), ["SubDir2"])
        sub2 = sub1.get_sub("SubDir2")
        self.assertIsInstance(sub2, SVNItem, msg="svn1.get_sub should return SVNItem object")

        flat3 = SVNItemFlat("SubDirA", "d", 2195)
        svni1.add_sub(*flat3)
        self.assertEqual(svni1.sub_names(), ["SubDir1", "SubDirA"])
        sub1 = svni1.get_sub("SubDir1")
        self.assertIsInstance(sub1, SVNItem, msg="svn1.get_sub should return SVNItem object")
        sub2 = svni1.get_sub("SubDirA")
        self.assertIsInstance(sub2, SVNItem, msg="svn1.get_sub should return SVNItem object")

    def test_add_sub_item_positive(self):
        """ Check the internal function _add_sub_item where is should succeed """
        svni1 = SVNItem("TestDir", "d", 15)
        svni2 = SVNItem("SubFile", "f", 1258)
        svni1._add_sub_item(svni2)
        self.assertEqual(svni1.sub_names(), ["SubFile"])
        self.assertIsNone(svni1.get_sub("kuku"), msg="svn1.get_sub should return None for none existing item")
        self.assertIs(svni1.get_sub("SubFile"), svni2, msg="svn1.get_sub should return the same object given")
        svni1.add_sub("SubDir", "d", 1258)
        self.assertEqual(svni1.sub_names(), ["SubDir", "SubFile"])
        self.assertIsNone(svni1.get_sub("kuku"), msg="svn1.get_sub should return None for none existing item")
        self.assertIsInstance(svni1.get_sub("SubDir"), SVNItem, msg="svn1.get_sub should return SVNItem object")

    def test_add_sub_item_negative(self):
        """ Check the internal function _add_sub_item where is should fail """
        svni1 = SVNItem("TestDir", "f", 15)
        svni2 = SVNItem("SubFile", "f", 1258)
        self.assertRaises(ValueError, svni1._add_sub_item, svni2)
        self.assertRaises(ValueError, svni1.sub_names)
        self.assertRaises(ValueError, svni1.get_sub, "SubFile")

    def test_other_flags_construction(self):
        """ Construct SVNItem with some flags flag """
        svni1 = SVNItem("TestFlags", "fx", 36)
        self.assertEqual(svni1.name(), "TestFlags")
        self.assertEqual(svni1.last_rev(), 36)
        self.assertTrue(svni1.isFile(), msg="SVNItem.isFile() should return True for file")
        self.assertFalse(svni1.isDir(), msg="SVNItem.isDir() should return False for directory")
        self.assertTrue(svni1.isExecutable(), msg="SVNItem.isExecutable() should return True for non-executable")
        self.assertFalse(svni1.isSymlink(), msg="SVNItem.isSymlink() should return False for non-symlink")
        self.assertRaises(ValueError, svni1.sub_names)
        self.assertRaises(ValueError, svni1.get_sub, "kuku")
        svni2 = SVNItem("TestFlags", "ds", 36)
        self.assertEqual(svni2.name(), "TestFlags")
        self.assertFalse(svni2.isFile(), msg="SVNItem.isFile() should return False for directory")
        self.assertTrue(svni2.isDir(), msg="SVNItem.isDir() should return True for directory")
        self.assertFalse(svni2.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertTrue(svni2.isSymlink(), msg="SVNItem.isSymlink() should return True for non-symlink")
        self.assertEqual(svni2.sub_names(), [])
        self.assertIsNone(svni2.get_sub("kuku"), "svn1.get_sub should return None for none existing item")

    def test_dir_construction(self):
        """ Construct SVNItem with directory flag """
        svni1 = SVNItem("TestDir", "d", 15)
        self.assertEqual(svni1.name(), "TestDir")
        self.assertEqual(svni1.last_rev(), 15)
        self.assertFalse(svni1.isFile(), msg="SVNItem.isFile() should return False for directory")
        self.assertTrue(svni1.isDir(), msg="SVNItem.isDir() should return True for directory")
        self.assertFalse(svni1.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertFalse(svni1.isSymlink(), msg="SVNItem.isSymlink() should return False for non-symlink")
        self.assertEqual(svni1.sub_names(), [])
        self.assertIsNone(svni1.get_sub("kuku"), msg="svn1.get_sub should return None for none existing item")
        
    def test_file_construction(self):
        """ Construct SVNItem with file flag """
        svni1 = SVNItem("TestFile", "f", 17)
        self.assertEqual(svni1.name(), "TestFile")
        self.assertEqual(svni1.last_rev(), 17)
        self.assertEqual(str(svni1), "TestFile: f 17")
        self.assertTrue(svni1.isFile(), msg="SVNItem.isFile() should return True for file")
        self.assertFalse(svni1.isDir(), msg="SVNItem.isDir() should return False for directory")
        self.assertFalse(svni1.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertRaises(ValueError, svni1.sub_names)
        self.assertRaises(ValueError, svni1.get_sub, "kuku")
