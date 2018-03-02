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
from sqlalchemy.exc import SQLAlchemyError

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
            #print("db_file:", db_file)
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


class TableBase(object):
    def __init__(self):
        self.session = create_session()
        self.locked_tables = set()

    def commit_changes(self):
        self.session.commit()

    def execute_script(self, script_text):
        db_conn = get_engine().raw_connection()
        db_curs = db_conn.cursor()
        script_results = db_curs.executescript(script_text)
        db_curs.close()
        db_conn.close()
        return script_results

    def lock_table(self, table_name):
        query_text = """
            CREATE TRIGGER IF NOT EXISTS lock_INSERT_{table_name}
            BEFORE INSERT ON {table_name}
            BEGIN
                SELECT raise(abort, '{table_name} is locked no INSERTs');
            END;
            CREATE TRIGGER IF NOT EXISTS lock_UPDATE_{table_name}
            BEFORE UPDATE ON {table_name}
            BEGIN
                SELECT raise(abort, '{table_name} is locked no UPDATEs');
            END;
            CREATE TRIGGER IF NOT EXISTS lock_DELETE_{table_name}
            BEFORE DELETE ON {table_name}
            BEGIN
                SELECT raise(abort, '{table_name} is locked no DELETEs');
            END;
        """.format(table_name=table_name)
        self.execute_script(query_text)
        self.commit_changes()
        self.locked_tables.add(table_name)

    def unlock_table(self, table_name):
        query_text = """
            DROP TRIGGER IF EXISTS lock_INSERT_{table_name};
            DROP TRIGGER IF EXISTS lock_UPDATE_{table_name};
            DROP TRIGGER IF EXISTS lock_DELETE_{table_name};
        """.format(table_name=table_name)
        self.execute_script(query_text)
        self.commit_changes()
        self.locked_tables.remove(table_name)

    def unlock_all_tables(self):
        for table_name in list(self.locked_tables):
            self.unlock_table(table_name)

    def select_and_fetchall(self, query_text, query_params=None):
        """
            execute a select statement and convert the returned list
            of tuples to a list of values.
            return empty list of no values were found.
        """
        retVal = list()
        try:
            if query_params is None:
                query_params = {}
            exec_result = self.session.execute(query_text, query_params)
            if exec_result.returns_rows:
                all_results = exec_result.fetchall()
                if all_results:
                    if len(all_results[0]) == 1:
                        retVal.extend([res[0] for res in all_results])
                    else:
                        retVal.extend(all_results)
        except SQLAlchemyError as ex:
            raise
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
    direct_sync = Column(Integer, default=0)

    def __str__(self):
        resolved_str = "resolved" if self.inherit_resolved else "unresolved"
        from_index_str = "yes" if self.from_index else "no"
        from_require_str = "yes" if self.from_require else "no"
        retVal = ("{self._id}) {self.iid}, "
                "inheritance: {resolved}, "
                "from index: {from_index_str}, "
                "from require: {from_require_str},"
                "status: {self.status}"
                "direct_sync: {self.direct_sync}"
                ).format(**locals())
        return retVal


class IndexItemDetailRow(get_declarative_base()):
    __tablename__ = 'IndexItemDetailRow'
    _id = Column(Integer, primary_key=True, autoincrement=True)
    original_iid = Column(String, ForeignKey(IndexItemRow.iid, ondelete="CASCADE"), index=True)
    owner_iid    = Column(String, ForeignKey(IndexItemRow.iid, ondelete="CASCADE"), index=True)
    os_id        = Column(Integer, ) #ForeignKey(active_operating_systems_t._id)
    detail_name  = Column(String, index=True)
    detail_value = Column(String)
    generation   = Column(Integer, default=0)
    tag          = Column(String)
    os_is_active       = Column(Integer, default=0, index=True)
    UniqueConstraint(original_iid, owner_iid, os_id, detail_name, detail_value, generation)

    def __str__(self):
        retVal = ("{self._id}) owner: {self.owner_iid}, "
                    "origi: {self.original_iid}, "
                    "os: {self.os_id}, "
                    "gen: {self.generation}, "
                    "tag: {self.tag}, "
                    "os_is_active: {self.os_is_active}, "
                    "{self.detail_name}: {self.detail_value}").format(**locals())
        return retVal


IndexItemRow.__table__.create(bind=get_engine(), checkfirst=True)
IndexItemDetailRow.__table__.create(bind=get_engine(), checkfirst=True)
