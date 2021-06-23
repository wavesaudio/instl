#!/usr/bin/env python3.9

import sys
import os
import time
import datetime
import stat
import json
import tarfile
import re
from pathlib import Path, PurePath

import utils


def disk_item_listing(files_or_folder_to_list, ls_format='*', output_format='text'):
    """ Create a manifest of one or more folders or files
        Format is a sequence of characters each specifying what details to include.
        Details are listed in the order they appear in, unless specified as non-positional.
    Options are:
    'C': sha1 checksum (files only)
    'D': Mac: if 'P' or 'p' is given "/" is appended to the path if item is a directory, non-positional
         Win: <DIR> if item is directory empty string otherwise
    'd': list only directories not files, non-positional.
    'E': Mac: if 'P' or 'p' is given extra character is appended to the path, '@' for link, '*' for executable, '=' for socket, '|' for FIFO
         Win: Not applicable
    'f': list only files not directories, non-positional.
    'g': Mac: gid
         Win: Not applicable
    'G': Mac: Group name or gid if name not found
         Win: domain+"\\"+group name
    'I': inode number (Mac only)
    'L': Mac: number of links
         Win: Not applicable
    'M': a remark beginning in '#' and containing the data & time when the listing was done and the path to the item listed
        non-positional. The remark appears before each top level item.
        If the item was not found a remark will be written any way
    'P': full path to the item
    'p': partial path to the item - relative to the top folder listed, or if top item is a file - the file name without the path
    'R': Mac: item's permissions in the format (-|d|l)rwxrwxrwx
         Win: Not applicable
    'S': size in bytes
    'T': modification time, format is "%Y/%m/%d-%H:%M:%S" as used by time.strftime
    'u': Mac: uid
         Win: Not applicable
    'U': Mac: User name or uid if name not found
         Win: domain+"\\"+user name
    'W': for wtar files only, total checksum
    '*' if ls_format contains only '*' it is and alias to the default and means:
        Mac: MIRLUGSTCPE
        Win: MTDSUGCP
    Note: if both 'd' and 'f' are not in ls_format disk_item_listing will act as if both are in ls_format
            so 'SCp' actually means 'SCpfd'
    """
    os_names = utils.get_current_os_names()
    folder_ls_func = None
    item_ls_func = None
    if "Mac" in os_names:
        if ls_format == '*':
            ls_format = 'MIRLUGSTCPE'
        folder_ls_func = unix_folder_ls
        item_ls_func = unix_item_ls
    elif "Win" in os_names:
        if ls_format == '*':
            ls_format = 'MTDSUGCP'
        folder_ls_func = win_folder_ls
        item_ls_func = win_item_ls

    if 'f' not in ls_format and 'd' not in ls_format:
        ls_format += 'fd'
    add_remarks = 'M' in ls_format
    ls_format = ls_format.replace('M', '')

    listing_items = list()
    error_items = list()
    opening_remarks = list()

    if add_remarks:
        opening_remarks.append(f"""# {datetime.datetime.today().isoformat()} listing of {files_or_folder_to_list}""")

    if utils.is_first_wtar_file(files_or_folder_to_list):
        listing_items, error_items = wtar_ls_func(files_or_folder_to_list, ls_format=ls_format)
    elif files_or_folder_to_list.is_dir():
        listing_items, error_items = folder_ls_func(files_or_folder_to_list, ls_format=ls_format, root_folder=files_or_folder_to_list)
    elif files_or_folder_to_list.is_file() and 'f' in ls_format:
        root_folder, _ = os.path.split(files_or_folder_to_list)
        listings, errors = item_ls_func(files_or_folder_to_list, ls_format=ls_format, root_folder=root_folder)
        listing_items.append(listings)
        error_items.append(errors)
    else:
        opening_remarks.append(f"""# folder was not found {files_or_folder_to_list}""")
    if error_items:
        opening_remarks.append(f"error listing {len(error_items)} of {len(listing_items)+len(error_items)} items")

    total_list = list()
    if output_format == 'text':
        total_list.extend(opening_remarks)
        total_list.extend("Error: " + ", ".join(error) for error in error_items)
        total_list.extend(list_of_dicts_describing_disk_items_to_text_lines(listing_items, ls_format))
        total_list.append("")  # line break at the end so not to be joined with the next line when printing to Terminal
    elif output_format == 'dicts':
        total_list.extend("Error: " + ", ".join(error) for error in error_items)
        for item in listing_items:
            total_list.append(translate_item_dict_to_be_keyed_by_path(item))
    elif output_format == 'json':
        total_list.extend({"Error": + ", ".join(error) for error in error_items})
        total_list.append({os.fspath(files_or_folder_to_list): translate_json_key_names(listing_items)})

    if output_format == 'text':
        retVal = "\n".join(total_list)
    elif output_format == 'dicts':
        retVal = total_list
    elif output_format == 'json':
        output_json = json.dumps(total_list, indent=1, default=utils.extra_json_serializer)
        retVal = output_json
    return retVal


