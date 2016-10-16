#!/usr/bin/env python3


import os
import sys
from collections import defaultdict, OrderedDict

from sqlalchemy import update
from sqlalchemy import or_
from sqlalchemy.ext import baked
from sqlalchemy import bindparam
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import func
from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.engine import reflection
from sqlalchemy.orm import aliased

import utils
from configVar import var_stack
from functools import reduce
from aYaml import YamlReader
from .db_alchemy import create_session, get_engine, IndexItemRow, IndexItemRequiredRow, IndexItemDetailRow, IndexItemToDetailRelation


class ItemTableYamlReader(YamlReader):
    def __init__(self):
        super().__init__()
        self.index_items = list()
        self.index_details = list()
        self.require_items = dict()

    def init_specific_doc_readers(self): # this function must be overridden
        self.specific_doc_readers["!index"] = self.read_index_from_yaml
        self.specific_doc_readers["!require"] = self.read_require_from_yaml

    def read_index_from_yaml(self, all_items_node):
        for IID in all_items_node:
            item = ItemTableYamlReader.item_from_index_node(IID, all_items_node[IID])
            self.index_items.append(item)

    @staticmethod
    def item_from_index_node(the_iid, the_node):
        item = IndexItemRow(iid=the_iid, inherit_resolved=False, from_index=True)
        item.original_details = ItemTableYamlReader.read_item_details_from_node(the_iid, the_node)
        return item

    @staticmethod
    def read_item_details_from_node(the_iid, the_node, the_os='common'):
        details = list()
        for detail_name in the_node:
            if detail_name in IndexItemsTable.os_names[1:]:
                os_specific_details = ItemTableYamlReader.read_item_details_from_node(the_iid, the_node[detail_name], detail_name)
                details.extend(os_specific_details)
            elif detail_name == 'actions':
                actions_details = ItemTableYamlReader.read_item_details_from_node(the_iid, the_node['actions'], the_os)
                details.extend(actions_details)
            else:
                for details_line in the_node[detail_name]:
                    details.append(IndexItemDetailRow(os=the_os, detail_name=detail_name, detail_value=details_line.value))
        return details

    def read_require_from_yaml(self, all_items_node):
        for IID in all_items_node:
            item_lists = ItemTableYamlReader.read_item_details_from_require_node(IID, all_items_node[IID])
            self.require_items[IID] = item_lists

    @staticmethod
    def read_item_details_from_require_node(the_iid, the_node):
        details = list()
        required_by = list()
        for detail_name in the_node:
            if detail_name == "guid":
                new_detail = IndexItemDetailRow(os="common", detail_name="guid_from_require", detail_value=the_node["guid"].value)
                details.append(new_detail)
            elif detail_name == "version":
                new_detail = IndexItemDetailRow(os="common", detail_name="version_from_require", detail_value=the_node["version"].value)
                details.append(new_detail)
            elif detail_name == "required_by":
                for riid in the_node["required_by"]:
                    required_by.append(IndexItemRequiredRow(owner_item_id=the_iid, required_by_iid=riid.value))
        return details, required_by


