#!/usr/bin/env python3


import os
import re
from functools import reduce
import csv

from sqlalchemy import update, Index
from sqlalchemy import or_
from sqlalchemy.ext import baked
from sqlalchemy import bindparam
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from pyinstl.db_alchemy import create_session, IndexItemDetailRow, get_engine, TableBase
from .svnRow import SVNRow, IIDToSVNItem

import utils
from configVar import var_stack

comment_line_re = re.compile(r"""
            ^
            \s*\#\s*
            (?P<the_comment>.*)
            $
            """, re.X)
text_line_re = re.compile(r"""
            ^
            (?P<path>.+)
            ,\s+
            (?P<flags>[dfsx]+)
            ,\s+
            (?P<revision>\d+)
            (,\s+
            (?P<checksum>[\da-f]+))?    # 5985e53ba61348d78a067b944f1e57c67f865162
            (,\s+
            (?P<size>[\d]+))?       # 356985
            (,\s+
            (?P<url>(http(s)?|ftp)://[^,]+))?    # http://....
            (,\s+dl_path:'
            (?P<dl_path>([^',]+))')?
            """, re.X)
flags_and_revision_re = re.compile(r"""
                ^
                \s*
                (?P<flags>[fdxs]+)
                \s*
                (?P<revision>\d+)
                (\s*
                (?P<checksum>[\da-f]+))? # 5985e53ba61348d78a067b944f1e57c67f865162
                $
                """, re.X)

map_info_extension_to_format = {"txt": "text", "text": "text",
                                "inf": "info", "info": "info",
                                "props": "props", "prop": "props",
                                "file-sizes": "file-sizes"}


