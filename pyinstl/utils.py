#!/usr/local/bin/python2.7
from __future__ import print_function
import sys

class write_to_file_or_stdout(object):
    def  __init__(self, file_path):
        self.file_path = file_path
        self.fd = sys.stdout

    def __enter__(self):
        if self.file_path != "stdout":
            self.fd = open(self.file_path, "w")
        return self.fd

    def __exit__(self, type, value, traceback):
        if self.file_path != "stdout":
            self.fd.close()


class write_to_list(object):
    """ list that behaves like a file. For each call to write
        another item is added to the list.
    """
    def __init__(self):
        self.the_list = list()

    def write(self, text):
        self.the_list.append(text)

    def list(self):
        return self.the_list

class unique_list(list):
    def __init__(self, *args):
        super(unique_list, self).__init__()
        self.extend(*args)
    def __setitem__(self, index, item):
        raise KeyError("unique_list does not support setting by index")
    def append(self, item):
        if item not in self:
            super(unique_list, self).append(item)
    def extend(self, items = ()):
        for item in items:
            if item not in self:
                super(unique_list, self).append(item)
            
