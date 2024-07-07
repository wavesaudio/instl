#!/usr/bin/env python3.12

import sys
import os
import re
import shutil
import time
import stat
import fnmatch
from contextlib import contextmanager
import ssl
import subprocess
from pathlib import Path
import logging

log = logging.getLogger()

import zlib
import urllib.request, urllib.error, urllib.parse

from typing import Optional, TextIO

global_acting_uid = -1
global_acting_gid = -1


def set_active_user_or_group_config_var_callback(config_var_name, config_var_value):
    try:
        if config_var_name == "ACTING_UID":
            global global_acting_uid
            global_acting_uid = int(config_var_value)
        elif config_var_name == "ACTING_GID":
            global global_acting_gid
            global_acting_gid = int(config_var_value)
    except ValueError as ex:
        # if value is not int it will not be assigned to global_acting_uid/global_acting_gid
        pass


def set_acting_ids(uid, gid):
    global global_acting_uid
    global_acting_uid = uid
    global global_acting_gid
    global_acting_gid = gid


import utils


def utf8_open_for_read(*args, **kwargs) -> TextIO:
    for _try in range(2):
        try:
            retVal = open(*args, encoding='utf-8', errors='backslashreplace', **kwargs)
            break
        except PermissionError as per_err:
            if _try == 0:
                the_path = args[0]
                from pybatch import FixAllPermissions
                with FixAllPermissions(the_path, report_own_progress=False) as fixer:
                    fixer()
            else:
                raise
        except Exception:
            raise
    return retVal


def utf8_open_for_write(*args, **kwargs) -> TextIO:
    Path(args[0]).parent.mkdir(parents=True, exist_ok=True)
    retVal = open(*args, encoding='utf-8', errors='backslashreplace', **kwargs)
    chown_chmod_on_fd(retVal)
    return retVal


def write_shell_command(cmd, output_script):
    script_start = "#!/bin/bash"
    exists = os.path.isfile(output_script)
    with utf8_open_for_write(output_script, "a") as script:
        if not exists:
            script.write(script_start + "\n")
        script.write(cmd)
    os.chmod(output_script, 0o755)


