#!/usr/bin/env python3


import sys
import os
import urllib.request, urllib.error, urllib.parse
import re
import hashlib
import base64
import collections
import subprocess
import time
import shutil
import numbers
import stat
import datetime
from pathlib import PurePath
import fnmatch
import pathlib
from timeit  import default_timer
from decimal import Decimal
import rsa
from functools import reduce
from itertools import repeat
import tarfile

def Is64Windows():
    return 'PROGRAMFILES(X86)' in os.environ


def Is32Windows():
    return not Is64Windows()


def GetProgramFiles32():
    if Is64Windows():
        return os.environ['PROGRAMFILES(X86)']
    else:
        return os.environ['PROGRAMFILES']


def GetProgramFiles64():
    if Is64Windows():
        return os.environ['PROGRAMW6432']
    else:
        return None


def get_current_os_names():
    retVal = None
    import platform
    current_os = platform.system()
    if current_os == 'Darwin':
        retVal = ('Mac',)
    elif current_os == 'Windows':
        if Is64Windows():
            retVal = ('Win', 'Win64')
        else:
            retVal = ('Win', 'Win32')
    elif current_os == 'Linux':
        retVal = ('Linux',)
    return retVal


class write_to_file_or_stdout(object):
    def __init__(self, file_path):
        self.file_path = file_path
        self.fd = sys.stdout

    def __enter__(self):
        if self.file_path != "stdout":
            self.fd = open(self.file_path, "w", encoding='utf-8', errors='namereplace')
        return self.fd

    def __exit__(self, unused_type, unused_value, unused_traceback):
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


class open_for_read_file_or_url(object):
    protocol_header_re = re.compile("""
                        \w+
                        ://
                        """, re.VERBOSE)

    def __init__(self, in_file_or_url, translate_url_callback=None, path_searcher=None, encoding='utf-8'):
        self.local_file_path = None
        self.url = None
        self.custom_headers = None
        self.encoding = encoding
        self.fd = None
        self._actual_path = in_file_or_url
        match = self.protocol_header_re.match(in_file_or_url)
        if not match:  # it's a local file
            self.local_file_path = in_file_or_url
            if path_searcher is not None:
                self.local_file_path = path_searcher.find_file(self.local_file_path)
            if self.local_file_path:
                if 'Win' in get_current_os_names():
                    self.local_file_path = os.path.abspath(self.local_file_path)
                else:
                    self.local_file_path = os.path.realpath(self.local_file_path)
            else:
                raise FileNotFoundError("Could not locate local file", self.local_file_path)
            self._actual_path = self.local_file_path
        else:
            self.url = in_file_or_url
            if translate_url_callback is not None:
                self.url, self.custom_headers = translate_url_callback(self.url)
            self._actual_path = self.url

    def __enter__(self):
        try:
            if self.url:
                opener = urllib.request.build_opener()
                if self.custom_headers:
                    for custom_header in self.custom_headers:
                        opener.addheaders.append(custom_header)
                self.fd = opener.open(self.url)
            elif self.local_file_path:
                if self.encoding is None:
                    self.fd = open(self.local_file_path, "rb")
                else:
                    self.fd = open(self.local_file_path, "r", encoding=self.encoding)
        except urllib.error.URLError as url_err:
            print (url_err, self.url)
            raise
        if "name" not in dir(self.fd) and "url" in dir(self.fd):
            self.fd.name = self.fd.url # so we can get the url with the same attribute as file object
        return self

    def __exit__(self, unused_type, unused_value, unused_traceback):
        self.fd.close()

    @property
    def actual_path(self):
        """ return the path or url after all translations and search paths searches"""
        return self._actual_path


def read_from_file_or_url(in_url, translate_url_callback=None, public_key=None, textual_sig=None, expected_checksum=None, encoding='utf-8'):
    """ Read a file from local disk or url. Check signature or checksum if given.
        If test against either sig or checksum fails - raise IOError.
        Return: file contents.
    """
    with open_for_read_file_or_url(in_url, translate_url_callback, encoding=encoding) as open_file:
        contents_buffer = open_file.fd.read()
        if encoding is not None: # when reading from url we're not sure what the encoding is
            contents_buffer = unicodify(contents_buffer, encoding=encoding)
        # check sig or checksum only if they were given
        if (public_key, textual_sig, expected_checksum) != (None, None, None):
            if len(contents_buffer) == 0:
                raise IOError("Empty contents returned from", in_url, "; expected checksum: ", expected_checksum, "; encoding:", encoding)
            if encoding is not None:
                raise IOError("Checksum check requested for", in_url, "but encoding is not None, encoding:", encoding, "; expected checksum: ", expected_checksum)
            buffer_ok = check_buffer_signature_or_checksum(contents_buffer, public_key, textual_sig, expected_checksum)
            if not buffer_ok:
                actual_checksum = get_buffer_checksum(contents_buffer)
                raise IOError("Checksum or Signature mismatch", in_url, "expected checksum: ", expected_checksum,
                              "actual checksum:", actual_checksum, "encoding:", encoding)
    return contents_buffer