class IndexItemsTable(object):
    os_names = ('common', 'Mac', 'Mac32', 'Mac64', 'Win', 'Win32', 'Win64')
    action_types = ('pre_copy', 'pre_copy_to_folder', 'pre_copy_item',
                    'post_copy_item', 'post_copy_to_folder', 'post_copy',
                    'pre_remove', 'pre_remove_from_folder', 'pre_remove_item',
                    'remove_item', 'post_remove_item', 'post_remove_from_folder',
                    'post_remove', 'pre_doit', 'doit', 'post_doit')
    not_inherit_details = ("name", "inherit")

    def __init__(self):
        self.session = create_session()
        self.clear_tables()
        self.add_views()
        #inspector = reflection.Inspector.from_engine(get_engine())
        #print("Tables:", inspector.get_table_names())
        #print("Views:", inspector.get_view_names())
        self.baked_queries_map = self.bake_baked_queries()
        self.bakery = baked.bakery()
        self._get_for_os = [IndexItemsTable.os_names[0]]
        self.reader = ItemTableYamlReader()

    def clear_tables(self):
        self.session.query(IndexItemToDetailRelation).delete()
        self.session.query(IndexItemDetailRow).delete()
        self.session.query(IndexItemRow).delete()
        self.session.query(IndexItemRequiredRow).delete()
        self.drop_views()
        self.session.commit()

    def add_views(self):
        stmt = text("""
          CREATE VIEW "full_details_view" AS
          SELECT IndexItemRow.iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, IndexItemToDetailRelation.generation FROM IndexItemRow
          LEFT JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id
          LEFT JOIN IndexItemDetailRow ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id
          """)
        self.session.execute(stmt)

        stmt = text("""
          CREATE VIEW "original_details_view" AS
          SELECT IndexItemRow.iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value FROM IndexItemRow
          LEFT JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id
                  AND IndexItemToDetailRelation.generation = 0
          LEFT JOIN IndexItemDetailRow ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id
          """)
        self.session.execute(stmt)

    def drop_views(self):
        stmt = text("""
            DROP VIEW IF EXISTS "full_details_view"
            """)
        self.session.execute(stmt)
        stmt = text("""
            DROP VIEW IF EXISTS "original_details_view"
            """)
        self.session.execute(stmt)

    def begin_get_for_all_oses(self):
        """ adds all known os names to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        _get_for_os = []
        _get_for_os.extend(IndexItemsTable.os_names)

    def reset_get_for_all_oses(self):
        """ resets the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        self._get_for_os = [self.os_names[0]]

    def begin_get_for_specific_os(self, for_os):
        """ adds another os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
        """
        self._get_for_os.append(for_os)

    def end_get_for_specific_os(self):
        """ removed the last added os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
             This is a static method so it will influence all InstallItem objects.
        """
        self._get_for_os.pop()

    def bake_baked_queries(self):
        """ prepare baked queries for later use
        """
        retVal = dict()

        # all queries are now baked just-in-time

        return retVal

    def insert_index_to_db(self):
        if self.reader.index_items:
            self.session.add_all(self.reader.index_items)
            self.session.flush()
            self.reader.index_items = self.reader.index_items[:]
        self.session.flush()

    def insert_required_to_db(self):
        for iid, details_and_required in self.reader.require_items.items():
            old_item = self.get_index_item(iid)
            if old_item is not None:
                old_item.from_require = True
                old_item.original_details.extend(details_and_required[0])
                for new_original in details_and_required[0]:
                    new_original.resolved_details.append(IndexItemToDetailRelation(item_id=old_item._id, detail_id=new_original._id))

                old_item.required_by.extend(details_and_required[1])
            else:
                new_item = IndexItemRow(iid=iid, from_require=True,
                                        original_details=details_and_required[0],
                                        required_by=details_and_required[1])
                self.session.add(new_item)
        self.session.commit()
        self.reader.require_items.clear()

    def get_all_index_items(self):
        """
        tested by: TestItemTable.test_??_IndexItemRow_get_item, test_??_empty_tables
        :return: list of all IndexItemRow objects in the db, empty list if none are found
        """
        if "get_all_items" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemRow))
            the_query += lambda q: q.order_by(IndexItemRow.iid)
            self.baked_queries_map["get_all_items"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_items"]
        retVal = the_query(self.session).all()
        return retVal

    def get_index_item(self, iid_to_get):
        """
        tested by: TestItemTable.test_ItemRow_get_item
        :return: IndexItemRow object matching iid_to_get or None
        """
        if "get_index_item" not in self.baked_queries_map:
            the_query = self.bakery(lambda q: q.query(IndexItemRow))
            the_query += lambda q: q.filter(IndexItemRow.iid == bindparam("iid_to_get"))
            self.baked_queries_map["get_index_item"] = the_query
        else:
            the_query = self.baked_queries_map["get_index_item"]
        retVal = the_query(self.session).params(iid_to_get=iid_to_get).first()
        return retVal

    def get_all_iids(self):
        """
        tested by: TestItemTable.test_06_get_all_iids
        :return: list of all iids in the db, empty list if none are found
        """
        if "get_all_iids" not in self.baked_queries_map:
            the_query = self.bakery(lambda q: q.query(IndexItemRow.iid))
            the_query += lambda q: q.order_by(IndexItemRow.iid)
            self.baked_queries_map["get_all_iids"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_iids"]
        retVal = the_query(self.session).all()
        retVal = [m[0] for m in retVal]
        return retVal

    def get_item_by_resolve_status(self, iid_to_get, resolve_status):  # tested by: TestItemTable.test_get_item_by_resolve_status
        # http://stackoverflow.com/questions/29161730/what-is-the-difference-between-one-and-first
        if "get_item_by_resolve_status" not in self.baked_queries_map:
            the_query = self.bakery(lambda q: q.query(IndexItemRow))
            the_query += lambda  q: q.filter(IndexItemRow.iid == bindparam("_iid"),
                                             IndexItemRow.inherit_resolved == bindparam("_resolved"))
            self.baked_queries_map["get_item_by_resolve_status"] = the_query
        else:
            the_query = self.baked_queries_map["get_item_by_resolve_status"]
        retVal = the_query(self.session).params(_iid=iid_to_get, _resolved=resolve_status).first()
        return retVal

    def get_items_by_resolve_status(self, resolve_status):  # tested by: TestItemTable.test_get_items_by_resolve_status
        if "get_items_by_resolve_status" not in self.baked_queries_map:
            the_query = self.bakery(lambda q: q.query(IndexItemRow))
            the_query += lambda  q: q.filter(IndexItemRow.inherit_resolved == bindparam("_resolved"))
            the_query += lambda q: q.order_by(IndexItemRow.iid)
            self.baked_queries_map["get_items_by_resolve_status"] = the_query
        else:
            the_query = self.baked_queries_map["get_items_by_resolve_status"]
        retVal = the_query(self.session).params(_resolved=resolve_status).all()
        return retVal

    def get_original_details_values(self, iid, detail_name):
        if "get_original_details_values" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow.detail_value))
            the_query += lambda q: q.join(IndexItemRow)
            the_query += lambda q: q.filter(IndexItemRow.iid == bindparam('iid'))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name == bindparam('detail_name'))
            the_query += lambda q: q.order_by(IndexItemDetailRow._id)
            self.baked_queries_map["get_original_details_values"] = the_query
        else:
            the_query = self.baked_queries_map["get_original_details_values"]

        retVal = the_query(self.session).params(iid=iid, detail_name=detail_name).all()
        retVal = [m[0] for m in retVal]
        return retVal

    def get_original_details(self, iid=None, detail_name=None, os=None):
        """
        tested by: TestItemTable.test_get_original_details_* functions
        :param iid: get detail for specific iid or all if None
        :param detail_name: get detail with specific name or all names if None
        :param os: get detail for os name or for all oses if None
        :return: list original details in the order they were inserted
        """
        if "get_original_details" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))
            the_query += lambda q: q.join(IndexItemRow)
            the_query += lambda q: q.filter(IndexItemRow.iid.like(bindparam('iid')))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name.like(bindparam('detail_name')))
            the_query += lambda q: q.filter(IndexItemDetailRow.os.like(bindparam('os')))
            the_query += lambda q: q.order_by(IndexItemDetailRow._id)
            self.baked_queries_map["get_original_details"] = the_query
        else:
            the_query = self.baked_queries_map["get_original_details"]

        # params with None are turned to '%'
        params = [iid, detail_name, os]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'
        retVal = the_query(self.session).params(iid=params[0], detail_name=params[1], os=params[2]).all()
        # filter by os, apparently sqlalchemy cannot handle a variable length bindparam
        #retVal = [od for od in retVal if od.os in self._get_for_os]
        return retVal

    def get_details_relations(self):
        q = self.session.query(IndexItemToDetailRelation)
        q.order_by(IndexItemToDetailRelation._id)
        retVal = q.all()
        return retVal

    def view_resolved(self):
        q = self.session.query(IndexItemDetailRow)
        q.join(IndexItemToDetailRelation)
        q.filter(IndexItemRow._id == IndexItemToDetailRelation.item_id, IndexItemDetailRow._id == IndexItemToDetailRelation.detail_id)
        q.order_by(IndexItemRow.iid)
        retVal = q.all()
        return retVal

    def get_resolved_details(self, iid, detail_name=None, os=None):  # tested by: TestItemTable.
        if "get_resolved_details" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))

            the_query += lambda q: q.join(IndexItemToDetailRelation)
            the_query += lambda q: q.filter(IndexItemDetailRow._id == IndexItemToDetailRelation.detail_id)

            the_query += lambda q: q.join(IndexItemRow)
            the_query += lambda q: q.filter(IndexItemRow._id == IndexItemToDetailRelation.item_id)
            the_query += lambda q: q.filter(IndexItemRow.iid == bindparam('iid'))

            the_query += lambda q: q.order_by(IndexItemToDetailRelation._id)
            self.baked_queries_map["get_resolved_details"] = the_query
        else:
            the_query = self.baked_queries_map["get_resolved_details"]


        # params with None are turned to '%'
        params = [detail_name, os]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'
        retVal = the_query(self.session).params(iid=iid).all()
        return retVal

    def get_first_resolved_detail(self, iid, detail_name, default=None):
        if "get_first_resolved_detail" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))

            the_query += lambda q: q.join(IndexItemToDetailRelation)
            the_query += lambda q: q.filter(IndexItemDetailRow._id == IndexItemToDetailRelation.detail_id)
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name == bindparam('detail_name'))

            the_query += lambda q: q.join(IndexItemRow)
            the_query += lambda q: q.filter(IndexItemRow._id == IndexItemToDetailRelation.item_id)
            the_query += lambda q: q.filter(IndexItemRow.iid == bindparam('iid'))

            the_query += lambda q: q.order_by(IndexItemToDetailRelation._id)
            self.baked_queries_map["get_first_resolved_detail"] = the_query
        else:
            the_query = self.baked_queries_map["get_first_resolved_detail"]

        the_detail = the_query(self.session).params(iid=iid, detail_name=detail_name).first()

        if the_detail:
            retVal = the_detail.detail_value
        else:
            retVal = default
        return retVal

    def get_item_to_detail_relations(self):

        # get_all_details: return all items either files dirs or both, used by get_all_index_items()
        if "get_item_to_detail_relations" not in self.baked_queries_map:
            self.baked_queries_map["get_item_to_detail_relations"] = self.bakery(lambda session: session.query(IndexItemToDetailRelation))
            self.baked_queries_map["get_item_to_detail_relations"] += lambda q: q.order_by(IndexItemToDetailRelation.iid)

        retVal = self.baked_queries_map["get_item_to_detail_relations"](self.session).all()
        return retVal

    def get_all_details_for_item(self, iid):
        if "get_all_details_for_item" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))
            the_query += lambda q: q.filter(IndexItemDetailRow.origin_iid == bindparam('iid'))
            the_query += lambda q: q.filter(IndexItemDetailRow.os.in_([bindparam('get_for_os')]))
            the_query += lambda q: q.order_by(IndexItemToDetailRelation._id)
            self.baked_queries_map["get_all_details_for_item"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_details_for_item"]

        retVal = the_query(self.session).params(iid=iid, get_for_os=self._get_for_os).all()
        retVal = [mm[0] for mm in retVal]
        return retVal
        #retVal = the_query(self.session).params(iid=iid, get_for_os=self._get_for_os, detail_name=detail_name).all()
        retVal = [mm[0] for mm in retVal]
        return retVal

    def resolve_item_inheritance(self, item_to_resolve, generation=0):
        # print("-"*generation, " ", item_to_resolve.iid)
        inherit_from = self.get_original_details_values(item_to_resolve.iid, 'inherit')
        if len(inherit_from) > 0:
            for inherit_detail in inherit_from:
                sub_item = self.get_index_item(inherit_detail)
                if not sub_item.inherit_resolved:
                    self.resolve_item_inheritance(sub_item, generation+1)
                detail_rows_for_item = self.get_resolved_details(sub_item.iid)
                new_relation_rows = list()
                for d_r in detail_rows_for_item:
                    if d_r.detail_name not in self.not_inherit_details:
                        new_relation_rows.append(IndexItemToDetailRelation(item_id=item_to_resolve._id, detail_id=d_r._id, generation=generation+1))
                self.session.add_all(new_relation_rows)
        item_to_resolve.inherit_resolved = True

    @utils.timing
    def resolve_inheritance(self):
        items = self.get_all_index_items()
        initial_relations = list()
        for item in items:
            initial_relations.extend([IndexItemToDetailRelation(item_id=item._id, detail_id=detail._id, generation=0) for detail in item.original_details])
        self.session.add_all(initial_relations)
        self.session.commit()

        for item in items:
            if not item.inherit_resolved:
                self.resolve_item_inheritance(item)
        self.session.commit()

    def read_index_node(self, a_node):
        self.reader.read_index_from_yaml(a_node)
        self.insert_index_to_db()

    def read_require_node(self, a_node):
        self.reader.read_index_from_yaml(a_node)
        self.insert_required_to_db()

    def read_yaml_file(self, in_file_path):
        self.reader.read_yaml_file(in_file_path)
        self.insert_index_to_db()

    def repr_item_for_yaml(self, iid):
        item_details = OrderedDict()
        for os_name in self.os_names:
            details_rows = self.get_original_details(iid=iid, os=os_name)
            if len(details_rows) > 0:
                if os_name == "common":
                    work_on_dict = item_details
                else:
                    work_on_dict = item_details[os_name] = OrderedDict()
                for details_row in details_rows:
                    if details_row.detail_name in self.action_types:
                        if 'actions' not in work_on_dict:
                            work_on_dict['actions'] = OrderedDict()
                        if details_row.detail_name not in work_on_dict['actions']:
                            work_on_dict[details_row.detail_name]['actions'] = list()
                        work_on_dict[details_row.detail_name]['actions'].append(details_row.detail_value)
                    else:
                        if details_row.detail_name not in work_on_dict:
                            work_on_dict[details_row.detail_name] = list()
                        work_on_dict[details_row.detail_name].append(details_row.detail_value)
        return item_details

    def repr_for_yaml(self):
        retVal = OrderedDict()
        the_items = self.get_all_index_items()
        for item in the_items:
            retVal[item.iid] = self.repr_item_for_yaml(item.iid)
        return retVal

    @utils.timing
    def versions_report(self):
        retVal = list()
        for item in self.get_all_index_items():
            guid = self.get_first_resolved_detail(item.iid, "guid")
            version = self.get_first_resolved_detail(item.iid, "version")
            require_version = self.get_first_resolved_detail(item.iid, "version_from_require", "_")
            if None not in (guid, version):
                retVal.append((item.iid, guid, require_version, version))
        return retVal

    select_details_for_IID_with_full_details_view = \
    "SELECT iid, detail_name, detail_value FROM full_details_view \
    WHERE detail_name = :d_n AND iid = :iid"

    select_details_for_IID = \
    "SELECT IndexItemRow.iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, IndexItemToDetailRelation.generation FROM IndexItemRow \
     INNER JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id \
     INNER JOIN IndexItemDetailRow \
       ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id \
         AND   IndexItemDetailRow.detail_name = :d_n \
     WHERE IndexItemRow.iid = :iid"

    @utils.timing
    def get_resolved_details_for_iid(self, iid, detail_name):
        retVal = self.session.execute(IndexItemsTable.select_details_for_IID_with_full_details_view, {'d_n': detail_name, 'iid': iid}).fetchall()
        return retVal
