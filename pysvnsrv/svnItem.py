#!/usr/bin/env python
from __future__ import print_function

import re
from collections import namedtuple, OrderedDict

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

class SVNItem(object):
    """ represents a single svn item, either file or directory with the item's
        flags and last changed revision. Only the item's name is kept not
        the whole path. Directory items have a dictionary of sub items.
        
        flags can be either f (file) or d (directory)
        and zero or more of the following:
        x - executable bit
        s - symlink
    """
    __slots__ = ("__name", "__flags", "__last_rev", "__subs")
    def __init__(self, in_name, in_flags, in_last_rev):
        self.__name = in_name
        self.__flags = in_flags
        self.__last_rev = in_last_rev
        self.__subs = None
        if self.isDir():
            self.__subs = dict()

    def __str__(self):
        retVal = "{self._SVNItem__name}: {self._SVNItem__flags} {self._SVNItem__last_rev}".format(**locals())
        return retVal
    
    def __getstate__(self):
        return ((self.__name, self.__flags, self.__last_rev), self.__subs)
    
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
        
    def name(self):
        return self.__name
    
    def last_rev(self):
        return self.__last_rev
    
    def flags(self):
        return self.__flags
        
    def isFile(self):
        return 'f' in self.__flags
        
    def isDir(self):
        return 'd' in self.__flags
        
    def isExecutable(self):
        return 'x' in self.__flags
        
    def isSymlink(self):
        return 's' in self.__flags
    
    def sub_names(self):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory, has no sub items")
        else:
            assert isinstance(self.__subs, dict), "self.__subs is not a directory"
        return sorted(self.__subs.keys())
        
    def get_sub(self, path):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory, has no sub items")
        else:
            assert isinstance(self.__subs, dict), "self.__subs is not a directory"
        path_parts = path.split("/")
        retVal = self.__subs.get(path_parts[0]) # will return None if not found
        if retVal and len(path_parts) > 1:
            retval = retVal.get_sub("/".join(path_parts[1:]))
        return retVal
         
    def add_sub(self, path, flags, last_rev):
        retVal = None
        #print("--- add sub to", self.name(), path, flags, last_rev)
        path_parts = path.split("/")
        if len(path_parts) == 1:
            retVal = SVNItem(path_parts[0], flags, last_rev)
            self._add_sub_item(retVal)
        else:
            if path_parts[0] not in self.__subs.keys():
                raise KeyError(path_parts[0]+" is not in sub items")
            retVal = self.get_sub(path_parts[0]).add_sub("/".join(path_parts[1:]), flags, last_rev)
        return retVal
            
    def clear_subs(self):
        self.__subs.clear()
    
    def _add_sub_item(self, in_item):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory")
        if in_item.name() in self.__subs:
            raise KeyError(in_item.name()+" is already in sub items")
        self.__subs[in_item.name()] = in_item
    
    def _add_flags(self, flags):
         new_flags = "".join(sorted(set(self.__flags+flags)))
         print("_add_flags:", self.__flags, "+", flags, "=", new_flags)
         self.__flags = new_flags
         
    def add_flags(self, path, flags):
        retVal = None
        print("--- add flags to", self.name(), path, flags)
        path_parts = path.split("/")
        if len(path_parts) == 1:
            self.__subs[path_parts[0]]._add_flags(flags)
        else:
            print(self.name(), self.__subs.keys())
            if path_parts[0] not in self.__subs.keys():
                raise KeyError(path_parts[0]+" is not in sub items")
            retVal = self.get_sub(path_parts[0]).add_flags("/".join(path_parts[1:]), flags)
        return retVal
    
    def walk_items(self, path_so_far=None, what="all"):
        """  Walk the item list and yield items in the SVNItemFlat format:
            (path, flags, last_rev). path is the full know path (up to the top
            item in the tree where walk_items was called).
        """
        if path_so_far is None:
            path_so_far = list()
        yield_files = what in ("f", "file", "a", "all")
        yield_dirs = what in ("d", "dir", "a", "all")
        
        if not self.isDir():
            raise TypeError("Files should not walk themselfs, ownning dir should do it for them")
        
        for sub_name in self.sub_names():
            the_sub = self.get_sub(sub_name)
            if the_sub.isFile() and yield_files:
                path_so_far.append(the_sub.name())
                yield ("/".join( path_so_far ) , the_sub.flags(), the_sub.last_rev())
                path_so_far.pop()
            if the_sub.isDir():
                path_so_far.append(the_sub.name())
                if yield_dirs:
                    yield ("/".join( path_so_far ) , the_sub.flags(), the_sub.last_rev())
                for yielded_from in the_sub.walk_items(path_so_far, what):
                    yield yielded_from
                path_so_far.pop()
    
    def num_subs(self, what="all"):
        retVal = sum(1 for i in self.walk_items(what="all"))
        return retVal

    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = OrderedDict()
        retVal["_p_"] = " ".join( (self.flags(), str(self.last_rev())) ) 
        for sub_name in sorted(self.sub_names()):
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
                    