def download_from_file_or_url(in_url, in_local_path, translate_url_callback=None, cache=False, public_key=None, textual_sig=None, expected_checksum=None):
    """ Copy a file or download it from a URL to in_local_path.
        If cache flag is True, the file will only be copied/downloaded if it does not already exist.
        If cache flag is True and signature or checksum is given they will be checked. If such check fails, copy/download
        will be done.
    """
    fileExists = False
    if cache and os.path.isfile(in_local_path):
        # cache=True means: if local file already exists, there is no need to download.
        # if public_key, textual_sig, expected_checksum are given, check local file signature or checksum.
        # If these do not match erase the file so it will be downloaded again.
        fileOK = True
        if (public_key, textual_sig, expected_checksum) != (None, None, None):
            fileOK = check_file_signature_or_checksum(in_local_path, public_key, textual_sig, expected_checksum)
        if not fileOK:
            print("File will be downloaded because check checksum failed for", in_url, "cached at local path", in_local_path, "expected_checksum:", expected_checksum)
            os.remove(in_local_path)
        fileExists = fileOK

    if not fileExists:
        contents_buffer = read_from_file_or_url(in_url, translate_url_callback, public_key, textual_sig, expected_checksum, encoding=None)
        if contents_buffer:
            with open(in_local_path, "wb") as wfd:
                make_open_file_read_write_for_all(wfd)
                wfd.write(contents_buffer)
        else:
            print("no content_buffer after reading", in_url, file=sys.stderr)
    #if os.path.isfile(in_local_path):
    #    print(in_local_path, "exists and has ", os.path.getsize(in_local_path), "bytes", file=sys.stderr)
    #else:
    #    print(in_local_path, "does not exists", file=sys.stderr)


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

    def __init__(self, initial_list=()):
        super().__init__()
        self.__attendance = set()
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
                    super().__delitem__(prev_index_for_item+1)
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
    def __init__(self, initial_list=()):
        super().__init__(initial_list)


# noinspection PyProtectedMember
def print_var(var_name):
    calling_frame = sys._getframe().f_back
    var_val = calling_frame.f_locals.get(var_name, calling_frame.f_globals.get(var_name, None))
    print (var_name+':', str(var_val))


def last_url_item(url):
    url = url.strip("/")
    url_path = urllib.parse.urlparse(url).path
    _, retVal = os.path.split(url_path)
    return retVal


def main_url_item(url):
    try:
        parseResult = urllib.parse.urlparse(url)
        #print("+++++++", url, "+", parseResult)
        retVal = parseResult.netloc
        if not retVal:
            retVal = parseResult.path
    except Exception:
        retVal = ""
    return retVal


def relative_url(base, target):
    base_path = urllib.parse.urlparse(base.strip("/")).path
    target_path = urllib.parse.urlparse(target.strip("/")).path
    retVal = None
    if target_path.startswith(base_path):
        retVal = target_path.replace(base_path, '', 1)
        retVal = retVal.strip("/")
    return retVal


def deprecated(deprecated_func):
    def raise_deprecation(*unused_args, **unused_kwargs):
        del unused_args, unused_kwargs
        raise DeprecationWarning(deprecated_func.__name__, "is deprecated")

    return raise_deprecation


class ChangeDirIfExists(object):
    """Context manager for changing the current working directory"""
    def __init__(self, newPath):
        if os.path.isdir(newPath):
            self.newPath = newPath
        else:
            self.newPath = None

    def __enter__(self):
        if self.newPath:
            self.savedPath = os.getcwd()
            os.chdir(self.newPath)

    def __exit__(self, etype, value, traceback):
        if self.newPath:
            os.chdir(self.savedPath)


def safe_remove_file(path_to_file):
    """ solves a problem with python 2.7 where os.remove raises if the file does not exist  """
    try:
        os.remove(path_to_file)
    except FileNotFoundError:  # os.remove raises is the file does not exists
        pass
    return path_to_file


