#!/usr/bin/env python3

from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

alchemy_base = declarative_base()


class ItemRow(alchemy_base):
    __tablename__ = 'ItemRow'
    #row_id = Column(Integer, primary_key=True, autoincrement=True)
    iid = Column(String, primary_key=True)
    name = Column(String(128), default=None)
    inheritance_resolved = Column(BOOLEAN, default=False)

    def __repr__(self):
        resolved_str = "resolved" if self.inheritance_resolved else "unresolved"
        return ("<{self.iid}"
                ", name:{self.name}, inheritance {resolved}>"
                ).format(**locals())

    def __str__(self):
        resolved_str = "resolved" if self.inheritance_resolved else "unresolved"
        retVal = "{self.iid}: '{self.name}', inheritance {resolved_str}".format(**locals())
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
        retVal = "{self.detail_id}, {self.iid}, {self.os}, {self.detail_name}: {self.detail_value}, inherited: {self.inherited}".format(**locals())
        return retVal

