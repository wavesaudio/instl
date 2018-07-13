#!/usr/bin/env python3

import sys
import os
import re
import shutil
import time
import stat
import fnmatch
from contextlib import contextmanager
import ssl
import pyinstl.connectionBase
#from pyinstl import connection_factory
import zlib

import urllib.request, urllib.error, urllib.parse

import utils


def utf8_open(*args, **kwargs):
    return open(*args, encoding='utf-8', errors='namereplace', **kwargs)


def main_url_item(url):
    try:
        parseResult = urllib.parse.urlparse(url)
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


def last_url_item(url):
    url = url.strip("/")
    url_path = urllib.parse.urlparse(url).path
    _, retVal = os.path.split(url_path)
    return retVal


class write_to_file_or_stdout(object):
    def __init__(self, file_path):
        self.file_path = file_path
        self.fd = sys.stdout

    def __enter__(self):
        if self.file_path != "stdout":
            self.fd = utf8_open(self.file_path, "w")
        return self.fd

    def __exit__(self, unused_type, unused_value, unused_traceback):
        if self.file_path != "stdout":
            self.fd.close()


@contextmanager
def patch_verify_ssl(verify_ssl):
    """ if verify_ssl is False, patch ssl._create_default_https_context to be
        ssl._create_unverified_context and un-patch after it was used
    """
    if not verify_ssl:
        original_create_default_https_context = ssl._create_default_https_context
        ssl._create_default_https_context = ssl._create_unverified_context
    yield
    if not verify_ssl:
        ssl._create_default_https_context = original_create_default_https_context


protocol_header_re = re.compile("""
                        \w+
                        ://
                        """, re.VERBOSE)


def read_file_or_url(in_file_or_url, path_searcher=None, encoding='utf-8', save_to_path=None, checksum=None):
    need_to_download = not utils.check_file_checksum(save_to_path, checksum)
    if not need_to_download:
        # if save_to_path contains the correct data just read it by recursively
        # calling read_file_or_url
        return read_file_or_url(save_to_path, encoding=encoding)
    match = protocol_header_re.match(os.fspath(in_file_or_url))
    if not match:  # it's a local file
        local_file_path = in_file_or_url
        if path_searcher is not None:
            local_file_path = path_searcher.find_file(local_file_path)
        if local_file_path:
            if 'Win' in utils.get_current_os_names():
                local_file_path = os.path.abspath(local_file_path)
            else:
                local_file_path = os.path.realpath(local_file_path)
        else:
            raise FileNotFoundError("Could not locate local file", local_file_path)
        if encoding is None:
            read_mod = "rb"
        else:
            read_mod = "r"
        with open(local_file_path, "r", encoding=encoding) as rdf:
            buffer = rdf.read()
    else:
        session = connection_factory().get_session(in_file_or_url)
        response = session.get(in_file_or_url, timeout=(33.05, 180.05))
        response.raise_for_status()
        buffer = response.text
    buffer = utils.unicodify(buffer) # make sure text is unicode
    if save_to_path and in_file_or_url != save_to_path:
        with open(save_to_path, "w") as wfd:
            wfd.write(buffer)
    return buffer


class open_for_read_file_or_url(object):

    def __init__(self, in_file_or_url, translate_url_callback=None, path_searcher=None, encoding='utf-8', verify_ssl=False):
        self.local_file_path = None
        self.url = None
        self.custom_headers = None
        self.encoding = encoding
        self.verify_ssl = verify_ssl
        self.fd = None
        self._actual_path = in_file_or_url
        match = protocol_header_re.match(in_file_or_url)
        if not match:  # it's a local file
            self.local_file_path = in_file_or_url
            if path_searcher is not None:
                self.local_file_path = path_searcher.find_file(self.local_file_path)
            if self.local_file_path:
                if 'Win' in utils.get_current_os_names():
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
                with patch_verify_ssl(self.verify_ssl):  # if self.verify_ssl is False this will disable SSL verifications
                    # crud retry mechanism, should be improved, use requests?
                    retries = 12
                    while retries > 0:
                        try:
                            retries -= 1
                            self.fd = opener.open(self.url, timeout=32)
                            retries = 0
                        except:
                            if retries == 0:
                                raise
                            else:
                                time.sleep(1.0)

            elif self.local_file_path:
                if self.encoding is None:
                    self.fd = open(self.local_file_path, "rb")
                else:
                    self.fd = open(self.local_file_path, "r", encoding=self.encoding)
        except urllib.error.URLError as url_err:
            print(url_err, self.url)
            raise
        if "name" not in dir(self.fd) and "url" in dir(self.fd):
            self.fd.name = self.fd.url  # so we can get the url with the same attribute as file object
        return self

    def __exit__(self, unused_type, unused_value, unused_traceback):
        self.fd.close()

    @property
    def actual_path(self):
        """ return the path or url after all translations and search paths searches"""
        return self._actual_path


