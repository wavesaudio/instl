#!/usr/bin/env python
from __future__ import print_function

import os
import re
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import update
from sqlalchemy import or_
from sqlalchemy.ext import baked
from sqlalchemy import bindparam
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import func
from sqlalchemy import event

from svnRow import SVNRow, alchemy_base

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
            (?P<url>(http(s)?|ftp)://.+))?    # http://....
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
wtar_file_re = re.compile(r""".+\.wtar(\...)?$""")
wtar_first_file_re = re.compile(r""".+\.wtar(\.aa)?$""")

map_info_extension_to_format = {"txt": "text", "text": "text",
                                "inf": "info", "info": "info",
                                "props": "props", "prop": "props",
                                "file-sizes": "file-sizes"}


class SVNTable(object):
    def __init__(self):
        self.engine = create_engine('sqlite:///:memory:', echo=False)
        alchemy_base.metadata.create_all(self.engine)
        self.session_maker = sessionmaker(bind=self.engine)
        self.session = self.session_maker()
        self.read_func_by_format = {"info": self.read_from_svn_info,
                                    "text": self.read_from_text,
                                    "props": self.read_props,
                                    "file-sizes": self.read_file_sizes
                                    }

        self.write_func_by_format = {"text": self.write_as_text,}
        self.files_read_list = list()
        self.files_written_list = list()
        self.comments = list()
        self.baked_queries_map = self.bake_baked_queries()
        self.bakery = baked.bakery()

    def bake_baked_queries(self):
        """ prepare baked queries for later use
        """
        retVal = dict()

        # all queries are now baked just-in-time

        return retVal

    def __repr__(self):
        return "\n".join([item.__repr__() for item in self.get_items()])

    def repr_to_file(self, file_path):
        with open(file_path, "w") as wfd:
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
            with utils.open_for_read_file_or_url(in_file) as rfd:
                if a_format not in ("props", "file-sizes"):
                    self.clear_all()
                self.read_func_by_format[a_format](rfd)
                self.files_read_list.append(in_file)
        else:
            raise ValueError("Unknown read a_format " + a_format)

    @utils.timing
    def read_from_svn_info(self, rfd):
        """ reads new items from svn info items prepared by iter_svn_info
            items are inserted in lexicographic directory order, so '/'
            sorts before other characters: key=lambda x: x['path'].split('/')
        """

        insert_dicts = sorted([item_dict for item_dict in self.iter_svn_info(rfd)], key=lambda x: x['path'].split('/'))
        self.session.bulk_insert_mappings(SVNRow, insert_dicts)

    def read_from_text_to_dict(self, in_rfd):
        retVal = list()
        for line in in_rfd:
            line = line.strip()
            item_dict = SVNTable.item_dict_from_str(line)
            if item_dict:
                retVal.append(item_dict)
            else:
                match = comment_line_re.match(line)
                if match:
                    self.comments.append(match.group("the_comment"))
        return retVal

    def insert_dicts_to_db(self, insert_dicts):
        # self.session.bulk_insert_mappings(SVNRow, insert_dicts)
        self.engine.execute(SVNRow.__table__.insert(), insert_dicts)

    def read_from_text(self, rfd):
        insert_dicts = self.read_from_text_to_dict(rfd)
        self.insert_dicts_to_db(insert_dicts)

    def update_from_text(self, rfd, revision_is_local=True):
        """
        Update the db from a text file
        :param rfd:
        :param revision_is_local: if true revision_local will be updated otherwise revision_remote
        :return: nada
        """
        update_dicts = list()
        for line in rfd:
            line = line.strip()
            item_dict = SVNTable.item_dict_from_str(line)
            if item_dict:
                if revision_is_local:
                    item_dict['revision_local'] = item_dict['revision_remote']
                    del item_dict['revision_remote']
                update_dicts.append(item_dict)
            else:
                match = comment_line_re.match(line)
                if match:
                    self.comments.append(match.group("the_comment"))
        self.session.bulk_update_mappings(SVNRow, update_dicts)

    @staticmethod
    def get_wtar_file_status(file_name):
        is_wtar_file = wtar_file_re.match(file_name) is not None
        is_wtar_first_file = is_wtar_file and wtar_first_file_re.match(file_name) is not None
        return is_wtar_file, is_wtar_first_file

    @staticmethod
    def item_dict_from_str(the_str):
        """ create a new a sub-item from string description.
            If create_folders is True, non existing intermediate folders
            will be created, with the same revision. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
            This is the regular expression version.
        """
        item_details = None
        match = text_line_re.match(the_str)
        if match:
            item_details = dict()
            item_details['path'] = match.group('path')
            item_details['parent'] = "/".join(item_details['path'].split("/")[:-1])
            item_details['level'] = len(item_details['path'].split("/"))
            item_details['revision_remote'] = int(match.group('revision'))
            item_details['flags'] = match.group('flags')
            item_details['fileFlag'] = 'f' in item_details['flags']
            item_details['dirFlag'] = 'd' in item_details['flags']
            item_details['checksum'] = match.group('checksum')
            item_details['url'] = match.group('url')
            item_details['size'] = int(match.group('size')) if match.group('size')  else 0
            item_details['required'] = False
            item_details['need_download'] = False
            item_details['extra_props'] = ""
        return item_details

    def valid_write_formats(self):
        return list(self.write_func_by_format.keys())

    def write_to_file(self, in_file, in_format="guess", comments=True, items_list=None):
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
                self.write_func_by_format[in_format](wfd, items_list, comments)
                self.files_written_list.append(in_file)
        else:
            raise ValueError("Unknown write in_format " + in_format)

    def write_as_text(self, wfd, items_list, comments=True):
        if comments and len(self.comments) > 0:
            for comment in self.comments:
                wfd.write("# " + comment + "\n")
            wfd.write("\n")
        for item in items_list:
            wfd.write(str(item) + "\n")

    def iter_svn_info(self, long_info_fd):
        """ Go over the lines of the output of svn info command
            for each block describing a file or directory, yield
            a tuple formatted as (path, type, last changed revision).
            Where type is 'f' for file or 'd' for directory. """
        try:
            svn_info_line_re = re.compile("""
                        ^
                        (?P<key>Path|Last\ Changed\ Rev|Node\ Kind|Revision|Checksum|Tree\ conflict)
                        :\s*
                        (?P<rest_of_line>.*)
                        $
                        """, re.VERBOSE)

            def create_info_dict_from_record(a_record):
                """ On rare occasions there is no 'Last Changed Rev' field, just 'Revision'.
                    So we use 'Revision' as 'Last Changed Rev'.
                """
                retVal = dict()
                retVal['path'] = a_record["Path"]
                retVal['parent'] = "/".join(retVal['path'].split("/")[:-1])
                retVal['level'] = len(retVal['path'].split("/"))
                if a_record["Node Kind"] == "file":
                    retVal['flags'] = "f"
                    retVal['fileFlag'] = True
                    retVal['dirFlag'] = False
                elif a_record["Node Kind"] == "directory":
                    retVal['flags'] = "d"
                    retVal['fileFlag'] = False
                    retVal['dirFlag'] = True
                if "Last Changed Rev" in a_record:
                    retVal['revision_remote'] = int(a_record["Last Changed Rev"])
                elif "Revision" in a_record:
                    retVal['revision_remote'] = int(a_record["Revision"])
                else:
                    retVal['revision_remote'] = -1
                retVal['checksum'] = a_record.get("Checksum", None)
                retVal['extra_props'] = ""

                return retVal

            record = dict()
            line_num = 0
            for line in long_info_fd:
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
                        yield create_info_dict_from_record(record)
                    record.clear()
            if record and record["Path"] != ".":  # in case there was no extra line at the end of file
                yield create_info_dict_from_record(record)
        except KeyError as unused_ke:
            print(unused_ke)
            print("Error:", "line:", line_num, "record:", record)
            raise

    def item_dict_from_disk_item(self, in_base_folder, full_path):
        prefix_len = len(in_base_folder)+1
        relative_path = full_path[prefix_len:]
        item_details = dict()
        item_details['path'] = relative_path
        split_path = item_details['path'].split("/")
        item_details['parent'] = "/".join(split_path[:-1])
        item_details['level'] = len(split_path)
        item_details['revision_remote'] = 0
        if os.path.islink(full_path): # check for link first: os.path.isdir returns True for a link to dir
            flags = "fs"
        elif os.path.isfile(full_path):
            if os.access(full_path, os.X_OK):
                flags = "fx"
            else:
                flags = "f"
        else:
            flags = "d"
        item_details['flags'] = flags
        item_details['fileFlag'] = 'f' in item_details['flags']
        item_details['dirFlag'] = 'd' in item_details['flags']
        item_details['checksum'] = None
        item_details['url'] = None
        item_details['size'] = 0
        item_details['required'] = False
        item_details['need_download'] = False
        item_details['extra_props'] = ""
        return item_details

    def initialize_from_folder(self, in_folder):
        insert_dicts = list()
        for root, dirs, files in os.walk(in_folder, followlinks=False):
            for item in sorted(files + dirs):
                if item != ".DS_Store": # temp hack, list of ignored files should be moved to a variable
                    insert_dicts.append(self.item_dict_from_disk_item(in_folder, os.path.join(root, item)))
        self.insert_dicts_to_db(insert_dicts)

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
        self.comments = list()

    def set_base_revision(self, base_revision):
        self.session.query(SVNRow).filter(SVNRow.revision_remote < base_revision).\
                                    update({"revision_remote": base_revision})

    def read_file_sizes(self, rfd):
        update_dicts = list()
        line_num = 0
        for line in rfd:
            line_num += 1
            match = comment_line_re.match(line)
            if not match:
                parts = line.rstrip().split(", ", 2)
                if len(parts) != 2:
                    print(line, line_num)
                update_dicts.append({"path": parts[0], "size": int(parts[1])})
        self.session.bulk_update_mappings(SVNRow, update_dicts)

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
            prop_name_to_flag = {'executable': 'x', 'special': 's'}
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
                                update_statement = update(SVNRow)\
                                    .where(SVNRow.path == path)\
                                    .values(flags = SVNRow.flags + prop_name_to_flag[prop_name])
                            else:
                                update_statement = update(SVNRow)\
                                    .where(SVNRow.path == path)\
                                    .values(extra_props = SVNRow.extra_props + (prop_name+";"))
                            self.session.execute(update_statement)
                else:
                    ValueError("no match at file: " + rfd.name + ", line: " + str(line_num) + ": " + line)
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
            self.baked_queries_map["get_one_item"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.dirFlag == bindparam('dir')))

        retVal = None
        try:
            want_file = what in ("any", "file")
            want_dir = what in ("any", "dir")
            retVal = self.baked_queries_map["get_one_item"](self.session).params(item_path=item_path, file=want_file, dir=want_dir).one()
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
            self.baked_queries_map["get_all_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.dirFlag == bindparam('dir')))
            self.baked_queries_map["get_all_items"] += lambda q: q.filter(SVNRow.level <= bindparam('levels_deep'))

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_all_items"](self.session).params(file=want_file, dir=want_dir, levels_deep=levels_deep).all()
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
            self.baked_queries_map["get_required_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.dirFlag == bindparam('dir')))
            self.baked_queries_map["get_required_items"] += lambda q: q.filter(or_(SVNRow.required == bindparam('required')))

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_required_items"](self.session).params(required=not get_unrequired, file=want_file, dir=want_dir).all()
        return retVal

    def get_exec_items(self, what="any"):
        """
        get_items applies a filter and return all items
        :param filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        # get_exec_items: return all exec items either files dirs or both, used by get_exec_items()
        if "get_exec_items" not in self.baked_queries_map:
            self.baked_queries_map["get_exec_items"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_exec_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.dirFlag == bindparam('dir')))
            self.baked_queries_map["get_exec_items"] += lambda q: q.filter(SVNRow.flags.contains('x'))

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_exec_items"](self.session).params(file=want_file, dir=want_dir).all()
        return retVal

    def get_required_exec_items(self, what="any"):
        """ :return: all required fies that are also exec
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")


        # required-exec-files: return all required files that are executables, used by get_required_exec_items()
        if "get_required_exec_items" not in self.baked_queries_map:
            self.baked_queries_map["get_required_exec_items"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_required_exec_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.dirFlag == bindparam('dir')))
            self.baked_queries_map["get_required_exec_items"] += lambda q: q.filter(SVNRow.required == True, SVNRow.flags.contains('x'))

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_required_exec_items"](self.session).params(file=want_file, dir=want_dir).all()
        return retVal

    def get_download_items(self, what="any"):
        """
        get_items applies a filter and return all items
        :param filter_name: one of predefined baked queries, e.g.: "all-files", "all-dirs", "all-items"
        :return: all items returned by applying the filter called filter_name
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        # get_exec_items: return all exec items either files dirs or both, used by get_exec_items()
        if "get_download_items" not in self.baked_queries_map:
            self.baked_queries_map["get_download_items"] = self.bakery(lambda session: session.query(SVNRow))
            self.baked_queries_map["get_download_items"] += lambda q: q.filter(or_(SVNRow.fileFlag == bindparam('file'), SVNRow.dirFlag == bindparam('dir')))
            self.baked_queries_map["get_download_items"] += lambda q: q.filter(SVNRow.need_download == True)

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        retVal = self.baked_queries_map["get_download_items"](self.session).params(file=want_file, dir=want_dir).all()
        return retVal

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

        return self.baked_queries_map["required_items_for_file"](self.session).params(file_path=file_path).all()

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

    def mark_required_for_files(self, parent_path):
        """ mark all files in parent_path as required.
        """
        parent_item = self.get_item(item_path=parent_path, what="dir")
        update_statement = update(SVNRow)\
            .where(SVNRow.level == parent_item.level+1)\
            .where(SVNRow.fileFlag == True)\
            .where(SVNRow.path.like(parent_item.path+"/%"))\
            .values(required=True)
        results = self.session.execute(update_statement)
        return results.rowcount

    def get_items_in_dir(self, dir_path="", what="any", levels_deep=1024):
        """ get all files in dir_path.
            level_deep: how much to dig in. level_deep=1 will only get immediate files
            :return: list of items in dir or empty list (if there aren't any) or None
            if dir_path is not a dir
        """
        try:
            if dir_path == "":
                dir_items = self.get_items(what=what, levels_deep=levels_deep)
            else:
                dir_item = self.get_item(item_path=dir_path, what="dir")

                if "dir_items_recursive" not in self.baked_queries_map:
                    self.baked_queries_map["dir_items_recursive"] = self.bakery(lambda session: session.query(SVNRow))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.filter(SVNRow.path.like(bindparam('dir_path')+"/%"))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.filter(SVNRow.level > bindparam('dir_level'))
                    self.baked_queries_map["dir_items_recursive"] += lambda q: q.filter(SVNRow.level <= bindparam('dir_level')+bindparam('levels_deep'))

                dir_items = self.baked_queries_map["dir_items_recursive"](self.session)\
                    .params(dir_path=dir_path, dir_level=dir_item.level, levels_deep=levels_deep)\
                    .all()
            return dir_items
        except NoResultFound:
            print(dir_path, "was not found")
        return None

    def mark_required_for_dir(self, dir_path):
        """ mark all files & dirs in dir_path as required.
            marking is recursive.
        """
        try:
            dir_item = self.get_item(item_path=dir_path, what="dir")
            update_statement = update(SVNRow)\
                    .where(SVNRow.fileFlag == True)\
                    .where(SVNRow.level > dir_item.level)\
                    .where(SVNRow.path.like(dir_item.path+"/%"))\
                    .values(required=True)
            results = self.session.execute(update_statement)
            retVal = results.rowcount
        except NoResultFound:
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
        elif source_type == '!files':
            num_required_files = self.mark_required_for_files(source_path)
        return num_required_files

    def mark_required_completion(self):
        """ after some files were marked as required,
            mark their parent dirs are required as well
        """
        required_file_items = self.get_required_items(what="file")
        ancestors = list()
        for file_item in required_file_items:
            ancestors.extend(file_item.get_ancestry()[:-1])
        ancestors = set(ancestors)
        if len(ancestors) == 0:
            print("no ancestors for")
        update_statement = update(SVNRow)\
                .where(SVNRow.path.in_(ancestors))\
                .values(required=True)
        self.session.execute(update_statement)

    def mark_need_download(self, local_sync_dir):
        ancestors = list()
        required_file_items = self.get_required_items(what="file")
        for file_item in required_file_items:
            local_path = os.path.join(local_sync_dir, file_item.path)
            if utils.need_to_download_file(local_path, file_item.checksum):
                file_item.need_download = True
                ancestors.extend(file_item.get_ancestry()[:-1])
        ancestors = set(ancestors)
        if len(ancestors) > 0:
            update_statement = update(SVNRow)\
                    .where(SVNRow.path.in_(ancestors))\
                    .values(need_download=True)
            self.session.execute(update_statement)

    def mark_required_for_revision(self, required_revision):
        """ mark all files and dirs as required if they are of specific revision
        """
        update_statement = update(SVNRow)\
            .where(SVNRow.fileFlag == True)\
            .where(SVNRow.revision_remote == required_revision)\
            .values(required=True)
        self.session.execute(update_statement)
        self.mark_required_completion()

    def clear_required(self):
        update_statement = update(SVNRow)\
            .values(required=False)
        self.session.execute(update_statement)

    def get_unrequired_paths_where_parent_required(self, what="files"):
        """ Get all unrequired items that have a parent that is required.
            This is a  trick to leave as on disk only folders that have siblings that are required.
            used in InstlAdmin.do_upload_to_s3_aws_for_revision
        """
        if what not in ("any", "file", "dir"):
            raise ValueError(what+" not a valid filter for get_item")

        want_file = what in ("any", "file")
        want_dir = what in ("any", "dir")
        get_files = what == "files"
        the_query = self.session.query(SVNRow.path)\
            .filter(SVNRow.fileFlag == want_file,
                    SVNRow.dirFlag == want_dir,
                    SVNRow.required == False,
                    or_(SVNRow.parent.in_(\
                        self.session.query(SVNRow.path)\
                            .filter(SVNRow.required==True, SVNRow.dirFlag==True)),\
                            SVNRow.parent == ""))

        unrequired_files = the_query.all()

        return [unrequired_file[0] for unrequired_file in unrequired_files]

    def min_max_revision(self):
        min_revision = self.session.query(SVNRow, func.min(SVNRow.revision_remote)).scalar()
        max_revision = self.session.query(SVNRow, func.max(SVNRow.revision_remote)).scalar()
        return min_revision.revision_remote, max_revision.revision_remote
