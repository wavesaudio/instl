#!/usr/bin/env python3

import os
import time
import datetime
import stat
import json
import tarfile
import pathlib

import utils


def disk_item_listing(*files_or_folders_to_list, ls_format='*', output_format='text'):
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
    'W': Not implemented yet. List contents of wtar files
    '*' if ls_format contains only '*' it is and alias to the default and means: 
        Mac: MIRLUGSTCPE
        Win: MTDSUGCP
    Note: if both 'd' and 'f' are not in ls_format disk_item_listing will act as if both are in ls_format
            so 'SCp' actually means 'SCpfd'
    """
    os_names = utils.get_current_os_names()
    files_or_folders_to_list = sorted(files_or_folders_to_list, key=lambda file: pathlib.PurePath(file).parts)
    if "Mac" in os_names:
        if ls_format == '*':
            ls_format = 'WMIRLUGSTCPE'
        folder_ls_func = unix_folder_ls
        item_ls_func = unix_item_ls
    elif "Win" in os_names:
        if ls_format == '*':
            ls_format = 'WMTDSUGCP'
        folder_ls_func = win_folder_ls
        item_ls_func = win_item_ls

    if 'f' not in ls_format and 'd' not in ls_format:
        ls_format += 'fd'
    add_remarks = 'M' in ls_format

    total_list = list()
    for root_file_or_folder_path in files_or_folders_to_list:
        listing_items = list()
        opening_remarks = list()
        if add_remarks:
            opening_remarks.append(" ".join(('#', datetime.datetime.today().isoformat(), "listing of", root_file_or_folder_path)))

        if utils.is_first_wtar_file(root_file_or_folder_path):
            listing_items.extend(wtar_ls_func(root_file_or_folder_path, ls_format=ls_format))
        elif os.path.isdir(root_file_or_folder_path):
            listing_items.extend(folder_ls_func(root_file_or_folder_path, ls_format=ls_format, root_folder=root_file_or_folder_path))
        elif os.path.isfile(root_file_or_folder_path) and 'f' in ls_format:
            root_folder, _ = os.path.split(root_file_or_folder_path)
            listing_items.append(item_ls_func(root_file_or_folder_path, ls_format=ls_format, root_folder=root_folder))
        else:
            opening_remarks.append(" ".join(('#', "folder was not found", root_file_or_folder_path)))

        if output_format == 'text':
            total_list.extend(opening_remarks)
            total_list.extend(list_of_dicts_describing_disk_items_to_text_lines(listing_items, ls_format))
            total_list.append("")  # line break at the end so not to be joined with the next line when printing to Terminal
        elif output_format == 'dicts':
            for item in listing_items:
                total_list.append(translate_item_dict_to_be_keyed_by_path(item))
        elif output_format == 'json':
           total_list.append({root_file_or_folder_path: translate_json_key_names(listing_items)})

    if output_format == 'text':
        retVal = "\n".join(total_list)
    elif output_format == 'dicts':
        retVal = total_list
    elif output_format == 'json':
        output_json = json.dumps(total_list, indent=1)
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
    'C': 'checksum',
    'D': 'DIR',
    'g': 'gid',
    'G': 'group',
    'I': 'inode',
    'L': 'num links',
    'P': 'full path',
    'p': 'relative path',
    'R': 'permissions',
    'S': 'size',
    'T': 'modification time',
    'W': 'total_checksum',
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
    for root_path, dirs, files in os.walk(the_path, followlinks=False):
        dirs = sorted(dirs, key=lambda s: s.lower())
        if 'd' in ls_format:
            listing_lines.append(unix_item_ls(root_path, ls_format=ls_format, root_folder=root_folder))
        if 'f' in ls_format:
            files_to_list = sorted(files + [slink for slink in dirs if os.path.islink(os.path.join(root_path, slink))], key=lambda s: s.lower())
            for file_to_list in files_to_list:
                full_path = os.path.join(root_path, file_to_list)
                listing_lines.append(unix_item_ls(full_path, ls_format=ls_format, root_folder=root_folder))

            # W (list content of .Wtar files) is a special case and must be specifically requested
            #if 'W' in ls_format:
            #    listing_lines.extend(produce_tar_list(tar_file=full_path, ls_format=ls_format))

    return listing_lines


def unix_item_ls(the_path, ls_format, root_folder=None):
    import grp
    import pwd

    the_parts = dict()
    the_stats = os.lstat(the_path)

    for format_char in ls_format:
        if format_char == 'I':
            the_parts[format_char] = the_stats[stat.ST_INO]  # inode number
        elif format_char == 'R':
            the_parts[format_char] = utils.unix_permissions_to_str(the_stats.st_mode) # permissions
        elif format_char == 'L':
            the_parts[format_char] = the_stats[stat.ST_NLINK]  # num links
        elif format_char == 'u':
            try:
                the_parts[format_char] = str(the_stats[stat.ST_UID])[0] # unknown user name, get the number
            except Exception:
                the_parts[format_char] = "no_uid"
        elif format_char == 'U':
            try:
                the_parts[format_char] = pwd.getpwuid(the_stats[stat.ST_UID])[0]  # user
            except KeyError:
                the_parts[format_char] = str(the_stats[stat.ST_UID])[0] # unknown user name, get the number
            except Exception:
                the_parts[format_char] = "no_uid"
        elif format_char == 'g':
            try:
                the_parts[format_char] = str(the_stats[stat.ST_GID])[0] # unknown group name, get the number
            except Exception:
                the_parts[format_char] = "no_gid"
        elif format_char == 'G':
            try:
                the_parts[format_char] = grp.getgrgid(the_stats[stat.ST_GID])[0]  # group
            except KeyError:
                the_parts[format_char] = str(the_stats[stat.ST_GID])[0] # unknown group name, get the number
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
            path_to_return = the_path
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

    return the_parts


def win_folder_ls(the_path, ls_format, root_folder=None):
    listing_lines = list()
    for root_path, dirs, files in os.walk(the_path, followlinks=False):
        dirs = sorted(dirs, key=lambda s: s.lower())
        if 'd' in ls_format:
            listing_lines.append(win_item_ls(root_path, ls_format=ls_format, root_folder=root_folder))
        if 'f' in ls_format:
            files_to_list = sorted(files + [slink for slink in dirs if os.path.islink(os.path.join(root_path, slink))], key=lambda s: s.lower())
            for file_to_list in files_to_list:
                full_path = os.path.join(root_path, file_to_list)
                listing_lines.append(win_item_ls(full_path, ls_format=ls_format, root_folder=root_folder))

            # W (list content of .Wtar files) is a special case and must be specifically requested
            #if 'W' in ls_format:
            #    listing_lines.extend(produce_tar_list(tar_file=full_path, ls_format=ls_format))

    return listing_lines


# noinspection PyUnresolvedReferences
def win_item_ls(the_path, ls_format, root_folder=None):
    import win32security
    the_parts = dict()
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
            sd = win32security.GetFileSecurity (the_path, win32security.OWNER_SECURITY_INFORMATION)
            owner_sid = sd.GetSecurityDescriptorOwner()
            name, domain, __type = win32security.LookupAccountSid (None, owner_sid)
            the_parts[format_char] = domain+"\\"+name  # user
        elif format_char == 'G':
            sd = win32security.GetFileSecurity (the_path, win32security.GROUP_SECURITY_INFORMATION)
            owner_sid = sd.GetSecurityDescriptorGroup()
            name, domain, __type = win32security.LookupAccountSid (None, owner_sid)
            the_parts[format_char] = domain+"\\"+name  # group
        elif format_char == 'C':
            if not (stat.S_ISLNK(the_stats.st_mode) or stat.S_ISDIR(the_stats.st_mode)):
                the_parts[format_char] = utils.get_file_checksum(the_path)
            else:
                the_parts[format_char] = ""
        elif format_char == 'P':
            as_posix = pathlib.PurePath(the_path).as_posix()
            the_parts[format_char] = str(as_posix)
        elif format_char == 'p' and root_folder is not None:
            relative_path = pathlib.PurePath(the_path).relative_to(pathlib.PurePath(root_folder))
            the_parts[format_char] = str(relative_path.as_posix())

    return the_parts


def wtar_ls_func(root_file_or_folder_path, ls_format):
    listing_lines = list()
    what_to_work_on = utils.find_split_files(root_file_or_folder_path)
    with utils.MultiFileReader("br", what_to_work_on) as fd:
        with tarfile.open(fileobj=fd) as tar:
            pax_headers = tar.pax_headers
            for item in tar:
                listing_lines.append(wtar_item_ls_func(item, ls_format, tar.pax_headers))

            listing_lines.append({'W': pax_headers.get("total_checksum", "no total checksum")})

    return listing_lines


def wtar_item_ls_func(item, ls_format, global_pax_headers):
    the_parts = dict()
    for format_char in ls_format:
        if format_char == 'R':
            the_parts[format_char] = utils.unix_permissions_to_str(item.mode) # permissions
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
            the_parts[format_char] = time.strftime("%Y/%m/%d-%H:%M:%S", time.gmtime((item.mtime)))  # modification time
        elif format_char == 'C':
            if global_pax_headers and item.name in global_pax_headers:
                the_parts[format_char] = global_pax_headers[item.name]
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


if __name__ == "__main__":

    path_list = ['/Users/shai/Desktop/wlc.app',
                 '/p4client/dev_main/ProAudio/Products/Release/Plugins/CODEX.bundle/Contents/sample.tar.PAX_FORMAT.wtar.aa']
    ls_format = "WMIRLUGSTCpE"  # 'MIRLUGSTCPE'
    for out_format in ('text', 'dicts', 'json'):
        listing = disk_item_listing(*path_list, ls_format=ls_format, output_format=out_format)
        with open("ls."+out_format, "w") as wfd:
            print(listing, file=wfd)
            print(os.path.realpath(wfd.name))
