#!/usr/bin/env python3.9


import os
import sqlite3
import io
from collections import OrderedDict
from collections import defaultdict
import re
import yaml
from typing import List
import logging
log = logging.getLogger()

import utils
from aYaml import *
from configVar import config_vars, private_config_vars

# when adding a new OS name also add the name in init-values.ddl
os_names = ('common', 'Mac', 'Mac32', 'Mac64', 'Win', 'Win32', 'Win64', 'Linux')
allowed_item_keys = ('name', 'guid','install_sources', 'install_folders', 'inherit',
                     'depends', 'actions', 'remark', 'version', 'phantom_version',
                     'direct_sync', 'previous_sources', 'info_map')
allowed_top_level_keys = os_names[1:] + allowed_item_keys
file_types = ('!dir_cont', '!file', '!dir')


class IndexItemsTable(object):
    # when adding a new OS name also add the name in init-values.ddl
    os_names_to_num = OrderedDict([('common', 0), ('Mac', 1), ('Mac32', 2), ('Mac64', 3), ('Win', 4), ('Win32', 5), ('Win64', 6), ('Linux', 7)])
    install_status = {"none": 0, "main": 1, "update": 2, "depend": 3, "remove": -1}
    action_types = ('pre_sync', 'post_sync', 'pre_copy', 'pre_copy_to_folder', 'pre_copy_item',
                    'post_copy_item', 'post_copy_to_folder', 'post_copy',
                    'pre_remove', 'pre_remove_from_folder', 'pre_remove_item',
                    'remove_item', 'post_remove_item', 'post_remove_from_folder',
                    'post_remove', 'pre_doit', 'doit', 'post_doit')
    not_inherit_details = ("name", "inherit")

    def __init__(self, db_master) -> None:
        super().__init__()

        self.db = db_master
        self.db.open()

        # no need to clear table here, when accepting --db option for the command line
        self.os_names_db_objs = list()
        self.add_triggers()
        self.add_views()
        self.defines_for_iids = dict()  # defines which are specific to an iid

    def __del__(self):
        self.db.unlock_all_tables()

    def clear_tables(self) -> None:
        self.drop_triggers()
        self.drop_views()
        with self.db.transaction() as curs:
            curs.execute("""DELETE FROM index_item_detail_t""")
            curs.execute("""DELETE FROM index_item_t""")

    def add_triggers(self) -> None:
        self.db.exec_script_file("create-triggers.ddl")

    def drop_triggers(self) -> None:
        self.db.exec_script_file("drop-triggers.ddl")

    def add_views(self) -> None:
        self.db.exec_script_file("create-views.ddl")

    def drop_views(self) -> None:
       self.db.exec_script_file("drop-views.ddl")

    def activate_all_oses(self) -> None:
        """ adds all known os names to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        query_text = """
            UPDATE active_operating_systems_t
            SET os_is_active = 1
         """
        with self.db.transaction() as curs:
            curs.execute(query_text)

    def reset_active_oses(self) -> None:
        """ resets the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        self.activate_specific_oses()

    def activate_specific_oses(self, *for_oses) -> None:
        """ adds another os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
        """
        for_oses = *for_oses, "common"
        quoted_os_names = [utils.quoteme_double(os_name) for os_name in for_oses]
        query_vars = ", ".join(quoted_os_names)
        query_text = f"""
            UPDATE active_operating_systems_t
            SET os_is_active = CASE WHEN active_operating_systems_t.name IN ({query_vars}) THEN
                    1
                ELSE
                    0
                END;
        """
        with self.db.transaction() as curs:
            curs.execute(query_text)

    def get_active_oses(self) -> List[str]:
        query_text = """
        SELECT name, os_is_active
        FROM active_operating_systems_t
        ORDER BY _id
        """
        return self.db.select_and_fetchall(query_text)

    def get_all_require_translate_items(self) -> List[dict]:
        """
        """
        query_text = """
            SELECT * FROM require_translate_t
            ORDER BY iid
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        retVal = [{key: row[key] for key in row.keys()} for row in retVal]
        return retVal

    def get_all_index_items(self):
        """
        tested by: TestItemTable.test_??_IndexItemRow_get_item, test_??_empty_tables
        :return: list of all index_item_t objects in the db, empty list if none are found
        """
        query_text = """
            SELECT * FROM index_item_t
            ORDER BY iid
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def get_index_item(self, iid_to_get):
        """
        tested by: TestItemTable.test_ItemRow_get_item
        :return: index_item_t object matching iid_to_get or None
        """
        query_text = """
            SELECT * FROM index_item_t
            WHERE iid == :iid_to_get
            """
        retVal = self.db.select_and_fetchone(query_text, query_params={"iid_to_get": iid_to_get})
        return retVal

    def get_all_iids_with_guids(self):
        """
        :return: list of all iids in the db that have guids, empty list if none are found
        """
        query_text = """
            SELECT owner_iid, detail_value
            from index_item_detail_t
            WHERE index_item_detail_t.detail_name="guid"
            AND owner_iid=original_iid
            ORDER BY owner_iid
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def get_all_installed_iids(self) -> List[str]:
        """ get all iids that are marked as required by them selves
            which indicates they were a primary install target
        """
        query_text = """
            SELECT original_iid
            from index_item_detail_t
            WHERE index_item_detail_t.detail_name="require_by"
            AND detail_value=original_iid
            AND os_is_active = 1
            ORDER BY owner_iid
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def get_all_installed_iids_needing_update(self):
        """ Return all iids that were installed, have a version, and that version is different from the version in the index
        """
        query_text = """
                SELECT DISTINCT require_version.owner_iid, require_version.detail_value AS require, remote_version.detail_value AS remote
                FROM index_item_detail_t AS require_version
                LEFT JOIN (
                    SELECT owner_iid, detail_value, min(generation)
                    from index_item_detail_t AS remote_version
                    WHERE detail_name="version"
                    AND os_is_active = 1
                    GROUP BY owner_iid
                    ) remote_version
                WHERE detail_name="require_version"
                      AND remote_version.owner_iid=require_version.owner_iid
                      AND require_version.detail_value!=remote_version.detail_value
                      AND require_version.os_is_active = 1
                GROUP BY require_version.owner_iid
            """
            # "GROUP BY" will make sure only one row is returned for an iid.
            # multiple rows can be found if and IID has 2 previous_sources both were found
            # on disk and their version identified.
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def get_all_iids(self) -> List[str]:
        """
        tested by: TestItemTable.test_06_get_all_iids
        :return: list of all iids in the db, empty list if none are found
        """
        retVal = list()
        query_text = """SELECT iid FROM index_item_t ORDER BY iid"""
        retVal.extend(self.db.select_and_fetchall(query_text))
        return retVal

    def create_default_index_items(self, iids_to_ignore: List[str]) -> None:
        iids_to_ignore_str = utils.quoteme_double_list_for_sql(iids_to_ignore)
        query_text = f"""
        BEGIN TRANSACTION;
        INSERT INTO index_item_t (iid, inherit_resolved, from_index, from_require, install_status, ignore)
        VALUES ("__ALL_ITEMS_IID__", 1, 0, 0, 0, 0);

        INSERT INTO index_item_detail_t(original_iid, owner_iid, detail_name, detail_value, os_id, generation)
            SELECT DISTINCT "__ALL_ITEMS_IID__", "__ALL_ITEMS_IID__", "depends", index_item_t.iid, 0, 0
            FROM index_item_t
            WHERE iid NOT IN {iids_to_ignore_str};

        INSERT INTO index_item_t (iid, inherit_resolved, from_index, from_require)
        VALUES ("__ALL_GUIDS_IID__", 1, 0, 0);

        INSERT INTO index_item_detail_t(original_iid, owner_iid, detail_name, detail_value, os_id, generation)
            SELECT DISTINCT "__ALL_GUIDS_IID__", "__ALL_GUIDS_IID__", "depends", index_item_detail_t.owner_iid, 0, 0
            FROM index_item_detail_t
            WHERE index_item_detail_t.detail_name="guid"
            AND index_item_detail_t.owner_iid=index_item_detail_t.original_iid
            AND index_item_detail_t.owner_iid NOT IN {iids_to_ignore_str};
        COMMIT TRANSACTION;
        """
        with self.db.transaction() as curs:
            curs.executescript(query_text)

    def create_default_require_items(self, iids_to_ignore: List[str]) -> None:
        iids_to_ignore_str = utils.quoteme_double_list_for_sql(iids_to_ignore)
        query_text = f"""
        BEGIN TRANSACTION;
        INSERT INTO index_item_t (iid, inherit_resolved, from_index, from_require, install_status, ignore)
        VALUES ("__REPAIR_INSTALLED_ITEMS__", 1, 0, 0, 0, 0);

        INSERT INTO index_item_detail_t(original_iid, owner_iid, detail_name, detail_value, os_id, generation)
            SELECT "__REPAIR_INSTALLED_ITEMS__", "__REPAIR_INSTALLED_ITEMS__", "depends", index_item_detail_t.original_iid, 0, 0
            FROM index_item_detail_t
            WHERE index_item_detail_t.detail_name="require_by"
            AND index_item_detail_t.detail_value=index_item_detail_t.original_iid
            AND index_item_detail_t.detail_value=index_item_detail_t.owner_iid
            AND index_item_detail_t.os_is_active = 1
            AND index_item_detail_t.original_iid NOT IN {iids_to_ignore_str};

        INSERT INTO index_item_t (iid, inherit_resolved, from_index, from_require)
        VALUES ("__UPDATE_INSTALLED_ITEMS__", 1, 0, 0);

        INSERT INTO index_item_detail_t(original_iid, owner_iid, detail_name, detail_value, os_id, generation)
            SELECT "__UPDATE_INSTALLED_ITEMS__", "__UPDATE_INSTALLED_ITEMS__", "depends", require_version.owner_iid, 0, 0
            FROM index_item_detail_t AS require_version
            LEFT JOIN (
                SELECT owner_iid, detail_value, min(generation)
                from index_item_detail_t AS remote_version
                WHERE detail_name="version"
                AND os_is_active = 1
                GROUP BY owner_iid
                ) remote_version
            WHERE detail_name="require_version"
                  AND remote_version.owner_iid=require_version.owner_iid
                  AND require_version.detail_value!=remote_version.detail_value
                  AND require_version.os_is_active = 1
            GROUP BY require_version.owner_iid;
            COMMIT TRANSACTION;
        """
        with self.db.transaction() as curs:
            curs.executescript(query_text)

    def get_original_details_values_for_active_iid(self, iid: str, detail_name: str, unique_values: bool=False) -> List[str]:
        """ get the items's original (e.g. not inherited) values for a specific detail
            for specific iid - but only if detail is in active os
        """
        distinct = "DISTINCT" if unique_values else ""
        query_text = f"""
            SELECT {distinct} detail_value
            FROM index_item_detail_t
            WHERE original_iid = :iid
            AND detail_name = :detail_name
            AND os_is_active = 1
            ORDER BY _id
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'iid': iid, 'detail_name': detail_name})
        return retVal

    def get_original_details(self, iid: str, detail_name: str=None, in_os=None):
        """
        tested by: TestItemTable.test_get_original_details_* functions
        :param iid: get detail for specific iid or all if None
        :param detail_name: get detail with specific name or all names if None
        :param in_os: get detail for os name or for all oses if None
        :return: list original details in the order they were inserted
        """

        # params with None are turned to '%'
        params = [iid, detail_name, in_os]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'

        query_text = """
                    SELECT * FROM index_item_detail_t
                    WHERE original_iid==:iid
                    AND owner_iid==:iid
                    AND detail_name LIKE :detail_name
                    AND os_id LIKE :in_os
                    ORDER BY _id
                    """
        retVal = self.db.select_and_fetchall(query_text, query_params={'iid': params[0], 'detail_name': params[1], "in_os": params[2]})
        return retVal

    def get_resolved_details(self, iid: str, detail_name: str=None, in_os=None):
        """
        :param iid: get detail for specific iid or all if None
        :param detail_name: get detail with specific name or all names if None
        :param in_os: get detail for os name or for all oses if None
        :return: list original details in the order they were inserted
        """

        # params with None are turned to '%'
        params = [iid, detail_name, in_os]
        for iparam in range(len(params)):
            if params[iparam] is None: params[iparam] = '%'

        query_text = """
                    SELECT * FROM index_item_detail_t
                    WHERE owner_iid==:iid
                    AND detail_name LIKE :detail_name
                    AND os_id LIKE :in_os
                    ORDER BY _id
                    """
        retVal = self.db.select_and_fetchall(query_text, query_params={'iid': params[0], 'detail_name': params[1], "in_os": params[2]})
        return retVal

    def get_resolved_details_for_active_iid(self, iid, detail_name):
        """ get the original and inherited index_item_detail_t's for a specific detail
            for specific iid - but only if detail is in active os
        """

        query_text = """
                    SELECT * FROM index_item_detail_t
                    WHERE original_iid==:iid
                    AND detail_name == :detail_name
                    AND os_is_active == 1
                    ORDER BY _id
                    """
        retVal = self.db.select_and_fetchall(query_text, query_params={'iid': iid, 'detail_name': detail_name})
        return retVal

    def get_resolved_details_for_iid(self, iid: str, detail_name: str):
        """ get the original and inherited index_item_detail_t's for a specific detail
            for specific iid - regardless if detail is in active os
        """
        query_text = """
                    SELECT * FROM index_item_detail_t
                    WHERE original_iid==:iid
                    AND detail_name == :detail_name
                    ORDER BY _id
                    """
        retVal = self.db.select_and_fetchall(query_text, query_params={'iid': iid, 'detail_name': detail_name})
        return retVal

    def get_resolved_details_value_for_active_iid(self, iid: str, detail_name: str, unique_values: bool=False):
        """ get the original and inherited values for a specific detail
            for specific iid - but only if iid is os_is_active
        """
        distinct = "DISTINCT" if unique_values else ""
        query_text = f"""
            SELECT {distinct} detail_value
            FROM index_item_detail_t
            WHERE owner_iid = :iid
            AND detail_name = :detail_name
            AND os_is_active = 1
            ORDER BY _id
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'iid': iid, 'detail_name': detail_name})
        return retVal

    def get_resolved_details_value_for_iid(self, iid: str, detail_name: str, unique_values: bool=False):
        """ get the original and inherited values for a specific detail
            for specific iid - regardless if detail is in active os
        """
        distinct = "DISTINCT" if unique_values else ""
        query_text = f"""
            SELECT {distinct} detail_value
            FROM index_item_detail_t
            WHERE owner_iid = :iid
            AND detail_name = :detail_name
            ORDER BY _id
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'iid': iid, 'detail_name': detail_name})
        return retVal

    def get_details_by_name_for_all_iids(self, detail_name: str):
        """ get all index_item_detail_t objects with detail_name.
            detail_name can contain wildcards e.g. require_%
        """
        query_text = """
                    SELECT * FROM index_item_detail_t
                    WHERE detail_name LIKE :detail_name
                    AND os_is_active == 1
                    ORDER BY owner_iid
                    """
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name})
        return retVal

    def get_detail_values_by_name_for_all_iids(self, detail_name: str):
        """ get values of specific detail for all iids
        """
        query_text = """
            SELECT DISTINCT detail_value
            FROM index_item_detail_t
            WHERE detail_name LIKE :detail_name
            AND os_is_active = 1
            ORDER BY _id
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name})
        return retVal

    def resolve_inheritance(self) -> None:
        # utils.add_to_actions_stack("resolving inheritance")
        inherit_order, inherit_dict = self.prepare_inherit_order()
        resolve_items_script = ""
        if bool(config_vars.get("DEBUG_INDEX_DB", False)):
            with self.db.transaction() as curs:
                for iid in inherit_order:
                    try:
                        resolve_item_script = self.get_resolve_item_query_for_iid(iid, inherit_dict[iid])
                        curs.executescript(resolve_item_script)
                    except sqlite3.IntegrityError as ex:
                        log.info(f"db exception resolving inheritance for {iid}, {ex}")
                curs.execute("""CREATE INDEX IF NOT EXISTS ix_svn_index_item_detail_t_owner_iid ON index_item_detail_t(owner_iid)""")
        else:
            for iid in inherit_order:
                resolve_items_script += self.get_resolve_item_query_for_iid(iid, inherit_dict[iid])
            with self.db.transaction() as curs:
                curs.executescript(resolve_items_script) #to imporove perofrmance we first execute, then create the index
                curs.execute("""CREATE INDEX IF NOT EXISTS ix_svn_index_item_detail_t_owner_iid ON index_item_detail_t(owner_iid)""")
                # creating these indexes did not improve DB performance and added 20s to preparing __ALL_GUIDS__ installation
                #curs.execute("""CREATE INDEX IF NOT EXISTS ix_svn_index_item_detail_t_value ON index_item_detail_t(detail_value)""")
                #curs.execute("""CREATE INDEX IF NOT EXISTS ix_svn_index_item_detail_t_name ON index_item_detail_t(detail_name)""")

    def prepare_inherit_order(self):
        inherit_order = utils.unique_list()
        inherit_dict = defaultdict(list)
        query_text = """
            SELECT original_iid, detail_value
            FROM index_item_detail_t
            JOIN active_operating_systems_t
            ON active_operating_systems_t._id=os_id
            AND active_operating_systems_t.os_is_active = 1
            WHERE detail_name = 'inherit'
            """
        inherit_pairs = self.db.select_and_fetchall(query_text)
        for pair in inherit_pairs:
            inherit_dict[pair[0]].append(pair[1])

        def resolve_iid(iid):
            iis = inherit_dict.get(iid,[])
            if iis:
                for ii in iis:
                    resolve_iid(ii)
                inherit_order.append(iid)

        def check_inherit_order():
            assert len(inherit_order) == len(set(inherit_order)), "retVal has duplicates"
            assert not set(inherit_order) ^ set(inherit_dict.keys()), "retVal and inherit_dict different"
            for i in range(len(inherit_order)):
                iis = inherit_dict[inherit_order[i]]
                for ii in iis:
                    if ii in inherit_dict:
                        ii_index = inherit_order.index(ii)
                        assert ii_index < i, f"{inherit_order[i]} inherit from {ii} but {ii} does not come before {inherit_order[i]}"

        for iid in sorted(inherit_dict):
            resolve_iid(iid)
        check_inherit_order()
        return inherit_order, inherit_dict

    def get_resolve_item_query_for_iid(self, iid_to_resolve, inherit_from_iids, generation=0):
        # print("-"*generation, " ", item_to_resolve.iid)
        query_text = """
            INSERT INTO index_item_detail_t(original_iid,
                                            owner_iid,
                                            os_id,
                                            detail_name,
                                            detail_value,
                                            generation,
                                            tag,
                                            os_is_active)
            SELECT
              inherited_details_t.original_iid,
              {inheritor_iid} AS owner_id,
              inherited_details_t.os_id,
              inherited_details_t.detail_name,
              inherited_details_t.detail_value,
              inherited_details_t.generation+1,
              inherited_details_t.tag,
              inherited_details_t.os_is_active
            FROM index_item_detail_t AS inherited_details_t
              JOIN active_operating_systems_t
                ON active_operating_systems_t._id=inherited_details_t.os_id
                AND active_operating_systems_t.os_is_active = 1
            WHERE inherited_details_t.owner_iid IN {inherit_from_iids}
            AND inherited_details_t.detail_name NOT IN {not_inherit_details};

            """.format(**{"inheritor_iid": utils.quoteme_single(iid_to_resolve),
                      "inherit_from_iids": utils.quoteme_single_list_for_sql(inherit_from_iids),
                      "not_inherit_details": utils.quoteme_single_list_for_sql(self.not_inherit_details)})
        return query_text

    def read_item_details_from_node(self, the_iid, the_node, the_os='common', **kwargs) -> List:
        details = list()
        # go through the raw yaml nodes instead of doing "for detail_name in the_node".
        # this is to overcome index.yaml with maps that have two keys with the same name.
        # Although it's not valid yaml some index.yaml versions have this problem.
        try:
            detail_name = ""
            for detail_node in the_node.value:
                with kwargs['node-stack'](detail_node):
                    detail_name = detail_node[0].value
                    with kwargs['node-stack'](detail_node[1]):
                        if detail_name in IndexItemsTable.os_names_to_num:
                            os_specific_details = self.read_item_details_from_node(the_iid, detail_node[1], the_os=detail_name, **kwargs)
                            details.extend(os_specific_details)
                        elif detail_name == 'actions':
                            actions_details = self.read_item_details_from_node(the_iid, detail_node[1], the_os, **kwargs)
                            details.extend(actions_details)
                        elif detail_name.startswith("define"):
                            self.defines_for_iids[the_iid] = detail_node[1]
                            self.defines_for_iids[the_iid].tag = "!"+detail_name
                        else:
                            for details_line in detail_node[1]:
                                with kwargs['node-stack'](details_line):
                                    tag = details_line.tag if details_line.tag[0] == '!' else None
                                    value = details_line.value
                                    if detail_name in ("install_sources", "previous_sources") and tag is None:
                                        tag = '!dir'
                                    elif detail_name == "guid":
                                        if value:
                                            value = value.lower()

                                    if detail_name == "install_sources":
                                        if value.startswith('/'):  # absolute path
                                            new_detail = (the_iid, the_iid, self.os_names_to_num[the_os],
                                                            detail_name, value[1:], tag)
                                            details.append(new_detail)
                                        else:  # relative path
                                            # because 'common' is in both groups this will create 2 index_item_detail_t
                                            # if OS is 'common', and 1 otherwise
                                            count_insertions = 0
                                            for os_group in (('common', 'Mac', 'Mac32', 'Mac64'),
                                                             ('common', 'Win', 'Win32', 'Win64')):
                                                if the_os in os_group:
                                                    item_detail_os = {'Mac32': 'Mac32', 'Mac64': 'Mac64', 'Win32': 'Win32', 'Win64': 'Win64'}.get(the_os, os_group[1])
                                                    path_prefix_os = {'Mac32': 'Mac', 'Mac64': 'Mac', 'Win32': 'Win', 'Win64': 'Win'}.get(the_os, os_group[1])
                                                    assert path_prefix_os == "Mac" or path_prefix_os == "Win", f"path_prefix_os: {path_prefix_os}"
                                                    new_detail = (the_iid, the_iid, self.os_names_to_num[item_detail_os],
                                                                    detail_name, "/".join((path_prefix_os, value)), tag)
                                                    details.append(new_detail)
                                                    count_insertions += 1
                                            assert count_insertions < 3, f"count_insertions: {count_insertions}"
                                    else:
                                        new_detail = (the_iid, the_iid, self.os_names_to_num[the_os], detail_name, value, tag)
                                        details.append(new_detail)
        except Exception as ex:
            print(f"exception while reading details for iid {the_iid}")
            print(f"lines {the_node.start_mark.line} - {the_node.end_mark.line}")
            if detail_name:
                print(f"detail name {detail_name}")
            raise
        return details

    def item_from_index_node(self, the_iid: str, the_node: yaml.MappingNode, **kwargs) -> ((str, bool), List):
        item = (the_iid, True)
        original_details = self.read_item_details_from_node(the_iid, the_node, **kwargs)
        return item, original_details

    template_re = re.compile("""(?P<template_name>.*)<(?P<template_args>[^>]*)>""")

    def read_index_node_helper(self, a_node: yaml.MappingNode, index_items: List, items_details: List, **kwargs) -> None:
        """ read index node to index_items+items_details lists, but do not commit to DB
            Helps read_index_node read template definitions without intermediate commits
            :param **kwargs:
        """
        for IID in a_node:
            template_match = self.template_re.match(IID)
            with kwargs['node-stack'](a_node[IID]):
                if template_match:
                    try:
                        node = self.read_index_template_node(template_match, a_node[IID], **kwargs)
                        self.read_index_node_helper(node, index_items, items_details, **kwargs)
                    except:
                        raise
                else:
                    item, original_item_details = self.item_from_index_node(IID, a_node[IID], **kwargs)
                    index_items.append(item)
                    items_details.extend(original_item_details)

    def read_index_node(self, a_node: yaml.MappingNode, **kwargs) -> None:
        if bool(config_vars.get("DEBUG_INDEX_DB", False)):
            print("DEBUG_INDEX_DB is true reading index one by one")
            self.read_index_node_one_by_one(a_node, **kwargs)
            return

        index_items = list()
        items_details = list()

        self.read_index_node_helper(a_node, index_items, items_details, **kwargs)

        insert_item_q =        """INSERT INTO index_item_t(iid, from_index) VALUES(?, ?)"""
        insert_item_detail_q = """INSERT INTO index_item_detail_t(original_iid, owner_iid, os_id,
                                                                  detail_name, detail_value, tag)
                                                                  VALUES(?,?,?,?,?,?)"""
        with self.db.transaction(description="read_index_node", progress_callback=kwargs.get('progress_callback', None)) as curs:
            curs.executemany(insert_item_q, index_items)
            curs.executemany(insert_item_detail_q, items_details)
            curs.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ix_index_item_t_iid ON index_item_t(iid)""")
            curs.execute("""CREATE INDEX IF NOT EXISTS ix_index_item_t_owner_iid ON index_item_detail_t(owner_iid)""")

    def read_index_node_one_by_one(self, a_node: yaml.MappingNode, **kwargs) -> None:
        """ for debugging problems with reading index.yaml use read_index_node_one_by_one instead of read_index_node"""
        insert_item_q =        """INSERT INTO index_item_t(iid, from_index) VALUES(?, ?)"""
        insert_item_detail_q = """INSERT INTO index_item_detail_t(original_iid, owner_iid, os_id,
                                                                  detail_name, detail_value, tag)
                                                                  VALUES(?,?,?,?,?,?)"""
        current_iid = None       # to keep track which iid is causing problems
        current_template = None  # to keep track which template is causing problems
        current_node = a_node  # to keep track which node is causing problems
        current_detail = None
        for IID_or_template in a_node:
            current_iid = IID_or_template
            try:
                current_node = a_node[IID_or_template]
                with kwargs['node-stack'](a_node[IID_or_template]):
                    index_items = list()
                    items_details = list()

                    template_match = self.template_re.match(IID_or_template)
                    if template_match:
                        current_template = IID_or_template
                        node = self.read_index_template_node(template_match, a_node[IID_or_template], **kwargs)
                        self.read_index_node_helper(node, index_items, items_details, **kwargs)
                    else:
                        current_template = None
                        item, original_item_details = self.item_from_index_node(IID_or_template, a_node[IID_or_template], **kwargs)
                        index_items.append(item)
                        items_details.extend(original_item_details)

                    with self.db.transaction() as curs:
                        for item in index_items:
                            current_iid = item[0]
                            curs.execute(insert_item_q, item)
                        for detail in items_details:
                            current_detail = detail
                            curs.execute(insert_item_detail_q, detail)
                        curs.execute("""CREATE UNIQUE INDEX IF NOT EXISTS ix_index_item_t_iid ON index_item_t(iid)""")
                        curs.execute("""CREATE INDEX IF NOT EXISTS ix_index_item_t_owner_iid ON index_item_detail_t(owner_iid)""")
            except Exception as ex:
                try:
                    from rich.console import Console
                    console = Console()
                    rich_print = console.print
                    rich_ruler = console.rule
                except:
                    rich_print = print
                    rich_ruler = print

                rich_ruler(f"[blue underline]failed reading {current_iid}")
                if current_template and current_template != current_iid:
                    rich_print(f"    from template {current_template}")
                if current_detail:
                    rich_print(f"    {current_detail}")
                if hasattr(ex, "lines"):
                    rich_print(f"    lines {ex.lines[0]} -> {ex.lines[0]}")
                else:
                    rich_print(f"    lines {current_node.start_mark.line} -> {current_node.end_mark.line}")
                rich_print(f"    {ex}")
                rich_ruler("***")
                raise

    def read_index_template_node(self, template_match, instances_node, **kwargs):
        resolve_one_by_one = bool(config_vars.get("DEBUG_INDEX_DB", False))
        try:
            lines_range = instances_node.start_mark.line, instances_node.end_mark.line
            template_name = template_match['template_name']
            template_args = template_match['template_args'].split(',')
            template_args = [a.strip() for a in template_args]
            template_text = config_vars[template_name].raw()
            yaml_stream = io.StringIO("--- !index\n")
            for instance_node in instances_node.value:
                with kwargs['node-stack'](instance_node):
                    lines_range = instance_node.start_mark.line+1, instance_node.end_mark.line+1
                    if instance_node.isSequence():
                        with private_config_vars() as pcf:  # use private config vars so that only template parameters will be resolved
                            arg_values = list(zip(template_args, [var_val.value for var_val in instance_node.value]))
                            for arg, val in arg_values:
                                pcf[arg] = val
                            resolved_instance = pcf.shallow_resolve_str(template_text)
                            yaml_stream.write(resolved_instance)
                            if resolve_one_by_one:  # call yaml.compose so that it will raise exception in case of error
                                yaml_stream.seek(0, io.SEEK_SET)
                                yaml.compose(yaml_stream)
                                yaml_stream.seek(0, io.SEEK_END)
            # yaml_stream = io.StringIO(yaml_text)  # convert the test to stream so 'name' attrib can be set,
            yaml_stream.name = template_name      # which is useful for error reporting
            yaml_stream.seek(0, io.SEEK_SET)
            out_node = yaml.compose(yaml_stream)
            YamlReader.convert_standard_tags(out_node)
        except Exception as ex:
            new_ex = ValueError(f"while parsing template {template_name}")
            new_ex.lines = lines_range
            raise new_ex from ex
        return out_node

    def clean_require_items(self, require_details):
        aux_guids = []
        aux_iids = list(config_vars.get("AUXILIARY_IIDS", []))
        for iid in aux_iids:
            guid = self.get_resolved_details_value_for_iid(iid, "guid")
            aux_guids.extend(guid)

        should_not_be_required_by_text = config_vars.get("SHOULD_NOT_BE_REQUIRED_BY", "a^").str()
        should_not_be_required_by_re = re.compile(should_not_be_required_by_text)

        iids_from_require = [*require_details]
        for iid in iids_from_require:
            good_require_by_count = 0
            old_details_list = require_details[iid]
            new_details_list = []
            for details in old_details_list:
                # replace guids such as UNINSTALL_AS_PLUGIN  with the real guid, or erase if no real guid exists
                use_new_detail = True
                if details['detail_name'] == 'require_guid':
                    if not details['detail_value'] or details['detail_value'] in aux_guids:  # aux_guids are the guids that should not appear as require_guid
                        real_guid = self.get_resolved_details_value_for_iid(iid, "guid")
                        if real_guid:  # real_guid is a list, might be empty
                            details['detail_value'] = real_guid[0]
                        else:
                            use_new_detail = False
                elif details['detail_name'] == "require_by":
                    if not details['detail_value']:
                        use_new_detail = False
                    else:
                        # only add the require_by field if it's NOT one of the guids matching the regex in SHOULD_NOT_BE_REQUIRED_BY
                        match = should_not_be_required_by_re.match(details['detail_value'])
                        if not match:
                            good_require_by_count += 1
                        else:
                            use_new_detail = False

                if use_new_detail:
                    new_details_list.append(details)

            if good_require_by_count == 0:
                # totally remove IIDs that (after cleaning) are not required by anyone
                del require_details[iid]
                #print(f"erase {iid} no require_by left")
            else:
                require_details[iid] = new_details_list

    def read_require_node(self, a_node: yaml.MappingNode, **kwargs):

        require_items = dict()
        if a_node.isMapping():
            all_iids = self.get_all_iids()
            for IID in a_node:
                with kwargs['node-stack'](a_node[IID]):
                    require_details = self.read_item_details_from_require_node(IID, a_node[IID], all_iids)
                    if require_details:
                        require_items[IID] = require_details

            self.clean_require_items(require_items)

            query_text1 = """
                INSERT INTO index_item_detail_t
                (original_iid, owner_iid, os_id, detail_name, detail_value)
                SELECT index_item_t.iid, :owner_iid, :os_id, :detail_name, :detail_value
                FROM index_item_t
                WHERE :original_iid == index_item_t.iid
                """
            all_details = list()
            for details_for_iid in require_items.values():
                all_details.extend(details_for_iid)

            req_items_formatted_for_sqlite = utils.quoteme_single_list_for_sql(require_items.keys())
            query_text2 = f"""
                UPDATE OR IGNORE index_item_t
                SET from_require=1
                WHERE iid in {req_items_formatted_for_sqlite}
                """
            with self.db.transaction() as curs:
                curs.executemany(query_text1, all_details)
                curs.execute(query_text2)

    def read_item_details_from_require_node(self, the_iid, the_node, all_iids):
        the_os_id = self.os_names_to_num['common']
        details = list()
        if the_node.isMapping():
            for detail_name in the_node:
                if detail_name == "guid":
                    for guid_sub in the_node["guid"]:
                        new_detail = {"original_iid": the_iid, "owner_iid": the_iid, "os_id": the_os_id, "detail_name": "require_guid", "detail_value": guid_sub.value}
                        details.append(new_detail)
                elif detail_name == "version":
                     for version_sub in the_node["version"]:
                        new_detail = {"original_iid": the_iid, "owner_iid": the_iid, "os_id": the_os_id, "detail_name": "require_version", "detail_value": version_sub.value}
                        details.append(new_detail)
                elif detail_name == "require_by":
                    for require_by in the_node["require_by"]:
                        if require_by.value in all_iids:
                            detail_name = "require_by"
                        else:
                            detail_name = "deprecated_require_by"
                        new_detail = {"original_iid": the_iid, "owner_iid": the_iid, "os_id": the_os_id, "detail_name": detail_name, "detail_value": require_by.value}
                        details.append(new_detail)
        elif the_node.isSequence():
            for require_by in the_node:
                if require_by.value in all_iids:
                    detail_name = "require_by"
                else:
                    detail_name = "deprecated_require_by"
                details.append({"original_iid": the_iid, "owner_iid": the_iid, "os_id": the_os_id, "detail_name": detail_name, "detail_value": require_by.value})
        return details

    def repr_item_for_yaml(self, iid, resolve=False):
        item_details = OrderedDict()
        for os_name, os_num in self.os_names_to_num.items():
            if resolve:
                details_rows = self.get_resolved_details(iid=iid)
            else:
                details_rows = self.get_original_details(iid=iid, in_os=os_num)
            if len(details_rows) > 0:
                if os_name == "common":
                    work_on_dict = item_details
                else:
                    work_on_dict = item_details[os_name] = OrderedDict()
                for details_row in details_rows:
                    detail_name = details_row['detail_name']
                    if detail_name in self.action_types:
                        if 'actions' not in work_on_dict:
                            work_on_dict['actions'] = OrderedDict()
                        if detail_name not in work_on_dict['actions']:
                            work_on_dict['actions'][detail_name] = list()
                        work_on_dict['actions'][detail_name].append(details_row['detail_value'])
                    else:
                        if detail_name not in work_on_dict:
                            work_on_dict[detail_name] = list()
                        work_on_dict[detail_name].append(details_row['detail_value'])
        return item_details

    def repr_for_yaml(self, resolve=False):
        retVal = OrderedDict()
        the_items = self.get_all_index_items()
        for item in the_items:
            iid = item['iid']
            retVal[iid] = self.repr_item_for_yaml(iid, resolve)
        return retVal

    def versions_report(self, report_only_installed=False, progress_callback=None):
        query_text = """
            SELECT *
            FROM 'report_versions_view'
            """
        if report_only_installed:
            query_text += """
            WHERE require_version != '_'
            AND remote_version != '_'
            """
        results = self.db.select_and_fetchall(query_text, query_params={}, progress_callback=progress_callback)
        retVal = [mm[:6] for mm in results]
        return retVal

        return retVal

    def iids_from_guids(self, guid_list):
        translated_iids = list()
        orphaned_guids = list()
        if guid_list:
            with self.db.temp_transaction() as curs:
                curs.execute("""
                CREATE TEMP TABLE guid_to_iid_temp_t
                (
                    _id  INTEGER PRIMARY KEY,
                    guid TEXT,
                    iid  TEXT
                );
                """)
                # add all guids to table guid_to_iid_temp_t with iid field defaults to Null
                reduced_guid_list = [(guid,) for guid in set(guid_list)]
                curs.executemany("""INSERT INTO guid_to_iid_temp_t (guid) VALUES (?)""", reduced_guid_list)

                # insert to table guid_to_iid_temp_t guid, iid pairs.
                # a guid might yield 0, 1, or more iids
                query_text = """
                    INSERT INTO guid_to_iid_temp_t(guid, iid)
                    SELECT index_item_detail_t.detail_value, index_item_detail_t.owner_iid
                    FROM index_item_detail_t
                    WHERE
                        index_item_detail_t.detail_name='guid'
                        AND index_item_detail_t.detail_value IN (SELECT guid FROM guid_to_iid_temp_t WHERE iid IS NULL);
                    """
                curs.execute(query_text)

                # return a list of guids with count of 1 which are guids that could not be translated to iids
                query_text = """
                    SELECT guid FROM guid_to_iid_temp_t
                    GROUP BY guid
                    HAVING count(guid) < 2;
                    """
                counted_orphaned_guids = curs.execute(query_text).fetchall()
                orphaned_guids.extend([iid[0] for iid in counted_orphaned_guids])

                not_null_iids = curs.execute("""SELECT DISTINCT iid FROM guid_to_iid_temp_t WHERE iid NOTNULL ORDER BY iid""").fetchall()
                translated_iids.extend([iid[0] for iid in not_null_iids])

                curs.execute("""DROP TABLE guid_to_iid_temp_t;""")
        return translated_iids, orphaned_guids

    # find which iids are in the database
    def iids_from_iids(self, iid_list):
        existing_iids = None
        orphan_iids = None
        query_vars = utils.quoteme_double_list_for_sql(iid_list)
        query_text = f"""
            SELECT iid
            FROM index_item_t
            WHERE iid IN {query_vars}
        """
        existing_iids = self.db.select_and_fetchall(query_text, query_params={})
        # query will return list those iid in iid_list that were found in the index
        orphan_iids = list(set(iid_list)-set(existing_iids))
        return existing_iids, orphan_iids

    def get_recursive_dependencies(self, look_for_status=1):
        query_text = """
            WITH RECURSIVE find_dependants(_IID_) AS
            (
            SELECT iid FROM index_item_t
            WHERE install_status=:look_for_status AND ignore = 0
            UNION

            SELECT index_item_detail_t.detail_value
            FROM index_item_detail_t, find_dependants
            WHERE
                index_item_detail_t.detail_name = 'depends'
            AND
                index_item_detail_t.owner_iid = find_dependants._IID_
            AND
                index_item_detail_t.os_is_active = 1
            )
            SELECT _IID_ FROM find_dependants
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'look_for_status': look_for_status})
        return retVal

    def change_status_of_iids_to_another_status__(self, old_status, new_status, iid_list):
        if iid_list:
            query_vars = '("' + '","'.join(iid_list) + '")'
            query_text = f"""
                UPDATE index_item_t
                SET install_status={new_status}
                WHERE install_status={old_status}
                AND iid IN {query_vars}
                AND ignore = 0
              """
            with self.db.transaction() as curs:
                curs.execute(query_text)

    def change_status_of_iids_to_another_status(self, old_status, new_status, iid_list, progress_callback=None):
        if iid_list:
            if bool(config_vars.get("DEBUG_INDEX_DB", False)):  # debug code
                for iid in iid_list:
                    try:
                        query_text = f"""
                            UPDATE index_item_t
                            SET install_status={new_status}
                            WHERE iid == "{iid}"
                            AND install_status={old_status}
                            AND ignore = 0
                          """
                        with self.db.transaction() as curs:
                            curs.execute(query_text)
                    except Exception as ex:
                        print(f"failed change_status_of_iids_to_another_status {iid}: {ex}")
                        raise
            else:  # release code
                query_vars = ((iid,) for iid in iid_list)
                query_text = f"""
                    UPDATE index_item_t
                    SET install_status={new_status}
                    WHERE iid == ?
                    AND install_status={old_status}
                    AND ignore = 0
                  """
                description = f"change status of iids from {old_status} to {new_status}"
                with self.db.transaction(description=description, progress_callback=progress_callback) as curs:
                    curs.executemany(query_text, query_vars)

    def change_status_of_iids(self, new_status, iid_list):
        if iid_list:
            query_vars = '("' + '","'.join(iid_list) + '")'
            query_text = f"""
                    UPDATE index_item_t
                    SET install_status={new_status}
                    WHERE iid IN {query_vars}
                    AND ignore = 0
                  """
            with self.db.transaction() as curs:
                curs.execute(query_text)

    def change_status_of_all_iids(self, new_status):

        if bool(config_vars.get("DEBUG_INDEX_DB", False)):
            all_iids = self.get_all_iids()
            for IID in all_iids:
                try:
                    query_text = """
                        UPDATE index_item_t
                        SET install_status=:new_status
                        WHERE iid == :IID
                    """
                    with self.db.transaction() as curs:
                        curs.execute(query_text, {'new_status': new_status, "IID": IID})
                except Exception as ex:
                    print("failed change status of {}: {}".format(IID, ex))
                    raise
        else:
            query_text = """
                UPDATE index_item_t
                SET install_status=:new_status
            """
            with self.db.transaction() as curs:
                curs.execute(query_text, {'new_status': new_status})

    def get_iids_by_status(self, min_status, max_status=None):
        if max_status is None:
            max_status = min_status

        query_text = """
            SELECT iid
            FROM index_item_t
            WHERE install_status >= :min_status
            AND install_status <= :max_status
            AND ignore = 0
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'min_status': min_status, 'max_status': max_status})
        return retVal

    def select_versions_for_installed_item(self):
        query_text = """
            SELECT index_item_detail_t.owner_iid, index_item_detail_t.detail_name, index_item_detail_t.detail_value, min(index_item_detail_t.generation)
            FROM index_item_t, index_item_detail_t
            WHERE index_item_t.install_status > 0
            AND index_item_t.ignore = 0
            AND index_item_t.iid=index_item_detail_t.owner_iid
            AND index_item_detail_t.detail_name='version'
            GROUP BY index_item_detail_t.owner_iid
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def target_folders_to_items(self):
        """ returns a list of (IID, install_folder, tag, direct_syc_indicator) """
        query_text = """
            SELECT index_item_detail_t.owner_iid,
                  index_item_detail_t.detail_value,
                  index_item_detail_t.tag,
                  direct_sync_t.detail_value
            FROM index_item_detail_t, index_item_t
            LEFT JOIN index_item_detail_t AS direct_sync_t
              ON index_item_t.iid=direct_sync_t.owner_iid
                AND direct_sync_t.detail_name = 'direct_sync'
                AND direct_sync_t.os_is_active = 1
            WHERE index_item_detail_t.detail_name="install_folders"
                AND index_item_t.iid=index_item_detail_t.owner_iid
                AND index_item_t.install_status != 0
                AND index_item_t.ignore = 0
                AND index_item_detail_t.os_is_active = 1
            ORDER BY index_item_detail_t.detail_value
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def source_folders_to_items_without_target_folders(self):
        query_text = """
           SELECT
              install_sources_t.detail_value source,
              install_sources_t.owner_iid AS iid,
              install_sources_t.tag AS tag
            FROM index_item_detail_t AS install_sources_t, index_item_t
            WHERE install_sources_t.owner_iid NOT IN (
                SELECT DISTINCT install_folders_t.owner_iid
                FROM index_item_detail_t AS install_folders_t, index_item_t
                WHERE install_folders_t.detail_name = "install_folders"
                      AND index_item_t.iid = install_folders_t.owner_iid
                      AND index_item_t.install_status > 0
                      AND index_item_t.ignore = 0
                      AND install_folders_t.os_is_active = 1
                ORDER BY install_folders_t.owner_iid
            )
            AND install_sources_t.detail_name="install_sources"
                AND index_item_t.iid = install_sources_t.owner_iid
                AND index_item_t.install_status != 0
                AND index_item_t.ignore = 0
                AND install_sources_t.os_is_active = 1
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def set_name_and_version_for_active_iids(self):
        """ Add detail named "name_and_version" to index_item_detail_t
            value is in the format 'name vVersion', or if no version is found, just 'name'.
            If no name if found for an iid the iid itself is used as a name
            using the function in a query can only be done with the connection that called create_function.
        """
        def _name_and_version(iid, name, version):
            retVal = ""
            if not name or name == '_':
                name = iid
            if not version or version == '_':
                retVal = name
            else:
                retVal = name + " v" + version
            return retVal
        self.db.create_function("name_and_version", 3, _name_and_version)

        query_text = """
        INSERT INTO index_item_detail_t
        (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT
            report_versions_view.owner_iid,
            report_versions_view.owner_iid,
            0,
            "name_and_version",
            name_and_version(report_versions_view.owner_iid, report_versions_view.name, report_versions_view.remote_version),
            report_versions_view.generation
        FROM report_versions_view
        JOIN index_item_t
            ON  index_item_t.iid=owner_iid
            AND index_item_t.install_status!=0
            AND index_item_t.ignore=0
        """
        with self.db.transaction() as curs:
           curs.execute(query_text)

    def get_iids_and_details_for_active_iids(self, detail_name, unique_values=False, limit_to_iids=None):
        retVal = list()
        group_by_values_filter = "GROUP BY index_item_detail_t.detail_value" if unique_values else ""
        limit_to_iids_filter = ""
        if limit_to_iids:
            quoted_limit_to_iids = [utils.quoteme_single(iid) for iid in limit_to_iids]
            limit_to_iids_filter = " ".join(('AND index_item_detail_t.owner_iid IN (', ",".join(quoted_limit_to_iids), ')'))

        query_text = f"""
            SELECT  index_item_detail_t.owner_iid, index_item_detail_t.detail_value
            FROM index_item_detail_t
                JOIN index_item_t
                    ON  index_item_t.iid=index_item_detail_t.owner_iid
                    AND index_item_t.install_status!=0
                    AND index_item_t.ignore = 0
            WHERE index_item_detail_t.detail_name=:detail_name
                AND index_item_detail_t.os_is_active = 1
            {limit_to_iids_filter}
            {group_by_values_filter}
            ORDER BY index_item_detail_t._id
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name})
        return retVal

    def get_details_for_active_iids(self, detail_name, unique_values=False, limit_to_iids=None):
        distinct = "DISTINCT" if unique_values else ""
        limit_to_iids_filter = ""
        if limit_to_iids:
            quoted_limit_to_iids = [utils.quoteme_single(iid) for iid in limit_to_iids]
            limit_to_iids_filter = " ".join(('AND index_item_detail_t.owner_iid IN (', ",".join(quoted_limit_to_iids), ')'))

        query_text = f"""
            SELECT {distinct} index_item_detail_t.detail_value
            FROM index_item_detail_t
                JOIN index_item_t
                    ON  index_item_t.iid=index_item_detail_t.owner_iid
                    AND index_item_t.install_status!=0
                    AND index_item_t.ignore = 0
            WHERE index_item_detail_t.detail_name=:detail_name
                AND index_item_detail_t.os_is_active = 1
                {limit_to_iids_filter}
            ORDER BY index_item_detail_t._id
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name})
        return retVal

    def get_details_and_tag_for_active_iids(self, detail_name, unique_values=False, limit_to_iids=None):
        retVal = list()
        distinct = "DISTINCT" if unique_values else ""
        limit_to_iids_filter = ""
        if limit_to_iids:
            limit_to_iids_filter = 'AND index_item_detail_t.owner_iid IN ("'
            limit_to_iids_filter += '","'.join(limit_to_iids)
            limit_to_iids_filter += '")'

        query_text = f"""
            SELECT {distinct} index_item_detail_t.detail_value, index_item_detail_t.tag
            FROM index_item_detail_t
                JOIN index_item_t
                    ON  index_item_t.iid=index_item_detail_t.owner_iid
                    AND index_item_t.install_status!=0
                    AND index_item_t.ignore = 0
            WHERE index_item_detail_t.detail_name=:detail_name
                AND index_item_detail_t.os_is_active = 1
                {limit_to_iids_filter}
            ORDER BY index_item_detail_t._id
            """
        # returns: [(iid, index_version, require_version, index_guid, require_guid, generation), ...]
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name})
        return retVal

    def create_default_items(self, iids_to_ignore):
        self.create_default_index_items(iids_to_ignore=iids_to_ignore)
        self.create_default_require_items(iids_to_ignore=iids_to_ignore)

    def require_items_without_version_or_guid(self):
        query_text = """
          SELECT index_item_t.iid,
                index_ver_t.detail_value AS index_version,
                require_ver_t.detail_value AS require_version,
                index_guid_t.detail_value AS index_guid,
                require_guid_t.detail_value AS require_guid,
                min(index_ver_t.generation) AS generation
            from index_item_t
                JOIN index_item_detail_t AS index_ver_t ON index_item_t.iid = index_ver_t.owner_iid
                AND index_ver_t.detail_name='version'
                Left JOIN index_item_detail_t AS require_ver_t ON index_item_t.iid = require_ver_t.owner_iid
                AND require_ver_t.detail_name='require_version'
                JOIN index_item_detail_t AS index_guid_t ON index_item_t.iid = index_guid_t.owner_iid
                AND index_guid_t.detail_name='guid'
                Left JOIN index_item_detail_t AS require_guid_t ON index_item_t.iid = require_guid_t.owner_iid
                AND require_guid_t.detail_name='require_guid'
            WHERE from_require=1 AND (require_ver_t.detail_value ISNULL OR require_guid_t.detail_value ISNULL)
            GROUP BY index_item_t.iid
          """
        # returns: [(iid, index_version, require_version, index_guid, require_guid, generation), ...]
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def insert_binary_versions(self, binaries_version_list):
        binaries_version_to_insert = list()
        for binary_details in binaries_version_list:
            folder, name = os.path.split(binary_details[0])
            binaries_version_to_insert.append((name, *binary_details))
        self.add_binary_versions(binaries_version_to_insert)

    def add_binary_versions(self, binaries_version_list):
         query_text = """INSERT INTO found_installed_binaries_t(name, path, version, guid)
                        VALUES (?, ?, ?, ?)
                     """
         with self.db.transaction() as curs:
            curs.executemany(query_text, binaries_version_list)

    def add_require_version_from_binaries(self):
        """ add require_version for iid that do not have this detail value (because previous index.yaml did not have it)
        1st try version found on disk from table found_installed_binaries_t
        2nd for iids still missing require_version try phantom_version detail value
        """
        query_text1 = """
        INSERT OR REPLACE INTO index_item_detail_t (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  found_installed_binaries_t.iid, -- original_iid
                found_installed_binaries_t.iid, -- owner_iid
                0,                      -- os_id
                'require_version',      -- detail_name
                found_installed_binaries_t.version, -- detail_value from disk
                0                       -- generation
        FROM require_items_without_require_version_view
        JOIN found_installed_binaries_t
            ON found_installed_binaries_t.iid=require_items_without_require_version_view.iid
            AND found_installed_binaries_t.version NOTNULL
        """

        query_text2 = """
        INSERT OR REPLACE INTO index_item_detail_t (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  index_item_detail_t.owner_iid, -- original_iid
                index_item_detail_t.owner_iid, -- owner_iid
                0,                      -- os_id
                'require_version',      -- detail_name
                index_item_detail_t.detail_value, -- detail_value from phantom_version
                0                       -- generation
        FROM require_items_without_require_version_view
        JOIN index_item_detail_t
            ON index_item_detail_t.owner_iid=require_items_without_require_version_view.iid
            AND index_item_detail_t.detail_name='phantom_version'
        """
        with self.db.transaction() as curs:
            curs.execute(query_text1)
            curs.execute(query_text2)

    def add_require_guid_from_binaries(self):
        query_text = """
        INSERT OR REPLACE INTO index_item_detail_t (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT  found_installed_binaries_t.iid,  -- original_iid
                found_installed_binaries_t.iid,  -- owner_iid
                0,                       -- os_id
                'require_guid',          -- detail_name
                found_installed_binaries_t.guid, -- detail_value
                0                        -- generation
        FROM require_items_without_require_guid_view
        JOIN found_installed_binaries_t
            ON found_installed_binaries_t.iid=require_items_without_require_guid_view.iid
            AND found_installed_binaries_t.guid NOTNULL
        """
        with self.db.transaction() as curs:
            curs.execute(query_text)

    def set_ignore_iids(self, iid_list):
        if iid_list:
            query_vars = utils.quoteme_single_list_for_sql(iid_list)
            query_text = f"""
                UPDATE index_item_t
                SET ignore=1
                WHERE iid IN {query_vars}
              """
            with self.db.transaction() as curs:
                curs.execute(query_text)

    def config_var_list_to_db(self, in_config_var_list):
        try:
            config_var_insert_list = list()
            for identifier in in_config_var_list.keys():
                raw_value = in_config_var_list[identifier].raw(join_sep=", ")
                resolved_value = in_config_var_list[identifier].join(" ")
                config_var_insert_list.append((identifier, raw_value, resolved_value))
            self.add_config_vars(config_var_insert_list)
        except Exception as ex:  # config vars are written to db for reference so we can continue even if exception ware raised
            log.warning(ex)

    def add_config_vars(self, list_of_config_var_values):
        query_text = """INSERT INTO config_var_t(name, raw_value, resolved_value)
                            VALUES (?, ?, ?)
                         """
        with self.db.transaction() as curs:
            curs.executemany(query_text, list_of_config_var_values)

    def mark_direct_sync_items(self):
        def _get_direct_sync_status_from_indicator(direct_sync_indicator):
            retVal = False
            if direct_sync_indicator is not None:
                try:
                    retVal = utils.str_to_bool_int(config_vars.resolve_str(direct_sync_indicator))
                except:
                    pass
            return retVal
        self.db.create_function("get_direct_sync_status_from_indicator", 1, _get_direct_sync_status_from_indicator)

        query_text = """
        INSERT INTO index_item_detail_t
        (original_iid, owner_iid, os_id, detail_name, detail_value, generation)
        SELECT
            report_versions_view.owner_iid,
            report_versions_view.owner_iid,
            0,
            "name_and_version",
            name_and_version(report_versions_view.owner_iid, report_versions_view.name, report_versions_view.remote_version),
            report_versions_view.generation
        FROM report_versions_view
        JOIN index_item_t
            ON  index_item_t.iid=owner_iid
            AND index_item_t.install_status!=0
            AND index_item_t.ignore=0
        """
        with self.db.transaction() as curs:
            curs.execute(query_text)

    def get_sync_folders_and_sources_for_active_iids(self):
        query_text = """
             SELECT install_sources_t.owner_iid AS iid,
                    direct_sync_t.detail_value AS direct_sync_indicator,
                    install_sources_t.detail_value AS source,
                    install_sources_t.tag AS tag,
                    install_folders_t.detail_value AS install_folder
            FROM index_item_detail_t AS install_sources_t
                JOIN index_item_t AS iid_t
                    ON iid_t.iid=install_sources_t.owner_iid
                    AND iid_t.install_status > 0
                LEFT JOIN index_item_detail_t AS install_folders_t
                    ON install_folders_t.os_is_active=1
                    AND install_sources_t.owner_iid = install_folders_t.owner_iid
                        AND install_folders_t.detail_name='install_folders'
                LEFT JOIN index_item_detail_t AS direct_sync_t
                    ON direct_sync_t.os_is_active=1
                    AND install_sources_t.owner_iid = direct_sync_t.owner_iid
                        AND direct_sync_t.detail_name='direct_sync'
            WHERE
                install_sources_t.os_is_active=1
                AND install_sources_t.detail_name='install_sources'
        """
        # returns [(iid, direct_sync_indicator, source, source_tag, install_folder),...]
        retVal = self.db.select_and_fetchall(query_text, query_params={})
        return retVal

    def get_sources_for_iid(self, the_iid):
        query_text = """
         SELECT
            install_sources_t.detail_value AS install_sources,
            install_sources_t.tag as tag
        FROM index_item_t AS iid_t, index_item_detail_t as install_sources_t
        WHERE
            iid_t.iid=install_sources_t.owner_iid
                AND
            install_sources_t.detail_name='install_sources'
                AND
            install_sources_t.os_is_active=1
                AND
            iid_t.iid=:the_iid
                AND
            iid_t.install_status != 0
                AND
            iid_t.ignore=0
        ORDER BY install_sources_t.detail_value
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'the_iid': the_iid})
        return retVal

    def get_unique_detail_values(self, detail_name):
        query_text = """
          SELECT DISTINCT index_item_detail_t.detail_value
          FROM index_item_detail_t
          WHERE detail_name = :detail_name
          ORDER BY index_item_detail_t.detail_value
        """
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name})
        return retVal

    def get_iids_with_specific_detail_values(self, detail_name, detail_value):
        """ get all iids that have detail_name with specific detail_value
            detail_name, detail_value can contain wild cards, e.g.:
            get_iids_with_specific_detail_values("require_%", "%banana%")
        """
        retVal = list()
        query_text = """
            SELECT DISTINCT original_iid
            FROM index_item_detail_t
            WHERE
                detail_name LIKE :detail_name
            AND
                detail_value LIKE :detail_value
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name, 'detail_value': detail_value})
        return retVal

    def get_missing_iids_from_details(self, detail_name):
        """ some details' values should be existing iids
            this function will return the original iid and the orphan iids in named details
        """
        query_text = """
            SELECT DISTINCT original_iid, detail_value
            FROM index_item_detail_t
            WHERE
                detail_name = :detail_name
                    AND
                detail_value NOT IN (SELECT iid FROM index_item_t)
            ORDER BY detail_value
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={'detail_name': detail_name})
        return retVal

    def get_ids_and_oses(self):
        return self.db.select_and_fetchall("SELECT _id, name FROM active_operating_systems_t")

    def get_ids_oses_active(self):
        return self.db.select_and_fetchall("SELECT _id, name, os_is_active FROM active_operating_systems_t")

    def get_active_iids(self):
        query_text = """
           SELECT iid
           FROM index_item_t
           WHERE index_item_t.install_status!=0
           AND index_item_t.ignore=0
           """
        retVal = self.db.select_and_fetchall(query_text)
        return retVal

    def get_info_map_and_sync_base_urls(self, detail_name):
        """ select all unique info_map names and their sync_base_url - if any
            results is a list of tuples: [(C1_Setups_Library_IID, None),
                                          (Instrument_Data_Electric200__SD_Sample_Library_IID, $(BASE_LINKS_URL)/Common)]
        """
        query_text = """
          SELECT DISTINCT index_item_detail_info_map_t.detail_value, index_item_detail_sync_base_url_t.detail_value
          FROM index_item_detail_t AS index_item_detail_info_map_t
          LEFT JOIN  index_item_detail_t AS index_item_detail_sync_base_url_t
          ON index_item_detail_sync_base_url_t.detail_name = 'sync_base_url'
          AND index_item_detail_info_map_t.owner_iid = index_item_detail_sync_base_url_t.owner_iid
          WHERE index_item_detail_info_map_t.detail_name = 'info_map'
          ORDER BY index_item_detail_info_map_t.detail_value
        """
        retVal = self.db.select_and_fetchall(query_text)
        return retVal

    def get_data_for_short_index(self):
        """ get all iids that have guids with their name and version
            returns IID, GUID, NAME, VERSION, generation
        """

        self.db.exec_script_file("short-index.ddl")

        query_text = f"""
                    -- select all rows that have some version
                    SELECT * FROM short_index_t
                    WHERE version_mac IS NOT NULL
                    OR version_win IS NOT NULL
                    OR name IS NOT NULL
                    OR install_guid IS NOT NULL;
                    """

        retVal = self.db.select_and_fetchall(query_text)
        return retVal

    def get_all_actions_from_index(self):
        action_string = "','".join(self.action_types)
        action_string = "'" + action_string + "'"
        query_text = f""" SELECT original_iid, detail_name, detail_value, os_id, _id
                    FROM index_item_detail_t
                    WHERE detail_name IN ({action_string}) 
                    ORDER BY _id    
                """
        retVal = self.db.select_and_fetchall(query_text)
        return retVal
