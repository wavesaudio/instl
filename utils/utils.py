#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import os
import stat
import urllib2
import re
import urlparse
import hashlib
import base64
import collections
import subprocess
import time
import shutil

import rsa
from functools import reduce


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
            self.fd = open(self.file_path, "w")
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

    def __init__(self, in_file_or_url, translate_url_callback=None, path_searcher=None):
        self.local_file_path = None
        self.url = None
        self.cookie = None
        self.fd = None
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
                raise IOError("Could not locate local file", self.local_file_path)
        else:
            self.url = in_file_or_url
            if translate_url_callback is not None:
                self.url, self.cookie = translate_url_callback(self.url)

    def __enter__(self):
        try:
            if self.url:
                opener = urllib2.build_opener()
                if self.cookie:
                    opener.addheaders.append(('Cookie', self.cookie))
                self.fd = opener.open(self.url)
            elif self.local_file_path:
                self.fd = open(self.local_file_path, "r")
        except urllib2.URLError as url_err:
            print (url_err, self.url)
            raise
        if "name" not in dir(self.fd) and "url" in dir(self.fd):
            self.fd.name = self.fd.url # so we can get the url with the same attribute as file object
        return self.fd

    def __exit__(self, unused_type, unused_value, unused_traceback):
        self.fd.close()


