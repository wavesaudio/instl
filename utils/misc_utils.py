#!/usr/bin/env python3.9


import sys
import os
import platform
import re
import hashlib
import base64
import collections
import subprocess
import numbers
import stat
from pathlib import Path, PurePath
from timeit import default_timer
from decimal import Decimal
import logging
from functools import reduce, wraps, lru_cache
import itertools
import tarfile
import types
import asyncio
import json
import appdirs
import time
from contextlib import contextmanager

from typing import Any, Dict, List, Set, Tuple

import utils

log = logging.getLogger()
doing_stack = []


@lru_cache(maxsize=None)
def Is64Windows():
    """Check if the installed version of Windows is 64 bit that is supported for both 32 and 64 apps"""
    return 'PROGRAMFILES(X86)' in os.environ


@lru_cache(maxsize=None)
def Is64Mac():
    """Check if the installed version of osx is greater than 14 (Mojave).
    such versions cannot run anymore 32 bit apps """
    return int(platform.mac_ver()[0].split('.')[1]) > 14


@lru_cache(maxsize=None)
def Is32Windows():
    return not Is64Windows()


@lru_cache(maxsize=None)
def GetProgramFiles32():
    if Is64Windows():
        return os.environ['PROGRAMFILES(X86)']
    else:
        return os.environ['PROGRAMFILES']


@lru_cache(maxsize=None)
def GetProgramFiles64():
    if Is64Windows():
        return os.environ['PROGRAMW6432']
    else:
        return None


@lru_cache(maxsize=None)
def get_current_os_names() -> Tuple[str, ...]:
    retVal: Tuple[str, ...] = ()
    current_os = platform.system()
    if current_os == 'Darwin':
        if Is64Mac():
            retVal = ('Mac', 'Mac64')
        else:
            retVal = ('Mac', 'Mac32')
    elif current_os == 'Windows':
        if Is64Windows():
            retVal = ('Win', 'Win64')
        else:
            retVal = ('Win', 'Win32')
    elif current_os == 'Linux':
        retVal = ('Linux',)
    return retVal


class write_to_list(object):
    """ list that behaves like a file. For each call to write
        another item is added to the list.
    """

    def __init__(self) -> None:
        self.the_list: List = list()

    def write(self, text: Any):
        self.the_list.append(text)

    def list(self) -> List:
        return self.the_list


class unique_list(list):
    """
    unique_list implements a list where all items are unique.
    Functionality can also be described as set with order.
    unique_list should behave as a python list except:
        - Adding items the end of the list (by append, extend) will do nothing if the
            item is already in the list.
        - Adding to the middle of the list (insert, __setitem__)
            will remove previous item with the same value - if any.
    """
    __slots__ = ('__attendance',)

    def __init__(self, initial_list=()) -> None:
        super().__init__()
        self.__attendance: Set = set()
        self.extend(initial_list)

    def __setitem__(self, index, item):
        prev_item = self[index]
        if prev_item != item:
            if item in self.__attendance:
                prev_index_for_item = self.index(item)
                super().__setitem__(index, item)
                del self[prev_index_for_item]
                self.__attendance.add(item)
            else:
                super().__setitem__(index, item)
                self.__attendance.remove(prev_item)
                self.__attendance.add(item)

    def __delitem__(self, index):
        super().__delitem__(index)
        self.__attendance.remove(self[index])

    def __contains__(self, item):
        """ Overriding __contains__ is not required - just more efficient """
        return item in self.__attendance

    def append(self, item):
        if item not in self.__attendance:
            super().append(item)
            self.__attendance.add(item)

    def extend(self, items=()):
        for item in items:
            if item not in self.__attendance:
                super().append(item)
                self.__attendance.add(item)

    def insert(self, index, item):
        if item in self.__attendance:
            prev_index_for_item = self.index(item)
            if index != prev_index_for_item:
                super().insert(index, item)
                if prev_index_for_item < index:
                    super().__delitem__(prev_index_for_item)
                else:
                    super().__delitem__(prev_index_for_item + 1)
        else:
            super().insert(index, item)
            self.__attendance.add(item)

    def remove(self, item):
        if item in self.__attendance:
            super().remove(item)
            self.__attendance.remove(item)

    def pop(self, index=-1):
        self.__attendance.remove(self[index])
        return super().pop(index)

    def count(self, item):
        """ Overriding count is not required - just more efficient """
        return 1 if item in self.__attendance else 0

    def sort(self, key=None, reverse=False):
        """ Sometimes sort is needed after all ... """
        super().sort(key=key, reverse=reverse)

    def empty(self):
        return len(self.__attendance) == 0

    def clear(self):
        super().clear()
        self.__attendance.clear()


