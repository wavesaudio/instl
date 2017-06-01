import re
import os
import stat
import sys
import shlex
import tarfile
import fnmatch
import time
import re
import shutil

from functools import reduce

import utils
from configVar import var_stack
from utils.multi_file import MultiFileReader


def path_without_wtar_extensions(in_path):
    retVal = None
    wtar_file_re = re.compile(r"""(?P<name_without>.+)\.wtar(\...)?$""")
    match = wtar_file_re.match(in_path)
    if match:
        retVal = match.group("name_without")
    return retVal


def find_split_files(first_file):
    try:
        norm_first_file = os.path.normpath(first_file)  # remove trialing . if any
        base_folder, base_name = os.path.split(norm_first_file)
        if not base_folder: base_folder = "."
        filter_pattern = base_name[:-2] + "??"  # with ?? instead of aa
        matching_files = sorted(fnmatch.filter((f.name for f in os.scandir(base_folder)), filter_pattern))
        files_to_read = []
        for a_file in matching_files:
            files_to_read.append(os.path.join(base_folder, a_file))

        return files_to_read

    except Exception as es:
        print("exception while find_split_files", first_file)
        raise es


def do_unwtar(what_to_work_on, where_to_unwtar=None):

    if os.path.isfile(what_to_work_on):
        if what_to_work_on.endswith(".wtar.aa"): # this case apparently is no longer relevant
            what_to_work_on = find_split_files(what_to_work_on)
            unwtar_a_file(what_to_work_on, where_to_unwtar)
        elif what_to_work_on.endswith(".wtar"):
            unwtar_a_file([what_to_work_on], where_to_unwtar)
    elif os.path.isdir(what_to_work_on):
        where_to_unwtar_the_file = None
        for root, dirs, files in os.walk(what_to_work_on, followlinks=False):
            # a hack to prevent unwtarring of the sync folder. Copy command might copy something
            # to the top level of the sync folder.
            if "bookkeeping" in dirs:
                dirs[:] = []
                continue

            tail_folder = root[len(what_to_work_on):].strip("\\/")
            if where_to_unwtar is not None:
                where_to_unwtar_the_file = os.path.join(where_to_unwtar, tail_folder)
            for a_file in files:
                a_file_path = os.path.join(root, a_file)
                if a_file_path.endswith(".wtar.aa"):
                    split_files = find_split_files(a_file_path)
                    unwtar_a_file(split_files, where_to_unwtar_the_file)
                elif a_file_path.endswith(".wtar"):
                    unwtar_a_file([a_file_path], where_to_unwtar_the_file)

    else:
        raise FileNotFoundError(what_to_work_on)


def unwtar_a_file(wtar_file_paths, destination_folder=None):
    try:
        _, destination_item = os.path.split(wtar_file_paths[0])
        if destination_folder is None:
            destination_folder, _ = os.path.split(wtar_file_paths[0])

        final_target = os.path.join(destination_folder, path_without_wtar_extensions(destination_item))
        if os.path.exists(final_target):
            the_listing = utils.disk_item_listing(final_target, ls_format="SCpf")
            manifest_file_path = final_target+".manifest"
            with open(manifest_file_path, "w") as wfd:
                wfd.write(the_listing)

        with utils.Timer_CM('unwtar_a_file') as timer_cm:
            with MultiFileReader("br", wtar_file_paths) as fd:
                with timer_cm.child('tar.extractall'):
                    with tarfile.open(fileobj=fd) as tar:
                        tar.extractall(destination_folder)
                #with timer_cm.child('manifest'):
                #    the_listing = utils.folder_listing(destination_folder)

    except OSError as e:
        print("Invalid stream on split file with {}".format(wtar_file_paths[0]))
        raise e

    except tarfile.TarError:
        print("tarfile error while opening file", os.path.abspath(wtar_file_paths[0]))
        raise


def dir_walk(path):
    for item in os.scandir(path):
        yield item
        if item.is_dir(follow_symlinks=False):
            yield from dir_walk(item.path)


def unwtar_no_checks(tar_files, target_folder):
    with utils.Timer_CM("unwtar_no_checks") as utc:
        with MultiFileReader("br", tar_files) as fd:
            with tarfile.open(fileobj=fd) as tar:
                tar.extractall(target_folder)


def unwtar_with_checks(tar_files, target_folder, tar_real_name):

    with utils.Timer_CM("unwtar_with_checks") as utc:
        ok_files = 0
        to_untar_files = 0
        with MultiFileReader("br", tar_files) as fd:
            with tarfile.open(fileobj=fd) as tar:
                the_pax_headers = tar.pax_headers
                for item in tar.getmembers():
                    checksum_good = utils.check_file_checksum(os.path.join(target_folder, item.path), the_pax_headers[item.path])
                    if not checksum_good:
                        to_untar_files += 1
                        tar.extract(item, target_folder)
                    else:
                        ok_files += 1
    print("   ", "unwtar_with_checks:", tar_files[0], to_untar_files, "files unwtarred,", ok_files, "not unwtarred")

