import os
import sqlite3
from contextlib import contextmanager
import datetime
import inspect
from pathlib import Path
from _collections import defaultdict
import shutil
import logging

import utils
from configVar import config_vars
from db.indexItemTable import IndexItemsTable
from svnTree import SVNTable

log = logging.getLogger()

"""
    todo:
        - python 3.7/3.8 connection object have backup method, so we can work with memory database and only write to disk in case of error
            see: https://docs.python.org/3.8/library/sqlite3.html#sqlite3.Connection.backup
        - replace iids in index_item_detail_t with index_item_t._id ?
        - normalize detail_name with table of names?
        - review indexes, do they really improve performance
        - lower case table names
        - svnitem - review whole parent/child relationship
"""

force_disk_db = False
unique_name_to_disk_db = False


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
    def __init__(self, db_url: str, ddl_folder: Path) -> None:
        self.top_user_version = 1  # user_version is a standard pragma tha defaults to 0
        if db_url == ":memory:":
            self.memory_db = True
            self.db_file_path = None
        else:
            self.memory_db = False
            self.db_file_path = Path(db_url)
        self.ddl_files_dir = ddl_folder
        self.__conn = None
        self.__curs = None
        self.locked_tables = set()
        self.statistics = defaultdict(Statistic)
        self.print_execute_times = False
        self.transaction_depth = 0

    def get_file_path(self) -> str:
        if self.memory_db:
            return ":memory:"
        else:
            return os.fspath(self.db_file_path)

    def init_from_ddl(self, ddl_files_dir: Path, db_file_path: Path):
        self.ddl_files_dir = ddl_files_dir
        self.open()

    def init_from_existing_connection(self, conn, curs):
        self.__conn = conn
        self.__curs = curs
        self.configure_db()
        self.exec_script_file("create-tables.ddl")
        self.exec_script_file("init-values.ddl")

    def open(self):
        if not self.__conn:
            try:
                create_new_db = self.memory_db or not self.db_file_path.is_file()
            except:
                create_new_db = True
            db_path_for_sqlite = ":memory:" if self.memory_db else os.fspath(self.db_file_path)
            self.__conn = sqlite3.connect(db_path_for_sqlite)

            self.__curs = self.__conn.cursor()
            self.configure_db()
            if create_new_db:
                #self.progress(f"created new db file {self.db_file_path}")
                self.exec_script_file("create-tables.ddl")
                self.exec_script_file("init-values.ddl")
                self.exec_script_file("create-indexes.ddl")
            else:
                pass
                #self.progress(f"reused existing db file {db_base_self.db_file_path}")

    def set_db_file_owner(self):
        # utils.add_to_actions_stack(f"""chmod db path {self.db_file_path} '""")
        if not self.memory_db and self.db_file_path.is_file():
            utils.chown_chmod_on_path(self.db_file_path)

    def configure_db(self):
        self.set_db_pragma("foreign_keys", "ON")
        self.set_db_pragma("user_version", self.top_user_version)
        #self.__conn.set_authorizer(self.authorizer_handler_sqlite3)
        #self.__conn.set_progress_handler(self.progress_handler_sqlite3, 8)
        self.__conn.row_factory = sqlite3.Row
        self.__conn.set_trace_callback(None)

    def authorizer_handler_sqlite3(self, *args, **kwargs):
        """ callback for sqlite3.connection.set_authorizer"""
        return sqlite3.SQLITE_OK

    def set_progress_handler(self, progress_callback, n_instructions):
        """ callback for sqlite3.connection.set_progress_handler"""
        self.__conn.set_progress_handler(progress_callback, n_instructions)

    def create_function(self, func_name, num_params, func_ptr):
        self.__conn.create_function(func_name, num_params, func_ptr)

    def close_and_delete(self):
        self.close()
        if not self.memory_db:
            from pybatch import RmFile
            with RmFile(self.db_file_path, report_own_progress=False) as rf:
                rf()

    def close(self):
        if self.__conn:
            self.__conn.close()
            self.__conn = None
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

    class ProgressCallBacker:
        def __init__(self, db_master, _description, _progress_callback, _n_instructions):
            self.db_master = db_master
            self.description = _description
            self.progress_callback = _progress_callback
            self.n_instructions = _n_instructions
            self.counter = 0

        def __enter__(self):
            if self.progress_callback:
                self.progress_callback(f"{self.description} {self.counter}")
                self.db_master.set_progress_handler(self, self.n_instructions)

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.progress_callback:
                self.db_master.set_progress_handler(None, 0)

        def __call__(self, *args, **kwargs):
            self.counter += 1
            self.progress_callback(f"{self.description} {self.counter}")

    @contextmanager
    def transaction(self, description=None, progress_callback=None, progress_callback_n_instructions=50*1024*1024):
        try:

            if not description:
                try:  # sporadically inspect.stack()[2] will raise 'list index out of range'
                    description = inspect.stack()[2][3]
                except IndexError as ex:
                    description = "unknown"
            with self.ProgressCallBacker(self, description, progress_callback, progress_callback_n_instructions):
                #time1 = time.perf_counter()
                self.begin()
                yield self.__curs
                self.commit()
                #time2 = time.perf_counter()
                #if self.print_execute_times:
                #    print('DB transaction %s took %0.3f ms' % (description, (time2-time1)*1000.0))
                #self.statistics[description].add_instance((time2-time1)*1000.0)
        except sqlite3.OperationalError as s3oo:
            if not self.memory_db:
                log.error("database error, disk %s", str(shutil.disk_usage(self.db_file_path.parent)), exc_info=True)
            self.rollback()
        except:
            self.rollback()
            raise

    @contextmanager
    def selection(self, description=None, progress_callback=None, progress_callback_n_instructions=50*1024*1024):
        """ returns a cursor for SELECT queries.
            no commit is done
        """
        try:
            if not description:
                description = inspect.stack()[2][3]
            with self.ProgressCallBacker(self, description, progress_callback, progress_callback_n_instructions):
                #time1 = time.perf_counter()
                yield self.__conn.cursor()
                #time2 = time.perf_counter()
                #if self.print_execute_times:
                #    if not description:
                #        description = inspect.stack()[2][3]
                #    print('DB selection %s took %0.3f ms' % (description, (time2-time1)*1000.0))
                #self.statistics[description].add_instance((time2-time1)*1000.0)
        except Exception as ex:
            raise

    @contextmanager
    def temp_transaction(self, description=None, progress_callback=None, progress_callback_n_instructions=50*1024*1024):
        """ returns a cursor for working with CREATE TEMP TABLE.
            no commit is done
        """
        try:
            if not description:
                description = inspect.stack()[2][3]
            with self.ProgressCallBacker(self, description, progress_callback, progress_callback_n_instructions):
                #time1 = time.perf_counter()
                yield self.__conn.cursor()
                #time2 = time.perf_counter()
                #if self.print_execute_times:
                #    if not description:
                #        description = inspect.stack()[2][3]
                #    print('DB temporary transaction %s took %0.3f ms' % (description, (time2-time1)*1000.0))
                #self.statistics[description].add_instance((time2-time1)*1000.0)
        except Exception as ex:
            raise

    def exec_script_file(self, file_name):
        with self.transaction("exec_script_file_"+file_name) as curs:
            if os.path.isfile(file_name):
                script_file_path = Path(file_name)
            else:
                script_file_path = self.ddl_files_dir.joinpath(file_name)
            with utils.utf8_open_for_read(script_file_path, "r") as rfd:
                ddl_text = rfd.read()
                curs.executescript(ddl_text)

    def select_and_fetchone(self, query_text, query_params=None, progress_callback=None):
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
            with self.selection(description=description, progress_callback=progress_callback) as curs:
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

    def select_and_fetchall(self, query_text, query_params=None, progress_callback=None):
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
            with self.selection(description=description, progress_callback=progress_callback) as curs:
                curs.execute(query_text, query_params)
                all_results = curs.fetchall()
                if all_results:
                    if len(all_results[0]) == 1:  # all_results is a list of one item lists, so flaten and return a list of items
                        retVal.extend([res[0] for res in all_results])
                    else:
                        retVal.extend(all_results)
        except sqlite3.Error as ex:
            raise
        return retVal

    def lock_table(self, table_name):
        query_text = f"""-- noinspection SqlResolveForFile

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
            self.get_default_db_file()
            db_url = config_vars["__MAIN_DB_FILE__"].Path()
            ddls_folder = config_vars["__INSTL_DEFAULTS_FOLDER__"].Path()
            self._db = DBMaster(os.fspath(db_url), ddls_folder)
            config_vars["__DATABASE_URL__"] = db_url
        return self._db

    def __delete__(self, instance):
        if self._db is not None:
            self._db.close()
            del self._db
            self._db = None

    def get_default_db_file(self):
        if "__MAIN_DB_FILE__" not in config_vars:
            db_base_path = None
            if "__MAIN_OUT_FILE__" in config_vars:
                # try to set the db file next to the output file
                db_base_path = config_vars["__MAIN_OUT_FILE__"].Path()
            elif "__MAIN_INPUT_FILE__" in config_vars:
                # if no output file try next to the input file
                db_base_path = Path(config_vars.resolve_str("$(__MAIN_INPUT_FILE__)-$(__MAIN_COMMAND__)"))
            else:
                # as last resort try the Logs folder
                logs_dir = utils.get_system_log_folder_path()
                if logs_dir.is_dir():
                    db_base_path = logs_dir.joinpath(config_vars.resolve_str("instl-$(__MAIN_COMMAND__)"))

            if db_base_path:
                # set the proper extension
                db_base_path = db_base_path.parent.joinpath(db_base_path.name+config_vars.resolve_str(".$(DB_FILE_EXT)"))
                config_vars["__MAIN_DB_FILE__"] = db_base_path
        log.info(f'DB FILE: {config_vars["__MAIN_DB_FILE__"].str()}')
        if self._owner.refresh_db_file:
            if config_vars["__MAIN_DB_FILE__"].str() != ":memory:":
                db_base_path = config_vars["__MAIN_DB_FILE__"].Path()
                if db_base_path.is_file():
                    utils.safe_remove_file(db_base_path)
                    log.info(f'DB FILE REMOVED: {config_vars["__MAIN_DB_FILE__"].str()}')
                else:
                    log.info(f'DB FILE DOES NOT EXIST: {config_vars["__MAIN_DB_FILE__"].str()}')






class TableAccess(object):
    def __init__(self, _type):
        self._table = None
        self._owner = None  # for reference and debugging
        self._name = None   # for reference and debugging
        self._type = _type

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
        these instances will be created on the fly when accessed, so instances that do not need any of these will
        not suffer the penalty of creating them.
    """
    db = DBAccess()
    info_map_table = TableAccess(SVNTable)
    items_table = TableAccess(IndexItemsTable)
    refresh_db_file = False

    @classmethod
    def set_refresh_db_file(cls, to_refresh):
        cls.refresh_db_file = to_refresh

    @classmethod
    def reset_db(cls):
        if cls.db:
            cls.db.close_and_delete()
        cls.db = DBAccess()
        cls.info_map_table = TableAccess(SVNTable)
        cls.items_table = TableAccess(IndexItemsTable)
        cls.refresh_db_file = False
