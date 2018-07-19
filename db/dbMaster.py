import os
import sys
import sqlite3
from contextlib import contextmanager
import time
import datetime
import inspect
from _collections import defaultdict
import operator

import utils
from configVar import config_vars
from pyinstl.indexItemTable import IndexItemsTable
from svnTree import SVNTable

"""
    todo:
        - replace iids in index_item_detail_t with index_item_t._id ?
        - normalize detail_name with table of names?
        - review indexes, do they really improve performance
        - lower case table names
        - svnitem - review whole parent/child relationship
"""

force_disk_db = False
unique_name_to_disk_db = False


def get_db_url(name_extra=None, db_file=None):
    if getattr(sys, 'frozen', False) and not force_disk_db and not db_file:
        db_url = ":memory:"
    else:
        if db_file:
            db_url = db_file
        else:
            logs_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Logs")
            os.makedirs(logs_dir, exist_ok=True)
            db_file_name = "instl.sqlite"
            if name_extra:
                db_file_name = name_extra+"."+db_file_name
            if unique_name_to_disk_db:
                db_file_name = str(datetime.datetime.now().timestamp())+"."+db_file_name
            db_file_in_logs = os.path.join(logs_dir, db_file_name)
            #print("db_file:", db_file)
            db_url = db_file_in_logs
    return db_url


class Statistic():
    def __init__(self) -> None:
        self.count = 0
        self.time = 0.0

    def add_instance(self, time):
        self.count += 1
        self.time += time

    def __str__(self):
        average = self.time/self.count if self.count else 0.0
        retVal = f"count, {self.count}, time, {self.time:.2f}, ms, average, {average:.2f}, ms"
        return retVal

    def __repr__(self):
        average = self.time/self.count if self.count else 0.0
        retVal = f"{self.count}, {self.time:.2f}, {average:.2f}"
        return retVal


