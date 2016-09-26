#!/usr/bin/env python3

from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

alchemy_base = declarative_base()


class ItemRow(alchemy_base):
    __tablename__ = 'instl_item'
    iid = Column(String, primary_key=True)
    name = Column(String(128), default=None)

    def __repr__(self):
        return ("<{self.iid}, {self.os}"
                ", name:{self.name}"
                ).format(**locals())

    def __str__(self):
        retVal = "{}, {}".format(self.iid, self.name)
        return retVal


class ItemDetailRow(alchemy_base):
    __tablename__ = 'item_detail'
    iid = Column(String, ForeignKey("ItemRow.iid"), primary_key=True)
    os = Column(String(8), default="common")  # enum?
    detail_name = Column(String)
    detail_value = Column(String)
    inherited = Column(BOOLEAN, default=False)

    def __repr__(self):
        return ("<{self.iid}, {self.os}"
                ", detail_name:{self.detail_name}"
                ", detail_value:{self.detail_value}"
                ", inherited:{self.inherited}"
                ).format(**locals())

    def __str__(self):
        retVal = "{self.iid}, {self.os}, {self.detail_name}, {self.detail_value}, {self.inherited}".format(**locals())
        return retVal

