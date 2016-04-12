#!/usr/bin/env python3


import os
import sys
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from svnTree.svnItem import *
from svnTree.svnTree import *


def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        return ret

    return wrap


def remove_sub_if_small_revision(svn_item):
    retVal = None
    if svn_item.isFile():
        retVal = svn_item.revision < 9
    elif svn_item.isDir():
        retVal = len(svn_item.subs) == 0
    return retVal

# some files have url some have size, some have both
item_list1 = [
    "Dir1, d, 17",
    "Dir1/File1.1, f, 15, fce43f9615d593ea9ea810f4b2eed5433057404e, 562365",
    "Dir1/File1.2, f, 16, 5a300ed54f2a0bf32be33c05b11fa62a9c92b8e1",
    "Dir1/File1.3, f, 17, 6abbdac26853f866e178c836ff9e8943d772d0d7",

    "Dir2, d, 9",
    "Dir2/Dir2.1, d, 8",
    "Dir2/Dir2.1/File2.1.1, f, 8, ee6b0f8fa7293180d63bee180a8d866afacccd84",
    "Dir2/Dir2.2, d, 5",
    "Dir2/Dir2.2/File2.2.1, fx, 5, 5ec3df52ddff28887f993a7f74cb5c1774c1bb7e",
    "Dir2/Dir2.2/File2.2.2, f, 3, ed27799de395df652c2a9ae931eb71b3f1b03f56",
    "Dir2/Dir2.3, d, 9",
    "Dir2/Dir2.3/File2.3.1, f, 7, 36dcb69c45fa1dc8d07c9827d46558138e7a246d",
    "Dir2/Dir2.3/File2.3.2, fx, 9, b52e3dbf5d8ac642ca2accb9d324189e6998670d",
    "Dir2/Dir2.3/File2.3.3, f, 1, ee4a6a6fc707682ddf37d93816fa542eb60b814c",

    "Dir3, ds, 14",
    "Dir3/File3.1, f, 13, 9e55b828c3d8025fb5b4f01304760332859a88b0",
    "Dir3/File3.2, f, 12, 9a0fa3014dc4ed3dbbed0c71980b6c31344ba9df",
    "Dir3/Dir3.1, d, 4",
    "Dir3/Dir3.1/File3.1.1, f, 2, de0bc7d99e814b069948ac628cca57c8d616438b",
    "Dir3/Dir3.1/File3.1.2, fx, 4, c5afc0b2ac740f2600667cd61a213ab85284a5d0",
    "Dir3/Dir3.2, d, 14",
    "Dir3/Dir3.2/File3.2.1, f, 6, 46aa43ab7fdd078715d7a48ab5b86e136933c76a",
    "Dir3/Dir3.2/File3.2.2, f, 10, dafe7de11d698fff78090e5cbfc32ea602a93ffd",
    "Dir3/Dir3.2/Dir3.2.1, d, 14",
    "Dir3/Dir3.2/Dir3.2.2, ds, 14"
]
item_list2 = [
    "Dir1, d, 17",
    "Dir1/File1.1, f, 15, fce43f9615d593ea9ea810f4b2eed5433057404e, 562365",
    "Dir1/File1.2, f, 16, 5a300ed54f2a0bf32be33c05b11fa62a9c92b8e1",
    "Dir1/File1.3, f, 17, 6abbdac26853f866e178c836ff9e8943d772d0d7",

    "Dir2, d, 9",
    "Dir2/Dir2.w, d, 8",
    "Dir2/Dir2.w/File2.w.1, f, 8, 6de6e2c5f3504e6519be6cd1dc217f4df8ac8796",
    "Dir2/Dir2.x, d, 5",
    "Dir2/Dir2.x/File2.x.1, fx, 5, 6c4912d5a0295c8658592b94c254dc54f9d32460",
    "Dir2/Dir2.x/File2.x.2, f, 3, ab2c43b101206f391b1de43287a858e7954aac19",
    "Dir2/Dir2.y, d, 9",
    "Dir2/Dir2.y/File2.y.1, f, 7, 0c260d58ef87fca3c6d017f57a0b75952421f2b1",
    "Dir2/Dir2.y/File2.y.2, fx, 9, 87b357680fb8b673daad27175ad3f16ad22959b6",
    "Dir2/Dir2.y/File2.y.3, f, 1, 6239ff4b875c56227cb051a1a68c2e9d672a41b9",

    "Dirz, ds, 14",
    "Dirz/File3.1, f, 13, a5bde1f695ea072aff3233465d285f735a0db5a0",
    "Dirz/File3.2, f, 12, 71dd3d8d090348aa3db982fad8d442e883afa0c2",
    "Dirz/Dir3.1, d, 4",
    "Dirz/Dir3.1/File3.1.1, f, 2, 9e6ed1698be6292705e08afafc1d74442af905fb",
    "Dirz/Dir3.1/File3.1.2, fx, 4, e38ab9bba32174083fa2ce515ca576d461417a27",
    "Dirz/Dir3.2, d, 14",
    "Dirz/Dir3.2/File3.2.1, f, 6, 87fa753db67c981728a06c4fe7ba87d0f013f5d0",
    "Dirz/Dir3.2/File3.2.2, f, 10, fe42f95900229290816ddc2b04e135976c55bd1b",
    "Dirz/Dir3.2/Dir3.2.1, d, 14",
    "Dirz/Dir3.2/Dir3.2.2, ds, 14"
]

