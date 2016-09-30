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



class ItemToDetailRelation(alchemy_base):
    __tablename__ = 'ItemToDetailRelation'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String, ForeignKey("ItemRow._id"))
    detail_id = Column(String, ForeignKey("ItemDetailRow._id"))

    item = relationship("ItemRow", back_populates="all_details")
    detail = relationship("ItemDetailRow", back_populates="resolved_details")

    def __repr__(self):
        return ("<{self._id}) {self.item_id}, {self.detail_id}>"
                ).format(**locals())

    def __str__(self):
        retVal = "{self._id}) {self.item_id}, {self.detail_id}".format(**locals())
        return retVal

ItemDetailRow.resolved_details = relationship(ItemToDetailRelation, back_populates="detail")
ItemRow.original_details = relationship("ItemDetailRow", back_populates="item")
ItemRow.all_details = relationship("ItemToDetailRelation", back_populates="item")

#db_engine = create_engine('sqlite:///:memory:', echo=False)
db_engine = create_engine('sqlite:////Users/shai/Desktop/instl.sqlite', echo=False)
db_session_maker = sessionmaker(bind=db_engine)
alchemy_base.metadata.create_all(db_engine)