class set_with_order(unique_list):
    """ Just another name for unique_list """

    def __init__(self, initial_list=()) -> None:
        super().__init__(initial_list)


# noinspection PyProtectedMember
def print_var(var_name):
    calling_frame = sys._getframe().f_back
    var_val = calling_frame.f_locals.get(var_name, calling_frame.f_globals.get(var_name, None))
    print(var_name + ':', str(var_val))


def deprecated(deprecated_func):
    def raise_deprecation(*unused_args, **unused_kwargs):
        del unused_args, unused_kwargs
        raise DeprecationWarning(deprecated_func.__name__, "is deprecated")

    return raise_deprecation


def max_widths(list_of_lists, string_align='<', numbers_align='>'):
    """ inputs is a list of lists. output is a list of maximum str length for each
        position. E.g (('a', 'ccc'), ('bb', a', 'fff')) will return: (2, 3, 3)
    """
    longest_list_len = reduce(max, [len(a_list) for a_list in list_of_lists], 0)
    width_list = [0] * longest_list_len  # pre allocate the max list length
    align_list = [string_align] * longest_list_len  # default is align to left
    for a_list in list_of_lists:
        for item_i, item in enumerate(a_list):
            width_list[item_i] = max(width_list[item_i], len(str(item)))
            if isinstance(item, numbers.Number):
                align_list[item_i] = numbers_align
    return width_list, align_list


def gen_col_format(width_list, align_list=None, sep=' '):
    """ generate a list of format string where each position is aligned to the adjacent
        position in the width_list.
        If align_list is supplied we can align numbers to the right and texts to the left
    """
    if align_list is None:
        align_list = ['<'] * len(width_list)

    format_list = list()

    for width_enum in enumerate(width_list):
        format_list.append("{{:{align}{width}}}".format(width=width_enum[1], align=align_list[width_enum[0]]))

    retVal = list()
    retVal.append("")  # for formatting a list of len 0
    for i in range(1, len(format_list) + 1):
        retVal.append(sep.join(format_list[0:i]))
    return retVal


def format_by_width(list_of_lists, string_align='<', numbers_align='>'):
    """ accept a list containing lists of text
        calculate the best width for each position
        and yield the lines one by one formatted
    """
    width_list, align_list = max_widths(list_of_lists, string_align=string_align, numbers_align=numbers_align)
    col_formats = gen_col_format(width_list, align_list)
    for a_line in list_of_lists:
        clean_line = [a if a is not None else "" for a in
                      a_line]  # replace None values with empty str, since Nones cannot have alignment format
        formatted_str = col_formats[len(clean_line)].format(*[str(item) for item in clean_line])
        yield formatted_str


def ContinuationIter(the_iter, continuation_value=None):
    """ ContinuationIter yield all the values of the_iter and then continue yielding continuation_value
    """
    yield from the_iter
    yield from itertools.repeat(continuation_value)


def ParallelContinuationIter(*iterables):
    """ Like zip ParallelContinuationIter will yield a list of items from the
        same positions in the lists in iterables. If list are not of the same size
        None will be produced
        ParallelContinuationIter([1, 2, 3], ["a", "b"]) will yield:
        [1, "a"]
        [2, "b"]
        [3, None]
    """
    max_size = max([len(lis) for lis in iterables])
    continue_iterables = list(map(ContinuationIter, iterables))
    for i in range(max_size):
        yield list(map(next, continue_iterables))