merge_list_1_and_files_of_list2_ref = [
    "Dir1, d, 17",
    "Dir1/File1.1, f, 15, fce43f9615d593ea9ea810f4b2eed5433057404e, 562365",
    "Dir1/File1.2, f, 16, 5a300ed54f2a0bf32be33c05b11fa62a9c92b8e1",
    "Dir1/File1.3, f, 17, 6abbdac26853f866e178c836ff9e8943d772d0d7",

    "Dir2, d, 9",
    "Dir2/Dir2.1, d, 8",
    "Dir2/Dir2.1/File2.1.1, f, 8, ee6b0f8fa7293180d63bee180a8d866afacccd84",
    "Dir2/Dir2.2, d, 5",
    "Dir2/Dir2.2/File2.2.1, fx, 5, 5ec3df52ddff28887f993a7f74cb5c1774c1bb7e",
    "Dir2/Dir2.2/File2.2.2, f, 3, ed27799de395df652c2a9ae931eb71b3f1b03f56",
    "Dir2/Dir2.3, d, 9",
    "Dir2/Dir2.3/File2.3.1, f, 7, 36dcb69c45fa1dc8d07c9827d46558138e7a246d",
    "Dir2/Dir2.3/File2.3.2, fx, 9, b52e3dbf5d8ac642ca2accb9d324189e6998670d",
    "Dir2/Dir2.3/File2.3.3, f, 1, ee4a6a6fc707682ddf37d93816fa542eb60b814c",
    "Dir2/Dir2.w, d, 8",
    "Dir2/Dir2.w/File2.w.1, f, 8, 6de6e2c5f3504e6519be6cd1dc217f4df8ac8796",
    "Dir2/Dir2.x, d, 5",
    "Dir2/Dir2.x/File2.x.1, fx, 5, 6c4912d5a0295c8658592b94c254dc54f9d32460",
    "Dir2/Dir2.x/File2.x.2, f, 3, ab2c43b101206f391b1de43287a858e7954aac19",
    "Dir2/Dir2.y, d, 9",
    "Dir2/Dir2.y/File2.y.1, f, 7, 0c260d58ef87fca3c6d017f57a0b75952421f2b1",
    "Dir2/Dir2.y/File2.y.2, fx, 9, 87b357680fb8b673daad27175ad3f16ad22959b6",
    "Dir2/Dir2.y/File2.y.3, f, 1, 6239ff4b875c56227cb051a1a68c2e9d672a41b9",

    "Dir3, ds, 14",
    "Dir3/File3.1, f, 13, 9e55b828c3d8025fb5b4f01304760332859a88b0",
    "Dir3/File3.2, f, 12, 9a0fa3014dc4ed3dbbed0c71980b6c31344ba9df",
    "Dir3/Dir3.1, d, 4",
    "Dir3/Dir3.1/File3.1.1, f, 2, de0bc7d99e814b069948ac628cca57c8d616438b",
    "Dir3/Dir3.1/File3.1.2, fx, 4, c5afc0b2ac740f2600667cd61a213ab85284a5d0",
    "Dir3/Dir3.2, d, 14",
    "Dir3/Dir3.2/File3.2.1, f, 6, 46aa43ab7fdd078715d7a48ab5b86e136933c76a",
    "Dir3/Dir3.2/File3.2.2, f, 10, dafe7de11d698fff78090e5cbfc32ea602a93ffd",
    "Dir3/Dir3.2/Dir3.2.1, d, 14",
    "Dir3/Dir3.2/Dir3.2.2, ds, 14"

    "Dirz, ds, 14",
    "Dirz/File3.1, f, 13, a5bde1f695ea072aff3233465d285f735a0db5a0",
    "Dirz/File3.2, f, 12, 71dd3d8d090348aa3db982fad8d442e883afa0c2",
    "Dirz/Dir3.1, d, 4",
    "Dirz/Dir3.1/File3.1.1, f, 2, 9e6ed1698be6292705e08afafc1d74442af905fb",
    "Dirz/Dir3.1/File3.1.2, fx, 4, e38ab9bba32174083fa2ce515ca576d461417a27",
    "Dirz/Dir3.2, d, 14",
    "Dirz/Dir3.2/File3.2.1, f, 6, 87fa753db67c981728a06c4fe7ba87d0f013f5d0",
    "Dirz/Dir3.2/File3.2.2, f, 10, fe42f95900229290816ddc2b04e135976c55bd1b",
]