def unwtar_one_check(tar_files, target_folder, tar_real_name):
    messages = list()
    with utils.Timer_CM("unwtar_one_check: "+target_folder) as utc:
        checksum_of_checksums_from_disk = "XXXX"
        tar_folder = os.path.join(target_folder, tar_real_name)
        with utc.child("disk checksum"):
            if os.path.isdir(tar_folder):
                checksum_of_checksums_from_disk = checksum_a_folder(tar_folder)
                messages.append('reading DISK, checksum_of_checksums: '+ str(checksum_of_checksums_from_disk))
        with utc.child("untarring"):
            with MultiFileReader("br", tar_files) as fd:
                with tarfile.open(fileobj=fd) as tar:
                    the_pax_headers = tar.pax_headers
                    checksum_of_checksums_from_pax = tar.pax_headers['checksum_of_checksums']
                    messages.append('reading tar, checksum_of_checksums: ' + str(checksum_of_checksums_from_pax))
                    if checksum_of_checksums_from_pax != checksum_of_checksums_from_disk:
                        tar.extractall(target_folder)
                        messages.append('checksum_of_checksums DIFF doing complete unwtar')
                    else:
                        messages.append('checksum_of_checksums OK no need to unwtar')
    for message in messages:
        print("   ", message)


def checksum_a_folder(folder_path):
    checksum_of_checksums = 0
    checksum_list = list()
    for item in dir_walk(path=folder_path):
        if item.is_file():
            checksum_list.append(utils.get_file_checksum(item.path))
    checksum_list.sort()
    string_of_checksums = "".join(checksum_list)
    checksum_of_checksums = utils.get_buffer_checksum(string_of_checksums.encode())
    return checksum_of_checksums


def scandir_walk(path):
    for item in os.scandir(path):
        if item.is_file() and not item.is_symlink():
            yield item
        elif item.is_dir(follow_symlinks=False):
            yield from scandir_walk(item.path)

if __name__ == "__main__":
    big_folder = "/Users/shai/Desktop"
    f_count = 0
    os_walk_files = list()
    with utils.Timer_CM("os.walk"):
        for root, dirs, files in os.walk(big_folder, followlinks=False):
            for f in files:
                #print(f)
                full_path = os.path.join(root, f)
                if not os.path.islink(full_path):
                    os_walk_files.append(f)
                    f_count += 1
                #else:
                #    print("found a mountain", full_path)
    print("os.walk", f_count, "files\n")
    f_count = 0
    scandir_walk_files = list()
    with utils.Timer_CM("scandir_walk"):
        for f in scandir_walk(big_folder):
            scandir_walk_files.append(f.name)
            f_count += 1
    print("scandir_walk", f_count, "files")

    print(os_walk_files[:10])
    print(scandir_walk_files[:10])
    sys.exit(0)

    #the_wtar = "C:\\Users\\shai\\Desktop\\CODEX.bundle\\Contents\\Resources.wtar.aa"
    #the_wtar = "/p4client/dev_main/ProAudio/Products/Release/Plugins/CODEX.bundle/Contents/Resources.wtar.aa"
    #the_folder = "/p4client/dev_main/ProAudio/Products/Release/Plugins/CODEX.bundle/Contents"
    the_folder = os.curdir
    test_create = False
    test_unwtar = True

    tar_file_name = "sample.tar.PAX_FORMAT.bz2"
    if test_create:
        pax_headers = dict()
        all_checksums = ""
        checksum_list = list()
        for item in dir_walk(path="Resources"):
            if item.is_file():
                pax_headers[item.path] = utils.get_file_checksum(item.path)
        pax_headers['checksum_of_checksums'] = checksum_a_folder("Resources")

        with tarfile.open(tar_file_name, "w|bz2", format= tarfile.PAX_FORMAT, pax_headers=pax_headers) as tar:
            for item in dir_walk(path="Resources"):
                if item.is_file():
                    tar.add(item.path)

        print('creating tar, pax_headers:', tar.pax_headers)
        print('creating tar, checksum_of_checksums:', tar.pax_headers['checksum_of_checksums'])

    if test_unwtar:
        first_split = tar_file_name+".aa"
        split_files = utils.find_split_files(first_split)
        #utils.safe_remove_folder(os.path.join(the_folder, "unwtarred_no_checks", "Resources"))
        unwtar_no_checks(split_files, "unwtarred_no_checks")
        #utils.safe_remove_folder(os.path.join(the_folder, "unwtarred_with_checks", "Resources"))
        unwtar_with_checks(split_files, "unwtarred_with_checks", "Resources")

        utils.safe_remove_folder(os.path.join(the_folder, "unwtar_one_check_empty", "Resources"))
        unwtar_one_check(split_files, "unwtar_one_check_empty", "Resources")

        unwtar_one_check(split_files, "unwtar_one_check_no_change", "Resources")

        utils.smart_copy_file(os.path.join("unwtar_one_check_extra_files", "Resources", "AlgXML", "1001.xml"),
                        os.path.join("unwtar_one_check_extra_files", "Resources", "AlgXML", "1002.xml"))
        unwtar_one_check(split_files, "unwtar_one_check_extra_files", "Resources")

        utils.safe_remove_file(os.path.join("unwtar_one_check_missing_files", "Resources", "AlgXML", "1001.xml"))
        unwtar_one_check(split_files, "unwtar_one_check_missing_files", "Resources")

# handle symlinks, .DS_Store, etc..
