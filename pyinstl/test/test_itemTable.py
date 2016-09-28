#!/usr/bin/env python3


import sys
import os
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from pyinstl.itemRow import ItemRow, ItemDetailRow, ItemToDetailRelation, alchemy_base
from pyinstl.itemTable import ItemTableYamlReader, ItemTable


def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        return ret

    return wrap


class TestItemTable(unittest.TestCase):
    def setUp(self):
        self.it = ItemTable()

        self.it.session.add(ItemRow(iid="D", inherit_resolved=True))
        self.it.session.add(ItemRow(iid="A", inherit_resolved=False))
        self.it.session.add(ItemRow(iid="C", inherit_resolved=False))
        self.it.session.add(ItemRow(iid="B", inherit_resolved=False))

        self.it.session.add(ItemDetailRow(origin_iid="D", os="common", detail_name="detail-1-D", detail_value="value-1-D"))
        self.it.session.add(ItemDetailRow(origin_iid="D", os="common", detail_name="detail-2-D", detail_value="value-2-D"))

    def tearDown(self):
        pass

    def test_ItemRow_get_item(self):
        the_item1 = self.it.get_item("B")
        self.assertEqual(the_item1.iid, "B")

        the_item2 = self.it.get_item("A")
        self.assertEqual(the_item2.iid, "A")

        self.assertNotEqual(the_item1, the_item2)

        the_item3 = self.it.get_item("B")
        self.assertIs(the_item1, the_item3, "same object should be returned by two calls with same iid")

        the_item3 = self.it.get_item("Z")
        self.assertIs(the_item3, None, "None should be returned for non existing ItemRow")

    def test_ItemRow_get_items(self):
        the_items1 = self.it.get_items()
        # items should come sorted by iid
        self.assertEqual(the_items1[0].iid, "A")
        self.assertEqual(the_items1[1].iid, "B")
        self.assertEqual(the_items1[2].iid, "C")
        self.assertEqual(the_items1[3].iid, "D")
        the_items2 = self.it.get_items()
        self.assertEqual(the_items1, the_items2, "same list should be returned by two calls")

    def test_get_item_by_resolve_status(self):
        a1 = self.it.get_item("A")
        a2 = self.it.get_item_by_resolve_status("A", False)
        self.assertIs(a1, a2)
        a3 = self.it.get_item_by_resolve_status("A", True)
        self.assertIs(a3, None)
        a1 = self.it.get_item("D")
        a2 = self.it.get_item_by_resolve_status("D", True)
        self.assertIs(a1, a2)
        a3 = self.it.get_item_by_resolve_status("D", False)
        self.assertIs(a3, None)
        a4 = self.it.get_item_by_resolve_status("Z", False)
        self.assertIs(a4, None)
        a5 = self.it.get_item_by_resolve_status("Z", True)
        self.assertIs(a5, None)

    def test_get_items_by_resolve_status(self):
        a = self.it.get_item("A")
        b = self.it.get_item("B")
        c = self.it.get_item("C")
        l1 = self.it.get_items_by_resolve_status(False)
        self.assertEqual(l1, [a, b, c])

        d = self.it.get_item("D")
        l2 = self.it.get_items_by_resolve_status(True)
        self.assertEqual(l2, [d])

    def test_get_all_iids(self):
        all_iids1 = self.it.get_all_iids()
        self.assertEqual(all_iids1, ["A", "B", "C", "D"])
        all_iids2 = self.it.get_all_iids()
        self.assertEqual(all_iids1, all_iids2)

    def test_get_original_details_for_item(self):
        ds_for_D = self.it.get_original_details_for_item("D")
        self.assertEqual(str(ds_for_D[0]), "1) D, common, detail-1-D: value-1-D")
        self.assertEqual(str(ds_for_D[1]), "2) D, common, detail-2-D: value-2-D")
        ds_for_Z = self.it.get_original_details_for_item("Z")
        self.assertEqual(ds_for_Z, [])

if False:
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
