#!/usr/bin/env python
from __future__ import print_function

import re
from collections import namedtuple, OrderedDict, MutableMapping
import copy

from aYaml import augmentedYaml

SVNItemFlat = namedtuple('SVNItemFlat', ["path", "flags", "last_rev"])

flags_and_last_rev_re = re.compile("""
                ^
                \s*
                (?P<flags>[fdxs]+)
                \s*
                (?P<last_rev>\d+)
                $
                """, re.X)

class SVNItem(MutableMapping):
    """ represents a single svn item, either file or directory with the item's
        flags and last changed revision. Only the item's name is kept not
        the whole path. Directory items have a dictionary of sub items.
        
        flags can be either f (file) or d (directory)
        and zero or more of the following:
        x - executable bit
        s - symlink
    """
    __slots__ = ("__name", "__flags", "__last_rev", "__subs", "__parent", "user_data")
    def __init__(self, in_name, in_flags, in_last_rev):
        self.__name = in_name
        self.__flags = in_flags
        self.__last_rev = in_last_rev
        self.__parent = None
        self.__subs = None
        if self.isDir():
            self.__subs = dict()
        self.user_data = None

    def __str__(self):
        retVal = "{self._SVNItem__name}: {self._SVNItem__flags} {self._SVNItem__last_rev}".format(**locals())
        return retVal

    def as_tuple(self):
        return ("/".join(self.full_path()), self.__flags, self.__last_rev)

    def text_line(self):
        retVal = "{}, {}, {}".format("/".join(self.full_path()), self.flags(), str(self.last_rev()))
        return retVal

    def __getstate__(self):
        return ((self.__name, self.__flags, self.__last_rev, self.__parent), self.__subs)

    def __len__(self):
        return len(self.__subs)

    def __setitem__(self, key, val):
        self.__subs[key] = val

    def __delitem__(self, key):
        del(self.__subs[key])

    def __getitem__(self, key):
        return self.__subs[key]

    def __iter__(self):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory, has no sub items")
        else:
            assert isinstance(self.__subs, dict), "self.__subs is not a directory"
        return iter(self.__subs)

    def __setstate__(self, state):
        self.__name = state[0][0]
        self.__flags = state[0][1]
        self.__last_rev = state[0][2]
        self.__subs = state[1]

    def copy_from(self, another_SVNItem):
        self.__name = another_SVNItem.name()
        self.__flags = another_SVNItem.flags()
        self.__last_rev = another_SVNItem.last_rev()
        self.__subs = another_SVNItem.__subs

    def __copy__(self):
        raise ValueError("Shallow copy not allowed for SVNItem, becaue children have pointer to parents")

    def __deepcopy__(self, memodict):
        retVal = SVNItem(self.__name, self.__flags, self.__last_rev)
        if self.__subs:
            retVal.__subs = {name: copy.deepcopy(item, memodict) for name, item in self.iteritems()}
            for item in self.__subs.values():
                item.set_parent(self)
        return retVal

    def __eq__(self, other):
        retVal = (self.__name == other.name() and
                    self.__flags == other.flags() and
                    self.__last_rev == other.last_rev() and
                    self.__subs == other.subs())
        return retVal

    def name(self):
        return self.__name
    
    def last_rev(self):
        return self.__last_rev

    def set_last_rev(self, new_last_rev):
        self.__last_rev = new_last_rev

    def flags(self):
        return self.__flags

    def set_flags(self, new_flags):
        self.__flags = new_flags

    def parent(self):
        return self.__parent

    def set_parent(self, in_parent):
        self.__parent = in_parent

    def full_path(self):
        if self.parent() is None:
            retVal = list()
        else:
            retVal = self.__parent.full_path()
            retVal.append(self.__name)
        return retVal

    def subs(self):
        return self.__subs

    def isFile(self):
        return 'f' in self.__flags
        
    def isDir(self):
        return 'd' in self.__flags
        
    def isExecutable(self):
        return 'x' in self.__flags
        
    def isSymlink(self):
        return 's' in self.__flags

    def get_sub(self, path):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory, has no sub items")
        else:
            assert isinstance(self.__subs, dict), "self.__subs is not a directory"
        path_parts = path
        if isinstance(path, basestring):
            path_parts = path.split("/")
        retVal = self.__subs.get(path_parts[0]) # will return None if not found
        if retVal is not None and len(path_parts) > 1:
            retVal = retVal.get_sub(path_parts[1:])
        return retVal
         
    def add_sub(self, path, flags, last_rev):
        retVal = None
        #print("--- add sub to", self.name(), path, flags, last_rev)
        path_parts = path
        if isinstance(path, basestring):
            path_parts = path.split("/")
        if len(path_parts) == 1:
            retVal = SVNItem(path_parts[0], flags, last_rev)
            self._add_sub_item(retVal)
        else:
            if path_parts[0] not in self.__subs.keys():
                raise KeyError(path_parts[0]+" is not in sub items")
            retVal = self.get_sub(path_parts[0]).add_sub(path_parts[1:], flags, last_rev)
        return retVal

    def add_sub_recursive(self, path, flags, last_rev):
        retVal = None
        #print("--- add sub to", self.name(), path, flags, last_rev)
        path_parts = path
        if isinstance(path, basestring):
            path_parts = path.split("/")
        if len(path_parts) == 1:
            retVal = self.add_sub(path_parts[0], flags, last_rev)
        else:
            the_new_sub = self.add_sub(path_parts[0], "d", last_rev)
            retVal = the_new_sub.add_sub_recursive(path_parts[1:], flags, last_rev)
        return retVal

    def add_sub_tree(self, path, sub_tree):
        where = self.get_sub(path)
        if not where:
            raise KeyError("/".join(path)+" is not in tree")
        where._add_sub_item(sub_tree)
    
    def add_sub_tree_recursive(self, path, sub_tree):
        #print("--- add sub to", self.name(), path, flags, last_rev)
        path_parts = path
        if isinstance(path, basestring):
            path_parts = path.split("/")
        where_to_add = self
        for part in path_parts:
            level_down = where_to_add.get_sub(part)
            if level_down is None:
                level_down = where_to_add.add_sub(part, "d", sub_tree.last_rev())
            where_to_add = level_down
        where_to_add._add_sub_item(sub_tree)

    def add_sub_list(self, list_of_tuples):
        for a_tuple in list_of_tuples:
            self.add_sub(*a_tuple)
            
    def clear_subs(self):
        self.__subs.clear()
    
    def _add_sub_item(self, in_item):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory")
        if in_item.name() in self.__subs:
            if self.__subs[in_item.name()].flags() != in_item.flags():
                raise KeyError(in_item.name()+" replacing "+self.__subs[in_item.name()].flags()+" with "+in_item.flags())
        in_item.set_parent(self)
        self.__subs[in_item.name()] = in_item
    
    def _add_flags(self, flags):
         new_flags = "".join(sorted(set(self.__flags+flags)))
         #print("_add_flags:", self.__flags, "+", flags, "=", new_flags)
         self.__flags = new_flags
         
    def add_flags(self, path, flags):
        retVal = None
        #print("--- add flags to", self.name(), path, flags)
        path_parts = path.split("/")
        if len(path_parts) == 1:
            self.__subs[path_parts[0]]._add_flags(flags)
        else:
            #print(self.name(), self.__subs.keys())
            if path_parts[0] not in self.__subs.keys():
                raise KeyError(path_parts[0]+" is not in sub items")
            retVal = self.get_sub(path_parts[0]).add_flags("/".join(path_parts[1:]), flags)
        return retVal

    def walk_items(self, what="all"):
        """  Walk the item list and yield items in the SVNItemFlat format:
            (path, flags, last_rev). path is the full known path (up to the top
            item in the tree where walk_items was called).
            for each folder the files will be listed alphabetically, than each sub folder
            with it's sub items.
        """
        yield_files = what in ("f", "file", "a", "all")
        yield_dirs = what in ("d", "dir", "a", "all")
        
        if not self.isDir():
            raise TypeError("Files should not walk themselves, owning dir should do it for them")

        sorted_keys = sorted(self.keys())
        file_list = [self.get_sub(sub_name) for sub_name in sorted_keys if self[sub_name].isFile()]
        dir_list = [self.get_sub(sub_name) for sub_name in sorted_keys if self[sub_name].isDir()]

        if yield_files:
            for the_sub in file_list:
                yield the_sub

        for the_sub in dir_list:
            if yield_dirs:
                yield the_sub
            for yielded_from in the_sub.walk_items(what):
                yield yielded_from

    def recursive_remove_depth_first(self, should_remove_func):
        sorted_keys = sorted(self.keys())
        dir_list = [self.get_sub(sub_name) for sub_name in sorted_keys if self[sub_name].isDir()]
        file_list = [self.get_sub(sub_name) for sub_name in sorted_keys if self[sub_name].isFile()]

        for the_sub in dir_list:
            the_sub.recursive_remove_depth_first(should_remove_func)
            if should_remove_func(the_sub):
                del (self[the_sub.name()])

        for the_sub in file_list:
            if should_remove_func(the_sub):
                del (self[the_sub.name()])

    def num_subs(self, what="all"):
        retVal = sum(1 for i in self.walk_items(what=what))
        return retVal

    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = OrderedDict()
        retVal["_p_"] = " ".join( (self.flags(), str(self.last_rev())) ) 
        for sub_name in sorted(self.__subs.keys()):
            the_sub = self.get_sub(sub_name)
            if the_sub.isFile():
                retVal[the_sub.name()] = " ".join( (the_sub.flags(), str(the_sub.last_rev())) )
            else:
                retVal[the_sub.name()] = the_sub.repr_for_yaml()
        return retVal

    def read_yaml_node(self, a_node):
        if a_node.isMapping():
            for identifier, contents in a_node:
                if identifier == "_p_": # the propertied belog to the folder above and were already read
                    continue
                if contents.isScalar(): # scalar contents means a file
                    match = flags_and_last_rev_re.match(contents.value)
                    if match:
                        self.add_sub(identifier, match.group('flags'), int(match.group('last_rev')))
                    else:
                        raise ValueError("Looks like a file, but is not %s %s" % (identifier, str(contents)))
                elif contents.isMapping():
                    props_node = contents["_p_"]
                    if props_node.isScalar():
                        match = flags_and_last_rev_re.match(props_node.value)
                        if match:
                            new_sub = self.add_sub(identifier, match.group('flags'), int(match.group('last_rev')))
                            new_sub.read_yaml_node(contents)
                        else:
                            raise ValueError("Looks like a folder, but is not %s %s" % (identifier, str(contents)))
                    else:
                        raise ValueError("props node is not a scalar for %s %s" % (identifier, str(contents)))
        else:
            ValueError("a_node is not a mapping", a_node)
                    