def item_dict_to_list(item_dict, ls_format):
    retVal = list()
    for format_char in ls_format:
        if format_char in item_dict:
            retVal.append(item_dict[format_char])
    return retVal


def translate_item_dict_to_be_keyed_by_path(item_dict):
    retVal = item_dict
    path = item_dict.get('P', item_dict.get('p', None))
    if path:
        item_dict_without_path = {k: v for k, v in item_dict.items() if k.lower() != 'p'}
        retVal = {path: item_dict_without_path}
    return retVal


def list_of_dicts_describing_disk_items_to_text_lines(items_list, ls_format):
    # when calculating widths - avoid comment lines
    real_line_list = list()  # lines that are not empty or comments
    # when printing - avoid formatting of comment lines or empty lines (empty lines might be created by weird ls_format)
    for item_dict in items_list:
        if item_dict:
            real_line_list.append(item_dict_to_list(item_dict, ls_format))
    width_list, align_list = utils.max_widths(real_line_list)
    col_formats = utils.gen_col_format(width_list, align_list)
    formatted_lines = list()
    for ls_line in real_line_list:
        formatted_lines.append(col_formats[len(ls_line)].format(*ls_line))
    return formatted_lines


format_char_to_json_key = {
    'a': 'attribs',  # sames as f - flags
    'C': 'checksum',
    'D': 'DIR',
    'g': 'gid',
    'f': 'flags',  # sames as a - attribs
    'G': 'group',
    'I': 'inode',
    'L': 'num links',
    'P': 'full path',
    'p': 'relative path',
    'R': 'permissions',
    'S': 'size',
    'T': 'modification time',
    'W': 'total_checksum',  # for wtars only
    'u': 'uid',
    'U': 'user'
}


def translate_json_key_names(items_list):
    retVal = list()
    for item in items_list:
        retVal.append({format_char_to_json_key[k]: v for k, v in item.items()})
    return retVal


def unix_folder_ls(the_path, ls_format, root_folder=None):
    listing_lines = list()
    error_lines = list()
    try:
        for root_path, dirs, files in os.walk(the_path, followlinks=False):
            dirs = sorted(dirs, key=lambda s: s.lower())
            if 'd' in ls_format:
                listings, errors = unix_item_ls(root_path, ls_format=ls_format, root_folder=root_folder)
                if errors:
                    error_lines.append(errors)
                else:
                    listing_lines.append(listings)
            if 'f' in ls_format:
                files_to_list = sorted(files + [slink for slink in dirs if os.path.islink(os.path.join(root_path, slink))], key=lambda s: s.lower())
                for file_to_list in files_to_list:
                    full_path = os.path.join(root_path, file_to_list)
                    listings, errors = unix_item_ls(full_path, ls_format=ls_format, root_folder=root_folder)
                    if errors:
                        error_lines.append(errors)
                    else:
                        listing_lines.append(listings)

    except Exception as ex:
        error_lines.append([the_path, ex.strerror])

    return listing_lines, error_lines


