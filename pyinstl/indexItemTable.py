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
from .db_alchemy import create_session, get_engine, IndexItemDetailOperatingSystem, IndexItemRow, IndexItemDetailRow, IndexGuidToItemTranslate


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
        self.add_default_values()
        self.add_triggers()
        self.add_views()
        #inspector = reflection.Inspector.from_engine(get_engine())
        #print("Tables:", inspector.get_table_names())
        #print("Views:", inspector.get_view_names())
        self.baked_queries_map = self.bake_baked_queries()
        self.bakery = baked.bakery()

    def finished_using_db(self):
        if not getattr(sys, 'frozen', False):
            self.session.commit()

    def clear_tables(self):
        #print(get_engine().table_names())
        self.drop_triggers()
        self.drop_views()
        self.session.query(IndexItemDetailOperatingSystem).delete()
        self.session.query(IndexItemDetailRow).delete()
        self.session.query(IndexItemRow).delete()
        self.session.commit()

    def add_default_values(self):

        for os_name, _id in IndexItemsTable.os_names.items():
            new_item = IndexItemDetailOperatingSystem(_id=_id, name=os_name, active=False)
            self.os_names_db_objs.append(new_item)
        self.session.add_all(self.os_names_db_objs)

    def add_triggers(self):
        return  # no triggers currently defined, below is an old one for reference
        stmt = text("""
            CREATE TRIGGER IF NOT EXISTS CreateRelationOnNewDetail
                AFTER INSERT ON IndexItemDetailRow
            BEGIN
                INSERT INTO IndexItemToDetailRelation (detail_id, generation, item_id)
                VALUES (NEW._id,  0, NEW.owner_item_id);
            END;
        """)
        self.session.execute(stmt)

    def drop_triggers(self):
        stmt = text("""
            DROP TRIGGER IF EXISTS "CreateRelationOnNewDetail"
            """)
        self.session.execute(stmt)

    def add_views(self):#!
        stmt = text("""
           CREATE VIEW "full_details_view" AS
            SELECT IndexItemDetailRow._id,
                IndexItemDetailRow.owner_iid AS "owner iid",
                IndexItemDetailRow.original_iid AS "original iid",
                IndexItemDetailRow.detail_name,
                IndexItemDetailRow.detail_value,
                IndexItemDetailOperatingSystem.name  AS "os"
            FROM IndexItemDetailRow
            LEFT JOIN IndexItemDetailOperatingSystem ON IndexItemDetailOperatingSystem._id = IndexItemDetailRow.os_id
          """)
        self.session.execute(stmt)

        stmt = text("""
            CREATE VIEW "original_details_view" AS
            SELECT IndexItemDetailRow._id,
                IndexItemDetailRow.original_iid AS "iid",
                IndexItemDetailRow.detail_name,
                IndexItemDetailRow.detail_value,
                IndexItemDetailOperatingSystem.name  AS "os"
            FROM IndexItemDetailRow
            LEFT JOIN IndexItemDetailOperatingSystem ON IndexItemDetailOperatingSystem._id = IndexItemDetailRow.os_id
            WHERE IndexItemDetailRow.original_iid == IndexItemDetailRow.owner_iid
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

    def insert_require_to_db(self, require_items):
        for iid, details in require_items.items():
            old_item = self.get_index_item(iid)
            if old_item is not None:
                old_item.from_require = True
                self.session.add_all(details)
            else:
                print(iid, "found in require but not in index")

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
            the_query += lambda q: q.join(IndexItemDetailRow, IndexItemDetailRow.owner_iid==IndexItemRow.iid)
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name == 'guid')
            the_query += lambda q: q.order_by(IndexItemRow.iid)
            self.baked_queries_map["get_all_iids_with_guids"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_iids_with_guids"]
        retVal = the_query(self.session).all()
        retVal = [m[0] for m in retVal]
        return retVal

    def get_all_installed_iids(self):
        """
        :return: list of all iids in the db that have guids, empty list if none are found
        """
        if "get_all_installed_iids" not in self.baked_queries_map:
            the_query = self.bakery(lambda q: q.query(IndexItemDetailRow.original_iid))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name == "require_by",
                                            IndexItemDetailRow.detail_value == IndexItemDetailRow.original_iid)
            self.baked_queries_map["get_all_installed_iids"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_installed_iids"]
        retVal = the_query(self.session).all()
        retVal = [m[0] for m in retVal]
        return retVal

    def get_all_installed_iids_needing_update(self):
        """ Return all iids that were installed, have a version, and that version is different from the version in the index
        """
        query_text = """
                SELECT require_version.owner_iid, require_version.detail_value AS require, remote_version.detail_value AS remote
                FROM IndexItemDetailRow AS require_version
                LEFT JOIN (
                    select owner_iid, detail_value, min(generation)
                    from IndexItemDetailRow AS remote_version
                      INNER JOIN IndexItemDetailOperatingSystem
                          ON IndexItemDetailOperatingSystem._id = remote_version.os_id
                              AND IndexItemDetailOperatingSystem.active = 1
                    WHERE detail_name="version"
                    GROUP BY owner_iid
                    ) remote_version
                WHERE detail_name="require_version"
                      AND remote_version.owner_iid=require_version.owner_iid
                      AND require_version.detail_value!=remote_version.detail_value
            """

        retVal = self.session.execute(query_text).fetchall()
        retVal = [mm[0] for mm in retVal]
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

    def create_default_index_items(self):
        the_os_id = self.os_names['common']
        the_iid = "__ALL_ITEMS_IID__"
        all_items_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        depends_details = [IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid,
                                              detail_name='depends', detail_value=iid,
                                              os_id=the_os_id, generation=0) for iid in self.get_all_iids()]
        self.session.add(all_items_item)
        self.session.add_all(depends_details)

        the_iid = "__ALL_GUIDS_IID__"
        all_guids_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        depends_details = [IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid,
                                              detail_name='depends', detail_value=iid,
                                              os_id=the_os_id, generation=0) for iid in self.get_all_iids_with_guids()]
        self.session.add(all_guids_item)
        self.session.add_all(depends_details)

    def create_default_require_items(self):
        the_os_id = self.os_names['common']
        the_iid = "__REPAIR_INSTALLED_ITEMS__"
        repair_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        repair_item_details = [IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid,
                                                  detail_name='depends', detail_value=iid,
                                                  os_id=the_os_id, generation=0) for iid in self.get_all_installed_iids()]
        self.session.add(repair_item)
        self.session.add_all(repair_item_details)

        the_iid = "__UPDATE_INSTALLED_ITEMS__"
        update_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        update_item_details = [IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid,
                                                  detail_name='depends', detail_value=iid,
                                                  os_id=the_os_id, generation=0) for iid in self.get_all_installed_iids_needing_update()]
        self.session.add(update_item)
        self.session.add_all(update_item_details)

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
            the_query += lambda q: q.filter(IndexItemDetailRow.original_iid == bindparam('iid'))
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

    def get_details_relations(self):#!
        q = self.session.query(IndexItemToDetailRelation)
        q.order_by(IndexItemToDetailRelation._id)
        retVal = q.all()
        return retVal

    def view_resolved(self):#!
        q = self.session.query(IndexItemDetailRow)
        q.join(IndexItemToDetailRelation)
        q.filter(IndexItemRow._id == IndexItemToDetailRelation.item_id, IndexItemDetailRow._id == IndexItemToDetailRelation.detail_id)
        q.order_by(IndexItemRow.iid)
        retVal = q.all()
        return retVal

    def get_resolved_details(self, iid, detail_name=None, os=None):#!  # tested by: TestItemTable.
        if "get_resolved_details" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))
            the_query += lambda q: q.filter(IndexItemDetailRow.owner_iid == bindparam('iid'))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name.like(bindparam('detail_name')))
            the_query += lambda q: q.join(IndexItemDetailOperatingSystem)
            the_query += lambda q: q.filter(IndexItemDetailRow.os_id == IndexItemDetailOperatingSystem._id)
            the_query += lambda q: q.filter(IndexItemDetailOperatingSystem.active == True)
            the_query += lambda q: q.order_by(IndexItemDetailRow._id)
            self.baked_queries_map["get_resolved_details"] = the_query
        else:
            the_query = self.baked_queries_map["get_resolved_details"]


        # params with None are turned to '%'
        params = [detail_name]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'
        retVal = the_query(self.session).params(iid=iid, detail_name=params[0]).all()
        return retVal

    def get_first_resolved_detail(self, iid, detail_name, default=None):#!
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

    def resolve_item_inheritance(self, item_to_resolve, generation=0):
        # print("-"*generation, " ", item_to_resolve.iid)
        iids_to_inherit_from = self.get_original_details_values(item_to_resolve.iid, 'inherit')
        for original_iid in iids_to_inherit_from:
            sub_item = self.get_index_item(original_iid)
            if not sub_item.inherit_resolved:
                self.resolve_item_inheritance(sub_item, 0)
            details_of_inherited_item = self.get_resolved_details(sub_item.iid)
            for d_of_ii in details_of_inherited_item:
                if d_of_ii.detail_name not in self.not_inherit_details:
                    inherited_detail = IndexItemDetailRow(original_iid=d_of_ii.original_iid, owner_iid=item_to_resolve.iid, os_id=d_of_ii.os_id, detail_name=d_of_ii.detail_name, detail_value=d_of_ii.detail_value, generation=d_of_ii.generation+1)
                    self.session.add(inherited_detail)
        item_to_resolve.inherit_resolved = True

    #@utils.timing
    def resolve_inheritance(self):
        items = self.get_all_index_items()
        for item in items:
            if not item.inherit_resolved:
                self.resolve_item_inheritance(item)

    def item_from_index_node(self, the_iid, the_node):
        item = IndexItemRow(iid=the_iid, inherit_resolved=False, from_index=True)
        original_details = self.read_item_details_from_node(the_iid, the_node)
        return item, original_details

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
                    tag = details_line.tag if details_line.tag[0]=='!' else None
                    if detail_name == "install_sources" and tag is None:
                        tag = '!dir'
                    new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=self.os_names[the_os], detail_name=detail_name, detail_value=details_line.value, generation=0, tag=tag)
                    details.append(new_detail)
        return details

    #@utils.timing
    def read_index_node(self, a_node):
        index_items = list()
        original_details = list()
        for IID in a_node:
            item, original_item_details = self.item_from_index_node(IID, a_node[IID])
            index_items.append(item)
            original_details.extend(original_item_details)
        self.session.add_all(index_items)
        self.session.add_all(original_details)
        self.create_default_index_items()

    #@utils.timing
    def read_require_node(self, a_node):
        require_items = dict()
        if a_node.isMapping():
            for IID in a_node:
                require_details = self.read_item_details_from_require_node(IID, a_node[IID])
                if require_details:
                    require_items[IID] = require_details
            self.insert_require_to_db(require_items)
            self.create_default_require_items()

    def read_item_details_from_require_node(self, the_iid, the_node):
        os_id=self.os_names['common']
        details = list()
        for detail_name in the_node:
            if detail_name == "guid":
                new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name="require_guid", detail_value=the_node["guid"].value)
                details.append(new_detail)
            elif detail_name == "version":
                new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name="require_version", detail_value=the_node["version"].value)
                details.append(new_detail)
            elif detail_name == "required_by":
                for require_by in the_node["required_by"]:
                   details.append(IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name="require_by", detail_value=require_by.value))
        return details

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

    #@utils.timing
    def versions_report(self):
        query_text = """
            SELECT
                remote.owner_iid, item_guid.detail_value AS guid, coalesce(require_version.detail_value, "_") AS 'require ver', remote.detail_value AS 'remote ver', min(remote.generation)
            FROM IndexItemDetailRow AS remote

            JOIN IndexItemDetailOperatingSystem
                ON IndexItemDetailOperatingSystem._id = remote.os_id
                    AND IndexItemDetailOperatingSystem.active = 1
            LEFT  JOIN IndexItemDetailRow as require_version
                ON  require_version.detail_name = 'require_version'
                AND require_version.owner_iid=remote.owner_iid
            JOIN IndexItemDetailRow as item_guid
                ON  item_guid.detail_name = 'guid'
                AND item_guid.owner_iid=remote.owner_iid
            WHERE
                remote.detail_name = 'version'
            GROUP BY remote.owner_iid
        """

        retVal = self.session.execute(query_text).fetchall()
        retVal = [mm[:4] for mm in retVal]
        return retVal

    select_details_for_IID_with_full_details_view = \
    "SELECT iid, detail_name, detail_value FROM full_details_view \
    WHERE detail_name = :d_n AND iid = :iid"

    #!
    select_details_for_IID = \
    "SELECT IndexItemRow.iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, IndexItemToDetailRelation.generation FROM IndexItemRow \
     INNER JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id \
     INNER JOIN IndexItemDetailRow \
       ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id \
         AND   IndexItemDetailRow.detail_name = :d_n \
     WHERE IndexItemRow.iid = :iid"

    #@utils.timing
    def get_resolved_details_for_iid(self, iid, detail_name):
        retVal = self.session.execute(IndexItemsTable.select_details_for_IID_with_full_details_view, {'d_n': detail_name, 'iid': iid}).fetchall()
        return retVal

    #@utils.timing
    def iids_from_guids(self, guid_or_iid_list):
        returned_iids = list()
        orphaned_guids = list()
        if guid_or_iid_list:
            query_vars = '("'+'","'.join(guid_or_iid_list)+'")'
            query_text = """
              SELECT DISTINCT owner_iid, detail_value FROM IndexItemDetailRow
                WHERE detail_name = "guid" AND detail_value in {0}
            """.format(query_vars)

            # query will return list of (iid, guid)'s
            ret_list = self.session.execute(query_text).fetchall()
            returned_guids = list()
            if len(ret_list) > 0:
                returned_iids, returned_guids = zip(*ret_list)
            orphaned_guids = list(set(guid_or_iid_list)-set(returned_guids))

        return returned_iids, orphaned_guids

    def activate_iids(self, iid_list, status_value=None):
        """ update the status field of the iids in the list.
            if status_value is not None this exact value will be used,
            otherwise the status field will be incremented.
        """
        if iid_list:
            status_set_value = "status+1"
            if status_value is not None:
                status_set_value=str(status_value)
            query_vars = '("'+'","'.join(iid_list)+'")'
            query_text = """
                UPDATE IndexItemRow
                SET status={0}
                WHERE iid IN {1}
            """.format(status_set_value, query_vars)

            self.session.execute(query_text)

    def activate_guids(self, guid_list, status_value=None):
        """ update the status field of the iids who's guid is in the list.
            if status_value is not None this exact value will be used,
            otherwise the status field will be incremented.
        """
        if guid_list:
            status_set_value = "status+1"
            if status_value is not None:
                status_set_value=str(status_value)
            query_vars = '("'+'","'.join(guid_list)+'")'
            query_text = """
                UPDATE IndexItemRow
                SET status={0}
                WHERE iid IN (
                    SELECT owner_iid
                    FROM IndexItemDetailRow
                    WHERE detail_name="guid"
                    AND detail_value in {1}
                    )
             """.format(status_set_value, query_vars)

            self.session.execute(query_text)

    def activate_direct_dependencies(self, depends_of_list, status_value=None):
        """ update the status field of the iids who are direct dependants of the iids in the list.
            if status_value is not None this exact value will be used,
            otherwise the status field will be incremented.
        """
        if depends_of_list:
            status_set_value = "status+1"
            if status_value is not None:
                status_set_value=str(status_value)
            query_vars = '("'+'","'.join(depends_of_list)+'")'
            query_text = """
                UPDATE IndexItemRow
                SET status={0}
                WHERE iid IN (
                    SELECT detail_value
                    FROM IndexItemDetailRow
                    WHERE detail_name="depends"
                    AND owner_iid in {1}
                )
            """.format(status_set_value, query_vars)

            self.session.execute(query_text)


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

    def get_recursive_dependencies(self):
        retVal = list()
        query_text = """
            WITH RECURSIVE find_dependants(_IID_) AS
            (
            SELECT iid FROM IndexItemRow WHERE status=1
            UNION

            SELECT IndexItemDetailRow.detail_value
            FROM IndexItemDetailRow, find_dependants
                 INNER JOIN IndexItemDetailOperatingSystem ON
                 IndexItemDetailRow.os_id = IndexItemDetailOperatingSystem._id
                    AND
                    IndexItemDetailOperatingSystem.active = 1
            WHERE
                IndexItemDetailRow.detail_name = 'depends'
            AND
                IndexItemDetailRow.owner_iid = find_dependants._IID_
            )
            SELECT _IID_ FROM find_dependants
        """.format()

        retVal = self.session.execute(query_text).fetchall()
        retVal = [mm[0] for mm in retVal]
        return retVal

    def change_items_status(self, old_status, new_status, iid_list):
        if iid_list:
            query_vars = '("'+'","'.join(iid_list)+'")'
            query_text = """
                UPDATE IndexItemRow
                SET status={new_status}
                WHERE status={old_status}
                AND iid IN {query_vars}
            """.format(**locals())

            self.session.execute(query_text)
        
    def translate_guids_to_iids(self, guid_list):
        guid_list = 'dae7bc2a-a257-440f-8ca7-f5ce1d999329', 'e8f6b97d-ad21-11e0-8088-b7fd7bebd530', 'e8f6b97d-ad21-11e0-8088-b7fd7bebdddd'
        for a_guid in guid_list:
            self.session.add(IndexGuidToItemTranslate(guid=a_guid))
        self.session.flush()

        query_text = """
            INSERT INTO IndexGuidToItemTranslate(guid, iid)
            SELECT IndexItemDetailRow.detail_value, IndexItemDetailRow.owner_iid
            FROM IndexItemDetailRow
            WHERE
                IndexItemDetailRow.detail_name='guid'
                AND IndexItemDetailRow.detail_value IN (SELECT guid FROM IndexGuidToItemTranslate WHERE iid IS NULL);
            """
        in_ret = self.session.execute(query_text)
        print("in_ret:", in_ret)
        self.session.flush()

        all_guids = self.session.query(IndexGuidToItemTranslate).order_by('guid').all()
        print("all_guids:\n", "\n".join([str(a_guid) for a_guid in all_guids]))

        query_text = """
            SELECT guid, count(guid) FROM IndexGuidToItemTranslate
            GROUP BY guid;
            """
        count_guids = self.session.execute(query_text).fetchall()
        print("count_guids:", count_guids)
