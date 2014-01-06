#!/usr/bin/env python

"""
    SVNItem represent a single file or folder.
    SVNTopItem is holding SVNItems without itself being part of the tree.
"""
from __future__ import print_function

import re
import copy
from collections import OrderedDict


text_line_re = re.compile(r"""
            ^
            (?P<path>.*)
            ,\s+
            (?P<flags>[dfsx]+)
            ,\s+
            (?P<last_rev>\d+)
            """, re.X)
flags_and_last_rev_re = re.compile(r"""
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

    __slots__ = ("__up", "__name", "__flags", "__last_rev", "__subs", "props", "user_data")
    def __init__(self, in_name, in_flags, in_last_rev):
        """ constructor """

        self.__up = None
        self.__name = in_name
        self.__flags = in_flags
        self.__last_rev = in_last_rev
        self.__subs = None
        if self.isDir():
            self.__subs = dict()
        self.props = None # extra props besides svn:executable, svn:special
        self.user_data = None

    def __str__(self):
        """ __str__ representation - this is what will be written to info_map.txt files"""
        full_path_str = self.full_path()
        retVal = "{}, {}, {}".format(full_path_str, self.__flags, self.__last_rev)
        return retVal

    def __copy__(self):
        """ __copy__ defined to prevent copying that is not deepcopy """
        raise ValueError("Shallow copy not allowed for SVNItem, because children have pointer to parents")

    def __deepcopy__(self, memodict):
        """ implement deepcopy """
        retVal = SVNItem(self.__name, self.__flags, self.__last_rev)
        if self.__subs:
            retVal.subs().update({name: copy.deepcopy(item, memodict) for name, item in self.subs().iteritems()})
            for item in retVal.subs().values():
                item.set_parent(self)
        return retVal

    def __getstate__(self):
        """ for pickling """
        return [[self.__up, self.__name, self.__flags, self.__last_rev], self.__subs]

    def __setstate__(self, state):
        """ for pickling """
        self.__up = state[0][0]
        self.__name = state[0][1]
        self.__flags = state[0][2]
        self.__last_rev = state[0][3]
        self.__subs = state[1]

    def __eq__(self, other):
        """ compare items and it's subs """
        same_name = self.name() == other.name()
        same_flags = self.flags() == other.flags()
        same_last_rev = self.last_rev() == other.last_rev()
        retVal = same_name and same_flags and same_last_rev
        same_subs = None

        both_are_files = self.isFile() and other.isFile()
         # do not bother checking subs if the containing objects are either both files or their members are not the equal
        if retVal and not both_are_files:
            same_subs = self.subs() == other.subs()
            retVal = retVal and same_subs

        return retVal

    def __ne__(self, other):
        """ compare items and it's subs - pythin does not implement the default != by negating
            the defined __eq__, so if defining __eq__, __ne__ must be also defined.
        """
        retVal = not (self == other)
        return retVal

    def name(self):
        """ return the name """
        return self.__name

    def last_rev(self):
        """ return last_rev """
        return self.__last_rev

    def set_last_rev(self, new_last_rev):
        """ update last_rev """
        self.__last_rev = new_last_rev

    def flags(self):
        """ return flags """
        return self.__flags

    def set_flags(self, new_flags):
        """ update last_rev """
        self.__flags = new_flags

    def add_flags(self, flags):
        """ add new flags to last_rev, retaining the previous ones """
        new_flags = "".join(sorted(set(self.__flags+flags)))
        #print("_add_flags:", self.__flags, "+", flags, "=", new_flags)
        self.__flags = new_flags

    def parent(self):
        return self.__up

    def set_parent(self, in_parent):
        if isinstance(in_parent, SVNItem) or in_parent is None:
            self.__up = in_parent
        else:
            raise ValueError("in_parent is not a SVNItem it's "+type(in_parent))

    def full_path_parts(self):
        retVal = None
        if self.__up is None:
            retVal = [self.__name]
        else:
            retVal = self.__up.full_path_parts()
            retVal.append(self.__name)
        return retVal

    def full_path(self):
        retVal = "/".join(self.full_path_parts())
        return retVal

    def subs(self):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory, has no sub items")
        return self.__subs

    def clear_subs(self):
        self.__subs.clear()

    def isFile(self):
        return 'f' in self.__flags

    def isDir(self):
        return 'd' in self.__flags

    def isExecutable(self):
        return 'x' in self.__flags

    def isSymlink(self):
        return 's' in self.__flags

    def get_item_at_path(self, at_path):
        """ return a sub-item at the give at_path or None is any part of the path
            does not exist. at_path is relative to self of course.
            at_path can be a list or tuple containing individual path parts
            or a string with individual path parts separated by "/".
        """
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory, has no sub items")
        else:
            assert isinstance(self.__subs, dict), "self.__subs is not a dictionary"
        path_parts = at_path
        if isinstance(at_path, basestring):
            path_parts = at_path.split("/")
        retVal = self.__subs.get(path_parts[0]) # will return None if not found
        if retVal is not None and len(path_parts) > 1:
            retVal = retVal.get_item_at_path(path_parts[1:])
        return retVal

    def new_item_at_path(self, at_path, flags, last_rev, create_folders=False):
        """ create a new a sub-item at the give at_path.
            at_path is relative to self of course.
            at_path can be a list or tuple containing individual path parts
            or a string with individual path parts separated by "/".
            If create_folders is True, non existing intermediate folders
            will be created, with the same last_rev. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
        """
        retVal = None
        #print("--- add sub to", self.name(), path, flags, last_rev)
        path_parts = at_path
        if isinstance(at_path, basestring):
            path_parts = at_path.split("/")
        if len(path_parts) == 1:
            retVal = SVNItem(path_parts[0], flags, last_rev)
            self.add_sub_item(retVal)
        else:
            sub_dir_item = self.__subs.get(path_parts[0])
            if sub_dir_item is None:
                if create_folders:
                    sub_dir_item = SVNItem(path_parts[0], "d", last_rev)
                    self.add_sub_item(sub_dir_item)
                else:
                    raise KeyError(path_parts[0]+" is not in sub items of "+self.full_path())
            retVal = sub_dir_item.new_item_at_path(path_parts[1:], flags, last_rev, create_folders)
        return retVal

    def add_item_at_path(self, at_path, in_item, create_folders=False):
        """ add an existing sub-item at the give at_path.
            at_path is relative to self of course.
            at_path can be a list or tuple containing individual path parts
            or a string with individual path parts separated by "/".
            If create_folders is True, non existing intermediate folders
            will be created, with the same last_rev. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
        """
        #print("--- add sub to", self.name(), path, flags, last_rev)
        path_parts = at_path
        if isinstance(at_path, basestring):
            path_parts = at_path.split("/")

        if create_folders:
            for i in xrange(0, len(path_parts)):
                folder = self.get_item_at_path(path_parts[0:i])
                if folder is None:
                    self.new_item_at_path(path_parts[0:i], "d", in_item.last_rev())
        folder = self.get_item_at_path(path_parts[0:len(path_parts)])
        folder.add_sub_item(in_item)

    def remove_item_at_path(self, at_path):
        path_parts = at_path
        if isinstance(at_path, basestring):
            path_parts = at_path.split("/")

        if path_parts[0] in self.__subs:
            if len(path_parts) == 1:
                del (self.__subs[path_parts[0]])
            else:
                self.remove_item_at_path(path_parts[1:])

    def new_item_from_str(self, the_str, create_folders=False):
        """ create a new a sub-item from string description.
            If create_folders is True, non existing intermediate folders
            will be created, with the same last_rev. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
        """
        retVal = None
        match = text_line_re.match(the_str)
        if match:
            self.new_item_at_path(match.group('path'),
                                  match.group('flags'),
                                  int(match.group('last_rev')),
                                  create_folders)
        return retVal

    def add_sub_item(self, in_item):
        if not self.isDir():
            raise ValueError(self.name()+" is not a directory")
        if in_item.name() in self.__subs:
            if self.__subs[in_item.name()].flags() != in_item.flags():
                raise KeyError(in_item.name()+" replacing "+self.__subs[in_item.name()].flags()+" with "+in_item.flags())
        in_item.set_parent(self)
        self.__subs[in_item.name()] = in_item

    def sorted_sub_items(self):
        if not self.isDir():
            raise TypeError("Files should not walk themselves, owning dir should do it for them")
        file_list = list()
        dir_list = list()
        for item_name in sorted(self.__subs.keys()):
            item = self.__subs[item_name]
            if item.isFile():
                file_list.append(item)
            elif item.isDir():
                dir_list.append(item)
        return file_list, dir_list

    def walk_items(self, what="all"):
        """  Walk the item list and yield items.
            for each folder the files will be listed alphabetically, than each sub folder
            with it's sub items.
        """
        file_list, dir_list = self.sorted_sub_items()
        yield_files = what in ("f", "file", "a", "all")
        yield_dirs = what in ("d", "dir", "a", "all")

        if yield_files:
            for the_sub in file_list:
                yield the_sub

        for the_sub in dir_list:
            if yield_dirs:
                yield the_sub
            for yielded_from in the_sub.walk_items(what):
                yield yielded_from

    def walk_items_depth_first(self, what="all"):
        """  Walk the item list and yield items.
            for each folder the files will be listed alphabetically, than each sub folder
            with it's sub items.
        """
        file_list, dir_list = self.sorted_sub_items()
        yield_files = what in ("f", "file", "a", "all")
        yield_dirs = what in ("d", "dir", "a", "all")

        for the_sub in dir_list:
            for yielded_from in the_sub.walk_items_depth_first(what):
                yield yielded_from
            if yield_dirs:
                yield the_sub

        if yield_files:
            for the_sub in file_list:
                yield the_sub

    def recursive_remove_depth_first(self, should_remove_func):
        file_list, dir_list = self.sorted_sub_items()

        for the_sub in dir_list:
            the_sub.recursive_remove_depth_first(should_remove_func)
            if should_remove_func(the_sub):
                del (self.__subs[the_sub.name()])

        for the_sub in file_list:
            if should_remove_func(the_sub):
                del (self.__subs[the_sub.name()])

    def set_user_data(self, value, how): # how=[only|file|all]
        self.user_data = value
        if self.isDir() and how in ("file", "all"):
            mark_list, dir_list = self.sorted_sub_items()
            if how == "all":
                mark_list.extend(dir_list)
            for item in mark_list:
                item.set_user_data(value, how)

    def num_subs_in_tree(self, what="all"):
        retVal = sum(1 for i in self.walk_items(what=what))
        return retVal

    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = OrderedDict()
        retVal["_p_"] = " ".join( (self.flags(), str(self.last_rev())) )
        file_list, dir_list = self.sorted_sub_items()
        for a_file_item in file_list:
            retVal[a_file_item.name()] = " ".join( (a_file_item.flags(), str(a_file_item.last_rev())) )
        for a_dir_item in dir_list:
            retVal[a_dir_item.name()] = a_dir_item.repr_for_yaml()
        return retVal

    def read_yaml_node(self, a_node):
        if a_node.isMapping():
            for identifier, contents in a_node:
                if identifier == "_p_": # the properties belong to the folder above and were already read
                    continue
                if contents.isScalar(): # scalar contents means a file
                    match = flags_and_last_rev_re.match(contents.value)
                    if match:
                        self.new_item_at_path(identifier, match.group('flags'), int(match.group('last_rev')))
                    else:
                        raise ValueError("Looks like a file, but is not %s %s" % (identifier, str(contents)))
                elif contents.isMapping():
                    props_node = contents["_p_"]
                    if props_node.isScalar():
                        match = flags_and_last_rev_re.match(props_node.value)
                        if match:
                            new_sub = self.new_item_at_path(identifier, match.group('flags'),
                                                            int(match.group('last_rev')))
                            new_sub.read_yaml_node(contents)
                        else:
                            raise ValueError("Looks like a folder, but is not %s %s" % (identifier, str(contents)))
                    else:
                        raise ValueError("props node is not a scalar for %s %s" % (identifier, str(contents)))
        else:
            raise ValueError("a_node is not a mapping", a_node)

class SVNTopItem(SVNItem):
    """ Represents the top item of the hierarchy. The difference from SVNItem
        is that SVNTopItem does not include itself in the path and so it's name in meaningless
    """
    def __init__(self, in_name="top_of_tree"):
        super(SVNTopItem, self).__init__(in_name, "d", 0)

    def full_path_parts(self):
        """ override full_path_parts so the top level SVNTopItem will
            no be counted as part of the path.
        """
        retVal = list()
        return retVal

    def __deepcopy__(self, memodict):
        retVal = SVNTopItem(self.name())
        retVal.set_last_rev(self.last_rev())
        retVal.set_flags(self.flags())

        retVal.subs().update({name: copy.deepcopy(item, memodict) for name, item in self.subs().iteritems()})
        for item in retVal.subs().values():
            item.set_parent(retVal)
        return retVal

    def __str__(self):
        retVal = "{}, {}, {}".format(self.name(), self.flags(), self.last_rev())
        return retVal

    def min_max_rev(self):
        """ Walk the sub-items and return the minimal and maximal last_rev
            If there are no sub items return 0,0
        """
        min_revision = 0
        max_revision = 0
        if len(self.subs()) > 0:
            min_revision = 4000000000
            for item in self.walk_items():
                min_revision = min(min_revision, item.last_rev())
                max_revision = max(max_revision, item.last_rev())
        return min_revision, max_revision
