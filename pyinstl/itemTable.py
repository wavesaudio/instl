#!/usr/bin/env python3


import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import update
from sqlalchemy import or_
from sqlalchemy.ext import baked
from sqlalchemy import bindparam
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import func
from sqlalchemy import event

import pyinstl
from pyinstl import itemRow
#from .itemRow import ItemRow, ItemDetailRow, alchemy_base

import utils
from configVar import var_stack
from functools import reduce
from aYaml import YamlReader


class ItemTableYamlReader(YamlReader):
    def __init__(self):
        super().__init__()
        self.items, self.details = list(), list()

    def init_specific_doc_readers(self): # this function must be overridden
        self.specific_doc_readers["!index"] = self.read_index_from_yaml

    def read_index_from_yaml(self,all_items_node):
        for IID in all_items_node:
            item, item_details = ItemTableYamlReader.item_dicts_from_node(IID, all_items_node[IID])
            self.items.append(item)
            self.details.extend(item_details)

    @staticmethod
    def item_dicts_from_node(the_iid, the_node):
        item, details = dict(), list()
        item['iid'] = the_iid
        if 'name' in the_node:
            item['name'] = the_node['name'].value
        else:
            item['name'] = None
        item['inheritance_resolved'] = False
        details = ItemTableYamlReader.read_item_details_from_node(the_iid, the_node)
        return item, details

    @staticmethod
    def read_item_details_from_node(the_iid, the_node, the_os='common'):
        details = list()
        for detail_name in the_node:
            if detail_name in ItemTable.os_names[1:]:
                os_specific_details = ItemTableYamlReader.read_item_details_from_node(the_iid, the_node[detail_name], detail_name)
                details.extend(os_specific_details)
            elif detail_name == 'actions':
                actions_details = ItemTableYamlReader.read_item_details_from_node(the_iid, the_node['actions'], the_os)
                details.extend(actions_details)
            else:
                for details_line in the_node[detail_name]:
                    details.append({'iid': the_iid, 'os': the_os, 'detail_name': detail_name, 'detail_value': details_line.value, 'inherited': False})
        return details