def get_buffer_checksum(buff):
    sha1ner = hashlib.sha1()
    sha1ner.update(buff)
    retVal = sha1ner.hexdigest()
    return retVal


def compare_checksums(_1st_checksum, _2nd_checksum):
    retVal = _1st_checksum.lower() == _2nd_checksum.lower()
    return retVal


def check_buffer_checksum(buff, expected_checksum):
    checksum = get_buffer_checksum(buff)
    retVal = compare_checksums(checksum, expected_checksum)
    return retVal


def check_file_checksum(file_path, expected_checksum):
    retVal = False  # if file does not exist return False
    if file_path and expected_checksum:  # prevent reading the file if file_path or expected_checksum is None
        try:
            with open(file_path, "rb") as rfd:
                retVal = check_buffer_checksum(rfd.read(), expected_checksum)
        except:
            pass
    return retVal


def get_file_checksum(file_path, follow_symlinks=True):
    """ return the sha1 checksum of the contents of a file.
        If file_path is a symbolic link and follow_symlinks is True
            the file pointed by the symlink is checksumed.
        If file_path is a symbolic link and follow_symlinks is False
            the contents of the symlink is checksumed - by calling os.readlink.
    """
    if os.path.islink(file_path) and not follow_symlinks:
        retVal = get_buffer_checksum(os.readlink(file_path).encode())
    else:
        with open(file_path, "rb") as rfd:
            retVal = get_buffer_checksum(rfd.read())
    return retVal


def compare_files_by_checksum(_1st_file_path, _2nd_file_path, follow_symlinks=False):
    """ compare the checksum of two files
        Return True if checksums match
        Return False if any or both files do not exit
        follow_symlinks  parameter has the same meaning as for get_file_checksum
    """
    try:
        _1st_checksum = get_file_checksum(_1st_file_path, follow_symlinks)
        _2nd_checksum = get_file_checksum(_2nd_file_path, follow_symlinks)
        retVal = _1st_checksum == _2nd_checksum
    except:
        retVal = False
    return retVal


def need_to_download_file(file_path, file_checksum):
    retVal = True
    if os.path.isfile(file_path):
        retVal = not check_file_checksum(file_path, file_checksum)
    return retVal


guid_re = re.compile(r"""
                [a-f0-9]{8}
                (-[a-f0-9]{4}){3}
                -[a-f0-9]{12}
                $
                """, re.VERBOSE)


def separate_guids_from_iids(items_list):
    reVal_non_guids = list()
    retVal_guids = list()
    for item in items_list:
        if guid_re.match(item.lower()):
            retVal_guids.append(item.lower())
        else:
            reVal_non_guids.append(item)
    return reVal_non_guids, retVal_guids


def make_one_list(*things):
    """ flatten things to one single list.
    """
    retVal = list()
    for thing in things:
        if isinstance(thing, collections.abc.Iterable) and not isinstance(thing, str):
            retVal.extend(thing)
        else:
            retVal.append(thing)
    return retVal


