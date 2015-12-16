import os
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy import update
from sqlalchemy import or_

from .svnRow import SVNRow, alchemy_base

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
        self.path_to_file = None
        self.comments = list()

    def __repr__(self):
        return "\n".join([item.__repr__() for item in self.session.query(SVNRow).all()])

    def repr_to_file(self, file_path):
        with open(file_path, "w") as wfd:
            wfd.write(self.__repr__())

    def valid_read_formats(self):
        """ returns a list of file formats that can be read by SVNTree """
        return list(self.read_func_by_format.keys())

    def read_info_map_from_file(self, in_file, a_format="guess"):
        """ Reads from file. All previous sub items are cleared
            before reading, unless the a_format is 'props' in which case
            the properties are added to existing sub items.
            raises ValueError is a_format is not supported.
        """
        self.path_to_file = in_file
        if a_format == "guess":
            _, extension = os.path.splitext(self.path_to_file)
            a_format = map_info_extension_to_format[extension[1:]]
        self.comments.append("Original file " + self.path_to_file)
        if a_format in list(self.read_func_by_format.keys()):
            with utils.open_for_read_file_or_url(self.path_to_file) as rfd:
                if a_format not in ("props", "file-sizes"):
                    self.clear_all()
                self.read_func_by_format[a_format](rfd)
        else:
            raise ValueError("Unknown read a_format " + a_format)

    def read_from_svn_info(self, rfd):
        """ reads new items from svn info items prepared by iter_svn_info """
        insert_dicts = [item_dict for item_dict in self.iter_svn_info(rfd)]
        self.session.bulk_insert_mappings(SVNRow, insert_dicts)

    def read_from_text_to_dict(self, in_rfd):
        retVal = list()
        for line in in_rfd:
            line = line.strip()
            item_dict = SVNTable.item_dict_from_str_re(line)
            if item_dict:
                retVal.append(item_dict)
            else:
                match = comment_line_re.match(line)
                if match:
                    self.comments.append(match.group("the_comment"))
        return retVal


    def insert_dicts_to_db(self, insert_dicts):
        #self.session.bulk_insert_mappings(SVNRow, insert_dicts)
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
            item_dict = SVNTable.item_dict_from_str_re(line)
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
    def item_dict_from_str_re(the_str):
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
            item_details['level'] = len(item_details['path'].split("/"))
            item_details['revision_remote'] = match.group('revision')
            item_details['flags'] = match.group('flags')
            item_details['fileFlag'] = 'f' in item_details['flags']
            #item_details['wtar_file'], item_details['wtar_first_file'] = Table.get_wtar_file_status(item_details['path'])
            #item_details['execFlag'] = 'x' in item_details['flags']
            item_details['checksum'] = match.group('checksum')
            item_details['url'] = match.group('url')
            item_details['size'] = int(match.group('size')) if match.group('size')  else -1
        return item_details

    def valid_write_formats(self):
        return list(self.write_func_by_format.keys())

    @utils.timing
    def write_to_file(self, in_file, in_format="guess", comments=True, filter_name=None):
        """ pass in_file="stdout" to output to stdout.
            in_format is either text, yaml, pickle
        """
        self.path_to_file = in_file
        if in_format == "guess":
            _, extension = os.path.splitext(self.path_to_file)
            in_format = map_info_extension_to_format[extension[1:]]
        if in_format in list(self.write_func_by_format.keys()):
            with utils.write_to_file_or_stdout(self.path_to_file) as wfd:
                self.write_func_by_format[in_format](wfd, comments, filter_name)
        else:
            raise ValueError("Unknown write in_format " + in_format)

    def write_as_text(self, wfd, comments=True, filter_name=None):
        if comments and len(self.comments) > 0:
            for comment in self.comments:
                wfd.write("# " + comment + "\n")
            wfd.write("\n")

        if filter_name:
            if filter_name == "required":
                the_query = self.session.query(SVNRow).filter(SVNRow.required==True)
            elif filter_name == "to_download":
                the_query = self.session.query(SVNRow).filter(SVNRow.to_download==True)
            else:
                the_query = self.session.query(SVNRow)
        else:
            the_query = self.session.query(SVNRow)

        for item in the_query.all():
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
                retVal['level'] = len(retVal['path'].split("/"))
                retVal['fileFlag'] = a_record["Node Kind"] == "file"
                retVal['flags'] = match.group('flags')
                retVal['fileFlag'] = 'f' in retVal['flags']
                if "Last Changed Rev" in a_record:
                    retVal['revision_remote'] = int(a_record["Last Changed Rev"])
                elif "Revision" in a_record:
                    retVal['revision_remote'] = int(a_record["Revision"])
                else:
                    retVal['revision_remote'] = -1
                retVal['checksum'] = a_record.get("Checksum", None)

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

    def initialize_from_folder(self, in_folder):
        prefix_len = len(in_folder)+1
        for root, dirs, files in os.walk(in_folder, followlinks=False):
            for a_file in files:
                if a_file != ".DS_Store": # temp hack, list of ignored files should be moved to a variable
                    relative_path = os.path.join(root, a_file)[prefix_len:]
                    self.new_item_at_path(relative_path, {'flags':"f", 'revision': 0, 'checksum': "0"}, create_folders=True)

    def clear_all(self):
        self.session.query(SVNRow).delete()

    def set_base_revision(self, base_revision):
        self.session.query(SVNRow).filter(SVNRow.revision_remote < base_revision).\
                                    update({"revision_remote": base_revision})

    def read_file_sizes(self, rfd):
        update_dicts = list()
        for line in rfd:
            match = comment_line_re.match(line)
            if not match:
                parts = line.rstrip().split(", ", 2)
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
        update_dicts = list()
        try:
            prop_name_to_col_name = {'executable': 'execFlag', 'special': 'symlinkFlag'}
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
                            if prop_name in prop_name_to_col_name:
                                update_dicts.append({"path": path, prop_name_to_col_name[prop_name]: True})
                else:
                    ValueError("no match at file: " + rfd.name + ", line: " + str(line_num) + ": " + line)
        except Exception as ex:
            print("Line:", line_num, ex)
            raise
        self.session.bulk_update_mappings(SVNRow, update_dicts)

    def get_items(self, in_parent="", in_level=700, get_files=True, get_dirs=True):
        get_dirs = not get_dirs
        if not in_parent:
            the_query = self.session.query(SVNRow).filter(or_(SVNRow.fileFlag==get_files, SVNRow.fileFlag==get_dirs))
        else:
            parent_item = self.session.query(SVNRow).filter(SVNRow.path==in_parent).one()
            the_query = self.session.query(SVNRow).filter(or_(SVNRow.fileFlag==get_files, SVNRow.fileFlag==get_dirs))\
                                                .filter(SVNRow.path.like(parent_item.path+"/%"))\
                                                .filter(SVNRow.level > parent_item.level, SVNRow.level < parent_item.level+in_level+1)

        return the_query.all()

    def get_ancestry(self, in_path):
        item = self.session.query(SVNRow).filter(SVNRow.path==in_path).one()
        ancestry = item.get_ancestry()
        the_query = self.session.query(SVNRow).filter(SVNRow.path.in_(ancestry))

        return the_query.all()

    def mark_required_for_item(self, item):
        ancestry = item.get_ancestry()
        update_statement = update(SVNRow)\
                .where(SVNRow.path.in_(ancestry))\
                .values(required=True)
        self.session.execute(update_statement)

    @utils.timing
    def mark_required_for_file(self, item_path):
        update_statement = update(SVNRow)\
                .where(SVNRow.fileFlag == True)\
                .where(or_(SVNRow.path == item_path, SVNRow.path.like(item_path+".wtar%")))\
                .values(required=True)
        self.session.execute(update_statement)

    @utils.timing
    def mark_required_for_files(self, parent_path):
        parent_item = self.session.query(SVNRow).filter(SVNRow.path == parent_path, SVNRow.fileFlag==False).first()
        update_statement = update(SVNRow)\
                .where(SVNRow.level == parent_item.level+1)\
                .where(SVNRow.fileFlag == True)\
                .where(SVNRow.path.like(parent_item.path+"/%"))\
                .values(required=True)
        self.session.execute(update_statement)

    @utils.timing
    def mark_required_for_dir(self, dir_path):
        dir_item = self.session.query(SVNRow).filter(SVNRow.path == dir_path, SVNRow.fileFlag==False).first()
        update_statement = update(SVNRow)\
                .where(SVNRow.level > dir_item.level)\
                .where(SVNRow.path.like(dir_item.path+"/%"))\
                .values(required=True)
        self.session.execute(update_statement)

    @utils.timing
    def mark_required_completion(self):
        file_items = self.session.query(SVNRow).filter(SVNRow.required==True, SVNRow.fileFlag==True).all()
        ancestors = list()
        for file_item in file_items:
            ancestors.extend(file_item.get_ancestry()[:-1])
        ancestors = set(ancestors)
        if len(ancestors) == 0:
            print("no ancestors for")
        update_statement = update(SVNRow)\
                .where(SVNRow.path.in_(ancestors))\
                .values(required=True)
        self.session.execute(update_statement)

    def get_required(self):
        the_query = self.session.query(SVNRow).filter(SVNRow.required==True)
        return the_query.all()

    def mark_required_for_source(self, source):
        """
        :param source: a tuple (source_folder, tag), where tag is either !file or !dir
        :return: None
        """
        if source[1] == '!file':
            self.mark_required_for_file(source[0])
        elif source[1] == '!files':
            self.mark_required_for_files(source[0])
        elif source[1] == '!dir' or source[1] == '!dir_cont':  # !dir and !dir_cont are only different when copying
            self.mark_required_for_dir(source[0])

    def mark_need_download(self, local_sync_dir):
        for item in self.session.query(SVNRow).filter(SVNRow.required == True).filter(SVNRow.fileFlag == True).all():
            local_path = os.path.join(local_sync_dir, item.path)
            if utils.need_to_download_file(local_path, item.checksum):
                item.need_download = True

    def get_to_download_list(self):
        file_list = [file_item for file_item in self.session.query(SVNRow).filter(SVNRow.need_download == True).all()]
        return file_list

    def write_to_download_list_to_file(self):
            self.work_info_map.write_to_file(var_stack.resolve("$(TO_SYNC_INFO_MAP_PATH)", raise_on_fail=True), in_format="text")
