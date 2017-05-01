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
    FoundOnDiskItemRow, \
    ConfigVar

import utils


class IndexItemsTable(object):
    os_names = {'common': 0, 'Mac': 1, 'Mac32': 2, 'Mac64': 3, 'Win': 4, 'Win32': 5, 'Win64': 6}
    install_status = {"none": 0, "main": 1, "update": 2, "depend": 3, "remove": -1}
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

    def get_db_url(self):
        return self.session.bind.url

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
                        ON (name_item_t.detail_name = 'install_sources'
                          OR
                          name_item_t.detail_name = 'previous_sources')
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
                    WHERE (detail_name='install_sources' OR detail_name='previous_sources')
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

        trigger_text = """
            CREATE TRIGGER IF NOT EXISTS create_require_by_for_main_iids_trigger
            AFTER UPDATE OF install_status ON IndexItemRow
            WHEN NEW.install_status = 1  -- 1 means iid requested explicitly by the user (not update or dependant)
            AND NEW.ignore = 0
            BEGIN

            -- self-referenced require_by for main install iids
            INSERT OR IGNORE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
            VALUES (NEW.iid, NEW.iid, 0, 'require_by', NEW.iid, 0);

            END;
        """
        self.session.execute(trigger_text)

        trigger_text = """
            CREATE TRIGGER IF NOT EXISTS create_require_for_all_iids_trigger
            AFTER UPDATE OF install_status ON IndexItemRow
            WHEN NEW.install_status > 0
            AND NEW.ignore = 0
            BEGIN

            -- remove previous require_version, require_guid owned NEW.iid
            DELETE FROM IndexItemDetailRow
            WHERE owner_iid = NEW.iid
            AND detail_name IN ("require_version", "require_guid");

            -- add require_version
            INSERT OR IGNORE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
            SELECT original_iid, owner_iid, os_id, 'require_version', detail_value, min(generation)
            FROM IndexItemDetailRow
            WHERE owner_iid  = NEW.iid
            AND active = 1
            AND detail_name='version'
            GROUP BY owner_iid;

            -- add require_guid
            INSERT OR IGNORE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
            SELECT original_iid, owner_iid, os_id, 'require_guid', detail_value, min(generation)
            FROM IndexItemDetailRow
            WHERE IndexItemDetailRow.owner_iid = NEW.iid
            AND active = 1
            AND detail_name='guid'
            GROUP BY owner_iid;

            -- require_by for all dependant of new iid
            INSERT OR IGNORE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
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
            CREATE TRIGGER IF NOT EXISTS remove_require_for_uninstalled_iids_trigger
            AFTER UPDATE OF install_status ON IndexItemRow
            WHEN NEW.install_status < 0
            AND NEW.ignore = 0
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
            CREATE TRIGGER IF NOT EXISTS adjust_active_os_for_details
            AFTER UPDATE OF active ON IndexItemDetailOperatingSystem
            BEGIN
                UPDATE IndexItemDetailRow
                SET    active =  NEW.active
                WHERE  IndexItemDetailRow.os_id = NEW._id;
            END;
        """
        self.session.execute(trigger_text)

        if False:  # debugging table and trigger
            table_text = """
                CREATE TABLE ChangeLog
                (
                _id INTEGER PRIMARY KEY NOT NULL,
                time DATETIME default (datetime('now','localtime')),
                owner_iid TEXT,
                detail_name TEXT,
                detail_value TEXT,
                os_id INTEGER,
                old_active INTEGER,
                new_active INTEGER,
                log_text TEXT
                );
            """
            self.session.execute(table_text)

            trigger_text = """
                CREATE TRIGGER IF NOT EXISTS log_adjust_active_os_for_details
                AFTER UPDATE OF active ON IndexItemDetailRow
                BEGIN
                    INSERT INTO ChangeLog (owner_iid, detail_name, detail_value, os_id, old_active, new_active)
                    VALUES (OLD.owner_iid, OLD.detail_name, OLD.detail_value, OLD.os_id,  OLD.active,  NEW.active);
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

        # when adding new install_source calculate the adjusted source relative to sync folder
        # If install_source starts with '/' - just remove the '/'
        # If install_source starts with $ leave as is since it's variable dependant
        # Otherwise add $(SOURCE_PREFIX)/ - which will later be resolved to Mac/Win
        trigger_text = """
            CREATE TRIGGER IF NOT EXISTS set_adjusted_source
            AFTER INSERT ON IndexItemDetailRow
            WHEN NEW.detail_name="install_sources"
            BEGIN
                 INSERT INTO AdjustedSources (detail_row_id, adjusted_source)
                 VALUES(NEW._id,
                    CASE substr(NEW.detail_value,1,1)
                    WHEN "/" THEN -- absolute path
                        substr(NEW.detail_value, 2)
                    WHEN "$" THEN -- relative to some variable
                        NEW.detail_value
                    ELSE          -- relative to $(SOURCE_PREFIX): Mac or Win
                        "$(SOURCE_PREFIX)/" || NEW.detail_value
                    END);
            END;
        """
        self.session.execute(trigger_text)
        self.commit_changes()
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
        stmt = """
            DROP TRIGGER IF EXISTS log_adjust_active_os_for_details;
            """
        self.session.execute(stmt)
        stmt = """
            DROP TRIGGER IF EXISTS set_adjusted_source;
            """
        self.session.execute(stmt)
        self.commit_changes()

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
                  coalesce(require_version.detail_value, "_") AS 'require_version',
                  coalesce(remote.detail_value, "_") AS 'remote_version',
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
        self.commit_changes()

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
        self.commit_changes()

    def begin_get_for_all_oses(self):
        """ adds all known os names to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        query_text = """
            UPDATE IndexItemDetailOperatingSystem
            SET active = 1
         """
        try:
            exec_result = self.session.execute(query_text)
            self.commit_changes()
        except SQLAlchemyError as ex:
            print(ex)
            raise

    def reset_get_for_all_oses(self):
        """ resets the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        self.begin_get_for_specific_oses()

    def begin_get_for_specific_oses(self, *for_oses):
        """ adds another os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This is a static method so it will influence all InstallItem objects.
        """
        for_oses = *for_oses, "common"
        quoted_os_names = [utils.quoteme_double(os_name) for os_name in for_oses]
        query_vars = ", ".join(quoted_os_names)
        query_text = """
            UPDATE IndexItemDetailOperatingSystem
            SET active = CASE WHEN IndexItemDetailOperatingSystem.name IN ({0}) THEN
                    1
                ELSE
                    0
                END;
        """.format(query_vars)
        try:
            exec_result = self.session.execute(query_text)
            self.commit_changes()
        except SQLAlchemyError as ex:
            print(ex)
            raise

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
        self.commit_changes()

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
                retVal = exec_result.fetchall()
                retVal = [mm[0] for mm in retVal]
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
                SELECT DISTINCT require_version.owner_iid, require_version.detail_value AS require, remote_version.detail_value AS remote
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
                      AND require_version.active = 1
                GROUP BY require_version.owner_iid
            """
            # "GROUP BY" will make sure only one row is returned for an iid.
            # multiple rows can be found if and IID has 2 previous_sources both were found
            # on disk and their version identified.
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
        retVal = list()
        query_text = """SELECT iid FROM IndexItemRow"""
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                retVal = exec_result.fetchall()
                retVal = [mm[0] for mm in retVal]
        except SQLAlchemyError as ex:
            raise

        return retVal

    def create_default_index_items(self, iids_to_ignore):
        the_os_id = self.os_names['common']
        the_iid = "__ALL_ITEMS_IID__"
        all_items_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        self.session.add(all_items_item)
        for iid in self.get_all_iids():
            if iid not in iids_to_ignore:
                depends_details = IndexItemDetailRow(original_iid=the_iid,
                                                 owner_iid=the_iid,
                                                 detail_name='depends',
                                                 detail_value=iid,
                                                 os_id=the_os_id,
                                                 generation=0)
                self.session.add(depends_details)

        the_iid = "__ALL_GUIDS_IID__"
        all_guids_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        self.session.add(all_guids_item)
        all_iids_with_guids = self.get_all_iids_with_guids()
        for iid in all_iids_with_guids:
            if iid not in iids_to_ignore:
                depends_details = IndexItemDetailRow(original_iid=the_iid,
                                                 owner_iid=the_iid,
                                                 detail_name='depends',
                                                 detail_value=iid,
                                                 os_id=the_os_id,
                                                 generation=0)
                self.session.add(depends_details)
        self.commit_changes()

    def create_default_require_items(self, iids_to_ignore):
        the_os_id = self.os_names['common']
        the_iid = "__REPAIR_INSTALLED_ITEMS__"
        repair_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        self.session.add(repair_item)
        for iid in self.get_all_installed_iids():
            if iid not in iids_to_ignore:
                repair_item_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid,
                                                  detail_name='depends', detail_value=iid,
                                                  os_id=the_os_id, generation=0)
                self.session.add(repair_item_detail)

        the_iid = "__UPDATE_INSTALLED_ITEMS__"
        update_item = IndexItemRow(iid=the_iid, inherit_resolved=True, from_index=False, from_require=False)
        self.session.add(update_item)
        iids_needing_update = self.get_all_installed_iids_needing_update()
        for iid in iids_needing_update:
            if iid not in iids_to_ignore:
                update_item_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid,
                                                  detail_name='depends', detail_value=iid,
                                                  os_id=the_os_id, generation=0)
                self.session.add(update_item_detail)
        self.commit_changes()

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

    def get_resolved_details_value(self, iid, detail_name):
        retVal = list()
        query_text = """
            SELECT detail_value
            FROM IndexItemDetailRow
            WHERE owner_iid = '{iid}'
            AND detail_name = '{detail_name}'
            AND active = 1
            ORDER BY _id
        """.format(**locals())
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                fetched_results = exec_result.fetchall()
                retVal = [mm[0] for mm in fetched_results]
        except SQLAlchemyError as ex:
            raise
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
        self.commit_changes()

    def item_from_index_node(self, the_iid, the_node):
        item = IndexItemRow(iid=the_iid, inherit_resolved=False, from_index=True)
        original_details = self.read_item_details_from_node(the_iid, the_node)
        return item, original_details

    def read_item_details_from_node(self, the_iid, the_node, the_os='common'):
        details = list()
        # go through the raw yaml nodes instead of doing "for detail_name in the_node".
        # this is to overcome index.yaml with maps that have two keys with the same name.
        # Although it's not valid yaml some index.yaml versions have this problem.
        for detail_node in the_node.value:
            detail_name = detail_node[0].value
            if detail_name in IndexItemsTable.os_names:
                os_specific_details = self.read_item_details_from_node(the_iid, detail_node[1], the_os=detail_name)
                details.extend(os_specific_details)
            elif detail_name == 'actions':
                actions_details = self.read_item_details_from_node(the_iid, detail_node[1], the_os)
                details.extend(actions_details)
            else:
                for details_line in detail_node[1]:
                    tag = details_line.tag if details_line.tag[0]=='!' else None
                    value = details_line.value
                    if detail_name in ("install_sources", "previous_sources") and tag is None:
                        tag = '!dir'
                    elif detail_name == "guid":
                        value = value.lower()
                    new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=self.os_names[the_os], detail_name=detail_name, detail_value=value, generation=0, tag=tag)
                    details.append(new_detail)
        return details

    def read_index_node(self, a_node):
        index_items = list()
        items_details = list()
        for IID in a_node:
            item, original_item_details = self.item_from_index_node(IID, a_node[IID])
            index_items.append(item)
            items_details.extend(original_item_details)
        self.session.add_all(index_items)
        self.session.add_all(items_details)
        self.commit_changes()

    # @utils.timing
    def read_require_node(self, a_node):
        require_items = dict()
        if a_node.isMapping():
            all_iids = self.get_all_iids()
            for IID in a_node:
                require_details = self.read_item_details_from_require_node(IID, a_node[IID], all_iids)
                if require_details:
                    require_items[IID] = require_details
        self.insert_require_to_db(require_items)

    def read_item_details_from_require_node(self, the_iid, the_node, all_iids):
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
                        if require_by.value in all_iids:
                            detail_name = "require_by"
                        else:
                            detail_name = "deprecated_require_by"
                        new_detail = IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name=detail_name, detail_value=require_by.value)
                        details.append(new_detail)
        elif the_node.isSequence():
            for require_by in the_node:
                if require_by.value in all_iids:
                    detail_name = "require_by"
                else:
                    detail_name = "deprecated_require_by"
                details.append(IndexItemDetailRow(original_iid=the_iid, owner_iid=the_iid, os_id=os_id, detail_name=detail_name, detail_value=require_by.value))
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

    def versions_report(self, report_only_installed=False):
        retVal = list()
        query_text = """
           SELECT *
          FROM 'report_versions_view'
        """
        if report_only_installed:
           query_text += """
           WHERE require_version != '_'
           AND remote_version != '_'
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
            self.commit_changes()

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
            self.commit_changes()

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
            SELECT iid FROM IndexItemRow
            WHERE install_status={} AND ignore = 0
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
                SET install_status={new_status}
                WHERE install_status={old_status}
                AND iid IN {query_vars}
                AND ignore = 0
              """.format(**locals())
            self.session.execute(query_text)
            #self.commit_changes()  # not sure why but commit is a must here of all places for the update to be written

    def change_status_of_iids(self, new_status, iid_list):
        if iid_list:
            query_vars = '("' + '","'.join(iid_list) + '")'
            query_text = """
                UPDATE IndexItemRow
                SET install_status={new_status}
                WHERE iid IN {query_vars}
                AND ignore = 0
              """.format(**locals())
            self.session.execute(query_text)
            #self.commit_changes()  # not sure why but commit is a must here of all places for the update to be written

    def get_iids_by_status(self, min_status, max_status=None):
        if max_status is None:
            max_status = min_status
        retVal = list()
        query_text = """
            SELECT iid
            FROM IndexItemRow
            WHERE install_status >= {min_status}
            AND install_status <= {max_status}
            AND ignore = 0
        """.format(**locals())
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                fetched_results = exec_result.fetchall()
                retVal = [mm[0] for mm in fetched_results]
        except SQLAlchemyError as ex:
            raise
        return retVal

    def select_versions_for_installed_item(self):
        retVal = list()
        query_text = """
            SELECT IndexItemDetailRow.owner_iid, IndexItemDetailRow.detail_name, IndexItemDetailRow.detail_value, min(IndexItemDetailRow.generation)
            FROM IndexItemRow, IndexItemDetailRow
            WHERE IndexItemRow.install_status > 0
            AND IndexItemRow.ignore = 0
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
        """ returns a list of (IID, install_folder, tag, direct_syc_indicator) """
        retVal = list()
        query_text = """
            SELECT IndexItemDetailRow.owner_iid,
                  IndexItemDetailRow.detail_value,
                  IndexItemDetailRow.tag,
                  direct_sync_t.detail_value
            FROM IndexItemDetailRow, IndexItemRow
            LEFT JOIN IndexItemDetailRow AS direct_sync_t
              ON IndexItemRow.iid=direct_sync_t.owner_iid
                AND direct_sync_t.detail_name = 'direct_sync'
                AND direct_sync_t.active = 1
            WHERE IndexItemDetailRow.detail_name="install_folders"
                AND IndexItemRow.iid=IndexItemDetailRow.owner_iid
                AND IndexItemRow.install_status != 0
                AND IndexItemRow.ignore = 0
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
            SELECT
              AdjustedSources.adjusted_source AS adjusted_source,
              IndexItemDetailRow.owner_iid AS iid,
              IndexItemDetailRow.tag AS tag
            FROM IndexItemDetailRow, IndexItemRow, AdjustedSources
            WHERE IndexItemDetailRow.owner_iid NOT IN (
                SELECT DISTINCT IndexItemDetailRow.owner_iid
                FROM IndexItemDetailRow, IndexItemRow
                WHERE IndexItemDetailRow.detail_name = "install_folders"
                      AND IndexItemRow.iid = IndexItemDetailRow.owner_iid
                      AND IndexItemRow.install_status > 0
                      AND IndexItemRow.ignore = 0
                      AND IndexItemDetailRow.active = 1
                ORDER BY IndexItemDetailRow.owner_iid
            )
            AND IndexItemDetailRow.detail_name="install_sources"
                AND IndexItemRow.iid = IndexItemDetailRow.owner_iid
                AND IndexItemRow.install_status != 0
                AND IndexItemRow.ignore = 0
                AND IndexItemDetailRow.active = 1
                AND AdjustedSources.detail_row_id = IndexItemDetailRow._id
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
            WHERE install_status!=0
            AND ignore=0
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
                    AND IndexItemRow.install_status!=0
                    AND IndexItemRow.ignore = 0
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
            quoted_limit_to_iids = [utils.quoteme_single(iid) for iid in limit_to_iids]
            limit_to_iids_filter = " ".join(('AND IndexItemDetailRow.owner_iid IN (', ",".join(quoted_limit_to_iids), ')'))

        query_text = """
            SELECT {0} IndexItemDetailRow.detail_value
            FROM IndexItemDetailRow
                JOIN IndexItemRow
                    ON  IndexItemRow.iid=IndexItemDetailRow.owner_iid
                    AND IndexItemRow.install_status!=0
                    AND IndexItemRow.ignore = 0
            WHERE IndexItemDetailRow.detail_name="{1}"
                AND IndexItemDetailRow.active = 1
                {2}
            ORDER BY IndexItemDetailRow._id
            """.format(distinct, detail_name, limit_to_iids_filter)
        fetched_results = self.session.execute(query_text).fetchall()
        retVal = [mm[0] for mm in fetched_results]
        return retVal

    def get_details_and_tag_for_active_iids(self, detail_name, unique_values=False, limit_to_iids=None):
        retVal = list()
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
                    AND IndexItemRow.install_status!=0
                    AND IndexItemRow.ignore = 0
            WHERE IndexItemDetailRow.detail_name="{1}"
                AND IndexItemDetailRow.active = 1
                {2}
            ORDER BY IndexItemDetailRow._id
            """.format(distinct, detail_name, limit_to_iids_filter)
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                fetched_results= exec_result.fetchall()
                retVal = [(mm[0], mm[1]) for mm in fetched_results]
        except SQLAlchemyError as ex:
            raise
        # returns: [(iid, index_version, require_version, index_guid, require_guid, generation), ...]
        return retVal

    def create_default_items(self, iids_to_ignore):
        self.create_default_index_items(iids_to_ignore=iids_to_ignore)
        self.create_default_require_items(iids_to_ignore=iids_to_ignore)

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
        """ add require_version for iid that do not have this detail value (because previous index.yaml did not have it)
        1st try version found on disk from table FoundOnDiskItemRow
        2nd for iids still missing require_version try phantom_version detail value
        """
        query_text = """
        INSERT OR REPLACE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  FoundOnDiskItemRow.iid, -- original_iid
                FoundOnDiskItemRow.iid, -- owner_iid
                0,                      -- os_id
                'require_version',      -- detail_name
                FoundOnDiskItemRow.version, -- detail_value from disk
                0                       -- generation
        FROM require_items_without_require_version_view
        JOIN FoundOnDiskItemRow
            ON FoundOnDiskItemRow.iid=require_items_without_require_version_view.iid
            AND FoundOnDiskItemRow.version NOTNULL
        """
        try:
            exec_result = self.session.execute(query_text)
            self.commit_changes()
        except SQLAlchemyError as ex:
            print(ex)
            raise

        query_text = """
        INSERT OR REPLACE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  IndexItemDetailRow.owner_iid, -- original_iid
                IndexItemDetailRow.owner_iid, -- owner_iid
                0,                      -- os_id
                'require_version',      -- detail_name
                IndexItemDetailRow.detail_value, -- detail_value from phantom_version
                0                       -- generation
        FROM require_items_without_require_version_view
        JOIN IndexItemDetailRow
            ON IndexItemDetailRow.owner_iid=require_items_without_require_version_view.iid
            AND IndexItemDetailRow.detail_name='phantom_version'
        """
        try:
            exec_result = self.session.execute(query_text)
            self.commit_changes()
        except SQLAlchemyError as ex:
            print(ex)
            raise

    def add_require_guid_from_binaries(self):
        query_text = """
        INSERT OR REPLACE INTO IndexItemDetailRow (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  FoundOnDiskItemRow.iid,  -- original_iid
                FoundOnDiskItemRow.iid,  -- owner_iid
                0,                       -- os_id
                'require_guid',          -- detail_name
                FoundOnDiskItemRow.guid, -- detail_value
                0                        -- generation
        FROM require_items_without_require_guid_view
        JOIN FoundOnDiskItemRow
            ON FoundOnDiskItemRow.iid=require_items_without_require_guid_view.iid
            AND FoundOnDiskItemRow.guid NOTNULL
        """
        try:
            exec_result = self.session.execute(query_text)
            self.commit_changes()
        except SQLAlchemyError as ex:
            print(ex)
            raise

    def set_ignore_iids(self, iid_list):
        if iid_list:
            query_vars = "".join((
                '(',
                ",".join(utils.quoteme_double_list(iid_list)),
                ')'))
            query_text = """
                UPDATE IndexItemRow
                SET ignore=1
                WHERE iid IN {query_vars}
              """.format(**locals())
            self.session.execute(query_text)
            self.commit_changes()

    def config_var_list_to_db(self, in_config_var_list):
        for identifier in in_config_var_list:
            raw_value = in_config_var_list.unresolved_var(identifier)
            resolved_value = in_config_var_list.ResolveVarToStr(identifier, list_sep=" ", default="")
            self.session.add(ConfigVar(name=identifier, raw_value=raw_value, resolved_value=resolved_value))
        self.commit_changes()

    def get_sync_folders_and_sources_for_active_iids(self):
        retVal = list()
        query_text = """
             SELECT install_sources_t.owner_iid AS iid,
                    direct_sync_t.detail_value AS direct_sync_indicator,
                    install_sources_t.detail_value AS source,
                    adjusted_sources_t.adjusted_source AS adjusted_source,
                    install_sources_t.tag AS tag,
                    install_folders_t.detail_value AS install_folder
            FROM IndexItemDetailRow AS install_sources_t
                JOIN IndexItemRow AS iid_t
                    ON iid_t.iid=install_sources_t.owner_iid
                    AND iid_t.install_status > 0
                JOIN AdjustedSources AS adjusted_sources_t
                  ON install_sources_t._id = adjusted_sources_t.detail_row_id
                LEFT JOIN IndexItemDetailRow AS install_folders_t
                    ON install_folders_t.active=1
                    AND install_sources_t.owner_iid = install_folders_t.owner_iid
                        AND install_folders_t.detail_name='install_folders'
                LEFT JOIN IndexItemDetailRow AS direct_sync_t
                    ON direct_sync_t.active=1
                    AND install_sources_t.owner_iid = direct_sync_t.owner_iid
                        AND direct_sync_t.detail_name='direct_sync'
            WHERE
                install_sources_t.active=1
                AND install_sources_t.detail_name='install_sources'
        """
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                # returns [(iid, direct_sync_indicator, source, source_tag, install_folder),...]
                retVal.extend(exec_result.fetchall())
        except SQLAlchemyError as ex:
            raise
        return retVal

    def get_adjusted_sources_for_iid(self, the_iid):
        retVal = list()
        query_text = """
        SELECT
            --iid_t.iid AS iid,
            adjusted_sources_t.adjusted_source AS install_sources,
            install_sources_t.tag as tag
        FROM IndexItemRow AS iid_t
        JOIN IndexItemDetailRow as install_sources_t
            ON iid_t.iid=install_sources_t.owner_iid
            AND install_sources_t.detail_name='install_sources'
            AND install_sources_t.active=1
        JOIN AdjustedSources AS adjusted_sources_t
            ON adjusted_sources_t.detail_row_id=install_sources_t._id
        WHERE
            iid_t.iid='{the_iid}'
            AND
            iid_t.install_status != 0
            AND
            iid_t.ignore=0
        ORDER BY adjusted_sources_t.adjusted_source
        """.format(the_iid=the_iid)
        try:
            exec_result = self.session.execute(query_text)
            if exec_result.returns_rows:
                # returns [(adjusted_source, source_tag),...]
                retVal.extend(exec_result.fetchall())
        except SQLAlchemyError as ex:
            raise
        return retVal
