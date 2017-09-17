#!/usr/bin/env python3


import sys
import os
import unittest
import time

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from pyinstl.db_alchemy import IndexItemRow, IndexItemDetailRow, IndexItemToDetailRelation
from pyinstl.indexItemTable import ItemTableYamlReader, IndexItemsTable
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
    @timing
    def setUp(self):
        self.it = IndexItemsTable()
        self.it.clear_tables()  # in case db was not cleaned last time the tests were run

        self.in_file_path = os.path.join(os.path.dirname(__file__), 'test-index-in.yaml')
        self.in_file_path = "/repositories/betainstl/svn/instl/index.yaml"
        self.out_file_path = os.path.join(os.path.dirname(__file__), 'test-index-out.yaml')
        self.ref_file_path = os.path.join(os.path.dirname(__file__), 'test-index-ref.yaml')

        self.it.read_yaml_file(self.in_file_path)
        self.it.resolve_inheritance()

    def tearDown(self):
        #self.it.clear_tables()
        pass

    def test_00(self):
        # dummy test to check setUp/tearDown on their own
        pass
if False:
    def test_01_contents_items(self):
        the_items1 = self.it.get_all_index_items()
        self.assertEqual(the_items1[0].iid, "C")
        self.assertEqual(the_items1[1].iid, "D")
        self.assertEqual(the_items1[2].iid, "A")
        self.assertEqual(the_items1[3].iid, "B")

    def test_02_contents_original_details(self):
        original_details = self.it.get_original_details()
        self.assertEqual(len(original_details), 11)
        self.assertEqual(str(original_details[0]), "1) 1, common, name: CCC")
        self.assertEqual(str(original_details[1]), "2) 1, common, install_sources: source_C")
        self.assertEqual(str(original_details[2]), "3) 2, common, name: DDD")
        self.assertEqual(str(original_details[3]), "4) 2, common, install_sources: source_D")
        self.assertEqual(str(original_details[4]), "5) 3, common, name: AAA")
        self.assertEqual(str(original_details[5]), "6) 3, common, inherit: B")
        self.assertEqual(str(original_details[6]), "7) 3, common, install_sources: source_A")
        self.assertEqual(str(original_details[7]), "8) 4, common, name: BBB")
        self.assertEqual(str(original_details[8]), "9) 4, common, inherit: C")
        self.assertEqual(str(original_details[9]), "10) 4, common, inherit: D")
        self.assertEqual(str(original_details[10]),"11) 4, common, install_sources: source_B")

    def test_03_contents_relations(self):
        all_relations = self.it.get_details_relations()
        all_relations_list = [(int(rel.item_id), int(rel.detail_id), int(rel.generation)) for rel in all_relations]
        expected_list = [(1,1,0), (1,2,0), (2,3,0), (2,4,0), (3,5,0), (3,6,0), (3,7,0), (4,8,0), (4,9,0), (4,10,0), (4,11,0), (4,2,2), (4,4,2), (3,11,1), (3,2,1), (3,4,1)]
        self.assertEqual(all_relations_list, expected_list)

    def test_04_contents_resolved_details(self):
        #print([(int(rel.item_id), int(rel.detail_id), int(rel.generation)) for rel in self.it.get_details_relations()])

        all_resolved_details = list()
        for iid in self.it.get_all_iids():
            iid_resolved_details = self.it.get_resolved_details_for_active_iid(iid)
            all_resolved_details.extend(iid_resolved_details)

    def test_write(self):
        as_yaml = self.it.repr_for_yaml()
        as_yaml_doc = aYaml.YamlDumpDocWrap(as_yaml, '!index')
        as_yaml_doc.ReduceOneItemLists()
        with open(self.out_file_path, "w") as wfd:
            aYaml.writeAsYaml(as_yaml_doc, wfd)