def chown_chmod_on_fd(fd, user=-1, group=-1):
    if user == -1:
        user = global_acting_uid
    if group == -1:
        group = global_acting_gid
    if user != -1 or group != -1:
        try:
            if hasattr(os, 'fchown'):
                os.fchown(fd.fileno(), user, group)
        except Exception:
            try:
                if hasattr(os, 'chown'):
                    os.chown(fd.name, user, group)
            except Exception as ex:
                log.warning(f"""chown_chmod_on_fd: chown failed for {fd.name}; {ex}""")
    try:
        if hasattr(os, 'fchmod'):
            os.fchmod(fd.fileno(),
                      stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
    except Exception:
        try:
            if hasattr(os, 'chmod'):
                os.chmod(fd.name,
                         stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except Exception as ex:
            log.warning(f"""chown_chmod_on_fd: chmod failed for {fd.name}; {ex}""")
    return f"""chown_chmod_on_fd: {fd.name} u:{user}, g:{group}"""


def chown_chmod_on_path(in_path, user=-1, group=-1):
    if user == -1:
        user = global_acting_uid
    if group == -1:
        group = global_acting_gid
    if user != -1 or group != -1:
        try:
            if isinstance(in_path, int):
                if hasattr(os, 'fchown'):
                    os.fchown(in_path, user, group)
            elif hasattr(os, 'chown'):
                os.chown(in_path, user, group)
        except Exception as ex:
            log.warning(f"""chown_chmod_on_path: chown failed for {in_path}; {ex}""")
        try:
            if hasattr(os, 'chmod'):
                os.chmod(in_path,
                         stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
        except Exception as ex:
            log.warning(f"""chown_chmod_on_path: chmod failed for {in_path}; {ex}""")


def get_file_owner(in_path):
    try:
        the_stat = os.stat(in_path)
        return f"""get_file_owner: {in_path} u:{the_stat.st_uid}, g:{the_stat.st_gid}"""
    except Exception as ex:
        return f"""get_file_owner: {in_path} Exception {ex}"""


def main_url_item(url: str) -> str:
    try:
        parseResult = urllib.parse.urlparse(url)
        retVal = parseResult.netloc
        if not retVal:
            retVal = parseResult.path
    except Exception:
        retVal = ""
    return retVal


def relative_url(base: str, target: str) -> Optional[str]:
    base_path = urllib.parse.urlparse(base.strip("/")).path
    target_path = urllib.parse.urlparse(target.strip("/")).path
    retVal = None
    if target_path.startswith(base_path):
        retVal = target_path.replace(base_path, '', 1)
        retVal = retVal.strip("/")
    return retVal


def last_url_item(url: str) -> str:
    url = url.strip("/")
    url_path = urllib.parse.urlparse(url).path
    _, retVal = os.path.split(url_path)
    return retVal


class write_to_file_or_stdout(object):
    def __init__(self, file_path, append_to_file=False) -> None:
        self.file_path = file_path
        self.append_to_file = append_to_file
        self.fd = sys.stdout

    def __enter__(self) -> TextIO:
        if self.file_path:  # if file_path is None self.fd defaults to stdout
            open_mode = 'a' if self.append_to_file else 'w'
            self.fd = utf8_open_for_write(self.file_path, open_mode)
        return self.fd

    def __exit__(self, unused_type, unused_value, unused_traceback):
        if self.file_path:
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


protocol_header_re = re.compile(r"""
                        \w+
                        ://
                        """, re.VERBOSE)


def read_file_or_url_utf8(in_file_or_url, config_vars, path_searcher=None, save_to_path=None, checksum=None,
                          connection_obj=None):
    need_to_download = not utils.check_file_checksum(save_to_path, checksum)
    if not need_to_download:
        # if save_to_path contains the correct data just read it by recursively
        # calling read_file_or_url
        return read_file_or_url_utf8(save_to_path, config_vars)
    match = protocol_header_re.match(os.fspath(in_file_or_url))
    actual_file_path = in_file_or_url
    if not match:  # it's a local file
        if path_searcher is not None:
            actual_file_path = path_searcher.find_file(actual_file_path)
        if actual_file_path:
            if 'Win' in utils.get_current_os_names():
                actual_file_path = os.path.abspath(actual_file_path)
            else:
                actual_file_path = os.path.realpath(actual_file_path)
        else:
            raise FileNotFoundError(f"Could not locate local file {in_file_or_url}")
        with utf8_open_for_read(actual_file_path, "r") as rdf:
            buffer = rdf.read()
    else:
        assert connection_obj, "no connection_obj given"
        session = connection_obj.get_session(in_file_or_url)
        response = session.get(in_file_or_url, timeout=(33.05, 180.05))
        response.raise_for_status()
        buffer = response.text
    buffer = utils.unicodify(buffer)  # make sure text is unicode
    if save_to_path and in_file_or_url != save_to_path:
        with open(save_to_path, "w") as wfd:
            utils.chown_chmod_on_fd(wfd)
            wfd.write(buffer)
    return buffer, actual_file_path


class open_for_read_file_or_url(object):

    def __init__(self, in_file_or_url, config_vars, translate_url_callback=None, path_searcher=None, encoding='utf-8',
                 verify_ssl=False) -> None:
        self.local_file_path = None
        self.url = None
        self.custom_headers = None
        self.encoding = encoding
        self.verify_ssl = verify_ssl
        self.fd = None
        self._actual_path = in_file_or_url
        match = protocol_header_re.match(os.fspath(in_file_or_url))
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
                raise FileNotFoundError(f"Could not locate local file {self.local_file_path}")
            self._actual_path = self.local_file_path
        else:
            self.url = in_file_or_url
            if translate_url_callback is not None:
                self.url, self.custom_headers = translate_url_callback(self.url, config_vars)
            self._actual_path = self.url

    def __enter__(self):
        try:
            if self.url:
                opener = urllib.request.build_opener()
                if self.custom_headers:
                    for custom_header in self.custom_headers:
                        opener.addheaders.append(custom_header)
                with patch_verify_ssl(
                        self.verify_ssl):  # if self.verify_ssl is False this will disable SSL verifications
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


def read_from_file_or_url(in_url, config_vars, translate_url_callback=None, expected_checksum=None, encoding='utf-8'):
    """ Read a file from local disk or url. Check checksum if given.
        If test against either sig or checksum fails - raise IOError.
        Return: file contents.
    """
    with open_for_read_file_or_url(in_url, config_vars, translate_url_callback, encoding=encoding) as open_file:
        contents_buffer = open_file.fd.read()
        if encoding is not None:  # when reading from url we're not sure what the encoding is
            contents_buffer = utils.unicodify(contents_buffer, encoding=encoding)
        # check checksum only if  given
        if expected_checksum is not None:
            if len(contents_buffer) == 0:
                raise IOError(
                    f"Empty contents returned from {in_url} ; expected checksum: {expected_checksum} ; encoding: {encoding}")
            if encoding is not None:
                raise IOError(
                    f"Checksum check requested for {in_url} but encoding is not None, encoding: {encoding} ; expected checksum: {expected_checksum}")
            buffer_ok = utils.check_buffer_checksum(contents_buffer, expected_checksum)
            if not buffer_ok:
                actual_checksum = utils.get_buffer_checksum(contents_buffer)
                raise IOError(
                    f"Checksum mismatch {in_url} expected checksum:  {expected_checksum} actual checksum: {actual_checksum} encoding: {encoding}")
    return contents_buffer


def download_and_cache_file_or_url(in_url, config_vars, cache_folder: Path, translate_url_callback=None,
                                   expected_checksum=None):
    """ download file to given cache folder
        if checksum is supplied and the a file with that checksum exists in cache folder - download can be avoided
        otherwise download the file
        :return: path of the downloaded file
    """
    from pybatch import MakeDir
    with MakeDir(cache_folder, report_own_progress=False) as md:
        md()

    url_file_name = last_url_item(in_url)
    cached_file_name = expected_checksum if expected_checksum else url_file_name
    cached_file_path = cache_folder.joinpath(cached_file_name)
    if expected_checksum is None:  # no checksum? -> force download
        safe_remove_file(cached_file_path)

    if cached_file_path.is_file():  # file exists? -> make sure it has the right checksum
        if not utils.check_file_checksum(cached_file_path, expected_checksum):
            safe_remove_file(cached_file_path)

    if not cached_file_path.is_file():  # need to download
        contents_buffer = read_from_file_or_url(in_url, config_vars, translate_url_callback, expected_checksum,
                                                encoding=None)
        if contents_buffer:
            with open(cached_file_path, "wb") as wfd:
                chown_chmod_on_fd(wfd)
                wfd.write(contents_buffer)
    return cached_file_path


def download_from_file_or_url(in_url, config_vars, in_target_path=None, translate_url_callback=None, cache_folder=None,
                              expected_checksum=None):
    """
        download a file from url and place it on a target path. Possibly also decompressed .wzip files.
        """

    final_file_path = None
    cached_file_path = download_and_cache_file_or_url(in_url=in_url, config_vars=config_vars,
                                                      translate_url_callback=translate_url_callback,
                                                      cache_folder=cache_folder, expected_checksum=expected_checksum)
    if not in_target_path:
        in_target_path = cache_folder
    if in_target_path:
        in_target_path = utils.ExpandAndResolvePath(in_target_path)
        url_file_name = last_url_item(in_url)
        url_base_file_name, url_extension = os.path.splitext(url_file_name)
        need_decompress = url_extension == ".wzip"
        if in_target_path.is_dir():
            target_file_name = url_base_file_name if need_decompress else url_file_name
            final_file_path = in_target_path.joinpath(target_file_name)
        else:
            final_file_path = in_target_path
            _, target_extension = os.path.splitext(final_file_path)
            if need_decompress and final_file_path.suffix == ".wzip":
                need_decompress = False  # no need to decompress if target is expected to be compressed

        if need_decompress:
            decompressed = zlib.decompress(open(cached_file_path, "rb").read())
            with open(final_file_path, "wb") as wfd:
                utils.chown_chmod_on_fd(wfd)
                wfd.write(decompressed)
        else:
            smart_copy_file(cached_file_path, final_file_path)
    else:
        final_file_path = cached_file_path
    return final_file_path


class ChangeDirIfExists(object):
    """Context manager for changing the current working directory"""

    def __init__(self, newPath: Path) -> None:
        if newPath.is_dir():
            self.newPath = newPath
        else:
            self.newPath = None

    def __enter__(self):
        if self.newPath:
            self.savedPath = os.getcwd()
            os.chdir(os.path.expandvars(self.newPath))

    def __exit__(self, etype, value, traceback):
        if self.newPath:
            os.chdir(self.savedPath)


def safe_remove_file(path_to_file, ignore_errors=True):
    """ solves a problem with python 2.7 where os.remove raises if the file does not exist  """
    try:
        os.remove(path_to_file)
    except FileNotFoundError:  # os.remove raises is the file does not exists
        pass
    except Exception as ex:
        if not ignore_errors:
            raise


def safe_remove_folder(path_to_folder, ignore_errors=True):
    try:
        shutil.rmtree(path_to_folder, ignore_errors=ignore_errors)
    except FileNotFoundError:
        pass
    except Exception as ex:
        if not ignore_errors:
            raise


def safe_remove_file_system_object(path_to_file_system_object, followlinks=False, ignore_errors=True):
    try:
        if os.path.islink(path_to_file_system_object):
            if followlinks:
                real_path = os.path.realpath(path_to_file_system_object)
                safe_remove_file_system_object(real_path, ignore_errors)
            else:
                os.unlink(path_to_file_system_object)
        elif os.path.isdir(path_to_file_system_object):
            safe_remove_folder(path_to_file_system_object, ignore_errors)
        elif os.path.isfile(path_to_file_system_object):
            safe_remove_file(path_to_file_system_object, ignore_errors)
    except Exception as ex:
        if not ignore_errors:
            raise


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
    if 'Win' in utils.get_current_os_names():
        secsPerCluster, bytesPerSec, nFreeCluster, totCluster = win32file.GetDiskFreeSpace(in_path)
        retVal = secsPerCluster * bytesPerSec * nFreeCluster
    elif 'Mac' in utils.get_current_os_names():
        st = os.statvfs(in_path)
        retVal = st.f_bavail * st.f_frsize
    return retVal


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


def find_split_files(first_file: Path):
    try:
        retVal = list()

        first_file_name = first_file.name
        first_file_dir = first_file.parent
        if first_file_name.endswith(".aa"):
            filter_pattern = first_file_name[:-2] + "??"  # with ?? instead of aa
            matching_files = sorted(fnmatch.filter((f.name for f in os.scandir(first_file_dir)), filter_pattern))
            for a_file in matching_files:
                retVal.append(first_file_dir.joinpath(a_file))
        else:
            retVal.append(first_file)
        return retVal

    except Exception as es:
        log.error(f"""exception while find_split_files {first_file}""")
        raise es


def find_split_files_from_base_file(base_file):
    split_files = list()
    try:
        wtar_first_file = base_file
        if not utils.is_first_wtar_file(wtar_first_file):
            wtar_first_file = wtar_first_file + ".wtar"
        if not os.path.isfile(wtar_first_file):
            wtar_first_file += ".aa"
        if os.path.isfile(wtar_first_file):
            split_files = find_split_files(wtar_first_file)
    except:
        pass  # no split files
    return split_files


def find_wtarred_parts_of_original(original: Path):
    parts_list = list()
    unsplit_wtar = utils.append_suffix(original, ".wtar")
    if unsplit_wtar.is_file():
        parts_list.append(unsplit_wtar)
    glob_pattern = "*" + original.name + ".wtar.??"
    glob_results = original.parent.glob(glob_pattern)
    parts_list.extend(glob_results)
    return parts_list


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
            yield from scandir_walk(item.path, report_files=report_files, report_dirs=report_dirs,
                                    follow_symlinks=follow_symlinks)


def translate_cookies_from_GetInstlUrlComboCollection(in_cookies):
    netloc = in_cookies['ResourceRootUrl']
    cookies_list = list()
    for k, v in in_cookies.items():
        if isinstance(v, dict):
            if 'Value' in v and 'Key' in v:
                cookies_list.append("=".join((v['Key'], v['Value'])))

    retVal = f"""{netloc}:{";".join(cookies_list)}"""
    return retVal


def ExpandAndResolvePath(path_to_resolve, resolve_path=True) -> Path:
    """ return a Path object after calling
        os.path.expandvars to expand environment variables
        and Path. resolve to resolve relative paths and
    """
    # repeat calling os.path.expandvars until no change
    # because os.path.expandvars does not expand recursively
    before_expand = os.fspath(path_to_resolve)
    expanded_path = os.path.expandvars(path_to_resolve)
    while before_expand != expanded_path:
        before_expand = expanded_path
        expanded_path = os.path.expandvars(expanded_path)

    path_path = Path(expanded_path)
    if resolve_path:
        path_path = path_path.resolve()
    return path_path


def get_main_drive_name():
    retVal = None
    try:
        if sys.platform == 'darwin':
            with os.scandir("/Volumes") as it:
                for volume in it:
                    if volume.is_symlink():
                        resolved_volume_path = Path("/Volumes", volume.name).resolve()
                        if str(resolved_volume_path) == "/":
                            retVal = volume.name
                            break
                else:
                    apple_script = """osascript -e 'return POSIX file (POSIX path of "/") as Unicode text' """
                    completed_process = subprocess.run(apple_script, stdout=subprocess.PIPE, shell=True)
                    retVal = utils.unicodify(completed_process.stdout)
                    retVal = retVal.strip("\n:")
        elif sys.platform == 'win32':
            import win32api
            retVal = win32api.GetVolumeInformation("C:\\")[0]
    except:
        pass
    return retVal


def append_suffix(in_path: Path, new_suffix: str):
    suffixes = in_path.suffixes
    suffixes.append(new_suffix)
    new_name = in_path.stem + "".join(suffixes)
    new_path = in_path.parent.joinpath(new_name)
    return new_path


def set_max_open_files(new_max_open_files):
    # doe nto work yet...
    if sys.platform == 'darwin':
        # on Mac resource.setrlimit returns hard limit of 9223372036854775807 which means unlimited
        # however there is some secret (no API) maximum on the soft limit, so increasing must be done gradually
        try:
            import resource
            max_files_soft, max_files_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            print(f"max open files was {max_files_soft}")
            while new_max_open_files > max_files_soft:
                max_files_soft += min(1, new_max_open_files - max_files_soft)
                print(f"increasing to {max_files_soft}")
                resource.setrlimit(resource.RLIMIT_NOFILE, max_files_soft, max_files_hard)
        except:
            print(f"failed to increase max open files to {max_files_soft}")
        max_files_soft, max_files_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        print(f"max open files is now {max_files_soft}")


@contextmanager
def trace_file_open(_callback=None):
    if _callback:
        import builtins
        save_builtin_open = builtins.open

        def open_override(*args, **kwargs):
            _callback(*args, **kwargs)
            return save_builtin_open(*args, **kwargs)

        builtins.open = open_override

    yield

    if _callback:
        builtins.open = save_builtin_open


def safe_getcwd(return_on_error="os.getcwd() failed", ignore_exceptions=True):
    """ weird as it maybe os.getcwd() might fail with FileNotFoundError
        this will happen if the current working dir was deleted - probably
        from outside out program.
    """
    retVal = None
    try:
        retVal = os.getcwd()
    except FileNotFoundError as fnf:
        if ignore_exceptions:
            if return_on_error:
                retVal = return_on_error
        else:
            raise
    return retVal


def who_locks_file(in_file_path, in_dll_path):
    """ windows only function to return the process that locks a file
        :param in_file_path: file to check
        :param in_dll_path: path to dll that implements the who_locks_file function
        :return: dict with lock information for the file
        :except function never raises exception, field "error" in return value will indicate an error
    """
    retVal = dict()
    try:
        import ctypes
        if not Path(in_dll_path).is_file():
            retVal["error"] = f"who_locks_file.dll not found {in_dll_path}"
        elif not Path(in_file_path).is_file():
            retVal["error"] = f"file not found {in_file_path}"
        else:
            who_locks_file_dll = ctypes.WinDLL(os.fspath(in_dll_path))
            replay_max_size = 260 * 128 * 2
            the_reply = ctypes.create_string_buffer(
                replay_max_size)  # supposedly enough for two long-form paths: the file and the process
            file_path_c_wchar_p = ctypes.c_wchar_p(os.fspath(in_file_path))
            ret_code = who_locks_file_dll.who_locks_file_json(file_path_c_wchar_p, the_reply, replay_max_size)
            if 0 == ret_code:
                import json
                return_value_str = bytes(the_reply.value).decode('utf-8')
                return_value_json = json.loads(return_value_str)
                retVal.update(return_value_json)
            else:
                retVal["error"] = ret_code
    except Exception as ex:
        retVal["error"] = str(ex)

    return retVal


def wait_for_break_file_to_be_removed(path_to_break_file, progress_callback=None):
    """ while path_to_break_file exist, sleep 1 second and call progress_callback"""
    if progress_callback is None:
        progress_callback = print
    path_to_break_file = Path(path_to_break_file)
    num_sleeps = 0
    while path_to_break_file.is_file():
        num_sleeps += 1
        progress_callback(f"{num_sleeps} found break file: {path_to_break_file}")
        time.sleep(1)
    if num_sleeps > 0:
        progress_callback(f"break file is gone {path_to_break_file}")
