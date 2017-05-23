#!/usr/bin/env python3

import os
import time
import datetime
from pathlib import PurePath
import stat

import utils


def disk_item_listing(*files_or_folders_to_list, ls_format='*'):
    """ Create a manifest of one or more folders or files
        Format is a sequence of characters specifying what details to include 
        and in what order. Options are:
    'C': sha1 checksum (files only)
    'D': if 'P' or 'p' is given "/" is appended to the path if item is a directory (Mac), <DIR> if item is directory empty string otherwise (Win only)
        note that for Mac the position of 'D' in ls_format is not relevant.
    'E': if 'P' or 'p' is given extra character is appended to the path, '@' for link, '*' for executable, '=' for socket, '|' for FIFO
    'G': Group name or gid if name not found (Mac), domain+"\\"+group name (Win)
    'I': inode number (Mac only)
    'L': number of links (Mac only)
    'M': a remark beginning in '#' and containing the data & time when the listing was done and the path to the item listed
        note that the position of 'M' in ls_format is not relevant. The remark appears before each item.
        If the item was not found a remark will be written any way
    'P': full path to the item
    'p': partial path to the item - relative to the top folder listed, or if top item is a file - the file name without the path
    'R' item's permissions in the format (-|d|l)rwxrwxrwx (Mac only)
    'S': size in bytes
    'T': modification time, format is "%Y/%m/%d-%H:%M:%S" as used by time.strftime
    'U': User name or uid if name not found (Mac), domain+"\\"+user name (Win)
    'W': Not implemented yet. List contents of wtar files
    '*' if ls_format contains only '*' it is and alias to the default and means: 
        MIRLUGSTCPE (Mac)
        MTDSUGCP (Win)
    """
    os_names = utils.get_current_os_names()
    listing_lines = list()
    add_remarks = ls_format=='*' or 'M' in ls_format
    files_or_folders_to_list = sorted(*files_or_folders_to_list, key=lambda file: PurePath(file).parts)
    if "Mac" in os_names:
        if ls_format == '*':
            ls_format = 'MIRLUGSTCPE'
        for root_file_or_folder_path in files_or_folders_to_list:
            if add_remarks:
                listing_lines.append(" ".join(("#", datetime.datetime.today().isoformat(), "listing of", root_file_or_folder_path)))
            if os.path.isdir(root_file_or_folder_path):
                listing_lines.extend(unix_folder_ls(root_file_or_folder_path, ls_format=ls_format, root_folder=root_file_or_folder_path))
            elif os.path.isfile(root_file_or_folder_path):
                root_folder, _ = os.path.split(root_file_or_folder_path)
                listing_lines.append(unix_item_ls(root_file_or_folder_path, ls_format=ls_format, root_folder=root_folder))
            else:
                listing_lines.append(" ".join(("#", "folder was not found", root_file_or_folder_path)))

    elif "Win" in os_names:
        if ls_format == '*':
            ls_format = 'MTDSUGCP' # order does matters!
        for root_file_or_folder_path in files_or_folders_to_list:
            if add_remarks:
                listing_lines.append(" ".join(("#", datetime.datetime.today().isoformat(), "listing of", root_file_or_folder_path)))
            if os.path.isdir(root_file_or_folder_path):
                listing_lines.extend(win_folder_ls(root_file_or_folder_path, ls_format=ls_format, root_folder=root_file_or_folder_path))
            elif os.path.isdir(root_file_or_folder_path):
                root_folder, _ = os.path.split(root_file_or_folder_path)
                listing_lines.append(win_item_ls(root_file_or_folder_path, ls_format=ls_format, root_folder=root_folder))
            else:
                listing_lines.append(" ".join(("#", "folder was not found:", root_file_or_folder_path)))
    # when calculating widths - avoid comment lines
    real_line_list = list()  # lines that ar enot empty or comments
    for line in listing_lines:
        if line and not str(line[0]).startswith('#'):
            real_line_list.append(line)
    width_list, align_list = utils.max_widths(real_line_list)
    col_formats = utils.gen_col_format(width_list, align_list)
    formatted_lines_lines = list()
    for ls_line in listing_lines:
        # when printing - avoid formatting of comment lines or empty lines (empty lines might be created by weird ls_format)
        if ls_line:
            if str(ls_line[0]).startswith('#'):
                formatted_lines_lines.append(ls_line)
            else:
                formatted_lines_lines.append(col_formats[len(ls_line)].format(*ls_line))
    formatted_lines_lines.append("")  # line break at the end so not to be joined with the next line when printing to Terminal
    retVal = "\n".join(formatted_lines_lines)
    return retVal