def read_from_file_or_url(in_url, translate_url_callback=None, expected_checksum=None, encoding='utf-8'):
    """ Read a file from local disk or url. Check checksum if given.
        If test against either sig or checksum fails - raise IOError.
        Return: file contents.
    """
    with open_for_read_file_or_url(in_url, translate_url_callback, encoding=encoding) as open_file:
        contents_buffer = open_file.fd.read()
        if encoding is not None:  # when reading from url we're not sure what the encoding is
            contents_buffer = utils.unicodify(contents_buffer, encoding=encoding)
        # check sig or checksum only if they were given
        if expected_checksum is not None:
            if len(contents_buffer) == 0:
                raise IOError("Empty contents returned from", in_url, "; expected checksum: ", expected_checksum, "; encoding:", encoding)
            if encoding is not None:
                raise IOError("Checksum check requested for", in_url, "but encoding is not None, encoding:", encoding, "; expected checksum: ", expected_checksum)
            buffer_ok = utils.check_buffer_checksum(contents_buffer, expected_checksum)
            if not buffer_ok:
                actual_checksum = utils.get_buffer_checksum(contents_buffer)
                raise IOError("Checksum mismatch", in_url, "expected checksum: ", expected_checksum,
                              "actual checksum:", actual_checksum, "encoding:", encoding)
    return contents_buffer


def download_and_cache_file_or_url(in_url, cache_folder, translate_url_callback=None, expected_checksum=None):
    """ download file to given cache folder
        if checksum is supplied and the a file with that checksum exists in cache folder - download can be avoided
        otherwise download the file
        :return: path of the downloaded file
    """

    if os.path.isfile(cache_folder):  # happens sometimes...
        safe_remove_file(cache_folder)
    if not os.path.isdir(cache_folder):
        os.makedirs(cache_folder, exist_ok=True)

    url_file_name = last_url_item(in_url)
    cached_file_name = expected_checksum if expected_checksum else url_file_name
    cached_file_path = os.path.join(cache_folder, cached_file_name)
    if expected_checksum is None:  # no checksum? -> force download
        safe_remove_file(cached_file_path)

    if os.path.isfile(cached_file_path):  # file exists? -> make sure it has the right checksum
        if not utils.check_file_checksum(cached_file_path, expected_checksum):
            safe_remove_file(cached_file_path)

    if not os.path.isfile(cached_file_path):  # need to download
        contents_buffer = read_from_file_or_url(in_url, translate_url_callback, expected_checksum, encoding=None)
        if contents_buffer:
            with open(cached_file_path, "wb") as wfd:
                make_open_file_read_write_for_all(wfd)
                wfd.write(contents_buffer)
    return cached_file_path


def download_from_file_or_url(in_url, in_target_path=None, translate_url_callback=None, cache_folder=None, expected_checksum=None):
    """
        download a file from url and place it on a target path. Possibly also decompressed .wzip files.
        """

    cached_file_path = download_and_cache_file_or_url(in_url=in_url, translate_url_callback=translate_url_callback, cache_folder=cache_folder, expected_checksum=expected_checksum)
    if not in_target_path:
        in_target_path = cache_folder
    if in_target_path:
        url_file_name = last_url_item(in_url)
        url_base_file_name, url_extension = os.path.splitext(url_file_name)
        need_decompress = url_extension == ".wzip"
        if os.path.isdir(in_target_path):
            target_file_name = url_base_file_name if need_decompress else url_file_name
            final_file_path = os.path.join(in_target_path, target_file_name)
        else:
            final_file_path = in_target_path
            _, target_extension = os.path.splitext(final_file_path)
            if need_decompress and target_extension == ".wzip":
                need_decompress = False  # no need to decompress if target is expected to be compressed

        if need_decompress:
            decompressed = zlib.decompress(open(cached_file_path, "rb").read())
            with open(final_file_path, "wb") as wfd:
                wfd.write(decompressed)
        else:
            smart_copy_file(cached_file_path, final_file_path)
    else:
        final_file_path = cached_file_path
    return final_file_path


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
    except Exception:
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
    except Exception:
        pass


