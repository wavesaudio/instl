#!/usr/bin/env python3

"""
session.new - uncommitted new records
session.dirty - uncommitted changed records

session.commit() explicitly done when querying
"""

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.engine import reflection

__db_engine = None
__db_session_maker = None
__db_declarative_base = None


def get_engine():
    global __db_engine
    if __db_engine is None:
        engine_path = "sqlite:///"
        if getattr(sys, 'frozen', False):
            engine_path += ":memory:"
        else:
            logs_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Logs")
            os.makedirs(logs_dir, exist_ok=True)
            db_file = os.path.join(logs_dir, "instl.sqlite")
            engine_path += db_file
        __db_engine = create_engine(engine_path, echo=False)
    return __db_engine


def create_session():
    global __db_session_maker
    if __db_session_maker is None:
        __db_session_maker = sessionmaker(bind=get_engine())
    new_session = __db_session_maker()
    return new_session


def get_declarative_base():
    global __db_declarative_base
    if __db_declarative_base is None:
        __db_declarative_base = declarative_base()
    return __db_declarative_base


class IndexItemRow(get_declarative_base()):
    __tablename__ = 'IndexItemRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    iid = Column(String, unique=True)
    inherit_resolved = Column(BOOLEAN, default=False)
    from_index = Column(BOOLEAN, default=False)
    from_require = Column(BOOLEAN, default=False)

    def __str__(self):
        resolved_str = "resolved" if self.inherit_resolved else "unresolved"
        from_index_str = "yes" if self.from_index else "no"
        from_require_str = "yes" if self.from_require else "no"
        retVal = ("{self._id}) {self.iid} "
                "inheritance: {resolved}, "
                "from index: {from_index_str}, "
                "from require: {from_require_str}"
                ).format(**locals())
        return retVal


class IndexItemRequiredRow(get_declarative_base()):
    __tablename__ = "IndexItemRequiredRow"
    _id = Column(Integer, primary_key=True, autoincrement=True)
    owner_item_id = Column(String, ForeignKey("IndexItemRow._id"))
    required_by_iid = Column(String)
    item = relationship("IndexItemRow", back_populates="required_by")

    def __str__(self):
         retVal = ("{self._id}) {self.owner_item_id} {self.required_by_iid}"
                ).format(**locals())
         return retVal


IndexItemRow.required_by = relationship("IndexItemRequiredRow", back_populates="item")


class IndexItemDetailRow(get_declarative_base()):
    __tablename__ = 'IndexItemDetailRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    owner_item_id = Column(String, ForeignKey("IndexItemRow._id"))
    os = Column(String(8), default="common")  # enum?
    detail_name = Column(String)
    detail_value = Column(String)

    item = relationship("IndexItemRow", back_populates="original_details")

    def __str__(self):
        retVal = "{self._id}) {self.owner_item_id}, {self.os}, {self.detail_name}: {self.detail_value}".format(**locals())
        return retVal


class IndexItemToDetailRelation(get_declarative_base()):
    __tablename__ = 'IndexItemToDetailRelation'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String, ForeignKey("IndexItemRow._id"))
    detail_id = Column(String, ForeignKey("IndexItemDetailRow._id"))
    generation = Column(Integer, default=0)

    item = relationship("IndexItemRow", back_populates="all_details")
    detail = relationship("IndexItemDetailRow", back_populates="resolved_details")

    def __str__(self):
        retVal = "{self._id}) {self.item_id}, {self.detail_id}, gen {self.generation}".format(**locals())
        return retVal

IndexItemDetailRow.resolved_details = relationship(IndexItemToDetailRelation, back_populates="detail")
IndexItemRow.original_details = relationship("IndexItemDetailRow", back_populates="item")
IndexItemRow.all_details = relationship("IndexItemToDetailRelation", back_populates="item")

IndexItemRow.__table__.create(bind=get_engine(), checkfirst=True)
IndexItemRequiredRow.__table__.create(bind=get_engine(), checkfirst=True)
IndexItemDetailRow.__table__.create(bind=get_engine(), checkfirst=True)
IndexItemToDetailRelation.__table__.create(bind=get_engine(), checkfirst=True)
