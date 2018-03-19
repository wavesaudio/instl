#!/usr/bin/env python3


import os
import re
from functools import reduce
import csv
import sqlite3
from contextlib import contextmanager


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


class SVNRow2(object):
    __slots__ = ('_id', 'path', 'flags', 'revision',
                'checksum', 'size', 'url', 'fileFlag',
                'wtarFlag', 'leaf', 'parent', 'level',
                'required', 'need_download', 'download_path',
                'download_root', 'extra_props', 'unwtarred')
    fields_relevant_to_dirs = ('path', 'parent', 'level', 'flags', 'revision', 'required')
    fields_relevant_to_str = ('path', 'flags', 'revision', 'checksum', 'size', 'url')

    def __init__(self, svn_item_tuple):
        self._id =              svn_item_tuple[0]
        self.path =             svn_item_tuple[1]
        self.flags =            svn_item_tuple[2]
        self.revision =         svn_item_tuple[3]
        self.checksum =         svn_item_tuple[4]
        self.size =             svn_item_tuple[5]
        self.url =              svn_item_tuple[6]
        self.fileFlag =         svn_item_tuple[7]
        self.wtarFlag =         svn_item_tuple[8]
        self.leaf =             svn_item_tuple[9]
        self.parent =           svn_item_tuple[10]
        self.level =            svn_item_tuple[11]
        self.required =         svn_item_tuple[12]
        self.need_download =    svn_item_tuple[13]
        self.download_path =    svn_item_tuple[14]
        self.download_root =    svn_item_tuple[15]
        self.extra_props =      svn_item_tuple[16]
        self.unwtarred =        svn_item_tuple[17]

    def __repr__(self):
        isDir = not self.fileFlag
        return ("<{self.level}, {self.path}, '{self.flags}'"
                ", rev-remote:{self.revision}, f:{self.fileFlag}, d:{isDir}"
                ", checksum:{self.checksum}, size:{self.size}"
                ", url:{self.url}"
                ", required:{self.required}, need_download:{self.need_download}"
                ", extra_props:{self.extra_props}, parent:{self.parent}>"
                ", download_path:{self.download_path}"
                ).format(**locals())

    def __str__(self):
        """ __str__ representation - this is what will be written to info_map.txt files"""
        retVal = "{}, {}, {}".format(self.path, self.flags, self.revision)
        if self.checksum:
            retVal = "{}, {}".format(retVal, self.checksum)
        if self.size != -1:
            retVal = "{}, {}".format(retVal, self.size)
        if self.url:
            retVal = "{}, {}".format(retVal, self.url)
        if self.download_path:
            retVal = "{}, dl_path:'{}'".format(retVal, self.download_path)
        return retVal

    def str_specific_fields(self, fields_to_repr):
        """ represent self as a string and limiting the fields written to those in fields_to_repr.
        :param fields_to_repr: only fields whose name is on this list will be written.
                if list is empty or None, fall back to __str__
        :return: string of comma separated values
        """
        if fields_to_repr is None or len(fields_to_repr) == 0:
            retVal = self.__str__()
        else:
            value_list = list()
            if self.isDir():
                for name in fields_to_repr:
                    if name in SVNRow2.fields_relevant_to_dirs:
                        value_list.append(str(getattr(self, name, "no member named "+name)))
            else:
                for name in fields_to_repr:
                    value_list.append(str(getattr(self, name, "no member named "+name)))
            retVal = ", ".join(value_list)
        return retVal

    def get_ancestry(self):
        ancestry = list()
        split_path = self.path.split("/")
        for i in range(1, len(split_path)+1):
            ancestry.append("/".join(split_path[:i]))
        return ancestry

    def name(self):
        retVal = self.path.split("/")[-1]
        return retVal

    def isDir(self):
        return not self.fileFlag

    def isFile(self):
        return self.fileFlag

    def isExecutable(self):
        return 'x' in self.flags

    def isSymlink(self):
        return 's' in self.flags

    def is_wtar_file(self):
        retVal = self.wtarFlag > 0
        return retVal

    def is_first_wtar_file(self):
        retVal = self.path.endswith((".wtar", ".wtar.aa"))
        return retVal

    def extra_props_list(self):
        retVal = self.extra_props.split(";")
        retVal = [prop for prop in retVal if prop]  # split will return [""] for empty list
        return retVal

    def chmod_spec(self):
        retVal = "a+rw"
        if self.isExecutable() or self.isDir():
            retVal += "x"
        return retVal

    def path_starting_from_dir(self, starting_dir):
        retVal = None
        if starting_dir == "":
            retVal = self.path
        else:
            if not starting_dir.endswith("/"):
                starting_dir += "/"
            if self.path.startswith(starting_dir):
                retVal = self.path[len(starting_dir):]
        return retVal

    def __eq__(self, other):
        """Overrides the default implementation"""
        retVal = False
        if isinstance(self, other.__class__):
            retVal = self.__dict__ == other.__dict__
        elif isinstance(other, sqlite3.Row): \
            retVal= (other['_id'] == self._id
            and     other['path'] == self.path
            and     other['flags'] == self.flags
            and     other['revision'] == self.revision
            and     other['checksum'] == self.checksum
            and     other['size'] == self.size
            and     other['url'] == self.url
            and     other['fileFlag'] == self.fileFlag
            and     other['wtarFlag'] == self.wtarFlag
            and     other['leaf'] == self.leaf
            and     other['parent'] == self.parent
            and     other['level'] == self.level
            and     other['required'] == self.required
            and     other['need_download'] == self.need_download
            and     other['download_path'] == self.download_path
            and     other['download_root'] == self.download_root
            and     other['unwtarred']     == self.unwtarred
                    )
        elif isinstance(other, tuple): \
            retVal= (other[0] == self._id
            and     other[1] == self.path
            and     other[2] == self.flags
            and     other[3] == self.revision
            and     other[4] == self.checksum
            and     other[5] == self.size
            and     other[6] == self.url
            and     other[7] == self.fileFlag
            and     other[8] == self.wtarFlag
            and     other[9] == self.leaf
            and     other[10] == self.parent
            and     other[11] == self.level
            and     other[12] == self.required
            and     other[13] == self.need_download
            and     other[14] == self.download_path
            and     other[15] == self.download_root
            and     other[16] == self.extra_props
            and     other[17] == self.unwtarred
                    )
        return retVal


