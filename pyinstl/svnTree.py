#!/usr/bin/env python
from __future__ import print_function

import time
from collections import OrderedDict
import yaml
import logging

from pyinstl.utils import *
import aYaml
import svnItem

import re
comment_line_re = re.compile(r"""
            ^
            \s*\#\s*
            (?P<the_comment>.*)
            $
            """, re.X)

map_info_extension_to_format = {"txt" : "text", "text" : "text",
                "inf" : "info", "info" : "info",
                "yml" : "yaml", "yaml" : "yaml",
                "pick" : "pickle", "pickl" : "pickle", "pickle" : "pickle",
                "props" : "props", "prop" : "props"
                }

class SVNTree(svnItem.SVNTopItem):
    """ SVNTree inherites from SVNTopItem and adds the functionality
        of reading and writing itself in variouse text formats:
            info: produced by SVN's info command (read only)
            props: produced by SVN's proplist command (read only)
            text: SVNItem's native format (read and write)
            yaml: yaml... (read and write)
    """
    def __init__(self):
        """ Initializes a SVNTree object """
        super(SVNTree, self).__init__()
        self.read_func_by_format = {"info": self.read_from_svn_info,
                                    "text": self.read_from_text,
                                    "yaml": self.pseudo_read_from_yaml,
                                    "props": self.read_props}

        self.write_func_by_format = {"text": self.write_as_text,
                                    "yaml": self.write_as_yaml,
                                    }
        self.path_to_file = None
        self.comments = list()

    def valid_read_formats(self):
        """ returns a list of file formats that can be read by SVNTree """
        return self.read_func_by_format.keys()

    def read_info_map_from_file(self, in_file, format="guess"):
        """ Reads from file. All previous sub items are cleared
            before reading, unless the format is 'props' in which case
            the properties are added to exsisting sub items.
            raises ValueError is format is not supported.
        """
        self.path_to_file = in_file
        if format == "guess":
            _, extension = os.path.splitext(self.path_to_file)
            format = map_info_extension_to_format[extension[1:]]
        self.comments.append("Original file "+self.path_to_file)
        if format in self.read_func_by_format.keys():
            with open_for_read_file_or_url(self.path_to_file) as rfd:
                logging.info("opened %s, format: %s", self.path_to_file, format)
                if format != "props":
                    self.clear_subs()
                self.read_func_by_format[format](rfd)
        else:
            logging.info("%s is not a known map_info format. Cannot read %s", format, in_file)
            ValueError("Unknown read format "+format)

    def read_from_svn_info(self, rfd):
        """ reads new items from svn info items prepared by iter_svn_info """
        for item in self.iter_svn_info(rfd):
            self.new_item_at_path(*item)

    def read_from_text(self, rfd):
        for line in rfd:
            match = comment_line_re.match(line)
            if match:
                self.comments.append(match.group("the_comment"))
            else:
                self.new_item_from_str(line)

    def read_from_yaml(self, rfd):
        try:
            for a_node in yaml.compose_all(rfd):
                self.read_yaml_node(a_node)
        except yaml.YAMLError as ye:
            raise InstlException(" ".join( ("YAML error while reading file", "'"+file_path+"':\n", str(ye)) ), ye)
        except IOError as ioe:
            raise InstlException(" ".join(("Failed to read file", "'"+file_path+"'", ":")), ioe)

    def pseudo_read_from_yaml(self, rfd):
        """ read from yaml file without the yaml parser - much faster
            but might break is the format changes.
        """
        yaml_line_re = re.compile("""
                    ^
                    (?P<indent>\s*)
                    (?P<path>[^:]+)
                    :\s
                    (?P<props>
                    (?P<flags>[dfsx]+)
                    \s
                    (?P<last_rev>\d+)
                    (\s
                    (?P<checksum>[\da-f]+))?
                    )?
                    $
                    """, re.X)
        try:
            line_num = 0
            indent = -1 # so indent of first line (0) > indent (-1)
            spaces_per_indent = 4
            path_parts = list()
            for line in rfd:
                line_num += 1
                match = yaml_line_re.match(line)
                if match:
                    new_indent = len(match.group('indent')) / spaces_per_indent
                    if match.group('path') != "_p_":
                        how_much_to_pop = indent-new_indent+1
                        if how_much_to_pop > 0:
                            path_parts = path_parts[0: -how_much_to_pop]
                        path_parts.append(match.group('path'))
                        if match.group('props'): # it's a file
                            #print(((new_indent * spaces_per_indent)-1) * " ", "/".join(path_parts), match.group('props'))
                            self.new_item_at_path(path_parts, match.group('flags'), int(match.group('last_rev')), match.group('checksum'))
                        indent = new_indent
                    else: # previous element was a folder
                        #print(((new_indent * spaces_per_indent)-1) * " ", "/".join(path_parts), match.group('props'))
                        self.new_item_at_path(path_parts, match.group('flags'), int(match.group('last_rev')))
                else:
                    if indent != -1: # first lines might be empty
                        ValueError("no match at line "+str(line_num)+": "+line)
        except Exception as unused_ex:
            print("exception at line:", line_num, line)
            raise

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
            prop_name_to_char = {'executable': 'x', 'special': 's'}
            item = None
            for line in rfd:
                line_num += 1
                match = props_line_re.match(line)
                if match:
                    if match.group('path'):
                        # get_item_at_path might return None for invalid paths, mainly '.'
                        item = self.get_item_at_path(match.group('path'))
                    elif match.group('prop_name'):
                        if item is not None:
                            prop_name = match.group('prop_name')
                            if prop_name in prop_name_to_char:
                                item.add_flags(prop_name_to_char[match.group('prop_name')])
                            else:
                                if not item.props:
                                    item.props = list()
                                item.props.append(prop_name)
                else:
                    ValueError("no match at file: "+rfd.name+", line: "+str(line_num)+": "+line)
        except Exception as ex:
            print("Line:", line_num, ex)
            raise

    def valid_write_formats(self):
        return self.write_func_by_format.keys()

    def write_to_file(self, in_file, in_format="guess"):
        """ pass in_file="stdout" to output to stdout.
            in_format is either text, yaml, pickle
        """
        self.path_to_file = in_file
        if in_format == "guess":
            _, extension = os.path.splitext(self.path_to_file)
            in_format = map_info_extension_to_format[extension[1:]]
        if in_format in self.write_func_by_format.keys():
            with write_to_file_or_stdout(self.path_to_file) as wfd:
                logging.info("opened %s, format: %s", self.path_to_file, format)
                self.write_func_by_format[in_format](wfd)
        else:
            logging.info("%s is not a known map_info format. Cannot write %s", format, in_file)
            ValueError("Unknown write in_format "+in_format)

    def write_as_text(self, wfd):
        if len(self.comments) > 0:
            for comment in self.comments:
                wfd.write("# "+comment+"\n")
            wfd.write("\n")
        for item in self.walk_items():
            wfd.write(str(item)+"\n")

    def write_as_yaml(self, wfd):
        aYaml.augmentedYaml.writeAsYaml(self, out_stream=wfd, indentor=None, sort=True)

    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = OrderedDict()
        for sub_name in sorted(self.subs().keys()):
            the_sub = self.subs()[sub_name]
            if the_sub.isDir():
                retVal[the_sub.name()] = the_sub.repr_for_yaml()
            else:
                ValueError("SVNTree does not support files in the top most directory")
        return retVal

    def iter_svn_info(self, long_info_fd):
        """ Go over the lines of the output of svn info command
            for each block describing a file or directory, yield
            a tuple formatted as (path, type, last changed revision).
            Where type is 'f' for file or 'd' for directory. """
        try:
            svn_info_line_re = re.compile("""
                        ^
                        (?P<key>Path|Last\ Changed\ Rev|Node\ Kind|Revision|Checksum)
                        :\s*
                        (?P<rest_of_line>.*)
                        $
                        """, re.VERBOSE)
            def create_info_line_from_record(record):
                """ On rare occasions there is no 'Last Changed Rev' field, just 'Revision'.
                    So we use 'Revision' as 'Last Changed Rev'.
                """
                revision = record.get("Last Changed Rev", None)
                if revision is None:
                    revision = record.get("Revision", None)
                checksum = record.get("Checksum", None)
                return (record["Path"], short_node_kind[record["Node Kind"]], int(revision), checksum)

            short_node_kind = {"file" : "f", "directory" : "d"}
            record = dict()
            line_num = 0
            for line in long_info_fd:
                line_num += 1
                if line != "\n":
                    the_match = svn_info_line_re.match(line)
                    if the_match:
                        record[the_match.group('key')] = the_match.group('rest_of_line')
                else:
                    if record and record["Path"] != ".": # in case there were several empty lines between blocks
                        yield create_info_line_from_record(record)
                    record.clear()
            if record and record["Path"] != ".": # in case there was no extra line at the end of file
                yield create_info_line_from_record(record)
        except KeyError as unused_ke:
            print("key error, file:", long_info_fd.name, "line:", line_num, "record:", record)
            raise

if __name__ == "__main__":
    t = SVNTree()
    t.read_svn_info_file(sys.argv[1])
    #for item in t.walk_items():
    #    print(str(item))
