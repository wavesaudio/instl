#!/usr/bin/env python3


import os
from collections import OrderedDict

from sqlalchemy.ext import baked
from sqlalchemy import bindparam
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db_alchemy import create_session,\
    IndexItemDetailOperatingSystem, \
    IndexItemRow, \
    IndexItemDetailRow, \
    IndexGuidToItemTranslate, \
    IndexRequireTranslate, \
    FoundOnDiskItemRow

import utils


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
        # inspector = reflection.Inspector.from_engine(get_engine())
        # print("Tables:", inspector.get_table_names())
        # print("Views:", inspector.get_view_names())
        self.baked_queries_map = self.bake_baked_queries()
        self.bakery = baked.bakery()

    def commit_changes(self):
        self.session.commit()

    def clear_tables(self):
        # print(get_engine().table_names())
        self.drop_triggers()
        self.drop_views()
        self.session.query(IndexRequireTranslate).delete()
        self.session.query(IndexItemDetailOperatingSystem).delete()
        self.session.query(IndexItemDetailRow).delete()
        self.session.query(IndexItemRow).delete()
        self.commit_changes()

    def add_default_values(self):

        for os_name, _id in IndexItemsTable.os_names.items():
            new_item = IndexItemDetailOperatingSystem(_id=_id, name=os_name, active=False)
            self.os_names_db_objs.append(new_item)
        self.session.add_all(self.os_names_db_objs)

    def add_triggers(self):
        # item found on disk that has a guid. This trigger will find the IID
        # for that guid in IndexItemDetailRow and update the FoundOnDiskItemRow row
        stmt = """
            CREATE TRIGGER IF NOT EXISTS add_iid_to_FoundOnDiskItemRow_guid_not_null
            AFTER INSERT ON FoundOnDiskItemRow
                WHEN(NEW.guid IS NOT NULL)
            BEGIN
                UPDATE FoundOnDiskItemRow
                SET iid  = (
                    SELECT name_item_t.owner_iid
                    FROM IndexItemDetailRow AS guid_item_t
                      JOIN IndexItemDetailRow AS name_item_t
                        ON name_item_t.detail_name='install_sources'
                        AND name_item_t.detail_value LIKE '%' || NEW.name
                        AND name_item_t.owner_iid=guid_item_t.owner_iid
                    WHERE guid_item_t.detail_name='guid'
                      AND guid_item_t.detail_value=NEW.guid)
               WHERE FoundOnDiskItemRow._id=NEW._id;
            END;
        """
        self.session.execute(stmt)

        # item found on disk that has no guid. This trigger will find the IID
        # for that  in IndexItemDetailRow by comparing the file's name and update the FoundOnDiskItemRow row
        stmt = """
            CREATE TRIGGER IF NOT EXISTS add_iid_to_FoundOnDiskItemRow_guid_is_null
            AFTER INSERT ON FoundOnDiskItemRow
                WHEN NEW.guid IS NULL
            BEGIN
                UPDATE OR IGNORE FoundOnDiskItemRow
                SET iid  = (
                    SELECT IndexItemDetailRow.owner_iid
                    FROM IndexItemDetailRow
                    WHERE detail_name='install_sources'
                    AND detail_value LIKE '%' || NEW.name)
               WHERE FoundOnDiskItemRow._id=NEW._id;
            END;
        """
        self.session.execute(stmt)

        # when reading "require_by" detail, add to IndexRequireTranslate table
        stmt = """
            CREATE TRIGGER IF NOT EXISTS translate_require_by_trigger
                AFTER INSERT ON IndexItemDetailRow
                WHEN NEW.detail_name="require_by"
            BEGIN
                INSERT OR IGNORE INTO IndexRequireTranslate (iid, require_by, status)
                VALUES (NEW.owner_iid,  NEW.detail_value, 0);
            END;
        """
        self.session.execute(stmt)

        # when changing the status of item to install, adjust item's require_XXX details
        trigger_text = """
            CREATE TRIGGER create_require_for_installed_iids_trigger
            AFTER UPDATE OF status ON IndexItemRow
            WHEN NEW.status > 0
            BEGIN

            -- remove previous require_by NEW.iid
            DELETE FROM IndexItemDetailRow
            WHERE detail_name = "require_by"
            AND detail_value = NEW.iid;

            -- remove previous require_version, require_guid owned NEW.iid
            DELETE FROM IndexItemDetailRow
            WHERE owner_iid = NEW.iid
            AND detail_name IN ("require_version", "require_guid");

            -- add require_version
            INSERT INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
            SELECT original_iid, owner_iid, os_id, 'require_version', detail_value, min(generation)
            FROM IndexItemDetailRow
            WHERE owner_iid  = NEW.iid
            AND active = 1
            AND detail_name='version'
            GROUP BY owner_iid;

            -- add require_guid
            INSERT INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
            SELECT original_iid, owner_iid, os_id, 'require_guid', detail_value, min(generation)
            FROM IndexItemDetailRow
            WHERE IndexItemDetailRow.owner_iid = NEW.iid
            AND active = 1
            AND detail_name='guid'
            GROUP BY owner_iid;

            -- self-referenced require_by for main install iids which are marked by status 1
            INSERT INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
            SELECT NEW.iid, NEW.iid, 0, 'require_by', NEW.iid, 0
            WHERE NEW.status=1;

            -- require_by for all install iids
            INSERT INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
            SELECT original_iid, detail_value, os_id, 'require_by', NEW.iid, generation
            FROM IndexItemDetailRow
            WHERE IndexItemDetailRow.owner_iid = NEW.iid
            AND active = 1
            AND detail_name='depends';

            END;
        """
        self.session.execute(trigger_text)

        # when changing the status of item to uninstall, remove item's require_XXX details
        trigger_text = """
            CREATE TRIGGER remove_require_for_uninstalled_iids_trigger
            AFTER UPDATE OF status ON IndexItemRow
            WHEN NEW.status < 0
            BEGIN
                DELETE FROM IndexItemDetailRow
                WHERE IndexItemDetailRow.owner_iid=NEW.iid
                AND IndexItemDetailRow.detail_name LIKE "req%";

                DELETE FROM IndexItemDetailRow
                WHERE IndexItemDetailRow.detail_value=NEW.iid
                AND IndexItemDetailRow.detail_name = "require_by";
            END;
        """
        self.session.execute(trigger_text)

        # when an os becomes active/de-active set all details accordingly
        trigger_text = """
            CREATE TRIGGER adjust_active_os_for_details
            AFTER UPDATE OF active ON IndexItemDetailOperatingSystem
            BEGIN
                UPDATE IndexItemDetailRow
                SET    active =  NEW.active
                WHERE  IndexItemDetailRow.os_id = NEW._id;
            END;
        """
        self.session.execute(trigger_text)

        # when adding new detail set it's active state according to os
        trigger_text = """
            CREATE TRIGGER set_active_os_for_details
            AFTER INSERT ON IndexItemDetailRow
            BEGIN
                 UPDATE IndexItemDetailRow
                 SET active = (SELECT IndexItemDetailOperatingSystem.active
                                FROM IndexItemDetailOperatingSystem
                                WHERE IndexItemDetailOperatingSystem._id=NEW.os_id)
                 WHERE IndexItemDetailRow._id = NEW._id;
            END;
        """
        self.session.execute(trigger_text)

    def drop_triggers(self):
        stmt = """
            DROP TRIGGER IF EXISTS translate_require_by_trigger;
            """
        self.session.execute(stmt)
        stmt = """
            DROP TRIGGER IF EXISTS create_require_for_installed_iids_trigger;
            """
        self.session.execute(stmt)
        stmt = """
            DROP TRIGGER IF EXISTS remove_require_for_uninstalled_iids_trigger;
            """
        self.session.execute(stmt)
        stmt = """
            DROP TRIGGER IF EXISTS adjust_active_os_for_details;
            """
        self.session.execute(stmt)
        stmt = """
            DROP TRIGGER IF EXISTS set_active_os_for_details;
            """
        self.session.execute(stmt)

        stmt = """
            DROP TRIGGER IF EXISTS add_iid_to_FoundOnDiskItemRow_guid_not_null;
            """
        self.session.execute(stmt)
        stmt = """
            DROP TRIGGER IF EXISTS add_iid_to_FoundOnDiskItemRow_guid_is_null;
            """
        self.session.execute(stmt)

    def add_views(self):
        # view of items from require.yaml that do not have a require_version field
        stmt = text("""
        -- iid, index_version, generation
        CREATE VIEW "require_items_without_require_version_view" AS
        SELECT main_details_t.owner_iid AS iid,
            main_details_t.detail_value AS index_version,
            min(main_details_t.generation) AS generation
        FROM IndexItemDetailRow AS main_details_t
            JOIN IndexItemRow AS main_item_t
            ON main_item_t.iid=main_details_t.owner_iid
            AND main_item_t.from_require=1
            LEFT JOIN IndexItemDetailRow AS no_require_version_t
            ON no_require_version_t.detail_name='require_version'
            AND main_details_t.owner_iid=no_require_version_t.owner_iid
        WHERE main_details_t.detail_name='version'
            AND no_require_version_t.detail_value ISNULL
            AND main_details_t.active=1
        GROUP BY (main_details_t.owner_iid)
        """)
        self.session.execute(stmt)

        # view of items from require.yaml that do not have a require_guid field
        stmt = text("""
        CREATE VIEW "require_items_without_require_guid_view" AS
        SELECT
            main_details_t.owner_iid       AS iid,
            main_details_t.detail_value    AS index_guid,
            min(main_details_t.generation) AS generation
        FROM IndexItemDetailRow AS main_details_t
            JOIN IndexItemRow AS main_item_t
                ON main_item_t.iid = main_details_t.owner_iid
                   AND main_item_t.from_require = 1
            LEFT JOIN IndexItemDetailRow AS no_guid_version_t
                ON no_guid_version_t.detail_name = 'require_guid'
                AND main_details_t.owner_iid=no_guid_version_t.owner_iid
        WHERE main_details_t.detail_name='guid'
        AND no_guid_version_t.detail_value ISNULL
        AND main_details_t.active=1
        GROUP BY (main_details_t.owner_iid)
         """)
        self.session.execute(stmt)

        # the final report-versions view
        stmt = text("""
        CREATE VIEW "report_versions_view" AS
            SELECT
                  coalesce(remote.owner_iid, "_") AS owner_iid,
                  coalesce(item_guid.detail_value, "_") AS guid,
                  coalesce(item_name.detail_value, "_") AS name,
                  coalesce(require_version.detail_value, "_") AS 'require ver',
                  coalesce(remote.detail_value, "_") AS 'remote ver',
                  min(remote.generation)
            FROM IndexItemDetailRow AS remote

            LEFT  JOIN IndexItemDetailRow as require_version
                ON  require_version.detail_name = 'require_version'
                AND require_version.owner_iid=remote.owner_iid
                AND require_version.active=1
            LEFT JOIN IndexItemDetailRow as item_guid
                ON  item_guid.detail_name = 'guid'
                AND item_guid.owner_iid=remote.owner_iid
                AND item_guid.active=1
            LEFT JOIN IndexItemDetailRow as item_name
                ON  item_name.detail_name = 'name'
                AND item_name.owner_iid=remote.owner_iid
                AND item_name.active=1
            WHERE
                remote.detail_name = 'version'
                AND remote.active=1
           GROUP BY remote.owner_iid
            """)
        self.session.execute(stmt)

    def drop_views(self):
        stmt = text("""
            DROP VIEW IF EXISTS "require_items_without_require_version_view"
            """)
        self.session.execute(stmt)
        stmt = text("""
            DROP VIEW IF EXISTS "require_items_without_require_guid_view"
            """)
        self.session.execute(stmt)
        stmt = text("""
            DROP VIEW IF EXISTS "report_versions_view"
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
        self.session.commit()

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
        self.session.commit()

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
        self.session.commit()

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
        # self.session.commit()

    def get_all_require_translate_items(self):
        """
        """
        if "get_all_require_translate_items" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexRequireTranslate))
            the_query += lambda q: q.order_by(IndexRequireTranslate.iid)
            self.baked_queries_map["get_all_require_translate_items"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_require_translate_items"]
        retVal = the_query(self.session).all()
        return retVal

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
        retVal = list()
        query_text = """
            SELECT owner_iid
            from IndexItemDetailRow
            WHERE IndexItemDetailRow.detail_name="guid"
            AND owner_iid=original_iid
            ORDER BY owner_iid
            """

        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal = exec_result.fetchall()   # now retVal is a list of (IID, require_ver, remote_ver)
                retVal = [mm[0] for mm in retVal] # need only the IID, but getting the versions is for debugging
        except SQLAlchemyError as ex:
            raise

        return retVal

    def get_all_installed_iids(self):
        """
        :return: list of all iids in the db that have guids, empty list if none are found
        """
        if "get_all_installed_iids" not in self.baked_queries_map:
            the_query = self.bakery(lambda q: q.query(IndexItemDetailRow.original_iid))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name == "require_by",
                                            IndexItemDetailRow.detail_value == IndexItemDetailRow.original_iid, IndexItemDetailRow.active == True)
            self.baked_queries_map["get_all_installed_iids"] = the_query
        else:
            the_query = self.baked_queries_map["get_all_installed_iids"]
        retVal = the_query(self.session).all()
        retVal = [m[0] for m in retVal]
        return retVal

    def get_all_installed_iids_needing_update(self):
        """ Return all iids that were installed, have a version, and that version is different from the version in the index
        """
        retVal = list()
        query_text = """
                SELECT require_version.owner_iid, require_version.detail_value AS require, remote_version.detail_value AS remote
                FROM IndexItemDetailRow AS require_version
                LEFT JOIN (
                    SELECT owner_iid, detail_value, min(generation)
                    from IndexItemDetailRow AS remote_version
                    WHERE detail_name="version"
                    AND active = 1
                    GROUP BY owner_iid
                    ) remote_version
                WHERE detail_name="require_version"
                      AND remote_version.owner_iid=require_version.owner_iid
                      AND require_version.detail_value!=remote_version.detail_value
            """

        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal = exec_result.fetchall()   # now retVal is a list of (IID, require_ver, remote_ver)
                retVal = [mm[0] for mm in retVal] # need only the IID, but getting the versions is for debugging
        except SQLAlchemyError as ex:
            raise

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
        iids_needing_update = self.get_all_installed_iids_needing_update()
        update_item_details = [IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid,
                                                  detail_name='depends', detail_value=iid,
                                                  os_id=the_os_id, generation=0) for iid in iids_needing_update]
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
            the_query += lambda q: q.filter(IndexItemDetailRow.active == True)
            the_query += lambda q: q.order_by(IndexItemDetailRow._id)
            self.baked_queries_map["get_original_details_values"] = the_query
        else:
            the_query = self.baked_queries_map["get_original_details_values"]

        retVal = the_query(self.session).params(iid=iid, detail_name=detail_name).all()
        retVal = [m[0] for m in retVal]
        return retVal

    def get_original_details(self, iid=None, detail_name=None, in_os=None):
        """
        tested by: TestItemTable.test_get_original_details_* functions
        :param iid: get detail for specific iid or all if None
        :param detail_name: get detail with specific name or all names if None
        :param in_os: get detail for os name or for all oses if None
        :return: list original details in the order they were inserted
        """
        if "get_original_details" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))
            the_query += lambda q: q.join(IndexItemRow)
            the_query += lambda q: q.filter(IndexItemRow.iid.like(bindparam('iid')))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name.like(bindparam('detail_name')))
            the_query += lambda q: q.filter(IndexItemDetailRow.os_id.like(bindparam('in_os')))
            the_query += lambda q: q.order_by(IndexItemDetailRow._id)
            self.baked_queries_map["get_original_details"] = the_query
        else:
            the_query = self.baked_queries_map["get_original_details"]

        # params with None are turned to '%'
        params = [iid, detail_name, in_os]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'
        retVal = the_query(self.session).params(iid=params[0], detail_name=params[1], os=params[2]).all()
        return retVal

    def get_resolved_details(self, iid, detail_name=None):#!  # tested by: TestItemTable.
        if "get_resolved_details" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))
            the_query += lambda q: q.filter(IndexItemDetailRow.owner_iid == bindparam('iid'))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name.like(bindparam('detail_name')))
            the_query += lambda q: q.filter(IndexItemDetailRow.active == True)
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

    def get_resolved_details_value(self, iid, detail_name=None):
        if "get_resolved_details_value" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow.detail_value))
            the_query += lambda q: q.filter(IndexItemDetailRow.owner_iid == bindparam('iid'))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name.like(bindparam('detail_name')))
            the_query += lambda q: q.filter(IndexItemDetailRow.active == True)
            the_query += lambda q: q.order_by(IndexItemDetailRow._id)
            self.baked_queries_map["get_resolved_details_value"] = the_query
        else:
            the_query = self.baked_queries_map["get_resolved_details_value"]

        # params with None are turned to '%'
        params = [detail_name]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'
        retVal = the_query(self.session).params(iid=iid, detail_name=params[0]).all()
        retVal = [m[0] for m in retVal]
        return retVal

    def get_details_by_name_for_all_iids(self, detail_name):
        if "get_details_by_name_for_all_iids" not in self.baked_queries_map:
            the_query = self.bakery(lambda session: session.query(IndexItemDetailRow))
            the_query += lambda q: q.filter(IndexItemDetailRow.detail_name.like(bindparam('detail_name')))
            the_query += lambda q: q.filter(IndexItemDetailRow.active == True)
            the_query += lambda q: q.order_by(IndexItemDetailRow.owner_iid)
            self.baked_queries_map["get_details_by_name_for_all_iids"] = the_query
        else:
            the_query = self.baked_queries_map["get_details_by_name_for_all_iids"]

        retVal = the_query(self.session).params(detail_name=detail_name).all()
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

    # @utils.timing
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
                    value = details_line.value
                    if detail_name == "install_sources" and tag is None:
                        tag = '!dir'
                    elif detail_name == "guid":
                        value = value.lower()
                    new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=self.os_names[the_os], detail_name=detail_name, detail_value=value, generation=0, tag=tag)
                    details.append(new_detail)
        return details

    def read_index_node(self, a_node):
        index_items = list()
        original_details = list()
        for IID in a_node:
            item, original_item_details = self.item_from_index_node(IID, a_node[IID])
            index_items.append(item)
            original_details.extend(original_item_details)
        self.session.add_all(index_items)
        self.session.add_all(original_details)
        # self.session.commit()

    # @utils.timing
    def read_require_node(self, a_node):
        require_items = dict()
        if a_node.isMapping():
            for IID in a_node:
                require_details = self.read_item_details_from_require_node(IID, a_node[IID])
                if require_details:
                    require_items[IID] = require_details
            self.insert_require_to_db(require_items)

    def read_item_details_from_require_node(self, the_iid, the_node):
        os_id=self.os_names['common']
        details = list()
        if the_node.isMapping():
            for detail_name in the_node:
                if detail_name == "guid":
                    for guid_sub in the_node["guid"]:
                        new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name="require_guid", detail_value=guid_sub.value)
                        details.append(new_detail)
                elif detail_name == "version":
                     for version_sub in the_node["version"]:
                        new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name="require_version", detail_value=version_sub.value)
                        details.append(new_detail)
                elif detail_name == "require_by":
                    for require_by in the_node["require_by"]:
                        new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name="require_by", detail_value=require_by.value)
                        details.append(new_detail)
        elif the_node.isSequence():
            for require_by in the_node:
                details.append(IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name="require_by", detail_value=require_by.value))
        return details

    def repr_item_for_yaml(self, iid):
        item_details = OrderedDict()
        for os_name in self.os_names:
            details_rows = self.get_original_details(iid=iid, in_os=os_name)
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

    def versions_report(self):
        retVal = list()
        query_text = """
           SELECT *
          FROM 'report_versions_view'
        """

        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                fetched_results = exec_result.fetchall()
                retVal.extend([mm[:5] for mm in fetched_results])
        except SQLAlchemyError as ex:
            raise

        return retVal

    select_details_for_IID_with_full_details_view = \
    "SELECT iid, detail_name, detail_value FROM full_details_view \
    WHERE detail_name = :d_n AND iid = :iid"

    # !
    select_details_for_IID = \
    "SELECT IndexItemRow.iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, IndexItemToDetailRelation.generation FROM IndexItemRow \
     INNER JOIN IndexItemToDetailRelation ON IndexItemToDetailRelation.item_id = IndexItemRow._id \
     INNER JOIN IndexItemDetailRow \
       ON IndexItemToDetailRelation.detail_id = IndexItemDetailRow._id \
         AND   IndexItemDetailRow.detail_name = :d_n \
     WHERE IndexItemRow.iid = :iid"

    # @utils.timing
    def get_resolved_details_for_iid(self, iid, detail_name):
        retVal = self.session.execute(IndexItemsTable.select_details_for_IID_with_full_details_view, {'d_n': detail_name, 'iid': iid}).fetchall()
        return retVal

    def iids_from_guids(self, guid_list):
        returned_iids = list()
        orphaned_guids = list()
        if guid_list:
            # add all guids to table IndexGuidToItemTranslate with iid field defaults to Null
            for a_guid in list(set(guid_list)):  # list(set()) will remove duplicates
                self.session.add(IndexGuidToItemTranslate(guid=a_guid))
            self.session.flush()

            # insert to table IndexGuidToItemTranslate guid, iid pairs.
            # a guid might yield 0, 1, or more iids
            query_text = """
                INSERT INTO IndexGuidToItemTranslate(guid, iid)
                SELECT IndexItemDetailRow.detail_value, IndexItemDetailRow.owner_iid
                FROM IndexItemDetailRow
                WHERE
                    IndexItemDetailRow.detail_name='guid'
                    AND IndexItemDetailRow.detail_value IN (SELECT guid FROM IndexGuidToItemTranslate WHERE iid IS NULL);
                """
            self.session.execute(query_text)
            self.session.flush()

            # return a list of guid, count pairs.
            # Guids with count of 0 are guid that could not be translated to iids
            query_text = """
                SELECT guid, count(guid) FROM IndexGuidToItemTranslate
                GROUP BY guid;
                """
            count_guids = self.session.execute(query_text).fetchall()
            for guid, count in count_guids:
                if count < 2:
                    orphaned_guids.append(guid)
            all_iids = self.session.query(IndexGuidToItemTranslate.iid)\
                    .distinct(IndexGuidToItemTranslate.iid)\
                    .filter(IndexGuidToItemTranslate.iid != None)\
                    .order_by('iid').all()
            returned_iids = [iid[0] for iid in all_iids]

        return returned_iids, orphaned_guids

    def set_status_of_iids(self, iid_list, status_value=None):
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

    def set_status_of_direct_dependencies(self, depends_of_list, status_value=None):
        """ update the status field of the iids who are direct dependants of the iids in the list.
            if status_value is not None this exact value will be used,
            otherwise the status field will be incremented.
            used to mark dependents of the special build in iids such as __ALL_ITEMS_IID__
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
        existing_iids = None
        orphan_iids = None
        query_vars = '("'+'","'.join(iid_list)+'")'
        query_text = """
            SELECT iid
            FROM IndexItemRow
            WHERE iid IN {0}
        """.format(query_vars)

        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                fetched_results = exec_result.fetchall()
                existing_iids = [mm[0] for mm in fetched_results]
                # query will return list those iid in iid_list that were found in the index
                orphan_iids = list(set(iid_list)-set(existing_iids))
        except SQLAlchemyError as ex:
            raise
        return existing_iids, orphan_iids

    def get_recursive_dependencies(self, look_for_status=1):
        retVal = list()
        query_text = """
            WITH RECURSIVE find_dependants(_IID_) AS
            (
            SELECT iid FROM IndexItemRow WHERE status={}
            UNION

            SELECT IndexItemDetailRow.detail_value
            FROM IndexItemDetailRow, find_dependants
            WHERE
                IndexItemDetailRow.detail_name = 'depends'
            AND
                IndexItemDetailRow.owner_iid = find_dependants._IID_
            AND
                IndexItemDetailRow.active = 1
            )
            SELECT _IID_ FROM find_dependants
        """.format(look_for_status)

        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                fetched_results = exec_result.fetchall()
                retVal = [mm[0] for mm in fetched_results]
        except SQLAlchemyError as ex:
            raise

        return retVal

    def change_status_of_iids_to_another_status(self, old_status, new_status, iid_list):
        if iid_list:
            query_vars = '("' + '","'.join(iid_list) + '")'
            query_text = """
                UPDATE IndexItemRow
                SET status={new_status}
                WHERE status={old_status}
                AND iid IN {query_vars}
              """.format(**locals())
            self.session.execute(query_text)
            #self.session.commit()  # not sure why but commit is a must here of all places for the update to be written

    def change_status_of_iids(self, new_status, iid_list):
        if iid_list:
            query_vars = '("' + '","'.join(iid_list) + '")'
            query_text = """
                UPDATE IndexItemRow
                SET status={new_status}
                WHERE iid IN {query_vars}
              """.format(**locals())
            self.session.execute(query_text)
            #self.session.commit()  # not sure why but commit is a must here of all places for the update to be written

    def get_iids_by_status(self, status):
        retVal = list()
        query_text = """
            SELECT iid
            FROM IndexItemRow
            WHERE status={status}
        """.format(**locals())
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                fetched_results = exec_result.fetchall()
                retVal = [mm[0] for mm in fetched_results]
        except SQLAlchemyError as ex:
            raise
        return retVal

    def mark_main_install_iids(self, iid_list, special_build_in_iids):
        special_iids_to_mark = set(iid_list) & set(special_build_in_iids)
        if "__UPDATE_INSTALLED_ITEMS__" in special_iids_to_mark\
            and "__REPAIR_INSTALLED_ITEMS__" in special_iids_to_mark:
            special_iids_to_mark.remove("__UPDATE_INSTALLED_ITEMS__") # repair takes precedent over update

        regular_iids_to_mark = set(iid_list) - set(special_build_in_iids)
        self.set_status_of_direct_dependencies(special_iids_to_mark, status_value=1)
        self.set_status_of_iids(regular_iids_to_mark, status_value=1)
        self.session.flush()
        retVal = self.get_iids_by_status(1)
        return retVal

    def select_versions_for_installed_item(self):
        retVal = list()
        query_text = """
            SELECT IndexItemDetailRow.owner_iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, min(IndexItemDetailRow.generation)
            FROM IndexItemRow, IndexItemDetailRow
            WHERE IndexItemRow.status > 0
            AND IndexItemRow.iid=IndexItemDetailRow.owner_iid
            AND IndexItemDetailRow.detail_name='version'
            GROUP BY IndexItemDetailRow.owner_iid
            """
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal.extend(exec_result.fetchall())
        except SQLAlchemyError as ex:
            raise
        return retVal

    def target_folders_to_items(self):
        retVal = list()
        query_text = """
            SELECT IndexItemDetailRow.detail_value, IndexItemDetailRow.owner_iid
            FROM IndexItemDetailRow, IndexItemRow
            WHERE IndexItemDetailRow.detail_name="install_folders"
                AND IndexItemRow.iid=IndexItemDetailRow.owner_iid
                AND IndexItemRow.status != 0
                AND IndexItemDetailRow.active = 1
            ORDER BY IndexItemDetailRow.detail_value
            """
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal.extend(exec_result.fetchall())
        except SQLAlchemyError:
            raise
        return retVal

    def source_folders_to_items_without_target_folders(self):
        retVal = list()
        query_text = """
            SELECT IndexItemDetailRow.detail_value, IndexItemDetailRow.owner_iid, IndexItemDetailRow.tag
            FROM IndexItemDetailRow, IndexItemRow
            WHERE IndexItemDetailRow.owner_iid NOT IN (
                SELECT DISTINCT IndexItemDetailRow.owner_iid
                FROM IndexItemDetailRow, IndexItemRow
                WHERE IndexItemDetailRow.detail_name = "install_folders"
                      AND IndexItemRow.iid = IndexItemDetailRow.owner_iid
                      AND IndexItemRow.status > 0
                      AND IndexItemDetailRow.active = 1
                ORDER BY IndexItemDetailRow.owner_iid
            )
            AND IndexItemDetailRow.detail_name="install_sources"
                AND IndexItemRow.iid = IndexItemDetailRow.owner_iid
                AND IndexItemRow.status != 0
                AND IndexItemDetailRow.active = 1
            """
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal.extend(exec_result.fetchall())
        except SQLAlchemyError as ex:
            raise
        return retVal

    def name_and_version_report_for_active_iids(self):
        query_text = """
            SELECT IndexItemRow.iid,
                    coalesce(name_row.detail_value, "")       AS name,
                    coalesce(version_row.detail_value, "")    AS version,
                    min(version_row.generation) AS ver_gen,
                    min(name_row.generation)    AS name_gen
            FROM IndexItemRow
                LEFT JOIN IndexItemDetailRow AS version_row
                    ON version_row.owner_iid=IndexItemRow.iid
                    AND version_row.detail_name='version'
                    AND version_row.active=1
                LEFT JOIN IndexItemDetailRow AS name_row
                    ON name_row.owner_iid=IndexItemRow.iid
                    AND name_row.detail_name='name'
                    AND name_row.active=1
            WHERE status!=0
            GROUP BY IndexItemRow.iid
            """
        fetched_results = self.session.execute(query_text).fetchall()
        return fetched_results

    def get_iids_and_details_for_active_iids(self, detail_name, unique_values=False, limit_to_iids=None):
        retVal = list()
        group_by_values_filter = "GROUP BY IndexItemDetailRow.detail_value" if unique_values else ""
        limit_to_iids_filter = ""
        if limit_to_iids:
            quoted_limit_to_iids = [utils.quoteme_single(iid) for iid in limit_to_iids]
            limit_to_iids_filter = " ".join(('AND IndexItemDetailRow.owner_iid IN (', ",".join(quoted_limit_to_iids), ')'))

        query_text = """
            SELECT  IndexItemDetailRow.owner_iid, IndexItemDetailRow.detail_value
            FROM IndexItemDetailRow
                JOIN IndexItemRow
                    ON  IndexItemRow.iid=IndexItemDetailRow.owner_iid
                    AND IndexItemRow.status!=0
            WHERE IndexItemDetailRow.detail_name="{detail_name}"
                AND IndexItemDetailRow.active = 1
            {limit_to_iids_filter}
            {group_by_values_filter}
            ORDER BY IndexItemDetailRow._id
            """.format(**locals())
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal.extend(exec_result.fetchall())
        except SQLAlchemyError as ex:
            raise
        return retVal

    def get_details_for_active_iids(self, detail_name, unique_values=False, limit_to_iids=None):
        distinct = "DISTINCT" if unique_values else ""
        limit_to_iids_filter = ""
        if limit_to_iids:
            limit_to_iids_filter = 'AND IndexItemDetailRow.owner_iid IN ('
            quoted_limit_to_iids = [utils.quoteme_single(iid) for iid in limit_to_iids_filter]
            limit_to_iids_filter += ','.join(quoted_limit_to_iids)
            limit_to_iids_filter += ')'

        query_text = """
            SELECT {0} IndexItemDetailRow.detail_value
            FROM IndexItemDetailRow
                JOIN IndexItemRow
                    ON  IndexItemRow.iid=IndexItemDetailRow.owner_iid
                    AND IndexItemRow.status!=0
            WHERE IndexItemDetailRow.detail_name="{1}"
                AND IndexItemDetailRow.active = 1
                {2}
            ORDER BY IndexItemDetailRow._id
            """.format(distinct, detail_name, limit_to_iids_filter)
        fetched_results = self.session.execute(query_text).fetchall()
        retVal = [mm[0] for mm in fetched_results]
        return retVal

    def get_details_and_tag_for_active_iids(self, detail_name, unique_values=False, limit_to_iids=None):
        distinct = "DISTINCT" if unique_values else ""
        limit_to_iids_filter = ""
        if limit_to_iids:
            limit_to_iids_filter = 'AND IndexItemDetailRow.owner_iid IN ("'
            limit_to_iids_filter += '","'.join(limit_to_iids)
            limit_to_iids_filter += '")'

        query_text = """
            SELECT {0} IndexItemDetailRow.detail_value, IndexItemDetailRow.tag
            FROM IndexItemDetailRow
                JOIN IndexItemRow
                    ON  IndexItemRow.iid=IndexItemDetailRow.owner_iid
                    AND IndexItemRow.status!=0
            WHERE IndexItemDetailRow.detail_name="{1}"
                AND IndexItemDetailRow.active = 1
                {2}
            ORDER BY IndexItemDetailRow._id
            """.format(distinct, detail_name, limit_to_iids_filter)
        fetched_results = self.session.execute(query_text).fetchall()
        return fetched_results

    def create_default_items(self):
        self.create_default_index_items()
        self.create_default_require_items()
        self.session.flush()

    def require_items_without_version_or_guid(self):
        retVal = list()
        query_text = """
          SELECT IndexItemRow.iid,
                index_ver_t.detail_value AS index_version,
                require_ver_t.detail_value AS require_version,
                index_guid_t.detail_value AS index_guid,
                require_guid_t.detail_value AS require_guid,
                min(index_ver_t.generation) AS generation
            from IndexItemRow
                JOIN IndexItemDetailRow AS index_ver_t ON IndexItemRow.iid = index_ver_t.owner_iid
                AND index_ver_t.detail_name='version'
                Left JOIN IndexItemDetailRow AS require_ver_t ON IndexItemRow.iid = require_ver_t.owner_iid
                AND require_ver_t.detail_name='require_version'
                JOIN IndexItemDetailRow AS index_guid_t ON IndexItemRow.iid = index_guid_t.owner_iid
                AND index_guid_t.detail_name='guid'
                Left JOIN IndexItemDetailRow AS require_guid_t ON IndexItemRow.iid = require_guid_t.owner_iid
                AND require_guid_t.detail_name='require_guid'
            WHERE from_require=1 AND (require_ver_t.detail_value ISNULL OR require_guid_t.detail_value ISNULL)
            GROUP BY IndexItemRow.iid
          """
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal.extend(exec_result.fetchall())
        except SQLAlchemyError as ex:
            raise
        # returns: [(iid, index_version, require_version, index_guid, require_guid, generation), ...]
        return retVal

    def insert_binary_versions(self, binaries_version_list):
        for binary_details in binaries_version_list:
            folder, name = os.path.split(binary_details[0])
            self.session.add(FoundOnDiskItemRow(name=name, path=binary_details[0], version=binary_details[1], guid=binary_details[2]))
        self.commit_changes()

    def add_require_version_from_binaries(self):
        query_text = """
        INSERT OR REPLACE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  FoundOnDiskItemRow.iid, -- original_iid
                FoundOnDiskItemRow.iid, -- owner_iid
                0,                      -- os_id
                'require_version',      -- detail_name
                FoundOnDiskItemRow.version, -- detail_value
                0                       -- generation
        FROM require_items_without_require_version_view
        JOIN FoundOnDiskItemRow
            ON FoundOnDiskItemRow.iid=require_items_without_require_version_view.iid
            AND FoundOnDiskItemRow.version NOTNULL
        """
        try:
            exec_result = self.session.execute(query_text)
        except SQLAlchemyError as ex:
            print(ex)
            raise

    def add_require_guid_from_binaries(self):
        query_text = """
        INSERT OR REPLACE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  FoundOnDiskItemRow.iid, -- original_iid
                FoundOnDiskItemRow.iid, -- owner_iid
                0,                      -- os_id
                'require_guid',      -- detail_name
                FoundOnDiskItemRow.version, -- detail_value
                0                       -- generation
        FROM require_items_without_require_guid_view
        JOIN FoundOnDiskItemRow
            ON FoundOnDiskItemRow.iid=require_items_without_require_guid_view.iid
            AND FoundOnDiskItemRow.guid NOTNULL
        """
        try:
            exec_result = self.session.execute(query_text)
        except SQLAlchemyError as ex:
            print(ex)
            raise
