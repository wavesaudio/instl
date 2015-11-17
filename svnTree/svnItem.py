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
            (?P<path>.+)
            ,\s+
            (?P<flags>[dfsx]+)
            ,\s+
            (?P<revision>\d+)
            (,\s+
            (?P<checksum>[\da-f]+))?    # 5985e53ba61348d78a067b944f1e57c67f865162
            (,\s+
            (?P<size>[\d]+))?       # 356985
            (,\s+
            (?P<url>(http(s)?|ftp)://.+))?    # http://....
            """, re.X)
flags_and_revision_re = re.compile(r"""
                ^
                \s*
                (?P<flags>[fdxs]+)
                \s*
                (?P<revision>\d+)
                (\s*
                (?P<checksum>[\da-f]+))? # 5985e53ba61348d78a067b944f1e57c67f865162
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

    __slots__ = ("__up", "__name", "__flags", "__revision", "__subs", "__checksum", "__url", "__size", "props", "user_data")

    def __init__(self, item_details):
        """ constructor accepts a dict formatted as:
            {name: 'xyz', flags: 'fx', revision: 47, checksum: 7d3859aea37f731db0261548d8eb8bb77dbbe131, url: http://.., size: 369874}
            name, flags, revision are mandatory for all items
            checksum is mandatory for file items
            url, size are optional for files items
        """
        self.__up = None
        self.__name = item_details['name']
        self.__flags = item_details['flags']
        self.__revision = int(item_details['revision'])

        self.__checksum = item_details.get('checksum')
        self.__url = item_details.get('url')
        self.__size = int(item_details.get('size', -1))

        self.__subs = None
        if self.isDir():
            self.__subs = dict()

        self.props = None # extra props besides svn:executable, svn:special
        self.user_data = None

    def __str__(self):
        """ __str__ representation - this is what will be written to info_map.txt files"""
        full_path_str = self.full_path()
        retVal = "{}, {}, {}".format(full_path_str, self.__flags, self.__revision)
        if self.__checksum:
            retVal = "{}, {}".format(retVal, self.__checksum)
        if self.__size != -1:
            retVal = "{}, {}".format(retVal, self.__size)
        if self.__url:
            retVal = "{}, {}".format(retVal, self.__url)
        return retVal

    def __copy__(self):
        """ __copy__ defined to prevent copying that is not deepcopy """
        raise ValueError("Shallow copy not allowed for SVNItem, because children have pointer to parents")

    def __deepcopy__(self, memodict):
        """ implement deepcopy """
        retVal = SVNItem({'name': self.__name,
                          'flags': self.__flags,
                          'revision': self.__revision,
                          'checksum': self.__checksum,
                          'url': self.__url,
                          'size': self.__size})
        if self.__subs:
            retVal.subs.update({name: copy.deepcopy(item, memodict) for name, item in self.subs.iteritems()})
            for item in retVal.subs.values():
                item.parent = self
        return retVal

    def __getstate__(self):
        """ for pickling """
        return [[self.__up, self.__name, self.__flags, self.__revision, self.__checksum, self.__url, self.__size], self.__subs]

    def __setstate__(self, state):
        """ for pickling """
        self.__up = state[0][0]
        self.__name = state[0][1]
        self.__flags = state[0][2]
        self.__revision = state[0][3]
        self.__checksum = state[0][4]
        self.__url = state[0][5]
        if len(state[0]) > 6:
            self.__size = state[0][6]
        self.__subs = state[1]

    def __ne__(self, other):
        """ compare items and it's subs - python does not implement the default != by negating
            the defined __eq__, so if defining __eq__, __ne__ must be also defined.
        """
        retVal = not (self == other)
        return retVal

    @property
    def name(self):
        """ return the name """
        return self.__name

    @property
    def revision(self):
        """ return revision """
        return self.__revision

    @revision.setter
    def revision(self, new_revision):
        """ update revision """
        self.__revision = int(new_revision)

    @property
    def highest_revision(self):
        """ get the highest revision for this items or sub items """
        retVal = self.__revision
        if self.isDir():
            retVal = reduce (max (an_item.__revision for an_item in self.walk_items()), retVal)
        return retVal

    @property
    def checksum(self):
        """ return checksum """
        return self.__checksum

    @checksum.setter
    def checksum(self, new_checksum):
        """ update checksum """
        self.__checksum = new_checksum

    @property
    def flags(self):
        """ return flags """
        return self.__flags

    @flags.setter
    def flags(self, new_flags):
        """ update flags """
        self.__flags = "".join(sorted(set(new_flags)))

    @property
    def url(self):
        """ return url """
        return self.__url

    @url.setter
    def url(self, new_url):
        """ update url """
        self.__url = new_url

    @property
    def parent(self):
        return self.__up

    @parent.setter
    def parent(self, in_parent):
        self.__up = in_parent

    @property
    def size(self):
        """ for a file: return file size
            for a dir: calculate sub items size recursively
        """
        retVal = 0
        if self.isFile():
            if self.__size == -1:
                raise ValueError(self.full_path()+" has no size assigned")
            retVal = self.__size
        else:
            for item in self.__subs.itervalues():
                retVal += item.size
        return retVal

    @size.setter
    def size(self, new_size):
        """ update new_size """
        if self.isDir():
            raise ValueError(self.name+" is a directory, cannot set it's size")
        self.__size = int(new_size)

    @property
    def safe_size(self):
        """calculate sub items size recursively return -1 if size is not available for any sub-item
        """
        try:
            return self.size
        except ValueError:
            return -1

    def __eq__(self, other):
        """ compare items and it's subs """
        retVal = (self.name == other.name
                and self.flags == other.flags
                and self.revision == other.revision)
        if retVal:
            if self.isFile():
                retVal = (self.checksum == other.checksum
                            and self.url == other.url
                            and self.safe_size == other.safe_size)
            else:
                retVal = self.subs == other.subs

        return retVal

    def full_path_parts(self):
        retVal = list()
        curr_item = self
        while curr_item is not None:
            if curr_item.__name != "top_of_tree": # avoid the name of the top item
                retVal.append(curr_item.__name)
            curr_item = curr_item.__up
        retVal.reverse()
        return retVal

    def full_path_parts_recursive(self):
        if self.__up is None:
            retVal = [self.__name]
        else:
            retVal = self.__up.full_path_parts_recursive()
            retVal.append(self.__name)
        return retVal

    def full_path(self):
        retVal = "/".join(self.full_path_parts())
        return retVal

    @property
    def subs(self):
        if not self.isDir():
            raise ValueError(self.name+" is not a directory and should not be asked for sub items")
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
            raise ValueError(self.name+" is not a directory, has no sub items")
        else:
            assert isinstance(self.__subs, dict), "self.__subs is not a dictionary"
        path_parts = at_path
        if isinstance(at_path, basestring):
            path_parts = at_path.split("/")
        retVal = self.__subs.get(path_parts[0]) # will return None if not found
        if retVal is not None and len(path_parts) > 1:
            retVal = retVal.get_item_at_path(path_parts[1:])
        return retVal

    def new_item_at_path(self, in_at_path, item_details, create_folders=False):
        """ create a new a sub-item at the give in_at_path.
            in_at_path is relative to self of course.
            in_at_path can be a list or tuple containing individual path parts
            or a string with individual path parts separated by "/".
            If create_folders is True, non existing intermediate folders
            will be created, with the same in_revision. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
            This is the non recursive version of this function.

            item_details is a dict formatted as:
            {flags: 'fx', revision: 47, checksum: 7d3859aea37f731db0261548d8eb8bb77dbbe131, url: http://.., size: 369874}
            flags, revision are mandatory for all items
            checksum is mandatory for file items
            url, size are optional for files items, not relevant for dir items
        """
        #print("--- add sub to", self.name, path, in_flags, in_revision)
        path_parts = in_at_path
        if isinstance(in_at_path, basestring):
            path_parts = in_at_path.split("/")
        curr_item = self
        for part in path_parts[:-1]:
            sub_dir_item = curr_item.__subs.get(part)
            if sub_dir_item is None:
                if create_folders:
                    sub_dir_item = SVNItem({'name': part, 'flags': "d", 'revision': item_details['revision']})
                    curr_item.add_sub_item(sub_dir_item)
                else:
                    raise KeyError(part+" is not in sub items of "+self.full_path())
            curr_item = sub_dir_item
        new_details = dict(item_details)
        new_details['name'] = path_parts[-1]
        retVal = SVNItem(new_details)
        curr_item.add_sub_item(retVal)
        return retVal

    def add_item_at_path(self, at_path, in_item, create_folders=False):
        """ add an existing sub-item at the give at_path.
            at_path is relative to self of course.
            at_path can be a list or tuple containing individual path parts
            or a string with individual path parts separated by "/".
            If create_folders is True, non existing intermediate folders
            will be created, with the same revision. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
        """
        #print("--- add sub to", self.name, path, flags, revision)
        path_parts = at_path
        if isinstance(at_path, basestring):
            path_parts = at_path.split("/")

        if create_folders:
            for i in xrange(0, len(path_parts)):
                folder = self.get_item_at_path(path_parts[0:i])
                if folder is None:
                    self.new_item_at_path(path_parts[0:i], {'flags': "d", 'revision': in_item.revision})
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

    def new_item_from_str_re(self, the_str, create_folders=False):
        """ create a new a sub-item from string description.
            If create_folders is True, non existing intermediate folders
            will be created, with the same revision. create_folders is False,
            and some part of the path does not exist KeyError will be raised.
            This is the regular expression version.
        """
        retVal = None
        match = text_line_re.match(the_str.strip())
        if match:
            item_details = {'flags': match.group('flags'),
                            'revision': match.group('revision')}
            if match.group('checksum') is not None:
                item_details['checksum'] = match.group('checksum')
            if match.group('url') is not None:
                item_details['url'] = match.group('url')
            if match.group('size') is not None:
                item_details['size'] = match.group('size')
            self.new_item_at_path(match.group('path'),
                                   item_details,
                                   create_folders)
        return retVal

    def add_sub_item(self, in_item):
        #if not self.isDir():
        #    raise ValueError(self.name+" is not a directory")
        #if in_item.name in self.__subs:
        #    if self.__subs[in_item.name].flags != in_item.flags:
        #        raise KeyError(in_item.name+" replacing "+self.__subs[in_item.name].flags+" with "+in_item.flags)
        in_item.parent = self
        self.__subs[in_item.name] = in_item

    def sorted_sub_items(self):
        if not self.isDir():
            raise TypeError("Files should not walk themselves, owning dir should do it for them")
        file_list = list()
        dir_list = list()
        for item_name in sorted(self.__subs.keys()):
            item = self.__subs[item_name]
            if item.isFile():
                file_list.append(item)
            else:
                dir_list.append(item)
        return file_list, dir_list

    def unsorted_sub_items(self):
        if not self.isDir():
            raise TypeError("Files should not walk themselves, owning dir should do it for them")
        file_list = list()
        dir_list = list()
        for item in self.__subs.itervalues():
            if item.isFile():
                file_list.append(item)
            else:
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

    def walk_file_items_with_filter(self, a_filter):
        """  Walk the item list and yield items.
            for each folder the files will be listed alphabetically, than each sub folder
            with it's sub items.
        """
        file_list, dir_list = self.sorted_sub_items()

        for the_sub in file_list:
            if a_filter(the_sub):
                yield the_sub
            else:
                continue

        for the_sub in dir_list:
            for yielded_from in the_sub.walk_file_items_with_filter(a_filter):
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
        file_list, dir_list = self.unsorted_sub_items()

        for the_sub in dir_list:
            the_sub.recursive_remove_depth_first(should_remove_func)
            if should_remove_func(the_sub):
                del (self.__subs[the_sub.name])

        for the_sub in file_list:
            if should_remove_func(the_sub):
                del (self.__subs[the_sub.name])

    def set_user_data_non_recursive(self, value):
        self.user_data = value

    def set_user_data_files_recursive(self, value):
        if self.isFile():
            self.user_data = value
        else:
            files_list, dir_list = self.unsorted_sub_items()
            for file_item in files_list:
                file_item.user_data = value
            for dir_item in dir_list:
                dir_item.set_user_data_files_recursive(value)

    def set_user_data_all_recursive(self, value):
        self.user_data = value
        files_list, dir_list = self.unsorted_sub_items()
        for file_item in files_list:
            file_item.user_data = value
        for dir_item in dir_list:
            dir_item.set_user_data_all_recursive(value)


    def num_subs_in_tree(self, what="all", predicate=lambda in_item: True ):
        retVal = sum(1 for item in self.walk_items(what=what) if predicate(item))
        return retVal

    def repr_for_yaml(self):
        """         writeAsYaml(svni1, out_stream=sys.stdout, indentor=None, sort=True)         """
        retVal = OrderedDict()
        retVal["_p_"] = " ".join( (self.flags, str(self.revision)) )
        file_list, dir_list = self.sorted_sub_items()
        for a_file_item in file_list:
            retVal[a_file_item.name] = " ".join( (a_file_item.flags, str(a_file_item.revision), a_file_item.checksum))
        for a_dir_item in dir_list:
            retVal[a_dir_item.name] = a_dir_item.repr_for_yaml()
        return retVal

    def read_yaml_node(self, a_node):
        if a_node.isMapping():
            for identifier, contents in a_node:
                if identifier == "_p_": # the properties belong to the folder above and were already read
                    continue
                if contents.isScalar(): # scalar contents means a file
                    match = flags_and_revision_re.match(contents.value)
                    if match:
                        self.new_item_at_path(identifier,
                                                {'flags': match.group('flags'),
                                                'revision': match.group('revision'),
                                                'checksum': match.group('checksum')})
                    else:
                        raise ValueError("Looks like a file, but is not %s %s" % (identifier, str(contents)))
                elif contents.isMapping():
                    props_node = contents["_p_"]
                    if props_node.isScalar():
                        match = flags_and_revision_re.match(props_node.value)
                        if match:
                            new_sub = self.new_item_at_path(identifier,
                                                             {'flags': match.group('flags'),
                                                             'revision': match.group('revision')})
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
        super(SVNTopItem, self).__init__({'name': in_name, 'flags': "d", 'revision': 0})

    def full_path_parts_recursive(self):
        """ override full_path_parts so the top level SVNTopItem will
            no be counted as part of the path.
        """
        retVal = list()
        return retVal

    def __deepcopy__(self, memodict):
        retVal = SVNTopItem(self.name)
        retVal.revision = self.revision
        retVal.flags = self.flags

        retVal.subs.update({name: copy.deepcopy(item, memodict) for name, item in self.subs.iteritems()})
        for item in retVal.subs.values():
            item.parent = retVal
        return retVal

    def __str__(self):
        retVal = "{}, {}, {}".format(self.name, self.flags, self.revision)
        return retVal

    def min_max_rev(self):
        """ Walk the sub-items and return the minimal and maximal revision
            If there are no sub items return 0,0
        """
        min_revision = 0
        max_revision = 0
        if len(self.subs) > 0:
            min_revision = 4000000000
            for item in self.walk_items():
                min_revision = min(min_revision, item.revision)
                max_revision = max(max_revision, item.revision)
        return min_revision, max_revision

