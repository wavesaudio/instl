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

def timing(f):
    def wrap(*args, **kwargs):
        time1 = time.time()
        ret = f(*args, **kwargs)
        time2 = time.time()
        print ('%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0))
        return ret
    return wrap

class SVNTree(svnItem.SVNItem):
    def __init__(self):
        super(SVNTree, self).__init__("top_of_tree", "d", 0)
        self.read_func_by_format = {"info": self.read_from_svn_info,
                                    "pickle": self.read_from_pickle,
                                    "text": self.read_from_text,
                                    "yaml": self.pseudo_read_from_yaml,
                                    "props": self.read_props}
                                    
        self.write_func_by_format = { "pickle": self.write_as_pickle,
                                    "text": self.write_as_text,
                                    "yaml": self.write_as_yaml,
                                    }

    """ reading """
    def valid_read_formats(self):
        return self.read_func_by_format.keys()
        
    @timing
    def read_from_file(self, in_file, format="text", report_level=0):
        """ format is either text, yaml, pickle
        """
        if format in self.read_func_by_format.keys():
            time_start = time.time()
            with open_for_read_file_or_url(in_file) as rfd:
                if report_level > 0:
                    print("opened file:", "'"+in_file+"'")
                if format != "props":
                    self.clear_subs()
                self.read_func_by_format[format](rfd, report_level)
            time_end = time.time()
            if report_level > 0:
                print("    %d items read in %0.3f ms" % (self.num_subs(), (time_end-time_start)*1000.0))
        else:
            ValueError("Unknown read format "+format)
                
    def read_from_svn_info(self, rfd, report_level=0):
        for item in self.iter_svn_info(rfd):
            self.add_sub(*item)
                
    def read_from_text(self, rfd, report_level=0):
        text_line_re = re.compile("""
                    ^
                    (?P<path>.*)
                    ,\s+
                    (?P<flags>[dfsx]+)
                    ,\s+
                    (?P<last_rev>\d+)
                    $
                    """, re.X)
        for line in rfd:
            match = text_line_re.match(line)
            if match:
                self.add_sub(match.group('path'), match.group('flags'), int(match.group('last_rev')))
                #print(match.group('path'), match.group('flags'), match.group('last_rev'))
                
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
                            self.add_sub("/".join(path_parts), match.group('flags'), int(match.group('last_rev')))
                        indent = new_indent
                    else: # previous element was a folder
                        #print(((new_indent * spaces_per_indent)-1) * " ", "/".join(path_parts), match.group('props'))
                        self.add_sub("/".join(path_parts), match.group('flags'), int(match.group('last_rev')))
                else:
                    if indent != -1: # first lines might be empty
                        ValueError("no matach at line "+str(line_num)+": "+line)
        except Exception as ex:
            print("exception at line:", line_num, line)
            raise
    
    def read_from_pickle(self, rfd, report_level=0):
        import cPickle as pickle
        my = pickle.load(rfd) # cannot pickle to self
        self.copy_from(my)
        
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
        prop_name_to_char = {'executable': 'x', 'special': 's'}
        line_num = 0
        path = ""
        for line in rfd:
            line_num += 1
            match = props_line_re.match(line)
            if match:
                if match.group('path'):
                    path = match.group('path')
                elif match.group('prop_name'):
                    self.add_flags(path, prop_name_to_char[match.group('prop_name')])
            else:
                ValueError("no matach at line "+str(line_num)+": "+line)
        
    """ writing """
    def valid_write_formats(self):
        return self.write_func_by_format.keys()

    def write_to_file(self, in_file, format="text", report_level=0):
        """ pass in_file="stdout" to output to stdout.
            format is either text, yaml, pickle
        """
        if format in self.write_func_by_format.keys():
            time_start = time.time()
            with write_to_file_or_stdout(in_file) as wfd:
                if report_level > 0:
                    print("opened file:", "'"+in_file+"'")
                self.write_func_by_format[format](wfd, report_level)
            time_end = time.time()
            if report_level > 0:
                print("    %d items written in %0.3f ms" % (self.num_subs(), (time_end-time_start)*1000.0))
        else:
            ValueError("Unknown write format "+format)
        
    def write_as_pickle(self, wfd, report_level=0):
        import cPickle as pickle
        pickle.dump(self, wfd, 2)
        
    def write_as_text(self, wfd, report_level=0):
        for item in self.walk_items():
            wfd.write("%s, %s, %d\n" % (item[0], item[1], item[2]) )

    def write_as_yaml(self, wfd, report_level=0):
        aYaml.augmentedYaml.writeAsYaml(self, out_stream=wfd, indentor=None, sort=True)
    
    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = OrderedDict()
        for sub_name in sorted(self.sub_names()):
            the_sub = self.get_sub(sub_name)
            if the_sub.isDir():
                retVal[the_sub.name()] = the_sub.repr_for_yaml()
            else:
                ValueError("SVNTree does not support files in the top most direcotry")
        return retVal
    
    def iter_svn_info(self, long_info_fd):
        """ Go over the lines of the output of svn info command
            for each block describing a file or directory, yield
            a tuple formatted as (path, type, last changed revision).
            Where type is 'f' for file or 'd' for directory. """
        svn_info_line_re = re.compile("""
                    ^
                    (?P<key>Path|Last\ Changed\ Rev|Node\ Kind)
                    :\s*
                    (?P<rest_of_line>.*)
                    $
                    """, re.X)
        short_node_kind = {"file" : "f", "directory" : "d"}
        record = dict()
        for line in long_info_fd:
            if line != "\n":
                the_match = svn_info_line_re.match(line)
                if the_match:
                    record[the_match.group('key')] = the_match.group('rest_of_line')
            else:
                if record: # in case there were several empty lines between blocks
                    yield svnItem.SVNItemFlat(record["Path"], short_node_kind[record["Node Kind"]], int(record["Last Changed Rev"]))
                record.clear()
        if record: # in case there was no extra line at the end of file
            yield svnItem.SVNItemFlat(record["Path"], short_node_kind[record["Node Kind"]], int(record["Last Changed Rev"]))

if __name__ == "__main__":
    t = SVNTree()
    t.read_svn_info_file(sys.argv[1])
    #for item in t.walk_items():
    #    print(str(item))