class SVNTable(object):
    create_path_index_q = """CREATE UNIQUE INDEX IF NOT EXISTS ix_svn_item_t_path ON svn_item_t (path);"""
    drop_path_index_q = """DROP INDEX IF EXISTS ix_svn_item_t_path;"""
    create_parent_id_index_q = """CREATE INDEX IF NOT EXISTS ix_svn_item_t_parent_id ON svn_item_t (parent_id);"""
    drop_parent_id_index_q = """DROP INDEX IF EXISTS ix_svn_item_t_parent_id;"""
    create_unwtarred_id_index_q = """CREATE INDEX IF NOT EXISTS ix_svn_item_t_unwtarred_id ON svn_item_t (unwtarred);"""
    drop_unwtarred_id_index_q = """DROP INDEX IF EXISTS ix_svn_item_t_unwtarred_id;"""
    update_parent_ids_q = """
        UPDATE svn_item_t
        SET parent_id =
        (SELECT parent_t._id
         FROM svn_item_t AS parent_t
         WHERE parent_t.path==svn_item_t.parent)
         """
    get_child_items_q = """
        WITH RECURSIVE get_children(__ID) AS
        (
            SELECT first_item_t._id
            FROM svn_item_t AS first_item_t
            WHERE first_item_t.parent_id=:parent_id

            UNION

            SELECT child_item_t._id
            FROM svn_item_t child_item_t, get_children
            WHERE child_item_t.parent_id = get_children.__ID
        )
        SELECT * FROM svn_item_t
        WHERE _id IN get_children
        {another_filter}
        ORDER BY parent_id
        """
    get_immediate_child_items_q =  """SELECT * FROM svn_item WHERE parent_id==:parent_id"""

    def __init__(self, db_master):
        super().__init__()
        self.db = db_master
        self.db.open()
        self.read_func_by_format = {"info": self.read_from_svn_info,
                                    "text": self.read_from_text,
                                    "props": self.read_props,
                                    "file-sizes": self.read_file_sizes
                                    }

        self.write_func_by_format = {"text": self.write_as_text,}
        self.files_read_list = list()
        self.files_written_list = list()
        self.comments = list()

    def __repr__(self):
        return "\n".join([item.__repr__() for item in self.get_items()])

    def repr_to_file(self, file_path):
        with utils.utf8_open(file_path, "w") as wfd:
            wfd.write(self.__repr__())

    def valid_read_formats(self):
        """ returns a list of file formats that can be read by SVNTree """
        return list(self.read_func_by_format.keys())

    @contextmanager
    def reading_files_context(self):
        self.db.curs.execute(self.drop_path_index_q)
        self.db.curs.execute(self.drop_parent_id_index_q)
        self.db.curs.execute(self.drop_unwtarred_id_index_q)
        yield
        with self.db.transaction() as curs:
            curs.execute(self.create_path_index_q)
            curs.execute(self.update_parent_ids_q)
            curs.execute(self.create_parent_id_index_q)
            curs.execute(self.create_unwtarred_id_index_q)

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

        with self.db.transaction() as curs:
            insert_q = """
                INSERT INTO svn_item_t (path, revision,
                                      checksum,
                                      level, parent, leaf,
                                      flags, fileFlag, wtarFlag,
                                      required, need_download, extra_props)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?);
                """
            curs.executemany(insert_q, yield_row(rfd))

    def read_from_text(self, rfd):
        dl_path_re = re.compile("dl_path:'(?P<ld_path>.+)'")
        def yield_row(_rfd_):
            reader = csv.reader(_rfd_, skipinitialspace=True)
            for row in reader:
                if row and row[0][0] != '#':
                    # when there are 6 items in row the last might be url or dl_path
                    # so if row is (path, flags, repo-rev, checksum, size, dl_path) insert a None for url so row will be:
                    # (path, flags, repo-rev, checksum, size, url, dl_path)
                    if len(row) == 6 and row[5].startswith("dl_path:"):
                        row.insert(5, None)
                    info_map_line_defaults = ('!path!', '!flags!', '!repo-rev!', None, 0, None, None)
                    row_data = list(utils.iter_complete_to_longest(row, info_map_line_defaults))  # path, flags, revision, checksum, size, url, dl_path
                    if row_data[6] is not None:
                        match = dl_path_re.match(row_data[6])
                        if match:
                            row_data[6] = match.group('ld_path')
                    row_data.extend(self.level_parent_and_leaf_from_path(row_data[0]))  # level, parent, leaf
                    row_data.append(1 if 'f' in row_data[1] else 0)  # fileFlag
                    wtar_match = utils.wtar_file_re.match(row_data[0])
                    if wtar_match:
                        row_data.append(1)
                        row_data.append(wtar_match.group('base_name'))
                    else:
                        row_data.extend((0, row_data[0]))
                    row_data.extend((0, 0))  # required, need_download
                    yield row_data

        with self.db.transaction() as curs:
            insert_q = """
                INSERT INTO svn_item_t (path, flags, revision,
                                      checksum, size, url, download_path,
                                      level, parent, leaf,
                                      fileFlag, wtarFlag, unwtarred,
                                      required, need_download)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
                """
            curs.executemany(insert_q, yield_row(rfd))

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

        with self.db.transaction() as curs:
            insert_q = """
                INSERT INTO svn_item_t (path, flags, revision,
                                      level, parent, leaf,
                                      fileFlag, wtarFlag)
                 VALUES(?,?,?,?,?,?,?,?);
                """
            curs.executemany(insert_q, yield_row(in_folder))

    def num_items(self, item_filter="all-items"):
        count = 0
        select_q = None
        with self.db.selection() as curs:
            if item_filter == "all-items":
                select_q = """SELECT COUNT(_id) FROM svn_item_t;"""
            elif item_filter == "all-files":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE fileFlag==1;"""
            elif item_filter == "all-dirs":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE fileFlag==0;"""
            if item_filter == "required-items":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE required==1;"""
            elif item_filter == "required-files":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE required==1 AND fileFlag==1;"""
            elif item_filter == "required-dirs":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE required==1 AND fileFlag==0;"""
            if item_filter == "unrequired-item":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE required==0;"""
            elif item_filter == "unrequired-files":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE required==0 AND fileFlag==1;"""
            elif item_filter == "unrequired-dirs":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE required==0 AND fileFlag==0;"""
            elif item_filter == "need-download-files":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE need_download==1 AND fileFlag==1;"""
            elif item_filter == "need-download-dirs":
                select_q = """SELECT COUNT(_id) FROM svn_item_t WHERE need_download==1 AND fileFlag==0;"""
            count = curs.execute(select_q).fetchone()[0]
        return count

    def clear_all(self):
        with self.db.transaction() as curs:
            curs.execute("DELETE FROM svn_item_t")
        self.comments = list()

    def set_base_revision(self, base_revision):
        with self.db.transaction() as curs:
            update_q = """
                UPDATE  svn_item_t
                SET revision = :base_revision
                WHERE revision < :base_revision
                """
            curs.execute(update_q, {"base_revision": base_revision})

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

        with self.db.transaction() as curs:
            update_q = """
                UPDATE  svn_item_t
                SET size = :new_size
                WHERE path = :old_path
                """
            curs.executemany(update_q, yield_row(rfd))

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
            with self.db.transaction() as curs:
                prop_name_to_flag_query_params = list()
                not_in_props_to_ignore_query_params = list()
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
                                    prop_name_to_flag_query_params.append({"new_prop": prop_name_to_flag[prop_name], "old_path": path})
                                elif prop_name not in props_to_ignore:
                                    not_in_props_to_ignore_query_params.append({"prop_name": prop_name, "old_path": path})
                    else:
                        ValueError("no match at file: " + rfd.name + ", line: " + str(line_num) + ": " + line)
                prop_name_to_flag_query = """UPDATE svn_item_t SET flags = flags || :new_prop WHERE path = :old_path;"""
                curs.executemany(prop_name_to_flag_query, prop_name_to_flag_query_params);
                not_in_props_to_ignore_query = """UPDATE svn_item_t SET extra_props = extra_props || :prop_name || ";" WHERE path = :old_path;"""
                curs.executemany(not_in_props_to_ignore_query, not_in_props_to_ignore_query_params);
        except Exception as ex:
            print("Line:", line_num, ex)
            raise

    def get_any_item(self, item_path):
        """ Get specific item or return None if not found
        :param item_path: path to the item
        :return: item found or None
        """
        retVal = None
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE path = :item_path
                    """, {"item_path": item_path})
            the_item = curs.fetchone()
            if the_item:
                retVal = SVNRow2(the_item)
        return retVal

    def get_file_item(self, item_path):
        """ Get specific file item or return None if not found
        :param item_path: path to the item
        :return: item found or None
        """

        retVal = None
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE path = :item_path
                    AND fileFlag = 1
                    """, {"item_path": item_path})
            the_item = curs.fetchone()
            if the_item:
                retVal = SVNRow2(the_item)
        return retVal

    def get_dir_item(self, item_path):
        """ Get specific dir item or return None if not found
        :param item_path: path to the item
        :return: item found or None
        """

        retVal = None
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE path = :item_path
                    AND fileFlag = 0
                    """, {"item_path": item_path})
            the_item = curs.fetchone()
            if the_item:
                retVal = SVNRow2(the_item)
        return retVal

    def get_files_that_should_be_removed_from_sync_folder(self, files_to_check):
        """
        :param files_to_check: a list of tuples [(partial_path, full_path), ...]
        :return: list of indexes into files_to_check who's partial path is not in info_map
        """
        retVal = list()

        with self.db.selection() as curs:
            create_table_text = """CREATE TEMP TABLE paths_from_disk_t (item_num INTEGER, path TEXT);"""
            curs.execute(create_table_text)

            # each partial path is inserted with it's index in the list
            list_of_inserts = [(i, path_pair[0]) for i, path_pair in enumerate(files_to_check)]
            insert_text = """INSERT INTO paths_from_disk_t (item_num, path) VALUES (?, ?);"""
            curs.executemany(insert_text, list_of_inserts)

            # this query will select all files found in the sync folder that are not in the info_map
            # database, BUT will exclude those files in folders that have their own info_map for
            # items that are not currently being installed.
            query_text = """
                SELECT file_index
                FROM
                (SELECT  paths_from_disk_t.item_num AS file_index
                  FROM paths_from_disk_t
                  WHERE UPPER(paths_from_disk_t.path) NOT IN (SELECT UPPER(path) FROM svn_item_t))

                WHERE file_index NOT IN (
                    SELECT paths_from_disk_t.item_num
                    FROM paths_from_disk_t
                    JOIN index_item_detail_t AS sources_t
                        ON sources_t.detail_name = 'install_sources'
                        AND paths_from_disk_t.path LIKE sources_t.detail_value || "/%"
                    JOIN index_item_t ON
                        index_item_t.install_status = 0
                        AND index_item_t.iid = sources_t.owner_iid
                    JOIN index_item_detail_t AS info_map_t ON
                        info_map_t.detail_name = 'info_map'
                        AND index_item_t.iid = info_map_t.owner_iid)
                """
            curs.execute(query_text)
            retVal.extend([fr[0] for fr in curs.fetchall()])
        return retVal

    def get_items(self, what="any", levels_deep=1024):
        """
        get_items applies a filter and return all items
        :param filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE level <= :levels_deep
                    AND (fileFlag = :file OR fileFlag = :dir)
                    ORDER BY _id
                    """, {"levels_deep": levels_deep, "file": want_file, "dir": not want_dir})
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def get_required_items(self, what="any", get_unrequired=False):
        """
        get_items applies a filter and return all items
        :param filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE required == :required
                    AND (fileFlag = :file OR fileFlag = :dir)
                    ORDER BY _id
                    """, {"required": not get_unrequired, "file": want_file, "dir": not want_dir})
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def get_exec_file_paths(self):
        query_text = """
          SELECT path
          FROM svn_item_t
          WHERE flags == 'fx'
        """
        retVal = self.db.select_and_fetchall(query_text)
        return retVal

    def get_required_exec_items(self, what="any"):
        """ :return: all required fies that are also exec
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE required == 1
                    AND instr(flags, 'x') != 0
                    AND (fileFlag = :file OR fileFlag = :dir)
                    ORDER BY _id
                    """, {"file": want_file, "dir": not want_dir})
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def get_download_items_sync_info(self):
        """ get just the fields required to calc urls"""
        query_text = """
            SELECT path, revision, size, download_path, url FROM svn_item_t
            WHERE need_download == 1
            AND fileFlag = 1
            ORDER BY _id
            """
        with self.db.selection("get_download_items") as curs:
            curs.execute(query_text)
            retVal = curs.fetchall()
        return retVal

    def get_download_items(self, what="any"):
        """
        get_items applies a filter and return all items
        :param: filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        if what == "file":
            query_text = """
                SELECT * FROM svn_item_t
                WHERE need_download == 1
                AND fileFlag = 1
                ORDER BY _id
                """
        elif what == "dir":
            query_text = """
                SELECT * FROM svn_item_t
                WHERE need_download == 1
                AND fileFlag = 0
                ORDER BY _id
                """
        else:
            query_text = """
                SELECT * FROM svn_item_t
                WHERE need_download == 1
                ORDER BY _id
                """

        with self.db.selection() as curs:
            curs.execute(query_text)
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def get_not_to_download_num_files_and_size(self):
        """ return the count and total size of the files that are already synced """
        query_text = """
            SELECT COUNT(*) as num_files, TOTAL(size) as total_size
            FROM svn_item_t
            WHERE required=1
            AND need_download=0
            AND fileFlag=1
            """
        with self.db.selection() as curs:
            retVal = curs.execute(query_text).fetchone()
        return retVal[0], int(retVal[1])  # sqlite's TOTAL returns float

    def get_to_download_num_files_and_size(self):
        """
        :return: a tuple: (a list of fies marked for download, their total size)
        """
        query_text = """
            SELECT COUNT(_id), SUM(size) FROM svn_item_t
            WHERE need_download == 1
            AND fileFlag = 1
            """
        with self.db.selection() as curs:
            curs.execute(query_text)
            num_files, total_size = curs.fetchone()
        return num_files, total_size

    def get_required_for_file(self, file_path):
        """ get the item for a required file as or if file was wtarred
            get the wtar files.
        """

        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE fileFlag = 1
                    AND path==:file_path
                    OR unwtarred==:file_path
                    ORDER BY _id
                    """, {"file_path": file_path})
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def mark_required_for_file(self, file_path):
        """ mark a file as required or if file was wtarred
            mark the wtar files are required.
        """
        retVal = 0
        with self.db.transaction() as curs:
            curs.execute("""
                    UPDATE svn_item_t
                    SET required=1
                    WHERE fileFlag = 1
                    AND (unwtarred==:file_path)
                    """, {"file_path": file_path})
            retVal = curs.rowcount
        return retVal

    def get_file_paths_of_dir(self, dir_path):
        query_text = """
            WITH RECURSIVE get_children(__ID) AS
            (
                SELECT first_item_t._id
                FROM svn_item_t AS first_item_t
                WHERE first_item_t.unwtarred == :dir_path

                UNION

                SELECT child_item_t._id
                FROM svn_item_t child_item_t, get_children
                WHERE child_item_t.parent_id = get_children.__ID
            )
            SELECT path
            FROM svn_item_t
            WHERE svn_item_t._id IN (SELECT __ID FROM get_children)
            AND fileFlag=1
            ORDER BY _id
            """
        with self.db.selection() as curs:
            curs.execute(query_text, {"dir_path": dir_path})
            retVal = [p[0] for p in curs.fetchall()]
        return retVal

    def get_file_items_of_dir(self, dir_path):
        """ get all file items in dir_path OR if the dir_path itself is wtarred - the wtarred file items.
            results are recursive so files from sub folders are also returned
        """
        query_text = """
            WITH RECURSIVE get_children(__ID) AS
            (
                SELECT first_item_t._id
                FROM svn_item_t AS first_item_t
                WHERE first_item_t.unwtarred == :dir_path

                UNION

                SELECT child_item_t._id
                FROM svn_item_t child_item_t, get_children
                WHERE child_item_t.parent_id = get_children.__ID
            )
            SELECT *
            FROM svn_item_t
            WHERE svn_item_t._id IN (SELECT __ID FROM get_children)
            AND fileFlag=1
            ORDER BY _id
            """
        with self.db.selection() as curs:
            curs.execute(query_text, {"dir_path": dir_path})
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def count_wtar_items_of_dir(self, dir_path):
        """ count all wtar items in dir_path OR if the dir_path itself is wtarred - count of wtarred file items.
            results are recursive so count from sub folders are also accumulated
        """
        retVal = 0
        with self.db.selection() as curs:
            query_text = """
                WITH RECURSIVE get_children(__ID, __PATH, __WTAR_FLAG) AS
                (
                    SELECT first_item_t._id, first_item_t.path, first_item_t.wtarFlag
                    FROM svn_item_t AS first_item_t
                    WHERE first_item_t.unwtarred == :dir_path
                
                    UNION
                
                    SELECT child_item_t._id, child_item_t.path, child_item_t.wtarFlag
                    FROM svn_item_t child_item_t, get_children
                    WHERE child_item_t.parent_id = get_children.__ID
                )
                SELECT COUNT(*)
                FROM get_children
                WHERE get_children.__WTAR_FLAG = 1
                """
            retVal = curs.execute(query_text, {'dir_path': dir_path}).fetchone()[0]
        return retVal

    def get_items_in_dir(self, dir_path="", immediate_children_only=False):
        """ get all files in dir_path.
            level_deep: how much to dig in. level_deep=1 will only get immediate files
            :return: list of items in dir or empty list (if there aren't any) or None
            if dir_path is not a dir
        """
        retVal = []
        if dir_path == "":
            retVal = self.get_items(what="any")
        else:
            root_dir_item = self.get_dir_item(item_path=dir_path)
            if root_dir_item is not None:
                with self.db.selection() as curs:
                    if immediate_children_only:
                        query_text = self.get_immediate_child_items_q
                    else:
                        query_text = self.get_child_items_q
                    query_text = query_text.format(another_filter="")
                    curs.execute(query_text, {"parent_id": root_dir_item._id})
                    retVal = curs.fetchall()
                    retVal = self.SVNRowListToObjects(retVal)
            else:
                print(dir_path, "was not found")
        return retVal

    def mark_required_for_dir(self, dir_path):
        """ mark all files & dirs in dir_path as required.
            marking is recursive.
            ToDo: unite the update with self.get_item
        """
        dir_item = self.get_dir_item(item_path=dir_path)
        if dir_item is not None:
            with self.db.transaction() as curs:
                query_text = """
                    UPDATE svn_item_t
                    SET required=1
                    WHERE fileFlag==1
                    AND level > :dir_item_level
                    AND path LIKE :dir_item_path
                    """
                curs.execute(query_text, {'dir_item_level': dir_item.level,
                                          'dir_item_path': dir_item.path+"/%"})
                retVal = curs.rowcount
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
        return num_required_files

    def mark_required_completion(self):
        """ after some files were marked as required,
            mark their parent dirs are required as well
        """
        query_text = """
            WITH RECURSIVE get_parents(__ID, __PATH, __PARENT_ID) AS
            (
                SELECT file_item_t._id, file_item_t.path, file_item_t.parent_id
                FROM svn_item_t AS file_item_t
                WHERE file_item_t.fileFlag=1
                AND file_item_t.required=1

                UNION

                SELECT parent_item_t._id, parent_item_t.path, parent_item_t.parent_id
                FROM svn_item_t parent_item_t, get_parents
                WHERE parent_item_t._id = get_parents.__PARENT_ID
            )
            UPDATE svn_item_t
            SET required=1
            WHERE _id IN (SELECT __ID FROM get_parents);
            """
        with self.db.transaction() as curs:
            curs.execute(query_text)

    def mark_need_download(self):
        self.db.create_function("need_to_download_file", 2, utils.need_to_download_file)
        # mark files that need download
        query_text = """
            UPDATE svn_item_t
            SET need_download = 1
            WHERE required == 1
            AND fileFlag == 1
            AND need_to_download_file(download_path, checksum)
            """
        with self.db.transaction("mark_need_download") as curs:
            curs.execute(query_text)
        # mark folders of files that need download
        query_text = """
            WITH RECURSIVE get_parents(__PARENT_ID) AS
            (
                SELECT file_item_t.parent_id
                FROM svn_item_t AS file_item_t
                WHERE file_item_t.fileFlag=1
                AND file_item_t.need_download=1

                UNION

                SELECT parent_item_t.parent_id
                FROM svn_item_t parent_item_t, get_parents
                WHERE parent_item_t._id = get_parents.__PARENT_ID
            )
            UPDATE svn_item_t
            SET need_download=1
            WHERE _id IN (SELECT __PARENT_ID FROM get_parents)
            """
        with self.db.transaction("mark_need_download_recursive") as curs:
            curs.execute(query_text)

    def mark_required_for_revision(self, required_revision):
        """ mark all files and dirs as required if they are of specific revision
        """
        with self.db.transaction() as curs:
            curs.execute("""UPDATE svn_item_t SET required=0
                                WHERE fileFlag==1 AND revision==:required_revision
                                """, {"required_revision": required_revision})
        self.mark_required_completion()

    def clear_required(self):
        with self.db.transaction() as curs:
            curs.execute("""UPDATE svn_item_t SET required=0""")

    def get_unrequired_paths_where_parent_required(self, what="file"):
        """ Get all unrequired items that have a parent that is required.
            This is a  trick to leave as on disk only folders that have siblings that are required.
            used in InstlAdmin.do_upload_to_s3_aws_for_revision
        """
        if what not in ("file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        query_text = """
            SELECT path
            FROM svn_item_t
            WHERE required==0
            AND fileFlag==:get_files
            AND parent IN (
                SELECT path
                FROM svn_item_t
                WHERE required==1
                AND fileFlag==0)
            """
        retVal = self.db.select_and_fetchall(query_text, query_params={"get_files": {"file": 1, "dir": 0}[what]})
        return retVal

    def min_max_revision(self):
        with self.db.selection() as curs:
            curs.execute(""" SELECT MIN(svn_item_t.revision), MAX(svn_item_t.revision) FROM svn_item_t""")
            min_revision, max_revision = curs.fetchone()
        return min_revision, max_revision

    def mark_required_files_for_active_items(self):
        script_text = """
            -- mark files and folders that appear in install_sources of required items
            UPDATE svn_item_t
            SET required=1
            WHERE svn_item_t._id IN
            (
                SELECT svn_item_t._id
                FROM svn_item_t
                JOIN index_item_t as active_items_t
                    ON active_items_t.install_status > 0
                    AND active_items_t.ignore = 0
                JOIN index_item_detail_t as install_sources_t
                    ON install_sources_t.owner_iid=active_items_t.iid
                    AND install_sources_t.detail_name='install_sources'
                    AND install_sources_t.os_is_active = 1
                WHERE svn_item_t.unwtarred == install_sources_t.detail_value
            );

            -- mark files and folders that are children of those appearing in install_sources of required items
            WITH RECURSIVE get_children(__ID) AS
            (
                SELECT first_item_t._id
                FROM svn_item_t AS first_item_t
                WHERE required==1 AND fileFlag==0
            
                UNION
            
                SELECT child_item_t._id
                FROM svn_item_t child_item_t, get_children
                WHERE child_item_t.parent_id = get_children.__ID
            )
            UPDATE svn_item_t
            SET required=1
            WHERE _id IN (SELECT __ID FROM get_children);
 
            -- mark the parent folders of all required items
            WITH RECURSIVE get_parents(__ID) AS
            (
                SELECT file_item_t.parent_id
                FROM svn_item_t AS file_item_t
                WHERE file_item_t.fileFlag=1
                AND file_item_t.required=1
            
                UNION
            
                SELECT parent_item_t.parent_id
                FROM svn_item_t parent_item_t, get_parents
                WHERE parent_item_t._id = get_parents.__ID
            )
            UPDATE svn_item_t
            SET required=1
            WHERE _id IN (SELECT __ID FROM get_parents);
        """
        with self.db.transaction() as curs:
            curs.executescript(script_text)

    def get_download_roots(self):
        query_text = """
        SELECT DISTINCT
            coalesce(download_root, "$(LOCAL_REPO_SYNC_DIR)")
        FROM svn_item_t
        WHERE need_download=1
        AND fileFlag=1
        """
        retVal = self.db.select_and_fetchall(query_text)
        return retVal

    def get_infomap_file_names(self):
        """ infomap file names are stored in extra_props column by set_infomap_file_names
        """
        query_text = """
          SELECT DISTINCT extra_props
          FROM svn_item_t
          ORDER BY extra_props
        """
        retVal = self.db.select_and_fetchall(query_text)
        return retVal

    def get_items_by_infomap(self, infomap_name):
        """
        get_items_by_infomap returns all items that should be written to a specific infomap file
        infomap file names were stored in extra_props column by set_infomap_file_names
        :param infomap_name: e.g. GrandRhapsody_SD_Sample_Library_info_map.txt
        """
        retVal = list()
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    JOIN iid_to_svn_item_t, index_item_detail_t
                      ON svn_item_t._id == iid_to_svn_item_t.svn_id
                      AND iid_to_svn_item_t.iid == index_item_detail_t.owner_iid
                      AND index_item_detail_t.detail_name == 'info_map'
                      AND index_item_detail_t.detail_value == :infomap_name
                    ORDER BY svn_item_t._id
                    """, {"infomap_name": infomap_name})
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def get_items_for_default_infomap(self):
        with self.db.selection() as curs:
            curs.execute("""
                    SELECT * FROM svn_item_t
                    WHERE svn_item_t._id NOT IN (
                    SELECT svnitem_with_non_default_info_map._id FROM svn_item_t AS svnitem_with_non_default_info_map
                    JOIN iid_to_svn_item_t, index_item_detail_t
                      ON svnitem_with_non_default_info_map._id == iid_to_svn_item_t.svn_id
                      AND iid_to_svn_item_t.iid == index_item_detail_t.owner_iid
                      AND index_item_detail_t.detail_name == 'info_map')
                    ORDER BY svn_item_t.path
                    """)
            retVal = curs.fetchall()
            retVal = self.SVNRowListToObjects(retVal)
        return retVal

    def populate_IIDToSVNItem(self):
        query_text = """
            INSERT INTO iid_to_svn_item_t (iid, svn_id)
            SELECT install_sources_t.owner_iid, svn_item_t._id
            FROM index_item_detail_t AS install_sources_t, svn_item_t
            WHERE
                install_sources_t.detail_name = 'install_sources'
                    AND
                (
                  svn_item_t.path = install_sources_t.detail_value
                    OR
                  svn_item_t.path LIKE install_sources_t.detail_value || "/%"
                    OR
                  svn_item_t.unwtarred == install_sources_t.detail_value
                )
            """
        with self.db.transaction() as curs:
            curs.execute(query_text)

    def set_info_map_file(self, info_map_file_name):
        query_text = """
            UPDATE svn_item_t
            SET extra_props = :info_map_file_name
            WHERE svn_item_t._id In (
            SELECT svn_item_t._id
            FROM svn_item_t, iid_to_svn_item_t, index_item_detail_t
            WHERE
                svn_item_t._id = iid_to_svn_item_t.svn_id
            AND
                iid_to_svn_item_t.iid = index_item_detail_t.owner_iid
            AND
                index_item_detail_t.detail_name = 'info_map'
            AND
                index_item_detail_t.detail_value = :info_map_file_name)
            """
        with self.db.transaction() as curs:
            curs.execute(query_text, {"info_map_file_name": info_map_file_name})

    def get_unrequired_file_paths(self):
        """ get paths for all unrequired files
        """
        query_text = """
            SELECT path
            FROM svn_item_t
            WHERE required==0
            AND fileFlag==1
            """
        with self.db.selection() as curs:
            retVal = curs.fetchall()
        return retVal

    def update_downloads(self, items_to_update):
        """
            items_to_update is a list of info_map items where download_root
            and download_path were changed.
        """
        query_text = """
                UPDATE svn_item_t
                SET download_root=:download_root,
                    download_path=:download_path
                WHERE _id=:_id
                """
        query_params = [{'download_root': item.download_root, 'download_path': item.download_path, '_id': item._id} for item in items_to_update]
        with self.db.transaction() as curs:
            curs.executemany(query_text, query_params)

    def SVNRowListToObjects(self, svn_row_list):
        retVal = [SVNRow2(item) for item in svn_row_list]
        return retVal
