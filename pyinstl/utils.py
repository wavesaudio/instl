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

"""
unique_list implements a list where all items are unique.
Functionality can also be decribed as set with order.
unique_list should behave as a python list except:
    Adding items the end of the list (by append, extend) will do nothing if the
        item is already in the list.
    Adding to the middle of the list (insert, __setitem__)
        will remove previous item with the same value - if any.
"""

class unique_list(list):
    def __init__(self, *args):
        super(unique_list, self).__init__()
        self.attendance = set()
        self.extend(args)
    def __setitem__(self, index, item):
        prev_item = self[index]
        if prev_item != item:
            if item in self.attendance:
                prev_index_for_item = self.index(item)
                super(unique_list, self).__setitem__(index, item)
                del self[prev_index_for_item]
            else:
                super(unique_list, self).__setitem__(index, item)
                self.attendance.add(item)
    def __delitem__(self, index):
        super(unique_list, self).__delitem__(index)
        self.attendance.remove(self[index])
    def __contains__(self, item):
        """ Overriding __contains__ is not required - just more efficient """
        return item in self.attendance
    def append(self, item):
        if item not in self.attendance:
            super(unique_list, self).append(item)
            self.attendance.add(item)
    def extend(self, items = ()):
        for item in items:
            if item not in self.attendance:
                super(unique_list, self).append(item)
                self.attendance.add(item)
    def insert(self, index, item):
        if item in self.attendance:
            prev_index_for_item = self.index(item)
            if index != prev_index_for_item:
                super(unique_list, self).insert(index, item)
                if prev_index_for_item < index:
                    del self[prev_index_for_item]
                else:
                    del self[prev_index_for_item+1]
        else:
            super(unique_list, self).insert(index, item)
            self.attendance.add(item)
    def remove(self, item):
        if item in self.attendance:
            super(unique_list, self).remove(item)
            self.attendance.remove(item)
    def pop(self, index=None):
        if index is None:
            index = len(self.attendance) - 1
        self.attendance.remove(self[index])
        return super(unique_list, self).pop(index)
    def count(self, item):
        """ Overriding count is not required - just more efficient """
        return self.attendance.count(item)

if __name__ == "__main__":
    u = unique_list('a', 'b', 'c','a', 'b', 'c')
    print(u)
    u.insert(2, 'b')
    print(u)
