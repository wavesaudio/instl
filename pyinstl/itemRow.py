#!/usr/bin/env python3

from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

alchemy_base = declarative_base()


class ItemRow(alchemy_base):
    __tablename__ = 'ItemRow'
    iid = Column(String, primary_key=True)
    inherit_resolved = Column(BOOLEAN, default=False)

    def __repr__(self):
        resolved_str = "resolved" if self.inherit_resolved else "unresolved"
        return ("<{self.iid}"
                ", inheritance {resolved}>"
                ).format(**locals())

    def __str__(self):
        resolved_str = "resolved" if self.inherit_resolved else "unresolved"
        retVal = "{self.iid}, inheritance {resolved_str}".format(**locals())
        return retVal


class ItemDetailRow(alchemy_base):
    __tablename__ = 'ItemDetailRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    origin_iid = Column(String, ForeignKey(ItemRow.iid))
    os = Column(String(8), default="common")  # enum?
    detail_name = Column(String)
    detail_value = Column(String)

    def __repr__(self):
        return ("<{self._id}) {self.origin_iid}, {self.os}"
                ", detail_name:{self.detail_name}"
                ", detail_value:{self.detail_value}>"
                ).format(**locals())

    def __str__(self):
        retVal = "{self._id}) {self.origin_iid}, {self.os}, {self.detail_name}: {self.detail_value}".format(**locals())
        return retVal


class ItemToDetailRelation(alchemy_base):
    __tablename__ = 'ItemToDetailRelation'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    iid = Column(String, ForeignKey("ItemRow.iid"))
    detail_row = Column(String, ForeignKey("ItemDetailRow._id"))

    def __repr__(self):
        return ("<{self._id}) {self.iid}, {self.detail_row}>"
                ).format(**locals())

    def __str__(self):
        retVal = "{self._id}) {self.iid}, {self.detail_row}".format(**locals())
        return retVal
