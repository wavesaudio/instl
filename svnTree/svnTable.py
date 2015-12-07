import os
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .svnRow import SVNRow, alchemy_base

import utils

comment_line_re = re.compile(r"""
            ^
            \s*\#\s*
            (?P<the_comment>.*)
            $
            """, re.X)

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

        self.write_func_by_format = {"text": self.write_as_text,
        }
        self.path_to_file = None
        self.comments = list()

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
        #self.session.commit()

    def read_from_svn_info(self, rfd):
        """ reads new items from svn info items prepared by iter_svn_info """
        insert_dicts = [item_dict for item_dict in self.iter_svn_info(rfd)]
        self.session.bulk_insert_mappings(SVNRow, insert_dicts)

    def read_from_text(self, rfd):
        for line in rfd:
            match = comment_line_re.match(line)
            if match:
                self.comments.append(match.group("the_comment"))
            else:
                self.new_item_from_str_re(line)

    def valid_write_formats(self):
        return list(self.write_func_by_format.keys())

    def write_to_file(self, in_file, in_format="guess", comments=True):
        """ pass in_file="stdout" to output to stdout.
            in_format is either text, yaml, pickle
        """
        self.path_to_file = in_file
        if in_format == "guess":
            _, extension = os.path.splitext(self.path_to_file)
            in_format = map_info_extension_to_format[extension[1:]]
        if in_format in list(self.write_func_by_format.keys()):
            with utils.write_to_file_or_stdout(self.path_to_file) as wfd:
                self.write_func_by_format[in_format](wfd, comments)
        else:
            raise ValueError("Unknown write in_format " + in_format)

    def write_as_text(self, wfd, comments=True):
        if comments and len(self.comments) > 0:
            for comment in self.comments:
                wfd.write("# " + comment + "\n")
            wfd.write("\n")
        for item in self.session.query(SVNRow).order_by(SVNRow.path):
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
                path_parts = retVal['path'].split("/")
                retVal['name'] = path_parts[-1]
                retVal['parent'] = "/".join(path_parts[:-1])+"/"
                retVal['fileFlag'] = a_record["Node Kind"] == "file"
                if "Last Changed Rev" in a_record:
                    retVal['revision_remote'] = int(a_record["Last Changed Rev"])
                elif "Revision" in a_record:
                    retVal['revision'] = int(a_record["Revision"])
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
