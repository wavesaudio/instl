#!/usr/bin/env python3

"""
session.new - uncommitted new records
session.dirty - uncommitted changed records

session.commit() explicitly done when querying
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey
from sqlalchemy.orm import relationship

alchemy_base = declarative_base()


class ItemRow(alchemy_base):
    __tablename__ = 'ItemRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    iid = Column(String, unique=True)
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
    owner_item_id = Column(String, ForeignKey("ItemRow._id"))
    os = Column(String(8), default="common")  # enum?
    detail_name = Column(String)
    detail_value = Column(String)

    item = relationship("ItemRow", back_populates="original_details")

    def __repr__(self):
        return ("<{self._id}) {self.owner_item_id}, {self.os}"
                ", detail_name:{self.detail_name}"
                ", detail_value:{self.detail_value}>"
                ).format(**locals())

    def __str__(self):
        retVal = "{self._id}) {self.owner_item_id}, {self.os}, {self.detail_name}: {self.detail_value}".format(**locals())
        return retVal

ItemRow.original_details = relationship("ItemDetailRow", back_populates="item")


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


db_engine = create_engine('sqlite:///:memory:', echo=False)
db_session_maker = sessionmaker(bind=db_engine)
alchemy_base.metadata.create_all(db_engine)
