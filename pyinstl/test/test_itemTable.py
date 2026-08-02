#!/usr/bin/env python3.12


import sys
import os
import unittest
import time
from pathlib import Path


from pybatch.info_mapBatchCommands import IndexYamlReader

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))
sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))
from db.indexItemTable import IndexItemsTable
import aYaml
import utils
from configVar import config_vars


def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        return ret

    return wrap


class TestConditionalsInIndex(unittest.TestCase):
    def setUp(self):
        config_vars["__INSTL_DEFAULTS_FOLDER__"] = Path(os.path.dirname(__file__), "../..", "defaults")
        self.in_file_path = Path(os.path.dirname(__file__), 'index_with_conditionals.yaml')
        self.out_file_path = Path(os.path.dirname(__file__), 'index_with_conditionals.out.yaml')

    def test_conditional(self):
        config_vars["DEFINED"] = "I'm defined"
        with IndexYamlReader(self.in_file_path, report_own_progress=False) as it:
            it()
            as_yaml = it.items_table.repr_for_yaml()
            as_yaml_doc = aYaml.YamlDumpDocWrap(as_yaml, '!index')
            as_yaml_doc.ReduceOneItemLists()
            with open(self.out_file_path, "w") as wfd:
                utils.chown_chmod_on_fd(wfd)
                aYaml.writeAsYaml(as_yaml_doc, wfd)
        out_text = self.out_file_path.read_text()
        num_iids = out_text.count('_IID')
        num_oks = out_text.count('OK')
        num_bads = out_text.count('Bad')

        self.assertNotEqual(num_iids, 0, "no _IIDs in output")
        self.assertNotEqual(num_oks, 0, "no OKs in output")
        self.assertEqual(num_bads, 0, f"{num_bads} bad results in output")
        self.assertEqual(num_iids, num_oks, f"{num_iids=} != {num_oks=}")


def _load_items_table(in_file_path, resolve_inheritance):
    """ Populate a fresh, in-memory IndexItemsTable from a yaml index file using
        the current public API (IndexYamlReader, a DBManager subclass that builds
        the items_table on demand). Returns (reader, items_table); keep the reader
        alive for the duration of the test so the table is not torn down.
    """
    config_vars["__INSTL_DEFAULTS_FOLDER__"] = Path(os.path.dirname(__file__), "../..", "defaults")
    config_vars["__MAIN_DB_FILE__"] = ":memory:"
    reader = IndexYamlReader(in_file_path, resolve_inheritance=resolve_inheritance, report_own_progress=False)
    reader.__enter__()
    reader.items_table.clear_tables()  # in case the shared DB was not cleaned by a prior test
    reader()
    return reader


class TestReadWrite(unittest.TestCase):
    """ Read a yaml index, resolve inheritance, and round-trip it back to yaml.
        Exercises the current IndexItemsTable read/repr API (raw-SQL backed),
        replacing the removed SQLAlchemy-ORM contract.
    """
    @timing
    def setUp(self):
        self.in_file_path = os.path.join(os.path.dirname(__file__), 'test-index-in.yaml')
        self.out_file_path = os.path.join(os.path.dirname(__file__), 'test-index-out.yaml')
        self.reader = _load_items_table(self.in_file_path, resolve_inheritance=True)
        self.it = self.reader.items_table

    def tearDown(self):
        self.it.clear_tables()
        self.reader.__exit__(None, None, None)

    def test_00(self):
        # dummy test to check setUp/tearDown on their own
        pass

    def test_01_contents_items(self):
        the_items = self.it.get_all_index_items()
        self.assertEqual([row["iid"] for row in the_items], ["A", "B", "C", "D"])

    def test_02_contents_original_details(self):
        # 'common' name + Mac/Win install_sources per item, plus inherit rows for A and B
        all_details = list()
        for iid in self.it.get_all_iids():
            all_details.extend(self.it.get_original_details(iid))
        names_and_values = [(d["owner_iid"], d["detail_name"], d["detail_value"]) for d in all_details]
        self.assertIn(("A", "name", "AAA"), names_and_values)
        self.assertIn(("A", "inherit", "B"), names_and_values)
        self.assertIn(("B", "inherit", "C"), names_and_values)
        self.assertIn(("B", "inherit", "D"), names_and_values)
        self.assertIn(("C", "install_sources", "Mac/source_C"), names_and_values)

    def test_03_resolved_details(self):
        # after resolve_inheritance, A should have inherited install_sources from B->C/D
        resolved = self.it.get_resolved_details_for_iid("A", "install_sources")
        resolved_values = sorted(d["detail_value"] for d in resolved)
        self.assertTrue(any("source_A" in v for v in resolved_values))

    def test_write(self):
        as_yaml = self.it.repr_for_yaml()
        as_yaml_doc = aYaml.YamlDumpDocWrap(as_yaml, '!index')
        as_yaml_doc.ReduceOneItemLists()
        with open(self.out_file_path, "w") as wfd:
            utils.chown_chmod_on_fd(wfd)
            aYaml.writeAsYaml(as_yaml_doc, wfd)
        out_text = Path(self.out_file_path).read_text()
        self.assertIn("AAA", out_text)
        self.assertIn("BBB", out_text)