def safe_remove_folder(path_to_folder, ignore_errors=True):
    try:
        shutil.rmtree(path_to_folder)
    except Exception as ex:
        pass
    return path_to_folder


def safe_remove_file_system_object(path_to_file_system_object, followlinks=False):
    try:
        if os.path.islink(path_to_file_system_object):
            if followlinks:
                real_path = os.path.realpath(path_to_file_system_object)
                safe_remove_file_system_object(real_path)
            else:
                os.unlink(path_to_file_system_object)
        elif os.path.isdir(path_to_file_system_object):
            safe_remove_folder(path_to_file_system_object)
        elif os.path.isfile(path_to_file_system_object):
            safe_remove_file(path_to_file_system_object)
    except Exception as ex:
        pass


def max_widths(list_of_lists):
    """ inputs is a list of lists. output is a list of maximum str length for each
        position. E.g (('a', 'ccc'), ('bb', a', 'fff')) will return: (2, 3, 3)
    """
    longest_list_len = reduce(max, [len(a_list) for a_list in list_of_lists], 0)
    width_list = [0] * longest_list_len  # pre allocate the max list length
    align_list = ['<'] * longest_list_len  # default is align to left
    for a_list in list_of_lists:
        for item in enumerate(a_list):
            width_list[item[0]] = max(width_list[item[0]], len(str(item[1])))
            if isinstance(item[1], numbers.Number):
                align_list[item[0]] = '>'
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
    for i in range(1, len(format_list)+1):
        retVal.append(sep.join(format_list[0:i]))
    return retVal


def ContinuationIter(the_iter, continuation_value=None):
    """ ContinuationIter yield all the values of the_iter and then continue yielding continuation_value
    """
    yield from the_iter
    yield from repeat(continuation_value)


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


def create_file_signatures(file_path, private_key_text=None):
    """ create rsa signature and sha1 checksum for a file.
        return a dict with "SHA-512_rsa_sig" and "sha1_checksum" entries.
    """
    retVal = dict()
    with open(file_path, "rb") as rfd:
        file_contents = rfd.read()
        sha1ner = hashlib.sha1()
        sha1ner.update(file_contents)
        checksum = sha1ner.hexdigest()
        retVal["sha1_checksum"] = checksum
        if private_key_text is not None:
            private_key_obj = rsa.PrivateKey.load_pkcs1(private_key_text, format='PEM')
            binary_sig = rsa.sign(file_contents, private_key_obj, 'SHA-512')
            text_sig = base64.b64encode(binary_sig)
            retVal["SHA-512_rsa_sig"] = text_sig
    return retVal


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


def check_buffer_signature(buff, textual_sig, public_key):
    try:
        pubkeyObj = rsa.PublicKey.load_pkcs1(public_key, format='PEM')
        binary_sig = base64.b64decode(textual_sig)
        rsa.verify(buff, binary_sig, pubkeyObj)
        return True
    except Exception:
        return False


def check_buffer_signature_or_checksum(buff, public_key=None, textual_sig=None, expected_checksum=None):
    retVal = False
    if public_key and textual_sig:
        retVal = check_buffer_signature(buff, textual_sig, public_key)
    elif expected_checksum:
        retVal = check_buffer_checksum(buff, expected_checksum)
    return retVal


def check_file_signature_or_checksum(file_path, public_key=None, textual_sig=None, expected_checksum=None):
    with open(file_path, "rb") as rfd:
        retVal = check_buffer_signature_or_checksum(rfd.read(), public_key, textual_sig, expected_checksum)
    return retVal


def check_file_checksum(file_path, expected_checksum):
    retVal = False  # if file does not exist return False
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


def check_file_signature(file_path, textual_sig, public_key):
    with open(file_path, "rb") as rfd:
        retVal = check_buffer_signature(rfd.read(), textual_sig, public_key)
    return retVal


def need_to_download_file(file_path, file_checksum):
    retVal = True
    if os.path.isfile(file_path):
        retVal = not check_file_checksum(file_path, file_checksum)
    return retVal


def quoteme_single(to_quote):
    return "".join( ("'", to_quote, "'") )


def quoteme_single_list(to_quote_list, ):
    return [quoteme_single(to_q) for to_q in to_quote_list]


def quoteme_double(to_quote):
    return "".join(('"', to_quote, '"'))


def quoteme_double_list(to_quote_list, ):
    return [quoteme_double(to_q) for to_q in to_quote_list]