class SVNTable(TableBase):
    def __init__(self):
        super().__init__()
        self.read_func_by_format = {"info": self.read_from_svn_info,
                                    "text": self.read_from_text,
                                    "props": self.read_props,
                                    "file-sizes": self.read_file_sizes
                                    }

        self.write_func_by_format = {"text": self.write_as_text,}
        self.files_read_list = list()
        self.files_written_list = list()
        self.comments = list()
        self.baked_queries_map = dict()
        self.bakery = baked.bakery()

    def __repr__(self):
        return "\n".join([item.__repr__() for item in self.get_items()])

    def repr_to_file(self, file_path):
        with utils.utf8_open(file_path, "w") as wfd:
            wfd.write(self.__repr__())

    def valid_read_formats(self):
        """ returns a list of file formats that can be read by SVNTree """
        return list(self.read_func_by_format.keys())

    def read_from_file(self, in_file, a_format="guess"):
        """ Reads from file. All previous sub items are cleared
            before reading, unless the a_format is 'props' in which case
            the properties are added to existing sub items.
            raises ValueError is a_format is not supported.
        """
        if a_format == "guess":
            _, extension = os.path.splitext(in_file)
            a_format = map_info_extension_to_format[extension[1:]]
        self.comments.append("Original file " + in_file)
        if a_format in list(self.read_func_by_format.keys()):
            with utils.open_for_read_file_or_url(in_file) as open_file:
                self.read_func_by_format[a_format](open_file.fd)
                self.files_read_list.append(in_file)
        else:
            raise ValueError("Unknown read a_format " + a_format)

    def read_from_svn_info(self, rfd):
        """ reads new items from svn info items prepared by iter_svn_info
            items are inserted in lexicographic directory order, so '/'
            sorts before other characters: key=lambda x: x['path'].split('/')
        """
        svn_info_line_re = re.compile("""
                    ^
                    (?P<key>Path|Last\ Changed\ Rev|Node\ Kind|Revision|Checksum|Tree\ conflict)
                    :\s*
                    (?P<rest_of_line>.*)
                    $
                    """, re.VERBOSE)

        def yield_row(_rfd_):
            def create_list_from_record(a_record):
                try:
                    row_data = list()
                    row_data.append(a_record["Path"])
                    if "Last Changed Rev" in a_record:
                        row_data.append(int(a_record["Last Changed Rev"]))
                    elif "Revision" in a_record:
                        row_data.append(int(a_record["Revision"]))
                    else:
                        row_data.append(-1)
                    row_data.append(a_record.get("Checksum", None))
                    row_data.extend(self.level_parent_and_leaf_from_path(a_record["Path"]))  # level, parent, leaf
                    if a_record["Node Kind"] == "file":
                        row_data.append('f')        # flags
                        row_data.append(1)          # fileFlag
                        row_data.append(1 if utils.wtar_file_re.match(a_record["Path"]) else 0)                     # wtarFlag
                    elif a_record["Node Kind"] == "directory":
                        row_data.append('d')
                        row_data.append(0)         # fileFlag
                        row_data.append(0)         # wtarFlag

                    row_data.extend((0, 0, ""))  # required, need_download, extra_props
                    return row_data
                except KeyError as unused_ke:
                    print(unused_ke)
                    print("Error:", "line:", line_num, "record:", record)
                    raise

            record = dict()
            line_num = 0
            for line in _rfd_:
                line_num += 1
                if line != "\n":
                    the_match = svn_info_line_re.match(line)
                    if the_match:
                        if the_match.group('key') == "Tree conflict":
                            raise ValueError(
                                " ".join(("Tree conflict at line", str(line_num), "Path:", record['Path'])))
                        record[the_match.group('key')] = the_match.group('rest_of_line')
                else:
                    if record and record["Path"] != ".":  # in case there were several empty lines between blocks
                        yield create_list_from_record(record)
                    record.clear()
            if record and record["Path"] != ".":  # in case there was no extra line at the end of file
                yield create_list_from_record(record)

        db_conn = get_engine().raw_connection()
        db_curs = db_conn.cursor()
        insert_q = """
        INSERT INTO svnitem (path, revision,
                              checksum,
                              level, parent, leaf,
                              flags, fileFlag, wtarFlag,
                              required, need_download, extra_props)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?);
        """
        db_curs.executemany(insert_q, yield_row(rfd))
        db_conn.commit()
        db_curs.close()
        db_conn.close()
        SVNTable.create_indexes()

    def read_from_text(self, rfd):
        def yield_row(_rfd_):
            reader = csv.reader(_rfd_, skipinitialspace=True)
            for row in reader:
                if row and row[0][0] != '#':
                    info_map_line_defaults = ('!path!', '!flags!', '!repo-rev!', None, 0, None)
                    row_data = list(utils.iter_complete_to_longest(row, info_map_line_defaults))  # path, flags, revision, checksum, size, url
                    row_data.extend(self.level_parent_and_leaf_from_path(row_data[0]))  # level, parent, leaf
                    row_data.append(1 if 'f' in row_data[1] else 0)  # fileFlag
                    row_data.append(1 if utils.wtar_file_re.match(row_data[0]) else 0)  # wtarFlag
                    row_data.extend((0, 0))  # required, need_download
                    yield row_data

        db_conn = get_engine().raw_connection()
        db_curs = db_conn.cursor()
        insert_q = """
        INSERT INTO svnitem (path, flags, revision,
                              checksum, size, url,
                              level, parent, leaf,
                              fileFlag, wtarFlag,
                              required, need_download)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?);
        """
        db_curs.executemany(insert_q, yield_row(rfd))
        db_conn.commit()
        db_curs.close()
        db_conn.close()

    @staticmethod
    def get_wtar_file_status(file_name):
        is_wtar_file = utils.is_wtar_file(file_name)
        is_wtar_first_file = utils.is_first_wtar_file(file_name)
        return is_wtar_file, is_wtar_first_file

    @staticmethod
    def level_parent_and_leaf_from_path(in_path):
        path_parts = in_path.split("/")
        return len(path_parts), "/".join(path_parts[:-1]), path_parts[-1]

    def valid_write_formats(self):
        return list(self.write_func_by_format.keys())

    def write_to_file(self, in_file, in_format="guess", comments=True, items_list=None, field_to_write=None):
        """ pass in_file="stdout" to output to stdout.
            in_format is either text, yaml, pickle
        """

        if items_list is None:
            items_list = self.get_items()
        if in_format == "guess":
            _, extension = os.path.splitext(in_file)
            in_format = map_info_extension_to_format[extension[1:]]
        if in_format in list(self.write_func_by_format.keys()):
            with utils.write_to_file_or_stdout(in_file) as wfd:
                self.write_func_by_format[in_format](wfd, items_list, comments, field_to_write=field_to_write)
                self.files_written_list.append(in_file)
        else:
            raise ValueError("Unknown write in_format " + in_format)

    def write_as_text(self, wfd, items_list, comments=True, field_to_write=None):
        if comments and len(self.comments) > 0:
            for comment in self.comments:
                wfd.write("# " + comment + "\n")
            wfd.write("\n")
        for item in items_list:
            wfd.write(item.str_specific_fields(field_to_write) + "\n")

    def initialize_from_folder(self, in_folder):
        def yield_row(_in_folder_):
            base_folder_len = len(_in_folder_)+1
            for root, dirs, files in os.walk(_in_folder_, followlinks=False):
                for item in sorted(files + dirs):
                    if item == ".DS_Store": # temp hack, list of ignored files should be moved to a variable
                        continue
                    row_data = list()
                    full_path  = os.path.join(root, item)
                    relative_path = full_path[base_folder_len:]
                    row_data.append(relative_path)  # path
                    # check for link first: os.path.isdir returns True for a link to dir
                    if os.path.islink(full_path):
                        flags = "fs"
                    elif os.path.isfile(full_path):
                        if os.access(full_path, os.X_OK):
                            flags = "fx"
                        else:
                            flags = "f"
                    else:
                        flags = "d"
                    row_data.append(flags)  # flags
                    row_data.append(0)      # revision
                    row_data.extend(self.level_parent_and_leaf_from_path(relative_path))  # level, parent, leaf
                    row_data.append(1 if 'f' in flags else 0)  # fileFlag
                    row_data.append(1 if utils.wtar_file_re.match(relative_path) else 0)  # wtarFlag
                    yield row_data

        db_conn = get_engine().raw_connection()
        db_curs = db_conn.cursor()
        insert_q = """
        INSERT INTO svnitem (path, flags, revision,
                              level, parent, leaf,
                              fileFlag, wtarFlag)
         VALUES(?,?,?,?,?,?,?,?);
        """
        db_curs.executemany(insert_q, yield_row(in_folder))
        db_conn.commit()
        db_curs.close()
        db_conn.close()

    def num_items(self, item_filter="all-items"):
        retVal = 0
        if item_filter == "all-items":
            retVal = self.session.query(SVNRow.path).count()
        elif item_filter == "all-files":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.fileFlag == True).count()
        elif item_filter == "all-dirs":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.fileFlag == False).count()
        if item_filter == "required-items":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.required == True).count()
        elif item_filter == "required-files":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.fileFlag == True, SVNRow.required == True).count()
        elif item_filter == "required-dirs":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.fileFlag == False, SVNRow.required == True).count()
        if item_filter == "unrequired-item":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.required == False).count()
        elif item_filter == "unrequired-files":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.fileFlag == True, SVNRow.required == False).count()
        elif item_filter == "unrequired-dirs":
            retVal = self.session.query(SVNRow.path).filter(SVNRow.fileFlag == False, SVNRow.required == False).count()
        return retVal

    def clear_all(self):
        self.session.query(SVNRow).delete()
        self.commit_changes()
        self.comments = list()

    def set_base_revision(self, base_revision):
        update_q = """
            UPDATE  svnitem
            SET revision = :base_revision
            WHERE revision < :base_revision
        """
        self.session.execute(update_q, {"base_revision": base_revision})
        self.commit_changes()

    def read_file_sizes(self, rfd):
        def yield_row(_rfd_):
            line_num = 0
            for line in rfd:
                line_num += 1
                match = comment_line_re.match(line)
                if not match:
                    parts = line.rstrip().split(", ", 2)
                    if len(parts) != 2:
                        print("weird line:", line, line_num)
                    yield {"old_path": parts[0], "new_size": int(parts[1])}  # path, size

        db_conn = get_engine().raw_connection()
        db_curs = db_conn.cursor()
        update_q = """
            UPDATE  svnitem
            SET size = :new_size
            WHERE path = :old_path
            """
        db_curs.executemany(update_q, yield_row(rfd))
        db_conn.commit()
        db_curs.close()
        db_conn.close()

    def read_props(self, rfd):
        props_line_re = re.compile("""
                    ^
                    (
                    Properties\son\s
                    '
                    (?P<path>[^:]+)
                    ':
                    )
                    |
                    (
                    \s+
                    svn:
                    (?P<prop_name>[\w\-_]+)
                    )
                    $
                    """, re.X)
        line_num = 0
        try:
            update_queries_list = list()
            prop_name_to_flag = {'executable': 'x', 'special': 's'}
            props_to_ignore = ['mime-type']
            path = None
            for line in rfd:
                line_num += 1
                match = props_line_re.match(line)
                if match:
                    if match.group('path'):
                        path = match.group('path')
                    elif match.group('prop_name'):
                        if path is not None:
                            prop_name = match.group('prop_name')
                            if prop_name in prop_name_to_flag:
                                update_query = """
                                    UPDATE svnitem
                                    SET flags = flags || "{new_prop}"
                                    WHERE path = "{old_path}";
                                """.format(new_prop=prop_name_to_flag[prop_name],
                                           old_path=path)
                                self.session.execute(update_query)
                            elif prop_name not in props_to_ignore:
                                update_query = """
                                    UPDATE svnitem
                                    SET extra_props = extra_props || "{prop_name}" || ";"
                                    WHERE path = "{old_path}";
                                """.format(prop_name=prop_name,
                                           old_path=path)
                                self.session.execute(update_query)
                else:
                    ValueError("no match at file: " + rfd.name + ", line: " + str(line_num) + ": " + line)
            self.commit_changes()
        except Exception as ex:
            print("Line:", line_num, ex)
            raise

    def get_item(self, item_path, what="any"):
        """ Get specific item or return None if not found
        :param item_path: path to the item
        :param what: either "any" (will return file or dir), "file", "dir
        :return: item found or None
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        # get_one_item query: return specific item which could be a dir or a file, used by get_item()
        if "get_one_item" not in self.baked_queries_map:
            self.baked_queries_map["get_one_item"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_one_item"] += lambda q: q.filter(SVNRow.path == bindparam('item_path'))
            self.baked_queries_map["get_one_item"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.fileFlag == bindparam('dir')))

        retVal = None
        try:
            want_file = what in ("any", "file")
            want_dir = what in ("any", "dir")
            retVal = self.baked_queries_map["get_one_item"](self.session).params(item_path=item_path, file=want_file, dir=not want_dir).one()
        except NoResultFound:
            pass
        return retVal

    def get_files_that_should_be_removed_from_sync_folder(self, files_to_check):
        """
        :param files_to_check: a list of tuples [(partial_path, full_path), ...]
        :return: list of indexes into files_to_check who's partial path is not in info_map
        """
        retVal = list()
        db_conn = get_engine().raw_connection()
        self.cursor = db_conn.cursor()
        db_curs = self.cursor
        script_text = """
        CREATE TABLE paths_from_disk_t
        (
          item_num INTEGER,
          path VARCHAR
        );
        """
        # each partial path is inserted with it's index in the list
        list_of_inserts = ["""INSERT INTO paths_from_disk_t (item_num, path) VALUES ({}, "{}");""".format(i, path_pair[0]) for i, path_pair in enumerate(files_to_check)]
        script_text += "\n".join(list_of_inserts)
        try:
            script_results = db_curs.executescript(script_text)

            # this query will select all files found in the sync folder that are not in the info_map
            # database, BUT will exclude those files in folders that have their own info_map for
            # items that are not currently being installed.
            query_text = """
            SELECT file_index
            FROM
            (SELECT  paths_from_disk_t.item_num AS file_index
              FROM paths_from_disk_t
              WHERE UPPER(paths_from_disk_t.path) NOT IN (SELECT UPPER(path) FROM svnitem))
            
            WHERE file_index NOT IN (
                SELECT paths_from_disk_t.item_num
                FROM paths_from_disk_t
                JOIN IndexItemDetailRow AS sources_t
                    ON sources_t.detail_name = 'install_sources'
                    AND paths_from_disk_t.path LIKE sources_t.detail_value || "/%"
                JOIN IndexItemRow ON
                    IndexItemRow.install_status = 0
                    AND IndexItemRow.iid = sources_t.owner_iid
                JOIN IndexItemDetailRow AS info_map_t ON
                    info_map_t.detail_name = 'info_map'
                    AND IndexItemRow.iid = info_map_t.owner_iid
)            """
            exec_result = db_curs.execute(query_text)
            retVal.extend([fr[0] for fr in exec_result.fetchall()])
            db_curs.close()
            db_conn.close()
        except SQLAlchemyError as ex:
            raise
        return retVal

    def get_item_case_insensitive(self, item_path, what="any"):
        """ Get specific item or return None if not found
        search is done case insensitive. This is needed in case where we look for
        a file that exist on disk in the database.
        :param item_path: path to the item
        :param what: either "any" (will return file or dir), "file", "dir
        :return: item found or None
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        item_path = item_path.lower()
        # get_one_item query: return specific item which could be a dir or a file, used by get_item()
        if "get_item_case_insensitive" not in self.baked_queries_map:
            self.baked_queries_map["get_item_case_insensitive"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_item_case_insensitive"] += lambda q: q.filter(func.lower(SVNRow.path) == bindparam('item_path'))
            self.baked_queries_map["get_item_case_insensitive"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.fileFlag == bindparam('dir')))

        retVal = None
        try:
            want_file = what in ("any", "file")
            want_dir = what in ("any", "dir")
            retVal = self.baked_queries_map["get_item_case_insensitive"](self.session).params(item_path=item_path, file=want_file, dir=not want_dir).one()
        except NoResultFound:
            pass
        return retVal

    def get_items(self, what="any", levels_deep=1024):
        """
        get_items applies a filter and return all items
        :param filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        # get_all_items: return all items either files dirs or both, used by get_items()
        if "get_all_items" not in self.baked_queries_map:
            self.baked_queries_map["get_all_items"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_all_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.fileFlag == bindparam('dir')))
            self.baked_queries_map["get_all_items"] += lambda q: q.filter(SVNRow.level <= bindparam('levels_deep'))
            self.baked_queries_map["get_all_items"] += lambda q: q.order_by(SVNRow.path)

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_all_items"](self.session).params(file=want_file, dir=not want_dir, levels_deep=levels_deep).all()
        return retVal

    def get_required_items(self, what="any", get_unrequired=False):
        """
        get_items applies a filter and return all items
        :param filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        # get_required_items: return all required (or unrequired) items either files dirs or both, used by get_required_items()
        if "get_required_items" not in self.baked_queries_map:
            self.baked_queries_map["get_required_items"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_required_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.fileFlag == bindparam('dir')))
            self.baked_queries_map["get_required_items"] += lambda q: q.filter(or_(SVNRow.required == bindparam('required')))
            self.baked_queries_map["get_required_items"] += lambda q: q.order_by(SVNRow.path)

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_required_items"](self.session).params(required=not get_unrequired, file=want_file, dir=not want_dir).all()
        return retVal

    def get_exec_file_paths(self):
        query_text = """
          SELECT path
          FROM svnitem
          WHERE flags == 'fx' 
        """
        retVal = self.select_and_fetchall(query_text)
        return retVal

    def get_required_exec_items(self, what="any"):
        """ :return: all required fies that are also exec
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")


        # required-exec-files: return all required files that are executables, used by get_required_exec_items()
        if "get_required_exec_items" not in self.baked_queries_map:
            self.baked_queries_map["get_required_exec_items"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_required_exec_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.fileFlag == bindparam('dir')))
            self.baked_queries_map["get_required_exec_items"] += lambda q: q.filter(SVNRow.required == True, SVNRow.flags.contains('x'))
            self.baked_queries_map["get_required_exec_items"] += lambda q: q.order_by(SVNRow.path)

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_required_exec_items"](self.session).params(file=want_file, dir=not want_dir).all()
        return retVal

    def get_download_items(self, what="any"):
        """
        get_items applies a filter and return all items
        :param: filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        # get_exec_items: return all exec items either files dirs or both, used by get_exec_items()
        if "get_download_items" not in self.baked_queries_map:
            self.baked_queries_map["get_download_items"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_download_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.fileFlag == bindparam('dir')))
            self.baked_queries_map["get_download_items"] += lambda q: q.filter(SVNRow.need_download == True)
            self.baked_queries_map["get_download_items"] += lambda q: q.order_by(SVNRow.path)

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_download_items"](self.session).params(file=want_file, dir=not want_dir).all()
        return retVal

    def get_not_to_download_num_files_and_size(self):
        """ return the count and total size of the files that are already synced """
        query_text = """
            SELECT COUNT(*) as num_files, TOTAL(size) as total_size
            FROM svnitem
            WHERE required=1
            AND need_download=0
            AND fileFlag=1
            """
        try:
            retVal = self.session.execute(query_text).first()
        except SQLAlchemyError:
            raise
        return retVal[0], int(retVal[1])  # sqlite's TOTAL returns float

    def get_to_download_files_and_size(self):
        """
        :return: a tuple: (a list of fies marked for download, their total size)
        """
        file_list = self.get_download_items(what="file")
        total_size = reduce(lambda total, item: total + item.size, file_list, 0)
        return file_list, total_size

    def get_required_for_file(self, file_path):
        """ get the item for a required file as or if file was wtarred
            get the wtar files.
        """

        if "required_items_for_file" not in self.baked_queries_map:
            self.baked_queries_map["required_items_for_file"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["required_items_for_file"] += lambda q: q.filter(SVNRow.fileFlag==True)
            self.baked_queries_map["required_items_for_file"] += lambda q: q.filter(or_(SVNRow.path == bindparam('file_path'), SVNRow.path.like(bindparam('file_path') + ".wtar%")))
            self.baked_queries_map["required_items_for_file"] += lambda q: q.order_by(SVNRow.path)

        retVal = self.baked_queries_map["required_items_for_file"](self.session).params(file_path=file_path).all()
        return retVal

    def mark_required_for_file(self, file_path):
        """ mark a file as required or if file was wtarred
            mark the wtar files are required.
        """
        update_statement = update(SVNRow)\
                .where(SVNRow.fileFlag == True)\
                .where(or_(SVNRow.path == file_path, SVNRow.path.like(file_path + ".wtar%")))\
                .values(required=True)
        results = self.session.execute(update_statement)
        return results.rowcount

    def get_file_items_of_dir(self, dir_path):
        """ get all file items in dir_path OR if the dir_path itself is wtarred - the wtarred file items.
            results are recursive so files from sub folders are also returned
        """
        if "get_file_items_of_dir" not in self.baked_queries_map:
            self.baked_queries_map["get_file_items_of_dir"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_file_items_of_dir"] += lambda q: q.filter(SVNRow.fileFlag == True)
            self.baked_queries_map["get_file_items_of_dir"] += lambda q: q.filter(or_(SVNRow.path.like(bindparam('dir_path')+"/%"),
                                                                                 SVNRow.path.like(bindparam('dir_path')+".wtar%")))
            self.baked_queries_map["get_file_items_of_dir"] += lambda q: q.order_by(SVNRow.path)

        files_of_dir = self.baked_queries_map["get_file_items_of_dir"](self.session).params(dir_path=dir_path).all()
        return files_of_dir

    def count_wtar_items_of_dir(self, dir_path):
        """ count all wtar items in dir_path OR if the dir_path itself is wtarred - count of wtarred file items.
            results are recursive so count from sub folders are also accumulated
        """
        retVal = 0
        query_text = """
            SELECT COUNT(*)
            FROM svnitem
            WHERE
              fileFlag = 1
              AND
              ( path LIKE "{dir_path}" || ".wtar%"
                OR
              path LIKE "{dir_path}" || "/%.wtar%" )
             """.format(dir_path=dir_path)
        try:
            retVal = self.session.execute(query_text).first()[0]
        except SQLAlchemyError:
            raise
        return retVal

    def get_items_in_dir(self, dir_path="", what="any", levels_deep=1024):
        """ get all files in dir_path.
            level_deep: how much to dig in. level_deep=1 will only get immediate files
            :return: list of items in dir or empty list (if there aren't any) or None
            if dir_path is not a dir
        """
        dir_items = []
        if dir_path == "":
            dir_items = self.get_items(what=what, levels_deep=levels_deep)
        else:
            root_dir_item = self.get_item(item_path=dir_path, what="dir")
            if root_dir_item is not None:
                if "dir_items_recursive" not in self.baked_queries_map:
                    self.baked_queries_map["dir_items_recursive"] = self.bakery(lambda session: session.query(SVNRow))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.filter(SVNRow.path.like(bindparam('dir_path')+"/%"))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.filter(SVNRow.level > bindparam('dir_level'))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.filter(SVNRow.level <= bindparam('dir_level')+bindparam('levels_deep'))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.fileFlag == bindparam('dir')))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.order_by(SVNRow.path)

                want_file = what in ("any", "file")
                want_dir = what in ("any", "dir")
                dir_items = self.baked_queries_map["dir_items_recursive"](self.session)\
                    .params(dir_path=dir_path, dir_level=root_dir_item.level, levels_deep=levels_deep,\
                            file=want_file, dir=not want_dir)\
                    .all()
            else:
                print(dir_path, "was not found")
        return dir_items

    def mark_required_for_dir(self, dir_path):
        """ mark all files & dirs in dir_path as required.
            marking is recursive.
        """
        dir_item = self.get_item(item_path=dir_path, what="dir")
        if dir_item is not None:
            update_statement = update(SVNRow)\
                    .where(SVNRow.fileFlag == True)\
                    .where(SVNRow.level > dir_item.level)\
                    .where(SVNRow.path.like(dir_item.path+"/%"))\
                    .values(required=True)
            results = self.session.execute(update_statement)
            retVal = results.rowcount
        else:
            # it might be a dir that was wtarred
            retVal = self.mark_required_for_file(dir_path)
        return retVal

    def mark_required_for_source(self, source):
        """ mark all files & dirs for specific source as required.
            :param source: a tuple (source_folder, tag), where tag is either !file or !dir
            :return: None
        """
        source_path, source_type = source[0], source[1]
        num_required_files = 0
        if source_type in ('!dir', '!dir_cont'):  # !dir and !dir_cont are only different when copying
            num_required_files = self.mark_required_for_dir(source_path)
        elif source_type == '!file':
            num_required_files = self.mark_required_for_file(source_path)
        self.commit_changes()
        return num_required_files

    def mark_required_completion(self):
        """ after some files were marked as required,
            mark their parent dirs are required as well
        """
        required_file_items = self.get_required_items(what="file")
        ancestors = list()
        for file_item in required_file_items:
            ancestors.extend(file_item.get_ancestry()[:-1])
        ancestors = sorted(list(set(ancestors)))
        # sqlite UPDATE cannot accept more than SQLITE_LIMIT_VARIABLE_NUMBER variables
        # SQLITE_LIMIT_VARIABLE_NUMBER == 999, but I found no way to get this number dynamically
        # following code does the updates in chunks:
        chunk_size = 512
        slice_begin = 0
        slice_end = 0
        while slice_end < len(ancestors):
            slice_end = min(slice_end + chunk_size, len(ancestors))
            update_statement = update(SVNRow)\
                    .where(SVNRow.path.in_(ancestors[slice_begin:slice_end]))\
                    .values(required=True)
            self.session.execute(update_statement)
            slice_begin += chunk_size
            self.commit_changes()

    def mark_need_download(self):
        ancestors = list()
        required_file_items = self.get_required_items(what="file")
        for file_item in required_file_items:
            if utils.need_to_download_file(file_item.download_path, file_item.checksum):
                file_item.need_download = True
                ancestors.extend(file_item.get_ancestry()[:-1])
        ancestors = sorted(list(set(ancestors)))
        # sqlite UPDATE cannot accept more than SQLITE_LIMIT_VARIABLE_NUMBER variables
        # SQLITE_LIMIT_VARIABLE_NUMBER == 999, but I found no way to get this number dynamically
        # following code does the updates in chunks:
        chunk_size = 512
        slice_begin = 0
        slice_end = 0
        while slice_end < len(ancestors):
            slice_end = min(slice_end + chunk_size, len(ancestors))
            update_statement = update(SVNRow)\
                    .where(SVNRow.path.in_(ancestors[slice_begin:slice_end]))\
                    .values(need_download=True)
            self.session.execute(update_statement)
            slice_begin += chunk_size
        self.commit_changes()

    def mark_required_for_revision(self, required_revision):
        """ mark all files and dirs as required if they are of specific revision
        """
        update_statement = update(SVNRow)\
            .where(SVNRow.fileFlag == True)\
            .where(SVNRow.revision == required_revision)\
            .values(required=True)
        self.session.execute(update_statement)
        self.commit_changes()
        self.mark_required_completion()

    def clear_required(self):
        update_statement = update(SVNRow)\
            .values(required=False)
        self.session.execute(update_statement)
        self.commit_changes()

    def get_unrequired_paths_where_parent_required(self, what="file"):
        """ Get all unrequired items that have a parent that is required.
            This is a  trick to leave as on disk only folders that have siblings that are required.
            used in InstlAdmin.do_upload_to_s3_aws_for_revision
        """
        if what not in ("file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        query_text = """
            SELECT path
            FROM svnitem
            WHERE required==0
            AND fileFlag==:get_files
            AND parent IN (
                SELECT path
                FROM svnitem
                WHERE required==1
                AND fileFlag==0)
            """
        retVal = self.select_and_fetchall(query_text, query_params={"get_files": {"file": 1, "dir": 0}[what]})
        return retVal

    def min_max_revision(self):
        min_revision = self.session.query(SVNRow, func.min(SVNRow.revision)).scalar()
        max_revision = self.session.query(SVNRow, func.max(SVNRow.revision)).scalar()
        return min_revision.revision, max_revision.revision

    def mark_required_files_for_active_items(self):
        query_text = """
        UPDATE svnitem
        SET required=1
        WHERE svnitem._id IN
        (
            SELECT svnitem._id
            FROM svnitem
            JOIN IndexItemRow as active_items_t
                ON active_items_t.install_status > 0
                AND active_items_t.ignore = 0
            JOIN IndexItemDetailRow as install_sources_t
                ON install_sources_t.owner_iid=active_items_t.iid
                AND install_sources_t.detail_name='install_sources'
                AND install_sources_t.os_is_active = 1
            WHERE fileFlag=1
            AND
                (
                  svnitem.path = install_sources_t.detail_value
                    OR
                  svnitem.path LIKE install_sources_t.detail_value || "/%"
                    OR
                  svnitem.path LIKE install_sources_t.detail_value || ".wtar%"
                )
        )
        """
        exec_result = self.session.execute(query_text)
        self.commit_changes()

    def get_download_roots(self):
        query_text = """
        SELECT DISTINCT
            coalesce(download_root, "$(LOCAL_REPO_SYNC_DIR)")
        FROM svnitem
        WHERE need_download=1
        AND fileFlag=1
        """
        retVal = self.select_and_fetchall(query_text)
        return retVal

    def get_infomap_file_names(self):
        """ infomap file names are stored in extra_props column by set_infomap_file_names
        """
        query_text = """
          SELECT DISTINCT extra_props
          FROM svnitem
          ORDER BY extra_props
        """
        retVal = self.select_and_fetchall(query_text)
        return retVal

    def get_items_by_infomap(self, infomap_name):
        """
        get_items_by_infomap returns all items that should be written to a specific infomap file
        infomap file names were stored in extra_props column by set_infomap_file_names
        :param infomap_name: e.g. GrandRhapsody_SD_Sample_Library_info_map.txt
        """
        retVal = list()
        if "get_items_by_infomap" not in self.baked_queries_map:
            self.baked_queries_map["get_items_by_infomap"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_items_by_infomap"] += lambda q: q.filter(SVNRow._id == IIDToSVNItem.svn_id)
            self.baked_queries_map["get_items_by_infomap"] += lambda q: q.filter(IndexItemDetailRow.owner_iid == IIDToSVNItem.iid)
            self.baked_queries_map["get_items_by_infomap"] += lambda q: q.filter(IndexItemDetailRow.detail_name == 'info_map')
            self.baked_queries_map["get_items_by_infomap"] += lambda q: q.filter(IndexItemDetailRow.detail_value == bindparam('infomap_name'))
            self.baked_queries_map["get_items_by_infomap"] += lambda q: q.order_by(SVNRow._id)

        retVal = self.baked_queries_map["get_items_by_infomap"](self.session).params(infomap_name=infomap_name).all()
        return retVal

    def get_items_for_default_infomap(self):
        select_all_q = self.session.query(SVNRow)

        select_non_default_info_map_items = self.session.query(SVNRow) \
                                            .filter(SVNRow._id == IIDToSVNItem.svn_id) \
                                            .filter(IIDToSVNItem.iid == IndexItemDetailRow.owner_iid) \
                                            .filter(IndexItemDetailRow.detail_name == 'info_map')

        select_default_info_map_items = select_all_q.except_(select_non_default_info_map_items)
        retVal = select_default_info_map_items.all()
        return retVal

    def populate_IIDToSVNItem(self):
        query_text = """
            INSERT INTO IIDToSVNItem (iid, svn_id)
            SELECT install_sources_t.owner_iid, svnitem._id
            FROM IndexItemDetailRow AS install_sources_t, svnitem
            WHERE
                install_sources_t.detail_name = 'install_sources'
                    AND
                (
                  svnitem.path = install_sources_t.detail_value 
                    OR
                  svnitem.path LIKE install_sources_t.detail_value || "/%"
                    OR
                  svnitem.path LIKE install_sources_t.detail_value || ".wtar%"
                )
            """
        self.session.execute(query_text)
        self.commit_changes()

    def set_info_map_file(self, info_map_file_name):
        query_text = """
            UPDATE svnitem
            SET extra_props = :info_map_file_name
            WHERE svnitem._id In (
            SELECT svnitem._id
            FROM svnitem, IIDToSVNItem, IndexItemDetailRow
            WHERE
                svnitem._id = IIDToSVNItem.svn_id
            AND
                IIDToSVNItem.iid = IndexItemDetailRow.owner_iid
            AND
                IndexItemDetailRow.detail_name = 'info_map'
            AND
                IndexItemDetailRow.detail_value = :info_map_file_name)
            """
        self.session.execute(query_text, {"info_map_file_name": info_map_file_name})
        self.commit_changes()

    @classmethod
    def create_indexes(cls):
        Index('required_idx', SVNRow.required).create(bind=get_engine())
        Index('need_download_idx', SVNRow.need_download).create(bind=get_engine())
        Index('fileFlag_idx', SVNRow.fileFlag).create(bind=get_engine())
        Index('path_idx', SVNRow.path).create(bind=get_engine())