class TestItemTable(unittest.TestCase):
    """ Exercise the lookup methods of the current IndexItemsTable against a
        yaml-loaded fixture. Populated via the current reader API (the previous
        SQLAlchemy session.add(index_item_t(...)) construction was removed).
    """
    def setUp(self):
        self.in_file_path = os.path.join(os.path.dirname(__file__), 'test-index-in.yaml')
        # load without resolving inheritance so original details stay 1:1 with the file
        self.reader = _load_items_table(self.in_file_path, resolve_inheritance=False)
        self.it = self.reader.items_table

    def tearDown(self):
        self.it.clear_tables()
        self.reader.__exit__(None, None, None)

    def test_00_empty_tables(self):
        self.it.clear_tables()
        the_items = self.it.get_all_index_items()
        self.assertEqual(the_items, [])

    def test_01_num_items(self):
        the_items = self.it.get_all_index_items()
        self.assertEqual(len(the_items), 4)

    def test_02_IndexItemRow_get_item(self):
        the_item1 = self.it.get_index_item("B")
        self.assertEqual(the_item1["iid"], "B")

        the_item2 = self.it.get_index_item("A")
        self.assertEqual(the_item2["iid"], "A")

        self.assertNotEqual(the_item1["iid"], the_item2["iid"])

        the_item3 = self.it.get_index_item("Z")
        self.assertIs(the_item3, None, "None should be returned for non existing index_item_t")

    def test_03_IndexItemRow_get_all_items(self):
        the_items1 = self.it.get_all_index_items()
        self.assertEqual([row["iid"] for row in the_items1], ["A", "B", "C", "D"])

    def test_06_get_all_iids(self):
        all_iids1 = self.it.get_all_iids()
        self.assertEqual(all_iids1, ["A", "B", "C", "D"])
        all_iids2 = self.it.get_all_iids()
        self.assertEqual(all_iids1, all_iids2)

    def test_07_get_original_details_for_item(self):
        ds_for_A = self.it.get_original_details("A")
        as_tuples = [(d["detail_name"], d["detail_value"]) for d in ds_for_A]
        self.assertIn(("name", "AAA"), as_tuples)
        self.assertIn(("inherit", "B"), as_tuples)
        ds_for_Z = self.it.get_original_details("Z")
        self.assertEqual(ds_for_Z, [])

    def test_09_get_original_details_by_name(self):
        ds_name = self.it.get_original_details("A", detail_name="name")
        self.assertEqual([d["detail_value"] for d in ds_name], ["AAA"])
        ds_none = self.it.get_original_details("A", detail_name="some-bullshit-detail-name")
        self.assertEqual(ds_none, [])

    def test_10_get_original_details_for_item_by_name(self):
        ds_for_A = self.it.get_original_details("A", "name")
        self.assertEqual([d["detail_value"] for d in ds_for_A], ["AAA"])
        ds_for_A = self.it.get_original_details("A", "some-bullshit-detail-name")
        self.assertEqual(ds_for_A, [])
        ds_for_A = self.it.get_original_details("some-bullshit-item", "name")
        self.assertEqual(ds_for_A, [])