def unix_item_ls(the_path, ls_format, root_folder=None):
    import grp
    import pwd

    the_parts = dict()
    the_error = None
    the_path_str = os.fspath(the_path)
    if 'p' in ls_format:
        the_parts['p'] = the_path_str
    elif 'P' in ls_format:
        the_parts['P'] = the_path_str

    try:
        the_stats = os.lstat(the_path)

        for format_char in ls_format:
            if format_char == 'I':
                the_parts[format_char] = the_stats[stat.ST_INO]  # inode number
            elif format_char == 'R':
                the_parts[format_char] = utils.unix_permissions_to_str(the_stats.st_mode)  # permissions
            elif format_char == 'L':
                the_parts[format_char] = the_stats[stat.ST_NLINK]  # num links
            elif format_char == 'u':
                try:
                    the_parts[format_char] = str(the_stats[stat.ST_UID])[0]  # unknown user name, get the number
                except Exception:
                    the_parts[format_char] = "no_uid"
            elif format_char == 'U':
                try:
                    the_parts[format_char] = pwd.getpwuid(the_stats[stat.ST_UID])[0]  # user
                except KeyError:
                    the_parts[format_char] = str(the_stats[stat.ST_UID])[0]  # unknown user name, get the number
                except Exception:
                    the_parts[format_char] = "no_uid"
            elif format_char == 'g':
                try:
                    the_parts[format_char] = str(the_stats[stat.ST_GID])[0]  # unknown group name, get the number
                except Exception:
                    the_parts[format_char] = "no_gid"
            elif format_char == 'G':
                try:
                    the_parts[format_char] = grp.getgrgid(the_stats[stat.ST_GID])[0]  # group
                except KeyError:
                    the_parts[format_char] = str(the_stats[stat.ST_GID])[0]  # unknown group name, get the number
                except Exception:
                    the_parts[format_char] = "no_gid"
            elif format_char == 'S':
                the_parts[format_char] = the_stats[stat.ST_SIZE]  # size in bytes
            elif format_char == 'T':
                the_parts[format_char] = time.strftime("%Y/%m/%d-%H:%M:%S", time.gmtime((the_stats[stat.ST_MTIME])))  # modification time
            elif format_char == 'C':
                if not (stat.S_ISLNK(the_stats.st_mode) or stat.S_ISDIR(the_stats.st_mode)):
                    the_parts[format_char] = utils.get_file_checksum(the_path)
                else:
                    the_parts[format_char] = ""
            elif format_char == 'P' or format_char == 'p':
                path_to_return = the_path_str
                if format_char == 'p' and root_folder is not None:
                    path_to_return = os.path.relpath(the_path, start=root_folder)

                # E will bring us Extra data (path postfix) but we want to know if it's DIR in any case
                if stat.S_ISDIR(the_stats.st_mode) and 'D' in ls_format:
                    path_to_return += '/'

                if 'E' in ls_format:
                    if stat.S_ISLNK(the_stats.st_mode):
                        path_to_return += '@'
                    elif not stat.S_ISDIR(the_stats.st_mode) and (the_stats.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
                        path_to_return += '*'
                    elif stat.S_ISSOCK(the_stats.st_mode):
                        path_to_return += '='
                    elif stat.S_ISFIFO(the_stats.st_mode):
                        path_to_return += '|'

                the_parts[format_char] = path_to_return
            elif format_char == 'a' or format_char == 'f':
                import subprocess
                completed_process = subprocess.run(f'ls -lO "{the_path_str}"', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if completed_process.returncode != 0:
                    the_parts[format_char] = utils.unicodify(completed_process.stderr)
                else:
                    ls_line = utils.unicodify(completed_process.stdout)
                    flag_matches = re.findall("arch|archived|opaque|nodump|sappnd|sappend|schg|schange|simmutable|uappnd|uappend|uchg|uchange|uimmutable|hidden", ls_line)
                    if flag_matches:
                        the_parts[format_char] = ",".join(flag_matches)
                    else:
                        the_parts[format_char] = "[]"

    except Exception as ex:
        the_error = [the_path_str, ex.strerror]

    return the_parts, the_error


def win_folder_ls(the_path, ls_format, root_folder=None):
    listing_lines = list()
    error_lines = list()
    try:
        for root_path, dirs, files in os.walk(the_path, followlinks=False):
            dirs = sorted(dirs, key=lambda s: s.lower())
            if 'd' in ls_format:
                listings, errors = win_item_ls(root_path, ls_format=ls_format, root_folder=root_folder)
                if errors:
                    error_lines.append(errors)
                else:
                    listing_lines.append(listings)
            if 'f' in ls_format:
                files_to_list = sorted(files + [slink for slink in dirs if os.path.islink(os.path.join(root_path, slink))], key=lambda s: s.lower())
                for file_to_list in files_to_list:
                    full_path = os.path.join(root_path, file_to_list)
                    listings, errors = win_item_ls(full_path, ls_format=ls_format, root_folder=root_folder)
                    if errors:
                        error_lines.append(errors)
                    else:
                        listing_lines.append(listings)

    except Exception as ex:
        error_lines.append([the_path, ex.strerror])

    return listing_lines, error_lines


# noinspection PyUnresolvedReferences
def win_item_ls(the_path, ls_format, root_folder=None):
    import win32security
    the_parts = dict()
    the_error = None
    the_path_str = os.fspath(the_path)
    if 'p' in ls_format:
        the_parts['p'] = the_path_str
    elif 'P' in ls_format:
        the_parts['P'] = the_path_str

    try:
        the_stats = os.lstat(the_path)

        for format_char in ls_format:
            if format_char == 'T':
                the_parts[format_char] = time.strftime("%Y/%m/%d %H:%M:%S", time.gmtime((the_stats[stat.ST_MTIME])))  # modification time
            elif format_char == 'D':
                if 'p' in ls_format.lower():  # 'p' or 'P'
                    if stat.S_ISDIR(the_stats.st_mode):
                        the_parts[format_char] = "<DIR>"
                    else:
                        the_parts[format_char] = ""
            elif format_char == 'S':
                the_parts[format_char] = the_stats[stat.ST_SIZE]  # size in bytes
            elif format_char == 'U':
                try:
                    sd = win32security.GetFileSecurity(the_path_str, win32security.OWNER_SECURITY_INFORMATION)
                    owner_sid = sd.GetSecurityDescriptorOwner()
                    name, domain, __type = win32security.LookupAccountSid(None, owner_sid)
                    the_parts[format_char] = domain+"\\"+name  # user
                except Exception as ex:  # we sometimes get exception: 'LookupAccountSid, No mapping between account names and security IDs was done.'
                    the_parts[format_char] = "Unknown user"

            elif format_char == 'G':
                try:
                    sd = win32security.GetFileSecurity(the_path_str, win32security.GROUP_SECURITY_INFORMATION)
                    owner_sid = sd.GetSecurityDescriptorGroup()
                    name, domain, __type = win32security.LookupAccountSid(None, owner_sid)
                    the_parts[format_char] = domain+"\\"+name  # group
                except Exception as ex:  # we sometimes get exception: 'LookupAccountSid, No mapping between account names and security IDs was done.'
                    the_parts[format_char] = "Unknown group"

            elif format_char == 'C':
                if not (stat.S_ISLNK(the_stats.st_mode) or stat.S_ISDIR(the_stats.st_mode)):
                    the_parts[format_char] = utils.get_file_checksum(the_path)
                else:
                    the_parts[format_char] = ""
            elif format_char == 'P':
                as_posix = PurePath(the_path).as_posix()
                the_parts[format_char] = str(as_posix)
            elif format_char == 'p' and root_folder is not None:
                relative_path = PurePath(the_path).relative_to(PurePath(root_folder))
                the_parts[format_char] = str(relative_path.as_posix())
            elif format_char == 'a' or format_char == 'f':
                import subprocess
                the_parts[format_char] = "[]"
                completed_process = subprocess.run(f'attrib "{the_path_str}"', shell=True, stdout=subprocess.PIPE,
                                                   stderr=subprocess.PIPE)
                if completed_process.returncode != 0:
                    the_parts[format_char] = utils.unicodify(completed_process.stderr)
                else:
                    ls_line = utils.unicodify(completed_process.stdout)
                    flag_matches = re.search("(?P<attribs>(A|R|S|H|O|I|X|P|U|\s)+?)\s+[A-Z]:", ls_line)
                    if flag_matches:
                        flags = "".join(flag_matches.group('attribs').split())
                        if flags:
                            the_parts[format_char] = flags

    except Exception as ex:
        the_error = [the_path_str, ex.strerror]

    return the_parts, the_error


def wtar_ls_func(root_file_or_folder_path, ls_format):
    listing_lines = list()
    error_lines = list()
    try:
        what_to_work_on = utils.find_split_files(root_file_or_folder_path)
        with utils.MultiFileReader("br", what_to_work_on) as fd:
            with tarfile.open(fileobj=fd) as tar:
                pax_headers = tar.pax_headers
                for item in tar:
                    listing_lines.append(wtar_item_ls_func(item, ls_format))

                listing_lines.append({'W': pax_headers.get("total_checksum", "no-total-checksum")})

    except Exception as ex:
        error_lines.append([root_file_or_folder_path, ex.strerror])

    return listing_lines, error_lines


def wtar_item_ls_func(item, ls_format):
    the_parts = dict()
    for format_char in ls_format:
        if format_char == 'R':
            the_parts[format_char] = utils.unix_permissions_to_str(item.mode)  # permissions
        elif format_char == 'u':
            the_parts[format_char] = item.uid
        elif format_char == 'U':
            the_parts[format_char] = item.uname
        elif format_char == 'g':
            the_parts[format_char] = item.gid
        elif format_char == 'G':
            the_parts[format_char] = item.gname
        elif format_char == 'S':
            the_parts[format_char] = item.size
        elif format_char == 'T':
            the_parts[format_char] = time.strftime("%Y/%m/%d-%H:%M:%S", time.gmtime(item.mtime))  # modification time
        elif format_char == 'C':
            the_parts[format_char] = item.pax_headers.get("checksum", "")
        elif format_char == 'P' or format_char == 'p':
            path_to_return = item.name
            if item.isdir() and 'D' in ls_format:
                path_to_return += '/'

            if 'E' in ls_format:
                if item.issym():
                    path_to_return += '@'
                elif item.isfifo():
                    path_to_return += '|'

            the_parts[format_char] = path_to_return
    return the_parts


def single_disk_item_listing(the_path, ls_format="PuUgGRTf", root_folder=None, output_format="text"):
    retVal = None
    if sys.platform in ('darwin', 'linux'):
        item_ls_dict, the_error = unix_item_ls(the_path, ls_format, root_folder)
    elif sys.platform == 'win32':
        item_ls_dict, the_error = win_item_ls(the_path, ls_format, root_folder)

    if output_format == "text":
        item_ls_lines = list_of_dicts_describing_disk_items_to_text_lines([item_ls_dict], ls_format)
        retVal = item_ls_lines[0]
    elif output_format == "json":
        item_ls_lines= translate_json_key_names([item_ls_dict])
        retVal = item_ls_lines[0]
    elif output_format == 'dicts':
        retVal = translate_item_dict_to_be_keyed_by_path(item_ls_dict)
    return retVal
