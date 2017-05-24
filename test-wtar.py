import re
import os
import stat
import sys
import shlex
import tarfile
import fnmatch
import time
import re
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


if __name__ == "__main__":
    the_wtar = "C:\\Users\\shai\\Desktop\\CODEX.bundle\\Contents\\Resources.wtar.aa"
    do_unwtar(the_wtar)