item_list_need = [
    # same dir
    "Dir1, d, 17",
    "Dir1/File1.1, f, 15, fce43f9615d593ea9ea810f4b2eed5433057404e, 562365",
    "Dir1/File1.2, f, 16, 5a300ed54f2a0bf32be33c05b11fa62a9c92b8e1",
    "Dir1/File1.3, f, 17, 6abbdac26853f866e178c836ff9e8943d772d0d7",

    "Dir2, d, 9",
    "Dir2/Dir2.1, d, 8",
    "Dir2/Dir2.1/File2.1.1, f, 8, ee6b0f8fa7293180d63bee180a8d866afacccd84",
    "Dir2/Dir2.3, d, 9",
    "Dir2/Dir2.3/File2.3.1, f, 8, 261dafb07b6e8ead2e223a22dedafba0656abf80",
    "Dir2/Dir2.3/File2.3.2, fx, 12, a516ae62e72b954ff7aabfd7e65016c339414868",
    "Dir2/Dir2.3/File2.3.3, f, 1, ee4a6a6fc707682ddf37d93816fa542eb60b814c",

    "Dir3, ds, 16",
    "Dir3/File3.1, f, 13, 9e55b828c3d8025fb5b4f01304760332859a88b0",
    "Dir3/File3.2, f, 12, 9a0fa3014dc4ed3dbbed0c71980b6c31344ba9df",
    "Dir3/Dir3.1, d, 4",
    "Dir3/Dir3.1/File3.1.2, fx, 5, 7fc1dad73016076c9f41d8bc8572c33bfbe93444",
    "Dir3/Dir3.2, d, 14",
    "Dir3/Dir3.2/File3.2.1, f, 6, 46aa43ab7fdd078715d7a48ab5b86e136933c76a",
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
        self.maxDiff = None

    def tearDown(self):
        pass

    # def test_duplicate_item(self):
    #    svni1 = SVNTopItem()
    #    for item in item_list1: svni1.new_item_from_str(item)
    #    svni2 = SVNTopItem()
    #    for item in item_list2: svni2.new_item_from_str(item)
    #
    #    #svni_result = SVNTopItem()
    #    for item in svni2.walk_items(what="file"):
    #        svni1.duplicate_item(item)
    #
    #    list_after  = [str(item) for item in svni1.walk_items()]
    #    self.assertEqual(list_after, merge_list_1_and_files_of_list2_ref)

    def test_recursive_remove_depth_first(self):
        svni1 = SVNTopItem()
        for item in item_list1:
            svni1.new_item_from_str_re(item)
        list_before = [str(item) for item in svni1.walk_items()]
        svni1.recursive_remove_depth_first(remove_sub_if_small_revision)
        list_after = [str(item) for item in svni1.walk_items()]
        self.assertNotEqual(list_before, list_after)

        item_list1_after_remove_ref = [
            "Dir1, d, 17",
            "Dir1/File1.1, f, 15, fce43f9615d593ea9ea810f4b2eed5433057404e, 562365",
            "Dir1/File1.2, f, 16, 5a300ed54f2a0bf32be33c05b11fa62a9c92b8e1",
            "Dir1/File1.3, f, 17, 6abbdac26853f866e178c836ff9e8943d772d0d7",

            "Dir2, d, 9",
            "Dir2/Dir2.3, d, 9",
            "Dir2/Dir2.3/File2.3.2, fx, 9, b52e3dbf5d8ac642ca2accb9d324189e6998670d",

            "Dir3, ds, 14",
            "Dir3/File3.1, f, 13, 9e55b828c3d8025fb5b4f01304760332859a88b0",
            "Dir3/File3.2, f, 12, 9a0fa3014dc4ed3dbbed0c71980b6c31344ba9df",
            "Dir3/Dir3.2, d, 14",
            "Dir3/Dir3.2/File3.2.2, f, 10, dafe7de11d698fff78090e5cbfc32ea602a93ffd",
        ]
        self.assertEqual(list_after, item_list1_after_remove_ref)

    def test_equal(self):
        svni1 = SVNTopItem()
        svni2 = SVNTopItem()
        svni3 = SVNItem({'name':  "svni3", 'flags': "f", 'revision': 15})
        self.assertEqual(svni1, svni2)
        self.assertNotEqual(svni1, svni3)
        svni1.new_item_at_path("file1", {'flags': "f", 'revision': 19})
        self.assertNotEqual(svni1, svni2)
        svni2.new_item_at_path("file1", {'flags': "f", 'revision': 19})
        self.assertEqual(svni1, svni2)
        svni1.add_sub_item(svni3)
        self.assertNotEqual(svni1, svni2)
        svni2.add_sub_item(copy.deepcopy(svni3))
        self.assertEqual(svni1, svni2)

    def test_looping(self):
        svni1 = SVNTopItem()
        for item in item_list1:
            svni1.new_item_from_str_re(item)
        sub1 = svni1.get_item("Dir1")
        files, dirs = sub1.sorted_sub_items()
        # test item keys
        self.assertEqual([a_file.name for a_file in files], sorted(["File1.1", "File1.2", "File1.3"]))

        sub3 = svni1.get_item("Dir3")
        files, dirs = sub3.sorted_sub_items()
        self.assertEqual([a_file.name for a_file in files], sorted(["File3.1", "File3.2"]))
        self.assertEqual([a_dir.name for a_dir in dirs], sorted(["Dir3.1", "Dir3.2"]))

    def test_deepcopy(self):
        svni1 = SVNTopItem()
        for text_item in item_list1:
            svni1.new_item_from_str_re(text_item)
        svni2 = copy.deepcopy(svni1)
        self.assertEqual(svni1, svni2)

    def test_walk_items_depth_first(self):
        svni1 = SVNTree()
        for item in item_list1:
            svni1.new_item_from_str_re(item)

        all_items_list_expected = [
            "Dir1/File1.1",
            "Dir1/File1.2",
            "Dir1/File1.3",
            "Dir1",

            "Dir2/Dir2.1/File2.1.1",
            "Dir2/Dir2.1",
            "Dir2/Dir2.2/File2.2.1",
            "Dir2/Dir2.2/File2.2.2",
            "Dir2/Dir2.2",
            "Dir2/Dir2.3/File2.3.1",
            "Dir2/Dir2.3/File2.3.2",
            "Dir2/Dir2.3/File2.3.3",
            "Dir2/Dir2.3",
            "Dir2",

            "Dir3/Dir3.1/File3.1.1",
            "Dir3/Dir3.1/File3.1.2",
            "Dir3/Dir3.1",
            "Dir3/Dir3.2/Dir3.2.1",
            "Dir3/Dir3.2/Dir3.2.2",
            "Dir3/Dir3.2/File3.2.1",
            "Dir3/Dir3.2/File3.2.2",
            "Dir3/Dir3.2",

            "Dir3/File3.1",
            "Dir3/File3.2",
            "Dir3"]
        all_items_list_result = []
        for item in svni1.walk_items_depth_first(what="a"):
            all_items_list_result.append(str(item.full_path()))
        self.assertEqual(all_items_list_result, all_items_list_expected)

        all_files_list_expected = [
            "Dir1/File1.1",
            "Dir1/File1.2",
            "Dir1/File1.3",

            "Dir2/Dir2.1/File2.1.1",
            "Dir2/Dir2.2/File2.2.1",
            "Dir2/Dir2.2/File2.2.2",
            "Dir2/Dir2.3/File2.3.1",
            "Dir2/Dir2.3/File2.3.2",
            "Dir2/Dir2.3/File2.3.3",

            "Dir3/Dir3.1/File3.1.1",
            "Dir3/Dir3.1/File3.1.2",
            "Dir3/Dir3.2/File3.2.1",
            "Dir3/Dir3.2/File3.2.2",

            "Dir3/File3.1",
            "Dir3/File3.2"]
        all_files_list_result = []
        for afile in svni1.walk_items_depth_first(what="f"):
            all_files_list_result.append(str(afile.full_path()))
        self.assertEqual(all_files_list_result, all_files_list_expected)

        all_dirs_list_expected = [
            "Dir1",
            "Dir2/Dir2.1",
            "Dir2/Dir2.2",
            "Dir2/Dir2.3",
            "Dir2",
            "Dir3/Dir3.1",
            "Dir3/Dir3.2/Dir3.2.1",
            "Dir3/Dir3.2/Dir3.2.2",
            "Dir3/Dir3.2",
            "Dir3"]
        all_dirs_list_result = []
        for adir in svni1.walk_items_depth_first(what="d"):
            all_dirs_list_result.append(str(adir.full_path()))
        self.assertEqual(all_dirs_list_result, all_dirs_list_expected)

    def test_walk_items(self):
        svni1 = SVNTree()
        for item in item_list1:
            svni1.new_item_from_str_re(item)

        all_items_list = []
        for item in svni1.walk_items(what="a"):
            all_items_list.append(str(item))
        self.assertEqual(sorted(all_items_list), sorted(item_list1))

        all_files_list = []
        for afile in svni1.walk_items(what="f"):
            all_files_list.append(str(afile))
        self.assertEqual(sorted(all_files_list), sorted([item for item in item_list1 if "f" in item.split(", ")[1]]))

        all_dirs_list = []
        for adir in svni1.walk_items(what="d"):
            all_dirs_list.append(str(adir))
        self.assertEqual(sorted(all_dirs_list), sorted([item for item in item_list1 if "d" in item.split(", ")[1]]))

    def test_add_sub_negative(self):
        svni1 = SVNTopItem()
        # should throw when adding and hierarchy does not exist
        self.assertRaises(KeyError, svni1.new_item_at_path, "SubDir1/SubFile1", {'flags': "f", 'revision': 19})

        svni1.new_item_at_path("SubFile1", {'flags': "f", 'revision': 19})
        self.assertEqual(list(svni1.subs.keys()), ["SubFile1"])
        # should throw when adding and path has non leaf file
        self.assertRaises(TypeError, svni1.new_item_at_path, "SubFile1/SubFile2", {'flags': "f", 'revision': 19})

    def test_add_sub_positive(self):
        svni1 = SVNTopItem()
        svni1.new_item_at_path("SubDir1", {'flags': "d", 'revision': 19})
        self.assertEqual(list(svni1.subs.keys()), ["SubDir1"])
        self.assertIsInstance(svni1.get_item("SubDir1"), SVNItem,
                              msg="svn1.get_item should return SVNItem object")

        svni1.new_item_at_path("SubDir1/SubDir2", {'flags': "d", 'revision': 219})
        self.assertEqual(list(svni1.subs.keys()), ["SubDir1"])
        sub1 = svni1.get_item("SubDir1")
        self.assertIsInstance(sub1, SVNItem, msg="svn1.get_item should return SVNItem object")
        self.assertEqual(list(sub1.subs.keys()), ["SubDir2"])
        sub2 = sub1.get_item("SubDir2")
        self.assertIsInstance(sub2, SVNItem, msg="svn1.get_item should return SVNItem object")

        svni1.new_item_at_path("SubDirA", {'flags': "d", 'revision': 2195})
        self.assertEqual(sorted(svni1.subs.keys()), ["SubDir1", "SubDirA"])
        sub1 = svni1.get_item("SubDir1")
        self.assertIsInstance(sub1, SVNItem, msg="svn1.get_item should return SVNItem object")
        sub2 = svni1.get_item("SubDirA")
        self.assertIsInstance(sub2, SVNItem, msg="svn1.get_item should return SVNItem object")

    def test_add_sub_item_positive(self):
        """ Check the internal function add_sub_item where is should succeed """
        svni1 = SVNTopItem()
        svni2 = SVNItem({'name':  "SubFile", 'flags': "f", 'revision': 1258})
        svni1.add_sub_item(svni2)
        self.assertEqual(list(svni1.subs.keys()), ["SubFile"])
        self.assertIsNone(svni1.get_item("kuku"),
                          msg="svn1.get_item should return None for none existing item")
        self.assertIs(svni1.get_item("SubFile"), svni2,
                      msg="svn1.get_item should return the same object given")
        svni1.new_item_at_path("SubDir", {'flags': "d", 'revision': 1258})
        self.assertEqual(sorted(svni1.subs.keys()), ["SubDir", "SubFile"])
        self.assertIsNone(svni1.get_item("kuku"),
                          msg="svn1.get_item should return None for none existing item")
        self.assertIsInstance(svni1.get_item("SubDir"), SVNItem,
                              msg="svn1.get_item should return SVNItem object")

    def test_add_sub_item_negative(self):
        """ Check the internal function add_sub_item where is should fail """
        svni1 = SVNItem({'name':  "TestDir", 'flags': "f", 'revision': 15})
        svni2 = SVNItem({'name':  "SubFile", 'flags': "f", 'revision': 1258})
        self.assertRaises(TypeError, svni1.add_sub_item, svni2)
        with self.assertRaises(ValueError):
            the_subs = svni1.subs
        self.assertRaises(ValueError, svni1.get_item, "SubFile")

    def test_other_flags_construction(self):
        """ Construct SVNItem with some flags flag """
        svni1 = SVNItem({'name':  "TestFlags", 'flags': "fx", 'revision': 36})
        self.assertEqual(svni1.name, "TestFlags")
        self.assertEqual(svni1.revision, 36)
        self.assertTrue(svni1.isFile(), msg="SVNItem.isFile() should return True for file")
        self.assertFalse(svni1.isDir(), msg="SVNItem.isDir() should return False for directory")
        self.assertTrue(svni1.isExecutable(), msg="SVNItem.isExecutable() should return True for non-executable")
        self.assertFalse(svni1.isSymlink(), msg="SVNItem.isSymlink() should return False for non-symlink")
        with self.assertRaises(ValueError):
            the_subs = svni1.subs
        self.assertRaises(ValueError, svni1.get_item, "kuku")
        svni2 = SVNItem({'name':  "TestFlags", 'flags': "ds", 'revision': 36})
        self.assertEqual(svni2.name, "TestFlags")
        self.assertFalse(svni2.isFile(), msg="SVNItem.isFile() should return False for directory")
        self.assertTrue(svni2.isDir(), msg="SVNItem.isDir() should return True for directory")
        self.assertFalse(svni2.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertTrue(svni2.isSymlink(), msg="SVNItem.isSymlink() should return True for non-symlink")
        self.assertEqual(svni2.subs, {})
        self.assertIsNone(svni2.get_item("kuku"),
                          "svn1.get_item should return None for none existing item")

    def test_dir_construction(self):
        """ Construct SVNItem with directory flag """
        svni1 = SVNTopItem()
        self.assertFalse(svni1.isFile(), msg="SVNItem.isFile() should return False for directory")
        self.assertTrue(svni1.isDir(), msg="SVNItem.isDir() should return True for directory")
        self.assertFalse(svni1.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        self.assertFalse(svni1.isSymlink(), msg="SVNItem.isSymlink() should return False for non-symlink")
        self.assertEqual(svni1.subs, {})
        self.assertIsNone(svni1.get_item("kuku"),
                          msg="svn1.get_item should return None for none existing item")

    def test_file_construction(self):
        """ Construct SVNItem with file flag """
        svni1 = SVNItem({'name':  "TestFile", 'flags': "f", 'revision': 17})
        self.assertEqual(svni1.name, "TestFile")
        self.assertEqual(svni1.revision, 17)
        self.assertEqual(str(svni1), "TestFile, f, 17")
        self.assertTrue(svni1.isFile(), msg="SVNItem.isFile() should return True for file")
        self.assertFalse(svni1.isDir(), msg="SVNItem.isDir() should return False for directory")
        self.assertFalse(svni1.isExecutable(), msg="SVNItem.isExecutable() should return False for non-executable")
        with self.assertRaises(ValueError):
            the_subs = svni1.subs
        self.assertRaises(ValueError, svni1.get_item, "kuku")