def read_from_file_or_url(in_url, translate_url_callback=None, public_key=None, textual_sig=None, expected_checksum=None):
    """ Read a file from local disk or url. Check signature or checksum if given.
        If test against either sig or checksum fails - raise IOError.
        Return: file contents.
    """
    contents_buffer = None
    with open_for_read_file_or_url(in_url, translate_url_callback) as rfd:
        contents_buffer = rfd.read()
        #print("After reading",in_url, "contents_buffer has", len(contents_buffer), "bytes", file=sys.stderr)
        if contents_buffer:
            # check sig or checksum only if they were given
            if (public_key, textual_sig, expected_checksum) != (None, None, None):
                buffer_ok = check_buffer_signature_or_checksum(contents_buffer, public_key, textual_sig, expected_checksum)
                if not buffer_ok:
                    raise IOError("Checksum or Signature mismatch", in_url)
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
            os.remove(in_local_path)
        fileExists = fileOK

    if not fileExists:
        contents_buffer = read_from_file_or_url(in_url, translate_url_callback, public_key, textual_sig, expected_checksum)
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
        Adding items the end of the list (by append, extend) will do nothing if the
            item is already in the list.
        Adding to the middle of the list (insert, __setitem__)
            will remove previous item with the same value - if any.
    """
    __slots__ = ('__attendance',)

    def __init__(self, initial_list=()):
        super(unique_list, self).__init__()
        self.__attendance = set()
        self.extend(initial_list)

    def __setitem__(self, index, item):
        prev_item = self[index]
        if prev_item != item:
            if item in self.__attendance:
                prev_index_for_item = self.index(item)
                super(unique_list, self).__setitem__(index, item)
                del self[prev_index_for_item]
                self.__attendance.add(item)
            else:
                super(unique_list, self).__setitem__(index, item)
                self.__attendance.remove(prev_item)
                self.__attendance.add(item)

    def __delitem__(self, index):
        super(unique_list, self).__delitem__(index)
        self.__attendance.remove(self[index])

    def __contains__(self, item):
        """ Overriding __contains__ is not required - just more efficient """
        return item in self.__attendance

    def append(self, item):
        if item not in self.__attendance:
            super(unique_list, self).append(item)
            self.__attendance.add(item)

    def extend(self, items=()):
        for item in items:
            if item not in self.__attendance:
                super(unique_list, self).append(item)
                self.__attendance.add(item)

    def insert(self, index, item):
        if item in self.__attendance:
            prev_index_for_item = self.index(item)
            if index != prev_index_for_item:
                super(unique_list, self).insert(index, item)
                if prev_index_for_item < index:
                    super(unique_list, self).__delitem__(prev_index_for_item)
                else:
                    super(unique_list, self).__delitem__(prev_index_for_item+1)
        else:
            super(unique_list, self).insert(index, item)
            self.__attendance.add(item)

    def remove(self, item):
        if item in self.__attendance:
            super(unique_list, self).remove(item)
            self.__attendance.remove(item)

    def pop(self, index=-1):
        self.__attendance.remove(self[index])
        return super(unique_list, self).pop(index)

    def count(self, item):
        """ Overriding count is not required - just more efficient """
        return self.__attendance.count(item)

    def sort(self, cmp=None, key=None, reverse=False):
        """ Sometimes sort is needed after all ... """
        super(unique_list, self).sort(cmp, key, reverse)

    def empty(self):
        return len(self.__attendance) == 0


class set_with_order(unique_list):
    """ Just another name for unique_list """
    def __init__(self, initial_list=()):
        super(set_with_order, self).__init__(initial_list)


def print_var(var_name):
    calling_frame = sys._getframe().f_back
    var_val = calling_frame.f_locals.get(var_name, calling_frame.f_globals.get(var_name, None))
    print (var_name+':', str(var_val))


def last_url_item(url):
    url = url.strip("/")
    url_path = urlparse.urlparse(url).path
    _, retVal = os.path.split(url_path)
    return retVal


def main_url_item(url):
    try:
        parseResult = urlparse.urlparse(url)
        #print("+++++++", url, "+", parseResult)
        retVal = parseResult.netloc
        if not retVal:
            retVal = parseResult.path
    except:
        retVal = ""
    return retVal


def relative_url(base, target):
    base_path = urlparse.urlparse(base.strip("/")).path
    target_path = urlparse.urlparse(target.strip("/")).path
    retVal = None
    if target_path.startswith(base_path):
        retVal = target_path.replace(base_path, '', 1)
        retVal = retVal.strip("/")
    return retVal


def deprecated(deprecated_func):
    def raise_deprecation(*unused_args, **unused_kargs):
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


def safe_makedirs(path_to_dir):
    """ solves a problem with python 2.7 where os.makedirs raises if the dir already exist  """
    try:
        os.makedirs(path_to_dir)
    except:  # os.makedirs raises is the directory already exists
        pass
    return path_to_dir


def safe_remove_file(path_to_file):
    """ solves a problem with python 2.7 where os.remove raises if the file does not exist  """
    try:
        os.remove(path_to_file)
    except:  # os.remove raises is the file does not exists
        pass
    return path_to_file


def max_widths(list_of_lists):
    """ inputs is a list of lists. output is a list of maximum str length for each
        position. E.g (('a', 'ccc'), ('bb', a', 'fff')) will return: (2, 3, 3)
    """
    loggest_list_len = reduce(max, [len(alist) for alist in list_of_lists])
    retVal = [0] * loggest_list_len  # pre allocate the max list length
    for alist in list_of_lists:
        for item in enumerate(alist):
            retVal[item[0]] = max(retVal[item[0]], len(str(item[1])))
    return retVal


def gen_col_format(width_list):
    """ generate a list of format string where each position is aligned to the adjacent
        position in the width_list.
    """
    retVal = list()
    format_str = ""
    retVal.append(format_str)
    for width in width_list:
        format_str += "{{:<{width}}}".format(width=width+1)
        retVal.append(format_str)
    return retVal


def ContinuationIter(the_iter, continuation_value=None):
    """ ContinuationIter yield all the values of the_iter and then continue yielding continuation_value
    """
    for val in the_iter:
        yield val
    while True:
        yield continuation_value


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
    except:
        return False


def check_buffer_signature_or_checksum(buff, public_key=None, textual_sig=None, expected_checksum=None):
    retVal = False
    if public_key and textual_sig:
        retVal = check_buffer_signature(buff, textual_sig, public_key)
    elif expected_checksum:
        retVal = check_buffer_checksum(buff, expected_checksum)
    return retVal


def check_file_signature_or_checksum(file_path, public_key=None, textual_sig=None, expected_checksum=None):
    retVal = False
    with open(file_path, "rb") as rfd:
        retVal = check_buffer_signature_or_checksum(rfd.read(), public_key, textual_sig, expected_checksum)
    return retVal


def check_file_checksum(file_path, expected_checksum):
    retVal = False
    with open(file_path, "rb") as rfd:
        retVal = check_buffer_checksum(rfd.read(), expected_checksum)
    return retVal


def get_file_checksum(file_path):
    with open(file_path, "rb") as rfd:
        retVal = get_buffer_checksum(rfd.read())
    return retVal


def check_file_signature(file_path, textual_sig, public_key):
    retVal = False
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


def quoteme_double(to_quote):
    return "".join(('"', to_quote, '"'))

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


def make_one_list(*things):
    """ flatten things to one single list.
    """
    retVal = list()
    for thing in things:
        if isinstance(thing, collections.Iterable) and not isinstance(thing, basestring):
            retVal.extend(thing)
        else:
            retVal.append(thing)
    return retVal


def P4GetPathFromDepotPath(depot_path):
    retVal = None
    command_parts = ["p4", "where", depot_path]
    proc = subprocess.Popen(command_parts, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    _stdout, _stderr = proc.communicate()
    retcode = proc.returncode
    if retcode == 0:
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


def convert_to_str_unless_None(to_convert):
    if to_convert is None:
        return None
    else:
        return str(to_convert)

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
    except:
        try:
            os.chmod(fd.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except:
            print("make_open_file_read_write_for_all: failed for ", fd.name)


def timing(f):
    import time

    def wrap(*args, **kwargs):
        time1 = time.clock()
        ret = f(*args, **kwargs)
        time2 = time.clock()
        if time1 != time2:
            print ('%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0))
        else:
            print ('%s function took apparently no time at all' % (f.func_name))
        return ret
    return wrap

# compile a list of regexs to one regex. regexs are ORed
# with the | character so if any regex return true when calling
# re.search or of re.match the whole regex will return true.
def compile_regex_list_ORed(regex_list, verbose=True):
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


def get_disk_free_space(in_path):
    retVal = 0
    if 'Win' in get_current_os_names():
        secsPerClus, bytesPerSec, nFreeClus, totClus = win32file.GetDiskFreeSpace(in_path)
        retVal = secsPerClus * bytesPerSec * nFreeClus
    elif 'Mac' in get_current_os_names():
        st = os.statvfs(in_path)
        retVal = st.f_bavail * st.f_frsize
    return retVal


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
                    # print ("will remove", a_file_path)
                    os.remove(a_file_path)
    except:
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
        safe_makedirs(d_dir) # will do nothing if already exists

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
    except Exception as link_ex:
        try:
            shutil.copy2(s, d)
        except Exception as shutil_ex:
            pass
