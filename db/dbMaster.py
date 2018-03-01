import os
import sqlite3

import utils


class DBMaster(object):
    def __init__(self, ddl_files_dir, db_file_path):
        self.top_user_version = 1  # user_version is a standard pragma tha defaults to 0
        self.ddl_files_dir = ddl_files_dir
        self.db_file_path = db_file_path
        self.__conn = None
        self.__curs = None
        self.open()

    def exec_script(self, file_name):
        script_file_path = os.path.join(self.ddl_files_dir, file_name)
        ddl_text = open(script_file_path, "r").read()
        self.__curs.executescript(ddl_text)
        self.commit()

    def open(self):
        self.__conn = sqlite3.connect(self.db_file_path)
        self.__curs = self.__conn.cursor()
        self.set_db_pragma("foreign_keys", "ON")
        self.exec_script("create-tables.ddl")
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


if __name__ == "__main__":
    ddl_path = "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl/defaults"
    db_path = "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl/defaults/instl.sqlite"
    utils.safe_remove_file(db_path)
    db = DBMaster(ddl_path, db_path)
    db.exec_script("create-indexes.ddl")
    db.exec_script("create-triggers.ddl")
    db.exec_script("create-views.ddl")