class ItemTable(object):
    os_names = ('common', 'Mac', 'Mac32', 'Mac64', 'Win', 'Win32', 'Win64')
    dont_inherit_details = ('name','inherit')
    def __init__(self):
        self.engine = create_engine('sqlite:///:memory:', echo=False)
        itemRow.alchemy_base.metadata.create_all(self.engine)
        self.session_maker = sessionmaker(bind=self.engine)
        self.session = self.session_maker()
        self.baked_queries_map = self.bake_baked_queries()
        self.bakery = baked.bakery()

    def bake_baked_queries(self):
        """ prepare baked queries for later use
        """
        retVal = dict()

        # all queries are now baked just-in-time

        return retVal

    def insert_dicts_to_db(self, item_insert_dicts, details_insert_dicts):
        # self.session.bulk_insert_mappings(SVNRow, insert_dicts)
        self.engine.execute(itemRow.ItemRow.__table__.insert(), item_insert_dicts)
        self.engine.execute(itemRow.ItemDetailRow.__table__.insert(), details_insert_dicts)

    def get_items(self, what="any"):

        # get_all_items: return all items either files dirs or both, used by get_items()
        if "get_all_items" not in self.baked_queries_map:
            self.baked_queries_map["get_all_items"] = self.bakery(lambda session: session.query(itemRow.ItemRow))
            self.baked_queries_map["get_all_items"] += lambda q: q.order_by(itemRow.ItemRow.iid, itemRow.ItemRow.row_id)

        retVal = self.baked_queries_map["get_all_items"](self.session).all()
        return retVal

    def get_details(self, what="any"):

        # get_all_details: return all items either files dirs or both, used by get_items()
        if "get_all_details" not in self.baked_queries_map:
            self.baked_queries_map["get_all_details"] = self.bakery(lambda session: session.query(itemRow.ItemDetailRow))

        retVal = self.baked_queries_map["get_all_details"](self.session).all()
        return retVal

    def get_item(self, iid_to_get):
        retVal = self.session.query(itemRow.ItemRow).filter(itemRow.ItemRow.iid==iid_to_get).scalar()
        return retVal

    def get_item_by_resolved(self, iid_to_get, resolved_status):
        retVal = self.session.query(itemRow.ItemRow).filter(itemRow.ItemRow.iid==iid_to_get, itemRow.ItemRow.inheritance_resolved == resolved_status).scalar()
        return retVal

    def get_all_iids(self):
        retVal = self.session.query(itemRow.ItemRow.iid).all()
        return retVal

    def get_unresolved_items(self):
        retVal = self.session.query(itemRow.ItemRow).filter(itemRow.ItemRow.inheritance_resolved == False).all()
        #retVal = [mm[0] for mm in retVal]
        return retVal

    def get_all_details_for_item(self, iid):
        retVal = self.session.query(itemRow.ItemDetailRow).filter(itemRow.ItemDetailRow.iid == iid).all()
        #retVal = [mm[0] for mm in retVal]
        return retVal

    def get_details_for_item(self, iid, detail_name):
        retVal = self.session.query(itemRow.ItemDetailRow.detail_value).filter(itemRow.ItemDetailRow.iid == iid,
                                                                  itemRow.ItemDetailRow.detail_name == detail_name).all()
        retVal = [mm[0] for mm in retVal]
        return retVal

    def resolve_item_inheritance(self, item_to_resolve):
        inherit_from = self.get_details_for_item(item_to_resolve.iid, 'inherit')
        if len(inherit_from) > 0:
            for i_f in inherit_from:
                self.resolve_iid_inheritance(i_f)
                details_for_item = self.get_all_details_for_item(i_f)
                for d_f_i in details_for_item:
                    if d_f_i.detail_name not in ItemTable.dont_inherit_details:
                        new_d_f_i = {'iid': item_to_resolve.iid, 'os': d_f_i.os,
                                 'detail_name': d_f_i.detail_name, 'detail_value': d_f_i.detail_value,
                                 'inherited': True}
                        self.engine.execute(itemRow.ItemDetailRow.__table__.insert(), new_d_f_i)
            item_to_resolve.inheritance_resolved = True

    def resolve_iid_inheritance(self, iid_to_resolve):
        item = self.get_item_by_resolved(iid_to_resolve, False)
        if item is not None:
            self.resolve_item_inheritance(item)

    def resolve_inheritance(self):
        unresolved_items = self.get_unresolved_items()
        for unresolved_item in unresolved_items:
            self.resolve_item_inheritance(unresolved_item)

    def add_something(self):
        to_add = {'iid': "ADD", 'os': "ADD-os", 'detail_name': "ADD-detail_name", 'detail_value': "ADD-details_value", 'inherited': True}
        self.engine.execute(itemRow.ItemDetailRow.__table__.insert(), to_add)

if __name__ == "__main__":
    reader = ItemTableYamlReader()

    reader.read_yaml_file('/repositories/betainstl/svn/instl/index.yaml')
    #reader.read_yaml_file('/Users/shai/Desktop/sample_index.yaml')
    #print("\n".join([str(item) for item in reader.items]))
    #print("\n".join([str(detail) for detail in reader.details]))
    it = ItemTable()
    it.insert_dicts_to_db(reader.items, reader.details)
    #print("\n".join([str(item) for item in it.get_items()]))
    #print("----")
    #print("\n".join([str(detail) for detail in it.get_details()]))
    #it.add_something()
    print("----\n----")
    #items = it.get_all_iids()
    #print(type(items[0]), items)
    it.resolve_inheritance()
    print("\n".join([str(item) for item in it.get_items()]))
    print("----")
    print("\n".join([str(detail) for detail in it.get_details()]))
    print("----\n----")

