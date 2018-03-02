import os
import sqlite3

import utils


class DBMaster(object):
    def __init__(self):
        self.top_user_version = 1  # user_version is a standard pragma tha defaults to 0
        self.ddl_files_dir = None
        self.db_file_path = None
        self.__conn = None
        self.__curs = None

    def init_from_ddl(self, ddl_files_dir, db_file_path):
        self.ddl_files_dir = ddl_files_dir
        self.db_file_path = db_file_path
        self.open()

    def init_from_existing_db(self, conn, curs):
        self.__conn = conn
        self.__curs = curs
        self.set_db_pragma("foreign_keys", "ON")

    def open(self):
        self.__conn = sqlite3.connect(self.db_file_path)
        self.__curs = self.__conn.cursor()
        self.set_db_pragma("foreign_keys", "ON")
        self.exec_script_file("create-tables.ddl")
        self.set_db_pragma("user_version", self.top_user_version)

    def close(self):
        if self.__conn:
            self.__conn.close()

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

    def commit(self):
        self.__conn.commit()

    @property
    def curs(self):
        return self.__curs

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


class ActiveOperatingSystem(object):
    def __init__(self, db_master):
        self.db_master = db_master

    def get_ids_and_oses(self):
        return self.db_master.select_and_fetchall("SELECT _id, name FROM IndexItemDetailOperatingSystem")

    def get_ids_oses_active(self):
        return self.db_master.select_and_fetchall("SELECT _id, name, os_is_active FROM IndexItemDetailOperatingSystem")

    def get_oses_and_active(self):
        query_text = """
        SELECT name, os_is_active
        FROM IndexItemDetailOperatingSystem
        ORDER BY _id
        """
        return self.db_master.select_and_fetchall(query_text)

    def activate_all_oses(self):
        """ adds all known os names to the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        query_text = """
            UPDATE IndexItemDetailOperatingSystem
            SET os_is_active = 1
         """
        try:
            self.db_master.execute_no_fetch(query_text)
            self.db_master.commit()
        except sqlite3.Error as ex:
            print(ex)
            raise

    def reset_active_oses(self):
        """ resets the list of os that will influence all get functions
            such as depend_list, source_list etc.
            This method is useful in code that does reporting or analyzing, where
            there is need to have access to all oses not just the current or target os.
        """
        self.activate_specific_oses()

    def activate_specific_oses(self, *for_oses):
        """ adds another os name to the list of os that will influence all get functions
            such as depend_list, source_list etc.
        """
        for_oses = *for_oses, "common"
        quoted_os_names = [utils.quoteme_double(os_name) for os_name in for_oses]
        query_vars = ", ".join(quoted_os_names)
        query_text = """
            UPDATE IndexItemDetailOperatingSystem
            SET os_is_active = CASE WHEN IndexItemDetailOperatingSystem.name IN ({0}) THEN
                    1
                ELSE
                    0
                END;
        """.format(query_vars)
        try:
            self.db_master.execute_no_fetch(query_text)
            self.db_master.commit()
        except sqlite3.Error as ex:
            print(ex)
            raise


if __name__ == "__main__":
    ddl_path = "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl/defaults"
    db_path = "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl/defaults/instl.sqlite"
    utils.safe_remove_file(db_path)
    db = DBMaster()
    db.init_from_ddl(ddl_path, db_path)
    db.exec_script_file("init-values.ddl")

    oses_t = ActiveOperatingSystem(db)
    print("creation:", oses_t.get_ids_oses_active())

    oses_t.activate_specific_oses("Mac64", "Win32")
    print("Mac64:", oses_t.get_ids_oses_active())

    oses_t.reset_active_oses()
    print("reset_active_oses:", oses_t.get_ids_oses_active())

    oses_t.activate_all_oses()
    print("activate_all_oses:", oses_t.get_ids_oses_active())

    #db.exec_script_file("create-indexes.ddl")
    #db.exec_script_file("create-triggers.ddl")
    #db.exec_script_file("create-views.ddl")
