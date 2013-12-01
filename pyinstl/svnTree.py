#!/usr/bin/env python
from __future__ import print_function

import os
import sys
import re
import time
from collections import namedtuple, OrderedDict
import yaml

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

def timing(f):
    def wrap(*args, **kwargs):
        time1 = time.time()
        ret = f(*args, **kwargs)
        time2 = time.time()
        print ('%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0))
        return ret
    return wrap

class SVNTree(svnItem.SVNTopItem):
    def __init__(self):
        super(SVNTree, self).__init__()
        self.read_func_by_format = {"info": self.read_from_svn_info,
                                    "pickle": self.read_from_pickle,
                                    "text": self.read_from_text,
                                    "yaml": self.pseudo_read_from_yaml,
                                    "props": self.read_props}

        self.write_func_by_format = { "pickle": self.write_as_pickle,
                                    "text": self.write_as_text,
                                    "yaml": self.write_as_yaml,
                                    }
        self.path_to_file = None
        self.comments = list()

    """ reading """
    def valid_read_formats(self):
        return self.read_func_by_format.keys()

    def read_from_file(self, in_file, format="text", report_level=0):
        """ format is either text, yaml, pickle
        """
        self.path_to_file = in_file
        if format in self.read_func_by_format.keys():
            time_start = time.time()
            with open_for_read_file_or_url(self.path_to_file) as rfd:
                if report_level > 0:
                    print("opened file:", "'"+self.path_to_file+"'")
                if format != "props":
                    self.clear_subs()
                self.read_func_by_format[format](rfd, report_level)
            time_end = time.time()
            if report_level > 0:
                print("    %d items read in %0.3f ms from %s file" % (self.num_subs_in_tree(), (time_end-time_start)*1000.0, format))
        else:
            ValueError("Unknown read format "+format)

    def read_from_svn_info(self, rfd, report_level=0):
        for item in self.iter_svn_info(rfd):
            self.new_item_at_path(*item)

    def read_from_text(self, rfd, report_level=0):
        for line in rfd:
            match = comment_line_re.match(line)
            if match:
                self.comments.append(match.group("the_comment"))
            else:
                self.new_item_from_str(line)

    def read_from_yaml(self, rfd, report_level=0):
        try:
            for a_node in yaml.compose_all(rfd):
                self.read_yaml_node(a_node)
        except yaml.YAMLError as ye:
            raise InstlException(" ".join( ("YAML error while reading file", "'"+file_path+"':\n", str(ye)) ), ye)
        except IOError as ioe:
            raise InstlException(" ".join(("Failed to read file", "'"+file_path+"'", ":")), ioe)

    def pseudo_read_from_yaml(self, rfd, report_level=0):
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
                            self.new_item_at_path(path_parts, match.group('flags'), int(match.group('last_rev')))
                        indent = new_indent
                    else: # previous element was a folder
                        #print(((new_indent * spaces_per_indent)-1) * " ", "/".join(path_parts), match.group('props'))
                        self.new_item_at_path(path_parts, match.group('flags'), int(match.group('last_rev')))
                else:
                    if indent != -1: # first lines might be empty
                        ValueError("no matach at line "+str(line_num)+": "+line)
        except Exception as ex:
            print("exception at line:", line_num, line)
            raise

    def read_from_pickle(self, rfd, report_level=0):
        import cPickle as pickle
        my = pickle.load(rfd) # cannot pickle to self
        self.__name = my.name()
        self.__flags = my.flags()
        self.__last_rev = my.last_rev()
        for sub_item in my.subs().values():
            self.add_sub_item(sub_item)

    def read_props(self, rfd, report_level=0):
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
                    (?P<prop_name>special|executable)
                    )
                    $
                    """, re.X)
        try:
            prop_name_to_char = {'executable': 'x', 'special': 's'}
            line_num = 0
            item = None
            for line in rfd:
                line_num += 1
                match = props_line_re.match(line)
                if match:
                    if match.group('path'):
                        item = self.get_item_at_path(match.group('path'))
                    elif match.group('prop_name'):
                        item.add_flags(prop_name_to_char[match.group('prop_name')])
                        item = None
                else:
                    ValueError("no match at file: "+rfd.name+", line: "+str(line_num)+": "+line)
        except Exception as ex:
            print(ex)
            raise

    """ writing """
    def valid_write_formats(self):
        return self.write_func_by_format.keys()

    def write_to_file(self, in_file, in_format="text", report_level=0):
        """ pass in_file="stdout" to output to stdout.
            in_format is either text, yaml, pickle
        """
        self.path_to_file = in_file
        if in_format in self.write_func_by_format.keys():
            time_start = time.time()
            with write_to_file_or_stdout(self.path_to_file) as wfd:
                if report_level > 0:
                    print("opened file:", "'"+self.path_to_file+"'")
                self.write_func_by_format[in_format](wfd, report_level)
            time_end = time.time()
            if report_level > 0:
                print("    %d items written in %0.3f ms" % (self.num_subs_in_tree(), (time_end-time_start)*1000.0))
        else:
            ValueError("Unknown write in_format "+in_format)

    def write_as_pickle(self, wfd, report_level=0):
        import cPickle as pickle
        pickle.dump(self, wfd, 2)

    def write_as_text(self, wfd, report_level=0):
        for comment in self.comments:
            wfd.write("# "+comment+"\n")
        wfd.write("\n")
        for item in self.walk_items():
            wfd.write(str(item)+"\n")

    def write_as_yaml(self, wfd, report_level=0):
        aYaml.augmentedYaml.writeAsYaml(self, out_stream=wfd, indentor=None, sort=True)

    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = OrderedDict()
        for sub_name in sorted(self.__subs.keys()):
            the_sub = self.get_sub(sub_name)
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
                        (?P<key>Path|Last\ Changed\ Rev|Node\ Kind)
                        :\s*
                        (?P<rest_of_line>.*)
                        $
                        """, re.X)
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
                        yield (record["Path"], short_node_kind[record["Node Kind"]], int(record["Last Changed Rev"]))
                    record.clear()
            if record and record["Path"] != ".": # in case there was no extra line at the end of file
                yield (record["Path"], short_node_kind[record["Node Kind"]], int(record["Last Changed Rev"]))
        except KeyError as ke:
            print("key error, file:", long_info_fd.name, "line:", line_num, "record:", record)
            raise

if __name__ == "__main__":
    t = SVNTree()
    t.read_svn_info_file(sys.argv[1])
    #for item in t.walk_items():
    #    print(str(item))