def make_open_file_read_write_for_all(fd):
    try:
        os.fchmod(fd.fileno(), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
    except Exception:
        try:
            os.chmod(fd.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except Exception:
            print("make_open_file_read_write_for_all: failed for ", fd.name)


def excluded_walk(root_to_walk, file_exclude_regex=None, dir_exclude_regex=None, followlinks=False):
    """ excluded_walk behaves like os.walk but will exclude files or dirs who's name pass the given regexs
    :param root_to_walk: the root folder to walk, this folder will *not* be tested against dir_exclude_regex
    :param file_exclude_regex: a regex to test files. Any file that matches this regex will not be returned
    :param dir_exclude_regex: a regex to test folders. Any folder that matches this regex will not be returned
    :param followlinks: passed directly to os.walk
    :yield: a tuple of (root, dirs, files) - just like os.walk
    """

    if file_exclude_regex is None:  # if file_exclude_regex is None all files should be included
        file_exclude_regex = re.compile("a^")

    if dir_exclude_regex is None:  # if file_exclude_regex is None all files should be included
        dir_exclude_regex = re.compile("a^")

    for root, dirs, files in os.walk(root_to_walk, followlinks=followlinks):
        dirs[:] = sorted([a_dir for a_dir in dirs if not dir_exclude_regex.search(a_dir)])
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
    else:  # assume destination is a non-existing file
        d = destination_path
        d_dir, d_name = os.path.split(destination_path)
        os.makedirs(d_dir, exist_ok=True)

    try:
        getattr(os, "link")  # will raise on windows, os.link is not always available (Win)
        if d_file_exists:
            if os.stat(s).st_ino != os.stat(d).st_ino:
                safe_remove_file(d)
                os.link(s, d)  # will raise if different drives
            else:
                pass  # same inode no need to copy
        else:
            os.link(s, d)
    except Exception:
        try:
            shutil.copy2(s, d)
        except Exception:
            pass


def find_split_files(first_file):
    try:
        retVal = list()
        norm_first_file = os.path.normpath(first_file)  # remove trailing . if any

        if norm_first_file.endswith(".aa"):
            base_folder, base_name = os.path.split(norm_first_file)
            if not base_folder:
                base_folder = "."
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


def find_split_files_from_base_file(base_file):
    split_files = list()
    try:
        wtar_first_file = base_file+".wtar"
        if not os.path.isfile(wtar_first_file):
            wtar_first_file += ".aa"
        if os.path.isfile(wtar_first_file):
            split_files = find_split_files(wtar_first_file)
    except:
        pass  # no split files
    return split_files


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


def translate_cookies_from_GetInstlUrlComboCollection(in_cookies):
    netloc = in_cookies['ResourceRootUrl']
    cookies_list = list()
    for k,v in in_cookies.items():
        if isinstance(v, dict):
            if 'Value' in v and 'Key' in v:
                cookies_list.append("=".join((v['Key'], v['Value'])))

    retVal = f"""{netloc}:{";".join(cookies_list)}"""
    return retVal


class WavesCentralRequester(object):
    def __init__(self, domain):
        self.domain = domain
        self.namespace = "Central/Central.svc"
        self.url_template = 'https://{self.domain}/{self.namespace}/{func}'
        self.standard_headers = {"Content-Type": "application/json"}
        self.time_token = None
        self.user_guid = None

    def request(self, func, data={}):
        import json
        import requests
        url = self.url_template.format(**locals())
        the_data = dict(data)
        if self.time_token:
            the_data['TimeToken'] = self.time_token
        if self.user_guid:
            the_data['UserGuid'] = self.user_guid
        data_string = json.dumps(the_data)
        response = requests.post(url, data=data_string, headers=self.standard_headers)
        response.raise_for_status()
        reply_data = response.json()
        IsSuccess = reply_data.get('IsSuccess', False)
        if IsSuccess:
            self.time_token = reply_data.get('TimeToken', self.time_token)
            #print("time_token:", self.time_token)
            if 'oResult' in reply_data and isinstance(reply_data['oResult'], dict):
                self.user_guid = reply_data.get('oResult', {}).get('UserGuid', self.user_guid)
                #print("new user guid:", self.user_guid)
            return reply_data

if __name__ == "__main__":
    import re
    from configVar import config_vars  # √
    repo_rev_re = re.compile("^(REPO_REV:\s+\d+)", re.MULTILINE)
    index_yaml_re = re.compile("^(NUMBER_OF_BITS:\s+.+)", re.MULTILINE)

    domain = "betanlb.waves.com"
    reqs = WavesCentralRequester(domain)
    login_data = reqs.request("Login", {"Password": "ShaiShasag1", "Username": "ShaiShasag"})

    # GetInstlUrlComboCollection
    combo_data = reqs.request("GetInstlUrlComboCollection", {'repositoryRevision': '-1', "repositoryVersions":[9]})
    #print("combo_data:\n", combo_data)
    InstlUrlAccessParameters = combo_data['oResult'][0]['InstlUrlAccessParameters']
    repo_rev_yaml_url = "https://" + InstlUrlAccessParameters['ResourceRootUrl'] + "/admin/V10_repo_rev.yaml"
    index_yaml_url = "https://" + InstlUrlAccessParameters['ResourceRootUrl'] + "/V10/795/instl/index.yaml"

    netloc_and_cookies = translate_cookies_from_GetInstlUrlComboCollection(InstlUrlAccessParameters)
    config_vars["COOKIE_JAR"] = netloc_and_cookies

    the_text = utils.read_file_or_url(repo_rev_yaml_url)
    print(the_text.name, repo_rev_re.search(the_text).groups(1)[0])

    the_text = utils.read_file_or_url(index_yaml_url)
    print("index.yaml:", index_yaml_re.search(the_text).groups(1)[0])

    local_index = "/Volumes/BonaFide/installers/betainstl/V10/svn/instl/index.yaml"
    the_text = utils.read_file_or_url(local_index)
    print("local index.yaml:", index_yaml_re.search(the_text).groups(1)[0])