detect_quotations = re.compile("(?P<prefix>[\"'])(?P<the_unquoted_text>.+)(?P=prefix)")


def unquoteme(to_unquote):
    retVal = to_unquote
    has_quotations = detect_quotations.match(to_unquote)
    if has_quotations:
        retVal = has_quotations.group('the_unquoted_text')
    return retVal

guid_re = re.compile("""
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
        if isinstance(thing, collections.Iterable) and not isinstance(thing, str):
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
        where_line_reg_str = "".join( (re.escape(depot_path), "\s+", "//.+", "\s+", "(?P<disk_path>/.+)") )
        match = re.match(where_line_reg_str, lines[0])
        if match:
            retVal = match.group('disk_path')
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
def find_sequences(in_sorted_list, is_next_func=lambda a,b: int(a)+1==int(b), return_string=True):
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
                sequence_strings.append(str(sequence[0])+"-"+str(sequence[-1]))
        retVal = ", ".join(sequence_strings)
        return retVal
    else:
        return sequences


def make_open_file_read_write_for_all(fd):
    try:
        os.fchmod(fd.fileno(), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
    except Exception:
        try:
            os.chmod(fd.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except Exception:
            print("make_open_file_read_write_for_all: failed for ", fd.name)


def timing(f):
    import time

    def wrap(*args, **kwargs):
        time1 = time.clock()
        ret = f(*args, **kwargs)
        time2 = time.clock()
        if time1 != time2:
            print ('%s function took %0.3f ms' % (f.__name__, (time2-time1)*1000.0))
        else:
            print ('%s function took apparently no time at all' % f.__name__)
        return ret
    return wrap


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


def excluded_walk(root_to_walk, file_exclude_regex=None, dir_exclude_regex=None, followlinks=False):
    """ excluded_walk behaves like os.walk but will exclude files or dirs who's name pass the given regexs
    :param root_to_walk: the root folder to walk, this folder will *not* be tested against dir_exclude_regex
    :param file_exclude_regex: a regex to test files. Any file that matches this regex will not be returned
    :param dir_exclude_regex: a regex to test folders. Any folder that matches this regex will not be returned
    :param followlinks: passed directly to os.walk
    :yield: a tuple of (root, dirs, files) - just like os.walk
    """

    if file_exclude_regex is None: # if file_exclude_regex is None all files should be included
        file_exclude_regex = re.compile("a^")

    if dir_exclude_regex is None:  # if file_exclude_regex is None all files should be included
        dir_exclude_regex = re.compile("a^")

    for root, dirs, files in os.walk(root_to_walk, followlinks=followlinks):
        dirs[:] =  sorted([a_dir  for a_dir  in dirs  if not dir_exclude_regex.search(a_dir)])
        files[:] = sorted([a_file for a_file in files if not file_exclude_regex.search(a_file)])
        yield root, dirs, files


# noinspection PyUnresolvedReferences
def get_disk_free_space(in_path):
    retVal = 0
    if 'Win' in get_current_os_names():
        secsPerCluster, bytesPerSec, nFreeCluster, totCluster = win32file.GetDiskFreeSpace(in_path)
        retVal = secsPerCluster * bytesPerSec * nFreeCluster
    elif 'Mac' in get_current_os_names():
        st = os.statvfs(in_path)
        retVal = st.f_bavail * st.f_frsize
    return retVal


# cache_dir_to_clean = var_stack.resolve(self.get_default_sync_dir(continue_dir="cache", make_dir=False))
# utils.clean_old_files(cache_dir_to_clean, 30)
def clean_old_files(dir_to_clean, older_than_days):
    """ clean a directory from file older than the given param
        block all exceptions since this operation is "nice to have" """
    try:
        threshold_time = time.time() - (older_than_days * 24 * 60 * 60)
        for root, dirs, files in os.walk(dir_to_clean, followlinks=False):
            for a_file in files:
                a_file_path = os.path.join(root, a_file)
                file_time = os.path.getmtime(a_file_path)
                if file_time < threshold_time:
                    os.remove(a_file_path)
    except Exception:
        pass


def smart_copy_file(source_path, destination_path):
    s = source_path
    s_dir, s_name = os.path.split(source_path)
    d_file_exists = False
    if os.path.isdir(destination_path):
        d = os.path.join(destination_path, s_name)
        d_file_exists = os.path.isfile(d)
    elif os.path.isfile(destination_path):
        d = destination_path
        d_file_exists = True
    else: # assume destination is a non-existing file
        d = destination_path
        d_dir, d_name = os.path.split(destination_path)
        os.makedirs(d_dir, exist_ok=True)

    try:
        getattr(os, "link") # will raise on windows, os.link is not always available (Win)
        if d_file_exists:
            if os.stat(s).st_ino != os.stat(d).st_ino:
                safe_remove_file(d)
                os.link(s, d)  # will raise if different drives
            else:
                pass # same inode no need to copy
        else:
            os.link(s, d)
    except Exception:
        try:
            shutil.copy2(s, d)
        except Exception:
            pass


oct_digit_to_perm_chars = {'7':'rwx', '6' :'rw-', '5' : 'r-x', '4':'r--', '3':'-wx', '2':'-w-', '1':'--x', '0': '---'}
def unix_permissions_to_str(the_mod):
    # python3: use stat.filemode for the permissions string
    prefix = '-'
    if stat.S_ISDIR(the_mod):
        prefix = 'd'
    elif stat.S_ISLNK(the_mod):
        prefix = 'l'
    oct_perm = oct(the_mod)[-3:]
    retVal = ''.join([prefix,] + [oct_digit_to_perm_chars[p] for p in oct_perm])
    return retVal


def find_split_files(first_file):
    try:
        retVal = list()
        norm_first_file = os.path.normpath(first_file)  # remove trailing . if any

        if norm_first_file.endswith(".aa"):
            base_folder, base_name = os.path.split(norm_first_file)
            if not base_folder: base_folder = "."
            filter_pattern = base_name[:-2] + "??"  # with ?? instead of aa
            matching_files = sorted(fnmatch.filter((f.name for f in os.scandir(base_folder)), filter_pattern))
            for a_file in matching_files:
                retVal.append(os.path.join(base_folder, a_file))
        else:
            retVal.append(norm_first_file)
        return retVal

    except Exception as es:
        print("exception while find_split_files", first_file)
        raise es


def unicodify(in_something, encoding='utf-8'):
    if in_something is not None:
        if isinstance(in_something, str):
            retVal = in_something
        elif isinstance(in_something, bytes):
            retVal = in_something.decode(encoding)
        else:
            retVal = str(in_something)
    else:
        retVal = None
    return retVal


def bool_int_to_str(in_bool_int):
    if in_bool_int == 0:
        retVal = "no"
    else:
        retVal = "yes"
    return retVal


def str_to_bool_int(the_str):
    if the_str.lower() in ("yes", "true", "y", 't'):
        retVal = 1
    elif the_str.lower() in ("no", "false", "n", "f"):
        retVal = 0
    else:
        raise ValueError("Cannot translate", the_str, "to bool-int")
    return retVal

def str_to_bool(the_str, default=False):
    retVal = default
    if the_str.lower() in ("yes", "true", "y", 't'):
        retVal = True
    elif the_str.lower() in ("no", "false", "n", "f"):
        retVal = False
    return retVal


def is_iterable_but_not_str(obj_to_check):
    retVal = hasattr(obj_to_check, '__iter__') and not isinstance(obj_to_check, str)
    return retVal


class DictDiffer(object):
    """
    Calculate the difference between two dictionaries as:
    (1) items added
    (2) items removed
    (3) keys same in both but changed values
    (4) keys same in both and unchanged values
    """
    def __init__(self, current_dict, past_dict):
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
    mount_p = pathlib.PurePath(path)
    while not os.path.ismount(str(mount_p)):
        mount_p = mount_p.parent
    return str(mount_p)


class Timer_CM(object):
    def __init__(self, name, print_results=True):
        self.elapsed = Decimal()
        self._name = name
        self._print_results = print_results
        self._start_time = None
        self._children = {}
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


wtar_file_re = re.compile("""
    (?P<base_name>.+?)
    (?P<wtar_extension>\.wtar)
    (?P<split_numerator>\.[a-z]{2})?$""",
                          re.VERBOSE)


def is_wtar_file(in_possible_wtar):
    match = wtar_file_re.match(in_possible_wtar)
    retVal =  match is not None
    return retVal


def is_first_wtar_file(in_possible_wtar):
    retVal = False
    match = wtar_file_re.match(in_possible_wtar)
    if match:
        split_numerator = match.group('split_numerator')
        retVal = split_numerator is None or split_numerator == ".aa"
    return retVal


# Given a name remove the trailing wtar or wtar.?? if any
# E.g. "a" => "a", "a.wtar" => "a", "a.wtar.aa" => "a"
def original_name_from_wtar_name(wtar_name):
    retVal = wtar_name
    match = wtar_file_re.match(wtar_name)
    if match:
        retVal = match.group('base_name')
    return retVal


# Given a list of file/folder names, replace those which are wtarred with the original file name.
# E.g. ['a', 'b.wtar', 'c.wtar.aa', 'c.wtar.ab'] => ['a', 'b', 'c']
# We must work on the whole list since several wtar file names might merge to a single original file name.
def original_names_from_wtars_names(original_list):
    replaced_list = unique_list()
    replaced_list.extend([original_name_from_wtar_name(file_name) for file_name in original_list])
    return replaced_list

def scandir_walk(top_path, report_files=True, report_dirs=True, follow_symlinks=False):
    """ Walk a folder hierarchy using the new and fast os.scandir, yielding 
    
    :param top_path: where to start the walk, top_path itself will NOT be yielded
    :param report_files: If True: files will be yielded
    :param report_dirs: If True: folders will be yielded
    :param follow_symlinks: if False symlinks will be reported as files
    :return: this function yields so not return
    """
    for item in os.scandir(top_path):
        if not follow_symlinks and item.is_symlink():
            if report_files:
                yield item
        elif item.is_file(follow_symlinks=follow_symlinks):
            if report_files:
                yield item
        elif item.is_dir(follow_symlinks=follow_symlinks):
            if report_dirs:
                yield item
            yield from scandir_walk(item.path, report_files=report_files, report_dirs=report_dirs, follow_symlinks=follow_symlinks)


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
    if ignore is None: ignore = ()
    retVal = dict()
    some_path_dir, some_path_leaf = os.path.split(some_path)
    if some_path_leaf not in ignore:
        if os.path.isfile(some_path):
                retVal[some_path_leaf] = get_file_checksum(some_path, follow_symlinks=False)
        elif os.path.isdir(some_path):
            for item in scandir_walk(some_path, report_dirs=False):
                item_path_dir, item_path_leaf = os.path.split(item.path)
                if item_path_leaf not in ignore:
                    the_checksum = get_file_checksum(item.path, follow_symlinks=False)
                    normalized_path = pathlib.PurePath(item.path).as_posix()
                    retVal[normalized_path] = the_checksum

        checksum_list = sorted(list(retVal.keys()) + list(retVal.values()))
        string_of_checksums = "".join(checksum_list)
        retVal['total_checksum'] = get_buffer_checksum(string_of_checksums.encode())
    return retVal

from .multi_file import MultiFileReader


def unwtar_a_file(wtar_file_path, destination_folder=None, no_artifacts=False, ignore=None):
    try:
        wtar_file_paths = find_split_files(wtar_file_path)

        if destination_folder is None:
            destination_folder, _ = os.path.split(wtar_file_paths[0])
        print("unwtar", wtar_file_path, " to ", destination_folder)
        if ignore is None: ignore = ()

        first_wtar_file_dir, first_wtar_file_name = os.path.split(wtar_file_paths[0])
        destination_leaf_name = original_name_from_wtar_name(first_wtar_file_name)
        destination_path = os.path.join(destination_folder, destination_leaf_name)

        disk_total_checksum = "disk_total_checksum_was_not_found"
        if os.path.exists(destination_path):
            with ChangeDirIfExists(destination_folder):
                disk_total_checksum = get_recursive_checksums(destination_leaf_name, ignore=ignore).get("total_checksum", "disk_total_checksum_was_not_found")

        do_the_unwtarring = True
        with MultiFileReader("br", wtar_file_paths) as fd:
            with tarfile.open(fileobj=fd) as tar:
                tar_total_checksum = tar.pax_headers.get("total_checksum", "tar_total_checksum_was_not_found")
                #print("    tar_total_checksum", tar_total_checksum)
                if disk_total_checksum == tar_total_checksum:
                    do_the_unwtarring = False
                    print("unwtar_a_file(", wtar_file_paths[0], ") skipping unwtarring because item exists and is identical to archive")
                if do_the_unwtarring:
                    safe_remove_file_system_object(destination_path)
                    tar.extractall(destination_folder)

        if no_artifacts:
            for wtar_file in wtar_file_paths:
                os.remove(wtar_file)

    except OSError as e:
        print("Invalid stream on split file with {}".format(wtar_file_paths[0]))
        raise e

    except tarfile.TarError:
        print("tarfile error while opening file", os.path.abspath(wtar_file_paths[0]))
        raise