def P4GetPathFromDepotPath(depot_path):
    retVal = None
    command_parts = ["p4", "where", depot_path]
    p4_process = subprocess.Popen(command_parts, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    _stdout, _stderr = p4_process.communicate()
    _stdout, _stderr = unicodify(_stdout), unicodify(_stderr)
    return_code = p4_process.returncode
    if return_code == 0:
        lines = _stdout.split("\n")
        where_line_reg_str = "".join((re.escape(depot_path), r"\s+", r"//.+", r"\s+", r"(?P<disk_path>/.+)"))
        match = re.match(where_line_reg_str, lines[0])
        if match:
            retVal = match['disk_path']
            if retVal.endswith("/..."):
                retVal = retVal[0:-4]
    return retVal


def replace_all_from_dict(in_text, *in_replace_only_these, **in_replacement_dic):
    """ replace all occurrences of the values in in_replace_only_these
        with the values in in_replacement_dic. If in_replace_only_these is empty
        use in_replacement_dic.keys() as the list of values to replace."""
    retVal = in_text
    if not in_replace_only_these:
        # use the keys of of the replacement_dic as replace_only_these
        in_replace_only_these = list(in_replacement_dic.keys())[:]
    # sort the list by size (longer first) so longer string will be replace before their shorter sub strings
    for look_for in sorted(in_replace_only_these, key=lambda s: -len(s)):
        retVal = retVal.replace(look_for, in_replacement_dic[look_for])
    return retVal


# find sequences in a sorted list.
# in_sorted_list: a sorted list of things to search sequences in.
# is_next_func: The function that determines if one thing is the consecutive of another.
#               The default is to compare as integers.
# return_string: If true (the default) return a string in the format: "1-3, 4-5, 6, 8-9"
#                If false return a list of sequences
def find_sequences(in_sorted_list, is_next_func=lambda a, b: int(a) + 1 == int(b), return_string=True):
    sequences = [[in_sorted_list[0]]]

    for item in in_sorted_list[1:]:
        if is_next_func(sequences[-1][-1], item):
            sequences[-1].append(item)
        else:
            sequences.append([item])

    if return_string:
        sequence_strings = []
        for sequence in sequences:
            if len(sequence) == 1:
                sequence_strings.append(str(sequence[0]))
            else:
                sequence_strings.append(str(sequence[0]) + "-" + str(sequence[-1]))
        retVal = ", ".join(sequence_strings)
        return retVal
    else:
        return sequences


def timing(f):
    import time

    def wrap(*args, **kwargs):
        time1 = time.perf_counter()
        ret = f(*args, **kwargs)
        time2 = time.perf_counter()
        if time1 != time2:
            print('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        else:
            print('%s function took apparently no time at all' % f.__name__)
        return ret

    return wrap


@contextmanager
def time_it(message):
    time1 = time.time()
    yield
    time2 = time.time()
    print('%s took %0.3f ms' % (message, (time2 - time1) * 1000.0))


# compile a list of regexs to one regex. regexs are ORed
# with the | character so if any regex return true when calling
# re.search or of re.match the whole regex will return true.
def compile_regex_list_ORed(regex_list, verbose=False):
    combined_regex = "(" + ")|(".join(regex_list) + ")"
    if verbose:
        retVal = re.compile(combined_regex, re.VERBOSE)
    else:
        retVal = re.compile(combined_regex)
    return retVal


oct_digit_to_perm_chars = {'7': 'rwx', '6': 'rw-', '5': 'r-x', '4': 'r--', '3': '-wx', '2': '-w-', '1': '--x',
                           '0': '---'}


def unix_permissions_to_str(the_mod):
    # python3: use stat.filemode for the permissions string
    prefix = '-'
    if stat.S_ISDIR(the_mod):
        prefix = 'd'
    elif stat.S_ISLNK(the_mod):
        prefix = 'l'
    oct_perm = oct(the_mod)[-3:]
    retVal = ''.join([prefix] + [oct_digit_to_perm_chars[p] for p in oct_perm])
    return retVal


class DictDiffer(object):
    """
    Calculate the difference between two dictionaries as:
    (1) items added
    (2) items removed
    (3) keys same in both but changed values
    (4) keys same in both and unchanged values
    """

    def __init__(self, current_dict, past_dict) -> None:
        self.current_dict, self.past_dict = current_dict, past_dict
        self.set_current, self.set_past = set(current_dict.keys()), set(past_dict.keys())
        self.intersect = self.set_current.intersection(self.set_past)

    def added(self):
        return self.set_current - self.intersect

    def removed(self):
        return self.set_past - self.intersect

    def changed(self):
        return set(o for o in self.intersect if sorted(self.past_dict[o]) != sorted(self.current_dict[o]))

    def unchanged(self):
        return set(o for o in self.intersect if sorted(self.past_dict[o]) == sorted(self.current_dict[o]))


def find_mount_point(path):
    mount_p = PurePath(path)
    while not os.path.ismount(str(mount_p)):
        mount_p = mount_p.parent
    return str(mount_p)


class Timer_CM(object):
    def __init__(self, name, print_results=True) -> None:
        self.elapsed = Decimal()
        self._name = name
        self._print_results = print_results
        self._start_time = None
        self._children: Dict = {}

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()
        if self._print_results:
            self.print_results()

    def child(self, name):
        try:
            return self._children[name]
        except KeyError:
            result = Timer_CM(name, print_results=False)
            self._children[name] = result
            return result

    def start(self):
        self._start_time = self._get_time()

    def stop(self):
        self.elapsed += self._get_time() - self._start_time

    def print_results(self):
        print(self._format_results())

    def _format_results(self, indent='  '):
        result = '%s: %.3fs' % (self._name, self.elapsed)
        children = self._children.values()
        for child in sorted(children, key=lambda c: c.elapsed, reverse=True):
            child_lines = child._format_results(indent).split('\n')
            child_percent = child.elapsed / self.elapsed * 100
            child_lines[0] += ' (%d%%)' % child_percent
            for line in child_lines:
                result += '\n' + indent + line
        return result

    def _get_time(self):
        return Decimal(default_timer())


wtar_file_re = re.compile(r"""
    (?P<base_name>.+?)
    (?P<wtar_extension>\.wtar)
    (?P<split_numerator>\.[a-z]{2})?$""",
                          re.VERBOSE)


def is_wtar_file(in_possible_wtar) -> bool:
    match = wtar_file_re.match(os.fspath(in_possible_wtar))
    retVal: bool = match is not None
    return retVal


def is_first_wtar_file(in_possible_wtar):
    retVal = False
    match = wtar_file_re.match(os.fspath(in_possible_wtar))
    if match:
        split_numerator = match['split_numerator']
        retVal = split_numerator is None or split_numerator == ".aa"
        if retVal:  # hack to ignore phantom files that begin with ._
            _, file_name = os.path.split(in_possible_wtar)
            if file_name.startswith("._"):
                print("ignoring possibly bad .wtar file", in_possible_wtar)
                retVal = False
    return retVal


# Given a name remove the trailing wtar or wtar.?? if any
# E.g. "a" => "a", "a.wtar" => "a", "a.wtar.aa" => "a"
def original_name_from_wtar_name(wtar_name):
    retVal = wtar_name
    match = wtar_file_re.match(wtar_name)
    if match:
        retVal = match['base_name']
    return retVal


# Given a list of file/folder names, replace those which are wtarred with the original file name.
# E.g. ['a', 'b.wtar', 'c.wtar.aa', 'c.wtar.ab'] => ['a', 'b', 'c']
# We must work on the whole list since several wtar file names might merge to a single original file name.
def original_names_from_wtars_names(original_list):
    replaced_list = unique_list()
    replaced_list.extend([original_name_from_wtar_name(file_name) for file_name in original_list])
    return replaced_list


def get_recursive_checksums(some_path, ignore=None):
    """ If some_path is a file return a dict mapping the file's path to it's sha1 checksum
        and mapping "total_checksum" to the files checksum, e.g.
        assuming /a/b/c.txt is a file
            get_recursive_checksums("/a/b/c.txt")
        will return: {c.txt: 1bc...aed, total_checksum: ed4...f4e}

        If some_path is a folder recursively walk the folder and return a dict mapping each file to it's sha1 checksum.
        and mapping "total_checksum" to a checksum of all the files checksums.

        total_checksum is calculated by concatenating two lists:
         - list of all the individual file checksums
         - list of all individual paths paths
        The combined list is sorted and all members are concatenated into one string.
        The sha1 checksum of that string is the total_checksum
        Sorting is done to ensure same total_checksum is returned regardless the order
        in which os.scandir returned the files, but that a different checksum will be
        returned if a file changed it's name without changing contents.
        Note:
            - If you have a file called total_checksum your'e f**d.
            - Symlinks are not followed and are checksum as regular files (by calling readlink).
    """
    if ignore is None:
        ignore = ()
    retVal = dict()
    some_path_dir, some_path_leaf = os.path.split(some_path)
    if some_path_leaf not in ignore:
        if os.path.isfile(some_path):
            retVal[some_path_leaf] = get_file_checksum(some_path, follow_symlinks=False)
        elif os.path.isdir(some_path):
            for item in utils.scandir_walk(some_path, report_dirs=False):
                item_path_dir, item_path_leaf = os.path.split(item.path)
                if item_path_leaf not in ignore:
                    the_checksum = get_file_checksum(item.path, follow_symlinks=False)
                    normalized_path = PurePath(item.path).as_posix()
                    retVal[normalized_path] = the_checksum

        checksum_list = sorted(list(retVal.keys()) + list(retVal.values()))
        string_of_checksums = "".join(checksum_list)
        retVal['total_checksum'] = get_buffer_checksum(string_of_checksums.encode())
    return retVal


def obj_memory_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = 0
    try:
        if seen is None:
            seen = set()
        obj_id = id(obj)
        if obj_id in seen:
            return 0
        seen.add(obj_id)
        size = sys.getsizeof(obj)
        if isinstance(obj, (types.ModuleType, asyncio.Future)):
            pass  # these types cause endless recursion
        elif isinstance(obj, dict):
            size += sum([obj_memory_size(k, seen) + obj_memory_size(v, seen) for k, v in obj.items()])
        elif hasattr(obj, '__dict__'):
            size += obj_memory_size(obj.__dict__, seen)
        elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
            size += sum([obj_memory_size(i, seen) for i in obj])
    except Exception as ex:
        print("obj_memory_size", ex)
    return size


def get_wtar_total_checksum(wtar_file_path):
    tar_total_checksum = None
    try:
        if not os.path.isfile(wtar_file_path):
            wtar_file_path += ".aa"
        if os.path.isfile(wtar_file_path):
            wtar_file_paths = utils.find_split_files(wtar_file_path)
            with utils.MultiFileReader("br", wtar_file_paths) as fd:
                with tarfile.open(fileobj=fd) as tar:
                    tar_total_checksum = tar.pax_headers.get("total_checksum")
    except Exception as ex:
        pass  # return None if there was exception from any reason
    return tar_total_checksum


def extra_json_serializer(obj):
    """ json module does not know to encode deque, PurePath,... """
    if isinstance(obj, (collections.deque,)):
        return list(obj)
    elif hasattr(obj, "__fspath__"):  # mainly for pathlib.PurePath
        return os.fspath(obj)
    elif hasattr(obj, "__repr__"):
        return repr(obj)
    else:
        raise TypeError(
            f"object of type {type(obj)} is not serializable. Add code to utils.extra_json_serializer to make it json compatible.")


class JsonExtraTypesDecoder(json.JSONDecoder):
    """ json module does not know to decode deque """

    def default(self, obj):
        if isinstance(obj, (collections.deque,)):
            return list(obj)
        return json.JSONEncoder.default(self, obj)


def get_system_log_folder_path():
    """ if Desktop/Logs exists put the file there, otherwise in the user's folder
    """
    # os.environ["VENDOR_NAME"], os.environ["APPLICATION_NAME"] should have been set by InvocationReporter
    vendor_name = os.environ["VENDOR_NAME"]
    app_name = os.environ["APPLICATION_NAME"]

    if sys.platform == 'win32':
        folder_to_write_in = Path(appdirs.user_data_dir(app_name, vendor_name, roaming=True), 'Logs')
    else:
        folder_to_write_in = Path(appdirs.user_data_dir(vendor_name), app_name, 'Logs')

    system_log_file_path = folder_to_write_in.joinpath('instl')
    return system_log_file_path


def get_system_log_file_path():
    """ if Desktop/Logs exists put the file there, otherwise in the user's folder
    """
    # os.environ["VENDOR_NAME"], os.environ["APPLICATION_NAME"] should have been set by InvocationReporter
    retVal = get_system_log_folder_path().joinpath("instl.log")
    return retVal


def iter_complete_to_longest(*list_of_lists):
    """ yield all values from first list complementing with the next
        until longest is exhausted. e.g. iter_complete_to_longest((1,), ('a', 2), ('b', 'c', 3)) would yield:
        1, 2, 3
    """
    start_from = 0
    for a_list in list_of_lists:
        yield from a_list[start_from:]
        start_from = max(len(a_list), start_from)


def clock(func):
    '''A decorator that measures the time it takes to run the original function that was decorated.
       The decorator will print a debug log msg with 8 decimal points, and will work even if an exception was raised.'''

    @wraps(func)
    def clocked(*args, **kwargs):
        name = func.__name__
        arg_lst = []
        if args:
            arg_lst.extend(repr(arg) for arg in args)
        if kwargs:
            arg_lst.extend('%s=%r' % (k, w) for k, w in sorted(kwargs.items()))
        args_str = ', '.join(arg_lst)

        caught_exception = False
        result = None
        t0 = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except:
            caught_exception = True
            raise
        finally:
            elapsed = time.perf_counter() - t0
            msg = '[{elapsed:0.8f}s] {name}({args_str})'.format(**locals())
            if not caught_exception:
                msg += ' -> {}'.format(result)
            log.debug(msg)
        return result

    return clocked


def partition_list(in_list, partition_condition):
    """ divide a list to sub lists according to partition_condition
        e.g. partition_list([1,2,3,0,4,5,6], lambda x: x==0) will return:
    """

    list_of_lists = []

    cur_list = []
    for i in in_list:
        if partition_condition(i):
            if cur_list:
                list_of_lists.append(cur_list)
                cur_list = []
        else:
            cur_list.append(i)
    if cur_list:
        list_of_lists.append(cur_list)
    return list_of_lists


def iter_grouper(n, iterable):
    """ take iterator and yield groups of size <= n """
    i = iter(iterable)
    piece = list(itertools.islice(i, n))
    while piece:
        yield piece
        piece = list(itertools.islice(i, n))


@lru_cache(maxsize=None)
def get_os_description():
    match sys.platform:
        case 'darwin':
            retVal = f"macOS {platform.mac_ver()[0]}"
        case 'linux':
            retVal = f"Linux {platform.uname().version}"
        case 'win32':
            retVal = f"Windows {platform.version()}"
    return retVal


def add_to_actions_stack(action: str):
    doing_stack.append(action)


def get_latest_action_from_stack():
    return doing_stack.pop()


# TODO: Shai, is this the best place for this type of function?
def get_curl_err_msg(key: int) -> str:
    """
        helper function for error monitoring, since the one of the most common errors we get are curl related
        we needed a more accurate description of what went wrong during the download
        note: I have written the most common curl errors below, more can be added if needed
    """
    curl_lookup_error = {
        3: 'URL malformed',
        5: 'Couldnt resolve proxy',
        6: "Couldn't resolve host",
        7: "Failed to connect to host",
        18: "Partial file. Only a part of the file was transferred",
        21: "Quote error. A quote command returned an error from the server",
        22: "HTTP page not retrieved. The requested url was not found or returned another error",
        23: "Write error. Curl could not write data to a local filesystem",
        28: "Operation timeout. The specified time-out period was reached according to the conditions",
        52: "Nothing was returned from the server",
        55: "Failure while sending network data",
        56: "Failure while receiving network data"
    }
    if curl_lookup_error and curl_lookup_error[key]:
        return "curl error code: " + str(key) + ": " + curl_lookup_error[key]
    else:
        return "please check curl error key: " + key + " online "
