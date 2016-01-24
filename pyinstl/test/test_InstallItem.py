#!/usr/bin/env python3


import sys
import os
import unittest
import filecmp

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from installItem import *


def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        return ret

    return wrap


class TestInstallItem(unittest.TestCase):
    def setUp(self):
        self.ii1 = InstallItem()
        self.ii1.iid = "TEST_self.iid"
        self.ii1.name = "My test self.ii1d"
        self.ii1.guid = "ec541a62-ad21-11e0-8150-b7fd7bebd530"
        self.ii1.remark = "just test install item"
        pass

    def tearDown(self):
        del self.ii1

    def test_Construction(self):
        self.assertEqual(self.ii1._inherit_list(), [])
        self.assertEqual(self.ii1._source_list(), [])
        self.assertEqual(self.ii1._depend_list(), [])
        for action_type in InstallItem.action_types:
            self.assertEqual(self.ii1._action_list(action_type), [])

    def test_get_set_by_common_os(self):
        self.ii1.add_inherit("AN_INHERITE_1")
        self.ii1.add_inherit("AN_INHERITE_2")
        self.ii1.add_folders("A_FOLDER_1")
        self.ii1.add_folders("A_FOLDER_2")
        self.ii1.add_depends("A_DEPEND_1")
        self.ii1.add_depends("A_DEPEND_2")
        for action_type in InstallItem.action_types:
            self.ii1.add_action(action_type, "AN_ACTION_OF_TYPE_" + action_type)

        # check get is correct for "common"
        self.assertEqual(self.ii1._inherit_list(), ["AN_INHERITE_1", "AN_INHERITE_2"])
        self.assertEqual(self.ii1._folder_list(), ["A_FOLDER_1", "A_FOLDER_2"])
        self.assertEqual(self.ii1._depend_list(), ["A_DEPEND_1", "A_DEPEND_2"])
        for action_type in InstallItem.action_types:
            self.assertEqual(self.ii1._action_list(action_type), ["AN_ACTION_OF_TYPE_" + action_type])

    def test_get_set_by_other_os(self):
        self.ii1.add_inherit("AN_INHERITE_1")
        self.ii1.add_folders("A_FOLDER_1")
        self.ii1.add_depends("A_DEPEND_1")
        for action_type in InstallItem.action_types:
            self.ii1.add_action(action_type, "AN_ACTION_1_OF_TYPE_" + action_type)

        with self.ii1.set_for_specific_os("Win"):
            self.ii1.add_inherit("AN_INHERITE_2")
            self.ii1.add_folders("A_FOLDER_2")
            self.ii1.add_depends("A_DEPEND_2")
            for action_type in InstallItem.action_types:
                self.ii1.add_action(action_type, "AN_ACTION_2_OF_TYPE_" + action_type)

        # check get is correct for "common & Win"
        self.assertEqual(self.ii1._inherit_list(),
                         ["AN_INHERITE_1", "AN_INHERITE_2"])  # inherite is not dependant on os
        self.assertEqual(self.ii1._folder_list(), ["A_FOLDER_1"])
        self.assertEqual(self.ii1._depend_list(), ["A_DEPEND_1"])
        for action_type in InstallItem.action_types:
            self.assertEqual(self.ii1._action_list(action_type), ["AN_ACTION_1_OF_TYPE_" + action_type])

        # check get is correct for "common & Win"
        InstallItem.begin_get_for_specific_os("Win")
        self.assertEqual(self.ii1._inherit_list(), ["AN_INHERITE_1", "AN_INHERITE_2"])
        self.assertEqual(self.ii1._folder_list(), ["A_FOLDER_1", "A_FOLDER_2"])
        self.assertEqual(self.ii1._depend_list(), ["A_DEPEND_1", "A_DEPEND_2"])
        for action_type in InstallItem.action_types:
            self.assertEqual(self.ii1._action_list(action_type),
                             ["AN_ACTION_1_OF_TYPE_" + action_type, "AN_ACTION_2_OF_TYPE_" + action_type])
        InstallItem.end_get_for_specific_os()