def unix_folder_ls(the_path, ls_format='*', root_folder=None):
    listing_lines = list()
    for root_path, dirs, files in os.walk(the_path, followlinks=False):
        dirs = sorted(dirs, key=lambda s: s.lower())
        listing_lines.append(unix_item_ls(root_path, ls_format=ls_format, root_folder=root_folder))
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

    the_parts = list()
    the_stats = os.lstat(the_path)

    for format_col in ls_format:
        if format_col == 'I':
            the_parts.append(the_stats[stat.ST_INO])  # inode number
        elif format_col == 'R':
            the_parts.append(utils.unix_permissions_to_str(the_stats.st_mode)) # permissions
        elif format_col == 'L':
            the_parts.append(the_stats[stat.ST_NLINK])  # num links
        elif format_col == 'U':
            try:
                the_parts.append(pwd.getpwuid(the_stats[stat.ST_UID])[0])  # user
            except KeyError:
                the_parts.append(str(the_stats[stat.ST_UID])[0]) # unknown user name, get the number
            except Exception:
                the_parts.append("no_uid")
        elif format_col == 'G':
            try:
                the_parts.append(grp.getgrgid(the_stats[stat.ST_GID])[0])  # group
            except KeyError:
                the_parts.append(str(the_stats[stat.ST_GID])[0]) # unknown group name, get the number
            except Exception:
                the_parts.append("no_gid")
        elif format_col == 'S':
            the_parts.append(the_stats[stat.ST_SIZE])  # size in bytes
        elif format_col == 'T':
            the_parts.append(time.strftime("%Y/%m/%d-%H:%M:%S", time.gmtime((the_stats[stat.ST_MTIME]))))  # modification time
        elif format_col == 'C':
            if not (stat.S_ISLNK(the_stats.st_mode) or stat.S_ISDIR(the_stats.st_mode)):
                the_parts.append(utils.get_file_checksum(the_path))
            else:
                the_parts.append("")
        elif format_col == 'P' or format_col == 'p':
            path_to_print = the_path
            if format_col == 'p' and root_folder is not None:
                path_to_print = os.path.relpath(the_path, start=root_folder)

            # E will bring us Extra data (path postfix) but we want to know if it's DIR in any case
            if stat.S_ISDIR(the_stats.st_mode) and 'D' in ls_format:
                path_to_print += '/'

            if 'E' in ls_format:
                if stat.S_ISLNK(the_stats.st_mode):
                    path_to_print += '@'
                elif not stat.S_ISDIR(the_stats.st_mode) and (the_stats.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
                    path_to_print += '*'
                elif stat.S_ISSOCK(the_stats.st_mode):
                    path_to_print += '='
                elif stat.S_ISFIFO(the_stats.st_mode):
                    path_to_print += '|'

            the_parts.append(path_to_print)

    return the_parts


def win_folder_ls(the_path, ls_format='*', root_folder=None):
    listing_lines = list()
    for root_path, dirs, files in os.walk(the_path, followlinks=False):
        dirs = sorted(dirs, key=lambda s: s.lower())
        listing_lines.append(win_item_ls(root_path, ls_format=ls_format, root_folder=root_folder))
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
    the_parts = list()
    the_stats = os.lstat(the_path)

    for format_col in ls_format:
        if format_col == 'T':
            the_parts.append(time.strftime("%Y/%m/%d %H:%M:%S", time.gmtime((the_stats[stat.ST_MTIME]))))  # modification time
        elif format_col == 'D':
            if 'p' in ls_format.lower():  # 'p' or 'P'
                if stat.S_ISDIR(the_stats.st_mode):
                    the_parts.append("<DIR>")
                else:
                    the_parts.append("")
        elif format_col == 'S':
            the_parts.append(the_stats[stat.ST_SIZE])  # size in bytes
        elif format_col == 'U':
            sd = win32security.GetFileSecurity (the_path, win32security.OWNER_SECURITY_INFORMATION)
            owner_sid = sd.GetSecurityDescriptorOwner()
            name, domain, __type = win32security.LookupAccountSid (None, owner_sid)
            the_parts.append(domain+"\\"+name)  # user
        elif format_col == 'G':
            sd = win32security.GetFileSecurity (the_path, win32security.GROUP_SECURITY_INFORMATION)
            owner_sid = sd.GetSecurityDescriptorGroup()
            name, domain, __type = win32security.LookupAccountSid (None, owner_sid)
            the_parts.append(domain+"\\"+name)  # group
        elif format_col == 'C':
            if not (stat.S_ISLNK(the_stats.st_mode) or stat.S_ISDIR(the_stats.st_mode)):
                the_parts.append(get_file_checksum(the_path))
            else:
                the_parts.append("")
        elif format_col == 'P':
            path_to_print = the_path
            the_parts.append(path_to_print)
        elif format_col == 'p' and root_folder is not None:
            path_to_print = os.path.relpath(the_path, start=root_folder)
            the_parts.append(path_to_print)

    return the_parts


# not fully implemented and checked. Will be used to implement the 'W' option
def wtar_list(tar_file, ls_format):
    tar_list = list()
    if tar_file.endswith(".wtar.aa") or tar_file.endswith(".wtar"):  # only wtar
        if os.path.isfile(tar_file):
            from utils.multi_file import MultiFileReader
            import tarfile

            what_to_work_on = None
            if tar_file.endswith(".wtar.aa"):
                what_to_work_on = utils.find_split_files(tar_file)
            elif tar_file.endswith(".wtar"):
                what_to_work_on = [tar_file]

            try:
                tar_list.append('# Start of .wtar content')
                with MultiFileReader("br", what_to_work_on) as fd:
                    with tarfile.open(fileobj=fd) as tar:
                        for member in tar:
                            the_parts = list()
                            for format_col in ls_format:
                                if format_col == 'W':
                                    continue # since W was the trigger to all that
                                elif format_col == 'R':
                                    the_parts.append(member.mode)
                                elif format_col == 'U':
                                    the_parts.append("--".join([member.uid, member.uname]))
                                elif format_col == 'G':
                                    the_parts.append("--".join([member.gid, member.gname]))
                                elif format_col == 'S':
                                    the_parts.append(member.size)
                                elif format_col == 'T':
                                    the_parts.append(member.mtime)
                                elif format_col == 'P':
                                    the_parts.append(member.name)
                                elif format_col == 'D':
                                    the_parts.append("<DIR>" if member.isdir() else "")
                                else:
                                    # coming here means that we got a char we can't do anything with.
                                    # still, we must allocate a place it
                                    the_parts.append("")

                            tar_list.append(the_parts)
                tar_list.append('# End of .wtar content')

            except OSError as e:
                print("Invalid stream on split file with {}".format(what_to_work_on[0]))
                raise e

            except tarfile.TarError:
                print("tarfile error while opening file", os.path.abspath(what_to_work_on[0]))
                raise
    return tar_list

if __name__ == "__main__":
    """
    'C': sha1 checksum (files only)
    'D': if 'P' or 'p' is given "/" is appended to the path if item is a directory (Mac), <DIR> if item is directory empty string otherwise (Win only)
        note that for Mac the position of 'D' in ls_format is not relevant.
    'E': if 'P' or 'p' is given extra character is appended to the path, '@' for link, '*' for executable, '=' for socket, '|' for FIFO
    'G': Group name or giu if name not found (Mac), domain+"\\"+group name (Win)
    'I': inode number (Mac only)
    'L': number of links (Mac only)
    'M': a remark beginning in '#' and containing the data & time when the listing was done and the path to the item listed
        note that the position of 'M' in ls_format is not relevant. The remark appears before each item.
        If the item was not found a remark will be written any way
    'P': full path to the item
    'p': partial path to the item - relative to the top folder listed, or if top item is a file - the file name without the path
    'R' item's permissions in the format (-|d|l)rwxrwxrwx (Mac only)
    'S': size in bytes
    'T': modification time, format is "%Y/%m/%d-%H:%M:%S" as used by time.strftime
    'U': User name or uid if name not found (Mac), domain+"\\"+user name (Win)
    """

    path_list = ['/Users/shai/Desktop/wlc.app', '/Users/shai/Desktop/info_map.info']
    ls_format = "MIRLUGSTCpE"  # 'MIRLUGSTCPE'
    listing = disk_item_listing(path_list, ls_format=ls_format)
    print(listing)