class TestItemTable(unittest.TestCase):
    def setUp(self):
        self.it = IndexItemsTable()
        self.it.clear_tables()  # in case db was not cleaned last time the tests were run

        D = IndexItemRow(iid="D", inherit_resolved=True)
        D.original_details.extend([IndexItemDetailRow(os="common", detail_name="detail-1-D", detail_value="value-1-D"),
                                   IndexItemDetailRow(os="common", detail_name="detail-2-D", detail_value="value-2-D")])
        self.it.session.add(D)

        self.it.session.add(IndexItemRow(iid="A", inherit_resolved=False))
        self.it.session.add(IndexItemRow(iid="C", inherit_resolved=False))
        self.it.session.add(IndexItemRow(iid="B", inherit_resolved=False))

        DD_detail_1 = IndexItemDetailRow(os="common", detail_name="detail-1-D", detail_value="value-1-DD")
        DD_detail_1.item = IndexItemRow(iid="DD", inherit_resolved=False)
        DD_detail_2 = IndexItemDetailRow(os="common", detail_name="detail-2-D", detail_value="value-2-DD")
        DD_detail_2.item = DD_detail_1.item
        self.it.session.add(DD_detail_1)
        self.it.session.add(DD_detail_2)

        self.it.session.commit()

    def tearDown(self):
        self.it.clear_tables()

    def test_00_empty_tables(self):
        self.it.clear_tables()
        the_items = self.it.get_all_index_items()
        self.assertEqual(the_items, [])

    def test_01_num_items(self):
        the_items = self.it.get_all_index_items()
        self.assertEqual(len(the_items), 5)
        the_details = self.it.get_original_details()
        self.assertEqual(len(the_details), 4)

    def test_02_IndexItemRow_get_item(self):
        the_item1 = self.it.get_index_item("B")
        self.assertEqual(the_item1.iid, "B")

        the_item2 = self.it.get_index_item("A")
        self.assertEqual(the_item2.iid, "A")

        self.assertNotEqual(the_item1, the_item2)

        the_item3 = self.it.get_index_item("B")
        self.assertIs(the_item1, the_item3, "same object should be returned by two calls with same iid")

        the_item3 = self.it.get_index_item("Z")
        self.assertIs(the_item3, None, "None should be returned for non existing IndexItemRow")

    def test_03_IndexItemRow_get_all_items(self):
        the_items1 = self.it.get_all_index_items()
        self.assertEqual(the_items1[0].iid, "D")
        self.assertEqual(the_items1[1].iid, "A")
        self.assertEqual(the_items1[2].iid, "C")
        self.assertEqual(the_items1[3].iid, "B")
        the_items2 = self.it.get_all_index_items()
        self.assertEqual(the_items1, the_items2, "same list should be returned by two calls")

    def test_04_get_item_by_resolve_status(self):
        a1 = self.it.get_index_item("A")
        a2 = self.it.get_item_by_resolve_status("A", False)
        self.assertIs(a1, a2)
        a3 = self.it.get_item_by_resolve_status("A", True)
        self.assertIs(a3, None)
        a1 = self.it.get_index_item("D")
        a2 = self.it.get_item_by_resolve_status("D", True)
        self.assertIs(a1, a2)
        a3 = self.it.get_item_by_resolve_status("D", False)
        self.assertIs(a3, None)
        a4 = self.it.get_item_by_resolve_status("Z", False)
        self.assertIs(a4, None)
        a5 = self.it.get_item_by_resolve_status("Z", True)
        self.assertIs(a5, None)

    def test_05_get_items_by_resolve_status(self):
        a = self.it.get_index_item("A")
        b = self.it.get_index_item("B")
        c = self.it.get_index_item("C")
        dd = self.it.get_index_item("DD")
        l1 = self.it.get_items_by_resolve_status(False)
        self.assertEqual(l1, [a, b, c, dd])

        d = self.it.get_index_item("D")
        l2 = self.it.get_items_by_resolve_status(True)
        self.assertEqual(l2, [d])

    def test_06_get_all_iids(self):
        all_iids1 = self.it.get_all_iids()
        self.assertEqual(all_iids1, ["A", "B", "C", "D", "DD"])
        all_iids2 = self.it.get_all_iids()
        self.assertEqual(all_iids1, all_iids2)

    def test_07_get_original_details_for_item(self):
        ds_for_D = self.it.get_original_details("D")
        self.assertEqual(str(ds_for_D[0]), "1) 1, common, detail-1-D: value-1-D")
        self.assertEqual(str(ds_for_D[1]), "2) 1, common, detail-2-D: value-2-D")
        ds_for_Z = self.it.get_original_details("Z")
        self.assertEqual(ds_for_Z, [])

    def test_08_get_original_details_all(self):
        all_details = self.it.get_original_details()
        self.assertEqual(len(all_details), 4)
        self.assertEqual(str(all_details[0]), "1) 1, common, detail-1-D: value-1-D")
        self.assertEqual(str(all_details[1]), "2) 1, common, detail-2-D: value-2-D")
        self.assertEqual(str(all_details[2]), "3) 5, common, detail-1-D: value-1-DD")
        self.assertEqual(str(all_details[3]), "4) 5, common, detail-2-D: value-2-DD")

    def test_09_get_original_details_by_name(self):
        ds_for_D = self.it.get_original_details(detail_name="detail-1-D")
        self.assertEqual(str(ds_for_D[0]), "1) 1, common, detail-1-D: value-1-D")
        self.assertEqual(str(ds_for_D[1]), "3) 5, common, detail-1-D: value-1-DD")
        ds_for_Z = self.it.get_original_details(detail_name="some-bullshit-detail-name")
        self.assertEqual(ds_for_Z, [])

    def test_10_get_original_details_for_item_by_name(self):
        ds_for_D = self.it.get_original_details("D", "detail-1-D")
        self.assertEqual(str(ds_for_D[0]), "1) 1, common, detail-1-D: value-1-D")
        ds_for_D = self.it.get_original_details("D", "some-bullshit-detail-name")
        self.assertEqual(ds_for_D, [])
        ds_for_D = self.it.get_original_details("some-bullshit-item", "detail-1-D")
        self.assertEqual(ds_for_D, [])
