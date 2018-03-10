import os
import sqlite3
from contextlib import contextmanager
import time

import utils

"""
    todo:
        - replace iids in index_item_detail_t with index_item_t._id ?
        - normalize detail_name with table of names?
        - review indexes, do they really improve performance
        - lower case table names
        - svnitem - review whole parent/child relationship
"""


class DBMaster(object):
    def __init__(self):
        self.top_user_version = 1  # user_version is a standard pragma tha defaults to 0
        self.ddl_files_dir = None
        self.db_file_path = None
        self.__conn = None
        self.__curs = None

    def read_ddl_file(self, ddl_file_name):
        ddl_path = os.path.join(self.internal_data_folder, "db", ddl_file_name)
        with open(ddl_path, "r") as rfd:
            ddl_text = rfd.read()
        return ddl_text

    def init_from_ddl(self, ddl_files_dir, db_file_path):
        self.ddl_files_dir = ddl_files_dir
        self.db_file_path = db_file_path
        self.open()

    def init_from_existing_connection(self, conn, curs):
        self.__conn = conn
        self.__curs = curs
        self.configure_db()
        self.exec_script_file("create-tables.ddl")
        self.exec_script_file("init-values.ddl")

    def open(self):
        self.__conn = sqlite3.connect(self.db_file_path)
        self.configure_db()
        self.__curs = self.__conn.cursor()
        self.exec_script_file("create-tables.ddl")
        self.exec_script_file("init-values.ddl")

    def configure_db(self):
        self.set_db_pragma("foreign_keys", "ON")
        #self.__conn.set_authorizer(self.authorizer)
        #self.__conn.set_progress_handler(self.progress, 8)
        self.__conn.set_trace_callback(self.tracer)

    def authorizer(self, *args, **kwargs):
        """ callback for sqlite3.connection.set_authorizer"""
        return sqlite3.SQLITE_OK

    def progress(self):
        """ callback for sqlite3.connection.set_progress_handler"""
        self.logger.debug('DB progress')

    def tracer(self, statement):
        """ callback for sqlite3.connection.set_trace_callback"""
        self.logger.debug('DB statement %s' % (statement))

    def create_function(self, func_name, num_params, func_ptr):
        self.__conn.create_function(func_name, num_params, func_ptr)

    def close(self):
        if self.__conn:
            self.__conn.close()

    def erase_db(self):
        self.close()
        utils.safe_remove_file(self.db_file_path)

    def set_db_pragma(self, pragma_name, pragma_value):
        set_pragma_q = """PRAGMA {pragma_name} = {pragma_value};""".format(**locals())
        self.__curs.execute(set_pragma_q)

    def get_db_pragma(self, pragma_name, default_value=None):
        pragma_value = default_value
        try:
            get_pragma_q = """PRAGMA {pragma_name};""".format(**locals())
            self.__curs.execute(get_pragma_q)
            pragma_value = self.__curs.fetchone()[0]
        except Exception as ex:  # just return the default value
            pass
        return pragma_value

    def begin(self):
        self.__conn.execute("begin")

    def commit(self):
        self.__conn.commit()

    def rollback(self):
        self.__conn.rollback()

    @property
    def curs(self):
        return self.__curs

    @contextmanager
    def transaction(self, description=""):
        try:
            time1 = time.clock()
            self.begin()
            yield self.__curs
            self.commit()
            time2 = time.clock()
            print('DB transaction %s took %0.3f ms' % (description, (time2-time1)*1000.0))
        except:
            self.rollback()
            raise

    @contextmanager
    def selection(self, description=""):
        """ returns a cursor for SELECT queries.
            no commit is done
        """
        try:
            time1 = time.clock()
            yield self.__conn.cursor()
            time2 = time.clock()
            print('DB selection %s took %0.3f ms' % (description, (time2-time1)*1000.0))
        except Exception as ex:
            raise

    @contextmanager
    def temp_transaction(self, description=""):
        """ returns a cursor for working with CREATE TEMP TABLE.
            no commit is done
        """
        try:
            time1 = time.clock()
            yield self.__conn.cursor()
            time2 = time.clock()
            print('DB temporary transaction %s took %0.3f ms' % (description, (time2-time1)*1000.0))
        except Exception as ex:
            raise

    def exec_script_file(self, file_name):
        if os.path.isfile(file_name):
            script_file_path = file_name
        else:
            script_file_path = os.path.join(self.ddl_files_dir, file_name)
        ddl_text = open(script_file_path, "r").read()
        self.__curs.executescript(ddl_text)
        self.commit()

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
            self.__curs.execute(query_text, query_params)
            all_results = self.__curs.fetchall()
            if all_results:
                if len(all_results[0]) == 1:
                    retVal.extend([res[0] for res in all_results])
                else:
                    retVal.extend(all_results)
        except sqlite3.Error as ex:
            raise
        return retVal

    def execute_no_fetch(self, query_text, query_params=None):
        try:
            if query_params is None:
                query_params = {}
            self.__curs.execute(query_text, query_params)
        except sqlite3.Error as ex:
            raise

    def executemany(self, query_text, value_list):
        try:
            self.__curs.executemany(query_text, value_list)
        except sqlite3.Error as ex:
            raise

    def execute_script(self, script_text):
        try:
            self.__curs.executescript(script_text)
        except sqlite3.Error as ex:
            raise

if __name__ == "__main__":
    ddl_path = "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl/defaults"
    db_path = "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl/defaults/instl.sqlite"
    utils.safe_remove_file(db_path)
    db = DBMaster()
    db.init_from_ddl(ddl_path, db_path)

    print("creation:", db.get_ids_oses_active())

    db.activate_specific_oses("Mac64", "Win32")
    print("Mac64:", db.get_ids_oses_active())

    db.reset_active_oses()
    print("reset_active_oses:", db.get_ids_oses_active())

    db.activate_all_oses()
    print("activate_all_oses:", db.get_ids_oses_active())

    #db.exec_script_file("create-indexes.ddl")
    #db.exec_script_file("create-triggers.ddl")
    #db.exec_script_file("create-views.ddl")
