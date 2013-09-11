#!/usr/bin/env python
from __future__ import print_function

from collections import namedtuple

SVNItemFlat = namedtuple('SVNItemFlat', ["path", "flags", "last_rev"])

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
         
     # functions have over descriptive names and over lapping functionality
     # until I realize what is the proper usage.

    def add_sub(self, path, flags, last_rev):
        path_parts = path.split("/")
        if len(path_parts) == 1:
            new_item = SVNItem(path_parts[0], flags, last_rev)
            self._add_sub_item(new_item)
        else:
            if path_parts[0] not in self.__subs.keys():
                raise KeyError(path_parts[0]+" is not in sub items")
            self.get_sub(path_parts[0]).add_sub("/".join(path_parts[1:]), flags, last_rev)
            
    def _add_sub_item(self, in_item):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory")
        if in_item.name() in self.__subs:
            raise KeyError(in_item.name()+" is already in sub items")
        self.__subs[in_item.name()] = in_item

    def walk_items(self, path_so_far=None, what="all"):
        """  Walk the item list and yield items in the SVNItemFlat format:
            (path, flags, last_rev). path is the full know path (up to the top
            item in the tree where walk_items was called).
        """
        if path_so_far is None:
            path_so_far = list()
        
        if self.isDir():
            # sub-files first
            if what in ("f", "file", "a", "all"):
                for sub_name in self.sub_names():
                    if self.__subs[sub_name].isFile():
                        path_so_far.append(self.__subs[sub_name].name())
                        yield ("/".join( path_so_far ) , self.__subs[sub_name].flags(), self.__subs[sub_name].last_rev())
                        path_so_far.pop()
            # sub-directories second
            for sub_name in self.sub_names():
                if self.__subs[sub_name].isDir():
                    path_so_far.append(self.__subs[sub_name].name())
                    if what in ("d", "dir", "a", "all"):
                        yield ("/".join( path_so_far ) , self.__subs[sub_name].flags(), self.__subs[sub_name].last_rev())
                    for yielded_from in self.__subs[sub_name].walk_items(path_so_far, what):
                        yield yielded_from
                    path_so_far.pop()
        else:
            raise TypeError("Files should not walk themselfs, ownning dir should do it for them")

    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = dict()
        for sub_name in sorted(self.sub_names()):
            if self.__subs[sub_name].isFile():
                retVal[self.__subs[sub_name].name()] = " ".join( (self.__subs[sub_name].flags(), str(self.__subs[sub_name].last_rev())) )
            else:
                retVal[self.__subs[sub_name].name()] = self.__subs[sub_name].repr_for_yaml()
                retVal[self.__subs[sub_name].name()]["__props__"] = " ".join( (self.__subs[sub_name].flags(), str(self.__subs[sub_name].last_rev())) )
        return retVal
