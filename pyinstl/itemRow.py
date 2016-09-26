#!/usr/bin/env python3

from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

alchemy_base = declarative_base()


class ItemRow(alchemy_base):
    __tablename__ = 'ItemRow'
    iid = Column(String, primary_key=True)
    name = Column(String(128), default=None)

    def __repr__(self):
        return ("<{self.iid}"
                ", name:{self.name}>"
                ).format(**locals())

    def __str__(self):
        retVal = "{self.iid}: '{self.name}'".format(**locals())
        return retVal


class ItemDetailRow(alchemy_base):
    __tablename__ = 'ItemDetailRow'
    detail_id = Column(Integer, primary_key=True, autoincrement=True)
    iid = Column(String, ForeignKey("ItemRow.iid"))
    os = Column(String(8), default="common")  # enum?
    detail_name = Column(String)
    detail_value = Column(String)
    inherited = Column(BOOLEAN, default=False)

    def __repr__(self):
        return ("<{self.detail_id}, {self.iid}, {self.os}"
                ", detail_name:{self.detail_name}"
                ", detail_value:{self.detail_value}"
                ", inherited:{self.inherited}"
                ).format(**locals())

    def __str__(self):
        retVal = "{self.detail_id}, {self.iid}, {self.os}, {self.detail_name}, {self.detail_value}, {self.inherited}".format(**locals())
        return retVal

