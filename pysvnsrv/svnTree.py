#!/usr/bin/env python
from __future__ import print_function

import os
import sys
import re
import time
import cPickle as pickle
from collections import namedtuple, OrderedDict
import yaml

from pyinstl.utils import *
import aYaml
import svnItem

def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print ('%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0))
        return ret
    return wrap

class SVNTree(svnItem.SVNItem):
    #__slots__ = ("__name", "__flags", "__last_rev", "__subs")
    def __init__(self):
        super(SVNTree, self).__init__("top_of_tree", "d", 0)
        self.read_func_by_format = {"info": self.read_from_svn_info,
                                    #"pickle": self.read_from_pickle,
                                    "text": self.read_from_text,
                                    "yaml": self.read_from_yaml}
                                    
        self.write_func_by_format = { # "pickle": self.write_as_pickle
                                    "text": self.write_as_text,
                                    "yaml": self.write_as_yaml,
                                    }

    """ reading """
    def valid_read_formats(self):
        return self.read_func_by_format.keys()
        
    def read_from_file(self, in_file, format="text", report_level=0):
        """ format is either text, yaml, pickle
        """
        if format in self.read_func_by_format.keys():
            time_start = time.time()
            with open_for_read_file_or_url(in_file) as rfd:
                if report_level > 0:
                    print("opened file:", "'"+in_file+"'")
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
        raise NotImplementedError("reading from text not implementred yet")
                
    def read_from_yaml(self, rfd, report_level=0):
        try:
            for a_node in yaml.compose_all(rfd):
                self.read_yaml_node(a_node)
        except yaml.YAMLError as ye:
            raise InstlException(" ".join( ("YAML error while reading file", "'"+file_path+"':\n", str(ye)) ), ye)
        except IOError as ioe:
            raise InstlException(" ".join(("Failed to read file", "'"+file_path+"'", ":")), ioe)
        
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
        line_re = re.compile("""
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
                the_match = line_re.match(line)
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
