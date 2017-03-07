#!/usr/bin/env python3

"""
session.new - uncommitted new records
session.dirty - uncommitted changed records

session.commit() explicitly done when querying
"""

import os
import sys
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey
from sqlalchemy import UniqueConstraint
from sqlalchemy.sql import default_comparator  # needed for PyInstaller

import utils

__db_engine = None
__db_session_maker = None
__db_session = None
__db_declarative_base = None

force_disk_db = False
unique_name_to_disk_db = False


def get_engine():
    global __db_engine
    if __db_engine is None:
        engine_path = "sqlite:///"
        if getattr(sys, 'frozen', False) and not force_disk_db:
            engine_path += ":memory:"
        else:
            logs_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Logs")
            os.makedirs(logs_dir, exist_ok=True)
            datetime.datetime.now().timestamp()
            db_file_name = "instl.sqlite"
            if unique_name_to_disk_db:
                db_file_name = str(datetime.datetime.now().timestamp())+"."+db_file_name
            db_file = os.path.join(logs_dir, db_file_name)
            utils.safe_remove_file(db_file)
            engine_path += db_file
        __db_engine = create_engine(engine_path, echo=False)
    return __db_engine


def create_session():
    global __db_session_maker, __db_session
    if __db_session_maker is None:
        __db_session_maker = sessionmaker(bind=get_engine(), autocommit=False)
        __db_session = __db_session_maker()
    return __db_session


def get_declarative_base():
    global __db_declarative_base
    if __db_declarative_base is None:
        __db_declarative_base = declarative_base()
    return __db_declarative_base


class IndexItemDetailOperatingSystem(get_declarative_base()):
    __tablename__ = 'IndexItemDetailOperatingSystem'
    _id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    active = Column(BOOLEAN, default=False)
    def __str__(self):
        retVal = "self._id) {self.name} active: {self.active}".format(**locals())
        return retVal


class IndexItemRow(get_declarative_base()):
    __tablename__ = 'IndexItemRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    iid = Column(String, unique=True, index=True)
    inherit_resolved = Column(BOOLEAN, default=False)
    from_index = Column(BOOLEAN, default=False)
    from_require = Column(BOOLEAN, default=False)
    install_status = Column(Integer, default=0)
    ignore = Column(Integer, default=0)

    def __str__(self):
        resolved_str = "resolved" if self.inherit_resolved else "unresolved"
        from_index_str = "yes" if self.from_index else "no"
        from_require_str = "yes" if self.from_require else "no"
        retVal = ("{self._id}) {self.iid}, "
                "inheritance: {resolved}, "
                "from index: {from_index_str}, "
                "from require: {from_require_str},"
                "status: {self.status}"
                ).format(**locals())
        return retVal


class IndexItemDetailRow(get_declarative_base()):
    __tablename__ = 'IndexItemDetailRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    original_iid = Column(String, ForeignKey("IndexItemRow.iid"), index=True)
    owner_iid    = Column(String, ForeignKey("IndexItemRow.iid"), index=True)
    os_id        = Column(Integer, ForeignKey("IndexItemDetailOperatingSystem._id"))
    detail_name  = Column(String, index=True)
    detail_value = Column(String)
    generation   = Column(Integer, default=0)
    tag          = Column(String)
    active       = Column(Integer, default=0)

    #os = relationship("IndexItemDetailOperatingSystem")
    #item = relationship("IndexItemRow", back_populates="original_details")

    def __str__(self):
        retVal = ("{self._id}) owner: {self.owner_iid}, "
                    "origi: {self.original_iid}, "
                    "os: {self.os_id}, "
                    "gen: {self.generation}, "
                    "tag: {self.tag}, "
                    "active: {self.active}, "
                    "{self.detail_name}: {self.detail_value}").format(**locals())
        return retVal


class FoundOnDiskItemRow(get_declarative_base()):
    __tablename__ = 'FoundOnDiskItemRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String)
    name = Column(String)
    version = Column(String)
    guid = Column(String)
    iid = Column(String)

    def __str__(self):
        retVal = ("{self._id}) name: {self.name}, "
                    "iid: {self.iid}, "
                    "version: {self.version}, "
                    "guid: {self.guid}, "
                    "path: {self.path}").format(**locals())
        return retVal


class IndexGuidToItemTranslate(get_declarative_base()):
    __tablename__ = 'IndexGuidToItemTranslate'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    guid  = Column(String)
    iid = Column(String, default=None)
    def __str__(self):
        retVal = "{self.guid} {self.iid}".format(**locals())
        return retVal


class IndexRequireTranslate(get_declarative_base()):
    __tablename__ = 'IndexRequireTranslate'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    iid = Column(String)
    require_by = Column(String)
    status = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint('iid', 'require_by'),)

    def __str__(self):
        retVal = "{self.iid} required by {self.require_by}, status: {self.status}".format(**locals())
        return retVal


class ConfigVar(get_declarative_base()):
    __tablename__ = "ConfigVar"
    _id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)
    raw_value = Column(String)
    resolved_value = Column(String)

#IndexItemDetailRow.resolved_details = relationship(IndexItemToDetailRelation, back_populates="detail")
#IndexItemRow.original_details = relationship("IndexItemDetailRow", back_populates="item")
#IndexItemRow.all_details = relationship("IndexItemToDetailRelation", back_populates="item")

IndexItemDetailOperatingSystem.__table__.create(bind=get_engine(), checkfirst=True)
IndexItemRow.__table__.create(bind=get_engine(), checkfirst=True)
IndexItemDetailRow.__table__.create(bind=get_engine(), checkfirst=True)
IndexGuidToItemTranslate.__table__.create(bind=get_engine(), checkfirst=True)
IndexRequireTranslate.__table__.create(bind=get_engine(), checkfirst=True)
FoundOnDiskItemRow.__table__.create(bind=get_engine(), checkfirst=True)
ConfigVar.__table__.create(bind=get_engine(), checkfirst=True)
