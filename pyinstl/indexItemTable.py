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
from sqlalchemy.orm import state

import utils
from configVar import var_stack
from functools import reduce
from aYaml import YamlReader
from .db_alchemy import create_session, get_engine, IndexItemDetailOperatingSystem, IndexItemRow, IndexItemRequiredRow, IndexItemDetailRow, IndexItemToDetailRelation


class IndexItemsTable(object):
    os_names = {'common': 0, 'Mac': 1, 'Mac32': 2, 'Mac64': 3, 'Win': 4, 'Win32': 5, 'Win64': 6}
    action_types = ('pre_copy', 'pre_copy_to_folder', 'pre_copy_item',
                    'post_copy_item', 'post_copy_to_folder', 'post_copy',
                    'pre_remove', 'pre_remove_from_folder', 'pre_remove_item',
                    'remove_item', 'post_remove_item', 'post_remove_from_folder',
                    'post_remove', 'pre_doit', 'doit', 'post_doit')
    not_inherit_details = ("name", "inherit")

    def __init__(self):
        self.session = create_session()
        self.clear_tables()
        self.os_names_db_objs = list()
        self.add_default_tables()
        self.add_views()
        #inspector = reflection.Inspector.from_engine(get_engine())
        #print("Tables:", inspector.get_table_names())
        #print("Views:", inspector.get_view_names())
        self.baked_queries_map = self.bake_baked_queries()
        self.bakery = baked.bakery()

    def clear_tables(self):
        #print(get_engine().table_names())
        self.session.query(IndexItemDetailOperatingSystem).delete()
        self.session.query(IndexItemToDetailRelation).delete()
        self.session.query(IndexItemDetailRow).delete()
        self.session.query(IndexItemRow).delete()
        self.session.query(IndexItemRequiredRow).delete()
        self.drop_views()
        self.session.commit()

    def add_default_tables(self):

        for os_name, _id in IndexItemsTable.os_names.items():
            new_item = IndexItemDetailOperatingSystem(_id=_id, name=os_name, active=False)
            self.os_names_db_objs.append(new_item)
        self.session.add_all(self.os_names_db_objs)

    def add_views(self):
        stmt = text("""
          CREATE VIEW "full_details_view" AS
          SELECT IndexItemRow.iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, IndexItemDetailOperatingSystem.name AS "os",IndexItemToDetailRelation.generation FROM IndexItemRow
          LEFT JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id
          LEFT JOIN IndexItemDetailRow ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id
          LEFT JOIN IndexItemDetailOperatingSystem ON IndexItemDetailOperatingSystem._id = IndexItemDetailRow.os_id
          """)
        self.session.execute(stmt)

        stmt = text("""
          CREATE VIEW "original_details_view" AS
          SELECT IndexItemRow.iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, IndexItemDetailOperatingSystem.name  AS "os" FROM IndexItemRow
          LEFT JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id
                  AND IndexItemToDetailRelation.generation = 0
          LEFT JOIN IndexItemDetailRow ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id
           LEFT JOIN IndexItemDetailOperatingSystem ON IndexItemDetailOperatingSystem._id = IndexItemDetailRow.os_id
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
        for os_name_obj in self.os_names_db_objs:
            os_name_obj.active = True

    def reset_get_for_all_oses(self):
        """ resets the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        for os_name_obj in self.os_names_db_objs:
            if os_name_obj.name == "common":
                os_name_obj.active = True
            else:
                os_name_obj.active = False

    def begin_get_for_specific_oses(self, *for_oses):
        """ adds another os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
        """
        for_oses = *for_oses, "common",
        for os_name_obj in self.os_names_db_objs:
            if os_name_obj.name in for_oses:
                os_name_obj.active = True
            else:
                os_name_obj.active = False

    def end_get_for_specific_os(self):
        """ removed the last added os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
             This is a static method so it will influence all InstallItem objects.
        """
        self.reset_get_for_all_oses()

    def bake_baked_queries(self):
        """ prepare baked queries for later use
        """
        retVal = dict()

        # all queries are now baked just-in-time

        return retVal

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

    def get_all_iids_with_guids(self):
        """
        :return: list of all iids in the db that have guids, empty list if none are found
        """
        if "get_all_iids_with_guids" not in self.baked_queries_map:
            the_query = self.bakery(lambda q: q.query(IndexItemRow.iid))
            the_query += lambda q: q.join(IndexItemDetailRow)
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name == 'guid')
            the_query += lambda q: q.order_by(IndexItemRow.iid)
            self.baked_queries_map["get_all_iids_with_guids"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_iids_with_guids"]
        retVal = the_query(self.session).all()
        retVal = [m[0] for m in retVal]
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

    def create_default_items(self):
        all_items_item = IndexItemRow(iid="__ALL_ITEMS_IID__", inherit_resolved=True, from_index=False)
        all_items_item.original_details = [IndexItemDetailRow(os_id=0, detail_name='depends', detail_value=iid) for iid in self.get_all_iids()]
        self.session.add(all_items_item)

        all_guids_item = IndexItemRow(iid="__ALL_GUIDS_IID__", inherit_resolved=True, from_index=False)
        all_guids_item.original_details = [IndexItemDetailRow(os_id=0, detail_name='depends', detail_value=iid) for iid in self.get_all_iids_with_guids()]
        self.session.add(all_guids_item)

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
            the_query += lambda q: q.join(IndexItemDetailOperatingSystem)
            the_query += lambda q: q.filter(IndexItemDetailOperatingSystem._id == IndexItemDetailRow.os_id, IndexItemDetailOperatingSystem.active == True)
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
            the_query += lambda q: q.filter(IndexItemDetailRow.os_id.like(bindparam('os')))
            the_query += lambda q: q.order_by(IndexItemDetailRow._id)
            self.baked_queries_map["get_original_details"] = the_query
        else:
            the_query = self.baked_queries_map["get_original_details"]

        # params with None are turned to '%'
        params = [iid, detail_name, os]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'
        retVal = the_query(self.session).params(iid=params[0], detail_name=params[1], os=params[2]).all()
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

        for item in items:
            if not item.inherit_resolved:
                self.resolve_item_inheritance(item)

    def item_from_index_node(self, the_iid, the_node):
        item = IndexItemRow(iid=the_iid, inherit_resolved=False, from_index=True)
        item.original_details = self.read_item_details_from_node(the_iid, the_node)
        return item

    def read_item_details_from_node(self, the_iid, the_node, the_os='common'):
        details = list()
        for detail_name in the_node:
            if detail_name in IndexItemsTable.os_names:
                os_specific_details = self.read_item_details_from_node(the_iid, the_node[detail_name], the_os=detail_name)
                details.extend(os_specific_details)
            elif detail_name == 'actions':
                actions_details = self.read_item_details_from_node(the_iid, the_node['actions'], the_os)
                details.extend(actions_details)
            else:
                for details_line in the_node[detail_name]:
                    new_detail = IndexItemDetailRow(os_id=self.os_names[the_os], detail_name=detail_name, detail_value=details_line.value)
                    details.append(new_detail)
        return details

    def read_index_node(self, a_node):
        index_items = list()
        for IID in a_node:
            item = self.item_from_index_node(IID, a_node[IID])
            index_items.append(item)
        for item in index_items:
            self.session.add(item)
        self.create_default_items()

    def read_require_node(self, a_node):
        for IID in a_node:
            self.read_item_details_from_require_node(IID, a_node[IID])
        self.insert_required_to_db()

    def read_item_details_from_require_node(self, the_iid, the_node):
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
                for required_by in the_node["required_by"]:
                    required_by.append(IndexItemRequiredRow(owner_item_id=the_iid, required_by_iid=required_by.value))
        self.require_items[the_iid] = details, required_by

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

    @utils.timing
    def iids_from_guids(self, guid_or_iid_list):
        query_vars = '("'+'","'.join(guid_or_iid_list)+'")'
        query_text = """
          SELECT DISTINCT iid, detail_value FROM full_details_view
            WHERE detail_name = "guid" AND detail_value in {0}
            AND generation = 0
        """.format(query_vars)

        # query will return list of (iid, guid)'s
        ret_list = self.session.execute(query_text).fetchall()
        returned_iids, returned_guids = zip(*ret_list)
        orphaned_guids = list(set(guid_or_iid_list)-set(returned_guids))

        return returned_iids, orphaned_guids

    # find which iids are in the database
    def iids_from_iids(self, iid_list):
        query_vars = '("'+'","'.join(iid_list)+'")'
        query_text = """
            SELECT iid
            FROM IndexItemRow
            WHERE iid IN {0}
        """.format(query_vars)

        # query will return list those iid in iid_list that were found in the index
        existing_iids = [iid[0] for iid in self.session.execute(query_text).fetchall()]
        orphan_iids = list(set(iid_list)-set(existing_iids))

        return existing_iids, orphan_iids

    def calculate_all_items(self, main_install_targets):
        query_vars = "('" + "'), ('".join(main_install_targets) + "')"
        query_text = """
    WITH RECURSIVE depends_on_temp_query(iid) AS (
        VALUES {0}
        UNION
        SELECT
            IndexItemDetailRow.detail_value

        FROM IndexItemRow
            INNER JOIN depends_on_temp_query ON IndexItemRow.iid = depends_on_temp_query.iid
            INNER JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id
            INNER JOIN IndexItemDetailRow ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id AND IndexItemDetailRow.detail_name = 'depends'
            INNER JOIN IndexItemDetailOperatingSystem ON IndexItemDetailRow.os_id = IndexItemDetailOperatingSystem._id AND IndexItemDetailOperatingSystem.active = 1
        )
    SELECT * FROM depends_on_temp_query ORDER BY depends_on_temp_query.iid
""".format(query_vars)

        retVal = self.session.execute(query_text).fetchall()
        retVal = [mm[0] for mm in retVal]
        return retVal
