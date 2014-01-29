#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import os
import urllib2
import re
import urlparse
import hashlib
import rsa
import base64

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

    def __init__(self, file_url, path_searcher=None):
        self.file_url = file_url
        self.fd = None
        match = self.protocol_header_re.match(self.file_url)
        if not match:  # it's a local file
            if path_searcher is not None:
                self.file_url = path_searcher.find_file(self.file_url)
            if self.file_url:
                if 'Win' in get_current_os_names():
                    self.file_url = "file:///"+os.path.abspath(self.file_url)
                else:
                    self.file_url = "file://"+os.path.realpath(self.file_url)
            else:
                raise IOError("Could not locate local file", file_url)

    def __enter__(self):
        #print("opening", self.file_url)
        self.fd = urllib2.urlopen(self.file_url)
        if "name" not in dir(self.fd) and "url" in dir(self.fd):
            self.fd.name = self.fd.url # so we can get the url with the same attribute as file object
        return self.fd

    def __exit__(self, unused_type, unused_value, unused_traceback):
        self.fd.close()

def download_from_file_or_url(in_url, in_local_path, public_key=None, textual_sig=None, expected_checksum=None):
    retVal = False
    # if local file already exists, check it's signature or checksum. If these match there is no need to download.
    fileExists = False
    if os.path.isfile(in_local_path):
        # if  public_key, textual_sig, expected_checksum are None, check_file_signature_or_checksum will return False
        fileOK = check_file_signature_or_checksum(in_local_path, public_key, textual_sig, expected_checksum)
        if not fileOK:
            os.remove(in_local_path)
        fileExists = fileOK

    if not fileExists:
        with open_for_read_file_or_url(in_url) as rfd:
            contents_buffer = rfd.read()
            if contents_buffer:
                fileOK = True
                # check sig or checksum only if they were given
                if (public_key, textual_sig, expected_checksum) != (None, None, None):
                    fileOK = check_buffer_signature_or_checksum(contents_buffer, public_key, textual_sig, expected_checksum)
                if fileOK:
                    with open(in_local_path, "wb") as wfd:
                        wfd.write(contents_buffer)

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
    retVal = ""
    try:
        parseResult = urlparse.urlparse(url)
        #print("+++++++", url, "+", parseResult)
        retVal = parseResult.netloc
        if not retVal:
            retVal = parseResult.path
        else:
            if parseResult.path:
                retVal += parseResult.path
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
    """ solves a problem with python 27 where is the dir already exists os.makedirs raises """
    try:
        os.makedirs(path_to_dir)
    except:  # os.makedirs raises is the directory already exists
        pass


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
    continue_iterables = map(ContinuationIter, iterables)
    for i in range(max_size):
        yield map(next, continue_iterables)

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

def check_buffer_checksum(buff, expected_checksum):
    checksum = get_buffer_checksum(buff)
    retVal = checksum == expected_checksum
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

def check_file_signature(file_path, textual_sig, public_key):
    retVal = False
    with open(file_path, "rb") as rfd:
        retVal = check_buffer_signature(rfd.read(), textual_sig, public_key)
    return retVal


def need_to_download_file(file_path, file_checksum):
    retVal = True
    if os.path.isfile(file_path):
        sig_dict = create_file_signatures(file_path)
        retVal =  sig_dict["sha1_checksum"] != file_checksum
    return retVal
