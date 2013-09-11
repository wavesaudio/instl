#!/usr/bin/env python
from __future__ import print_function

import os
import sys
import re
import time
import cPickle as pickle

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
        super(SVNTree, self).__init__("to_of_tree", "d", 0)
        self.dump_func_by_format = {"text": self.dump_as_text,
                                    "yaml": self.dump_as_yaml,
                                    "pickle": self.dump_as_pickle}
    @classmethod
    def init_from_picke():
        pass
        

    def unpickle(self, in_file):
        with open(in_file,'rb') as rfd:
            tmp_dict = pickle.load(rfd)
        self.__dict__.update(tmp_dict) 
    
    def dump_to_file(self, in_file, format="text"):
        """ pass in_file="stdout" to output to stdout.
            format is either text, yaml, pickle
        """
        if format in self.dump_func_by_format.keys():
            with write_to_file_or_stdout(in_file) as fd:
                self.dump_func_by_format[format](fd)
        else:
            ValueError("Unknown format "+format)
            
    def dump_as_text(self, wfd):
        for item in self.walk_items():
            wfd.write("%s, %s, %d\n" % (item[0], item[1], item[2]) )

    def dump_as_yaml(self, wfd):
        aYaml.augmentedYaml.writeAsYaml(self, out_stream=wfd, indentor=None, sort=True)

    def dump_as_pickle(self, wfd):
        pickle.dump(self.__dict__, wfd, 2)

    def read_svn_info_file(self, info_file, report_level=0):
        time_start = time.time()
        num_items = 0
        with open(info_file, "r") as fd:
            if report_level > 0:
                print(info_file, "opened")
            for item in self.iter_svn_info(fd):
                if report_level > 1:
                    print(item)
                self.add_sub(*item)
                num_items += 1
        time_end = time.time()
        if report_level > 0:
            print("%d items read in %0.3f ms" % (num_items, (time_end-time_start)*1000.0))
                
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