class DBMaster(object):
    def __init__(self, db_url, ddl_folder) -> None:
        self.top_user_version = 1  # user_version is a standard pragma tha defaults to 0
        self.db_file_path = db_url
        self.ddl_files_dir = ddl_folder
        self.__conn = None
        self.__curs = None
        self.locked_tables = set()
        self.statistics = defaultdict(Statistic)
        self.print_execute_times = False
        self.transaction_depth = 0

    def get_file_path(self):
        return self.db_file_path

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
        if not self.__conn:
            create_new_db = not os.path.isfile(self.db_file_path)
            self.__conn = sqlite3.connect(self.db_file_path)
            self.__curs = self.__conn.cursor()
            self.configure_db()
            if create_new_db:
                self.exec_script_file("create-tables.ddl")
                self.exec_script_file("init-values.ddl")
                self.exec_script_file("create-indexes.ddl")

    def configure_db(self):
        self.set_db_pragma("foreign_keys", "ON")
        self.set_db_pragma("user_version", self.top_user_version)
        #self.__conn.set_authorizer(self.authorizer)
        #self.__conn.set_progress_handler(self.progress, 8)
        self.__conn.row_factory = sqlite3.Row
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
        if bool(config_vars.get("PRINT_STATISTICS_DB", "False")) and self.statistics:
            for name, stats in sorted(self.statistics.items()):
                average = stats.time/stats.count
                print(f"{name}, {repr(stats)}")

                max_count = max(self.statistics.items(), key=lambda S: S[1].count)
                max_time = max(self.statistics.items(), key=lambda S: S[1].time)
                total_DB_time = sum(stat.time for stat in self.statistics.values())
                print("max count:", max_count[0], max_count[1])
                print("max time:", max_time[0], max_time[1])
                print("total DB time:", total_DB_time)

    def erase_db(self):
        self.close()
        utils.safe_remove_file(self.db_file_path)

    def set_db_pragma(self, pragma_name, pragma_value):
        set_pragma_q = f"""PRAGMA {pragma_name} = {pragma_value};"""
        self.__curs.execute(set_pragma_q)

    def get_db_pragma(self, pragma_name, default_value=None):
        pragma_value = default_value
        try:
            get_pragma_q = f"""PRAGMA {pragma_name};"""
            self.__curs.execute(get_pragma_q)
            pragma_value = self.__curs.fetchone()[0]
        except Exception as ex:  # just return the default value
            pass
        return pragma_value

    def begin(self):
        self.commit()
        #assert self.transaction_depth == 0, f"begin: self.transaction_depth: {self.transaction_depth}"
        self.__conn.execute("begin")
        self.transaction_depth += 1

    def commit(self):
        #assert self.transaction_depth == 1, f"commit: self.transaction_depth: {self.transaction_depth}"
        self.__conn.commit()
        self.transaction_depth -= 1

    def rollback(self):
        #assert self.transaction_depth > 0, f"rollback: self.transaction_depth: {self.transaction_depth}"
        self.__conn.rollback()
        self.transaction_depth = 0

    @property
    def curs(self):
        return self.__curs

    @contextmanager
    def transaction(self, description=None):
        try:
            if not description:
                description = inspect.stack()[2][3]
            time1 = time.perf_counter()
            self.begin()
            yield self.__curs
            self.commit()
            time2 = time.perf_counter()
            if self.print_execute_times:
                print('DB transaction %s took %0.3f ms' % (description, (time2-time1)*1000.0))
            self.statistics[description].add_instance((time2-time1)*1000.0)
        except:
            self.rollback()
            raise

    @contextmanager
    def selection(self, description=None):
        """ returns a cursor for SELECT queries.
            no commit is done
        """
        try:
            if not description:
                description = inspect.stack()[2][3]
            time1 = time.perf_counter()
            yield self.__conn.cursor()
            time2 = time.perf_counter()
            if self.print_execute_times:
                if not description:
                    description = inspect.stack()[2][3]
                print('DB selection %s took %0.3f ms' % (description, (time2-time1)*1000.0))
            self.statistics[description].add_instance((time2-time1)*1000.0)
        except Exception as ex:
            raise

    @contextmanager
    def temp_transaction(self, description=None):
        """ returns a cursor for working with CREATE TEMP TABLE.
            no commit is done
        """
        try:
            if not description:
                description = inspect.stack()[2][3]
            time1 = time.perf_counter()
            yield self.__conn.cursor()
            time2 = time.perf_counter()
            if self.print_execute_times:
                if not description:
                    description = inspect.stack()[2][3]
                print('DB temporary transaction %s took %0.3f ms' % (description, (time2-time1)*1000.0))
            self.statistics[description].add_instance((time2-time1)*1000.0)
        except Exception as ex:
            raise

    def exec_script_file(self, file_name):
        with self.transaction("exec_script_file_"+file_name) as curs:
            if os.path.isfile(file_name):
                script_file_path = file_name
            else:
                script_file_path = os.path.join(self.ddl_files_dir, file_name)
            ddl_text = open(script_file_path, "r").read()
            curs.executescript(ddl_text)

    def select_and_fetchone(self, query_text, query_params=None):
        """
            execute a select statement and convert the returned list
            of tuples to a list of values.
            return empty list of no values were found.
        """
        retVal = None
        try:
            if query_params is None:
                query_params = {}
            if self.print_execute_times:
                description = inspect.stack()[1][3]
            else:
                description = None
            with self.selection(description) as curs:
                curs.execute(query_text, query_params)
                one_result = curs.fetchone()
                if one_result:
                    if isinstance(one_result, (tuple, list)):
                        retVal = one_result[0]
                    else:
                        retVal = one_result
        except sqlite3.Error as ex:
            raise
        return retVal

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
            if self.print_execute_times:
                description = inspect.stack()[1][3]
            else:
                description = None
            with self.selection(description) as curs:
                curs.execute(query_text, query_params)
                all_results = curs.fetchall()
                if all_results:
                    if len(all_results[0]) == 1:
                        retVal.extend([res[0] for res in all_results])
                    else:
                        retVal.extend(all_results)
        except sqlite3.Error as ex:
            raise
        return retVal

    def lock_table(self, table_name):
        query_text = f"""
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
        """
        with self.transaction("lock_table") as curs:
            curs.executescript(query_text)
        self.locked_tables.add(table_name)

    def unlock_table(self, table_name):
        query_text = f"""
            DROP TRIGGER IF EXISTS lock_INSERT_{table_name};
            DROP TRIGGER IF EXISTS lock_UPDATE_{table_name};
            DROP TRIGGER IF EXISTS lock_DELETE_{table_name};
        """
        with self.transaction("unlock_table") as curs:
            curs.executescript(query_text)
        self.locked_tables.remove(table_name)

    def unlock_all_tables(self):
        for table_name in list(self.locked_tables):
            self.unlock_table(table_name)


class DBAccess(object):
    def __init__(self):
        self._db = None
        self._owner = None  # for reference and debugging
        self._name = None   # for reference and debugging

    def __set_name__(self, owner, name):
        self._owner = owner
        self._name = name

    def __get__(self, instance, owner):
        if self._db is None:
            the_command = getattr(instance, 'the_command', None)
            db_file = getattr(instance, 'db_file', None)
            db_url = get_db_url(the_command, db_file)
            if db_url != ":memory:" and not db_file:
                # erase the db only if it's default created no given
                utils.safe_remove_file(db_url)
            ddls_folder = config_vars["__INSTL_DEFAULTS_FOLDER__"].str()
            self._db = DBMaster(db_url, ddls_folder)
            config_vars["__DATABASE_URL__"] = db_url
        return self._db

    def __delete__(self, instance):
        if self._db is not None:
            self._db.close()
            del self._db
            self._db = None


class TableAccess(object):
    def __init__(self, type):
        self._table = None
        self._owner = None  # for reference and debugging
        self._name = None   # for reference and debugging
        self._type = type

    def __set_name__(self, owner, name):
        self._owner = owner
        self._name = name
        assert self._type is {'items_table': IndexItemsTable, 'info_map_table': SVNTable}[self._name]

    def __get__(self, instance, owner):
        if self._table is None:
            self._table = self._type(instance.db)
        return self._table

    def __delete__(self, instance):
        if self._table is not None:
            del self._table
            self._table = None


class DBManager(object):
    """ all classes inheriting from DBManager will have access to singleton instances db, info_map and items table.
        these instances will be created on the fly when accessed, to instances that do not need any of these will
        not suffer the penalty of creating them.
    """
    db = DBAccess()
    info_map_table = TableAccess(SVNTable)
    items_table = TableAccess(IndexItemsTable)
