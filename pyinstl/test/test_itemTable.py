#!/usr/bin/env python3


import sys
import os
import unittest
import time

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from pyinstl.itemRow import ItemRow, ItemDetailRow, ItemToDetailRelation, alchemy_base
from pyinstl.itemTable import ItemTableYamlReader, ItemTable
import aYaml


def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        return ret

    return wrap


class TestReadWrite(unittest.TestCase):
    def setUp(self):
        self.it = ItemTable()
        self.in_file_path = os.path.join(os.path.dirname(__file__), 'test-index-in.yaml')
        self.out_file_path = os.path.join(os.path.dirname(__file__), 'test-index-out.yaml')
        self.ref_file_path = os.path.join(os.path.dirname(__file__), 'test-index-ref.yaml')

        self.it.read_yaml_file(self.in_file_path)

    def tearDown(self):
        pass

    def test_write(self):
        as_yaml = self.it.repr_for_yaml()
        as_yaml_doc = aYaml.YamlDumpDocWrap(as_yaml, '!index')
        as_yaml_doc.ReduceOneItemLists()
        with open(self.out_file_path, "w") as wfd:
            aYaml.writeAsYaml(as_yaml_doc, wfd)


class TestItemTable(unittest.TestCase):
    def setUp(self):
        self.it = ItemTable()

        self.it.session.add(ItemRow(iid="D", inherit_resolved=True))
        self.it.session.add(ItemRow(iid="A", inherit_resolved=False))
        self.it.session.add(ItemRow(iid="C", inherit_resolved=False))
        self.it.session.add(ItemRow(iid="B", inherit_resolved=False))
        self.it.session.add(ItemRow(iid="DD", inherit_resolved=False))

        self.it.session.add(ItemDetailRow(origin_iid="D", os="common", detail_name="detail-1-D", detail_value="value-1-D"))
        self.it.session.add(ItemDetailRow(origin_iid="D", os="common", detail_name="detail-2-D", detail_value="value-2-D"))
        self.it.session.add(ItemDetailRow(origin_iid="DD", os="common", detail_name="detail-1-D", detail_value="value-1-DD"))
        self.it.session.add(ItemDetailRow(origin_iid="DD", os="common", detail_name="detail-2-D", detail_value="value-2-DD"))

    def tearDown(self):
        pass

    def test_A_num_items(self):
        the_items = self.it.get_items()
        self.assertEqual(len(the_items), 5)
        the_details = self.it.get_original_details()
        self.assertEqual(len(the_details), 4)

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
        self.assertEqual(the_items1[0].iid, "D")
        self.assertEqual(the_items1[1].iid, "A")
        self.assertEqual(the_items1[2].iid, "C")
        self.assertEqual(the_items1[3].iid, "B")
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
        dd = self.it.get_item("DD")
        l1 = self.it.get_items_by_resolve_status(False)
        self.assertEqual(l1, [a, b, c, dd])

        d = self.it.get_item("D")
        l2 = self.it.get_items_by_resolve_status(True)
        self.assertEqual(l2, [d])

    def test_get_all_iids(self):
        all_iids1 = self.it.get_all_iids()
        self.assertEqual(all_iids1, ["A", "B", "C", "D", "DD"])
        all_iids2 = self.it.get_all_iids()
        self.assertEqual(all_iids1, all_iids2)

    def test_get_original_details_all(self):
        all_details = self.it.get_original_details()
        self.assertEqual(len(all_details), 4)
        self.assertEqual(str(all_details[0]), "1) D, common, detail-1-D: value-1-D")
        self.assertEqual(str(all_details[1]), "2) D, common, detail-2-D: value-2-D")
        self.assertEqual(str(all_details[2]), "3) DD, common, detail-1-D: value-1-DD")
        self.assertEqual(str(all_details[3]), "4) DD, common, detail-2-D: value-2-DD")

    def test_get_original_details_for_item(self):
        ds_for_D = self.it.get_original_details("D")
        self.assertEqual(str(ds_for_D[0]), "1) D, common, detail-1-D: value-1-D")
        self.assertEqual(str(ds_for_D[1]), "2) D, common, detail-2-D: value-2-D")
        ds_for_Z = self.it.get_original_details("Z")
        self.assertEqual(ds_for_Z, [])

    def test_get_original_details_by_name(self):
        ds_for_D = self.it.get_original_details(detail_name="detail-1-D")
        self.assertEqual(str(ds_for_D[0]), "1) D, common, detail-1-D: value-1-D")
        self.assertEqual(str(ds_for_D[1]), "3) DD, common, detail-1-D: value-1-DD")
        ds_for_Z = self.it.get_original_details(detail_name="some-bullshit-detail-name")
        self.assertEqual(ds_for_Z, [])

    def test_get_original_details_for_item_by_name(self):
        ds_for_D = self.it.get_original_details("D", "detail-1-D")
        self.assertEqual(str(ds_for_D[0]), "1) D, common, detail-1-D: value-1-D")
        ds_for_D = self.it.get_original_details("D", "some-bullshit-detail-name")
        self.assertEqual(ds_for_D, [])
        ds_for_D = self.it.get_original_details("some-bullshit-item", "detail-1-D")
        self.assertEqual(ds_for_D, [])
