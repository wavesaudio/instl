from typing import List, Any
import os
import stat
import tarfile
from collections import OrderedDict
import pathlib

from configVar import config_vars
import utils
import zlib

from .baseClasses import PythonBatchCommandBase


def can_skip_unwtar(what_to_work_on: os.PathLike, where_to_unwtar: os.PathLike):
    return False
    # disabled for now because Info.xml is copied before unwtarring take place
    try:
        what_to_work_on_info_xml = os.path.join(what_to_work_on, "Contents", "Info.xml")
        where_to_unwtar_info_xml = os.path.join(where_to_unwtar, "Contents", "Info.xml")
        retVal = filecmp.cmp(what_to_work_on_info_xml, where_to_unwtar_info_xml, shallow=True)
    except:
        retVal = False
    return retVal


def unwtar_a_file(wtar_file_path, destination_folder=None, no_artifacts=False, ignore=None):
    try:
        wtar_file_paths = utils.find_split_files(wtar_file_path)

        if destination_folder is None:
            destination_folder, _ = os.path.split(wtar_file_paths[0])
        print("unwtar", wtar_file_path, " to ", destination_folder)
        if ignore is None:
            ignore = ()

        first_wtar_file_dir, first_wtar_file_name = os.path.split(wtar_file_paths[0])
        destination_leaf_name = utils.original_name_from_wtar_name(first_wtar_file_name)
        destination_path = os.path.join(destination_folder, destination_leaf_name)

        do_the_unwtarring = True
        with utils.MultiFileReader("br", wtar_file_paths) as fd:
            with tarfile.open(fileobj=fd) as tar:
                tar_total_checksum = tar.pax_headers.get("total_checksum")
                if tar_total_checksum:
                    if os.path.exists(destination_path):
                        disk_total_checksum = "disk_total_checksum_was_not_found"
                        with utils.ChangeDirIfExists(destination_folder):
                            disk_total_checksum = utils.get_recursive_checksums(destination_leaf_name, ignore=ignore).get("total_checksum", "disk_total_checksum_was_not_found")

                        if disk_total_checksum == tar_total_checksum:
                            do_the_unwtarring = False
                            print(wtar_file_paths[0], "skipping unwtarring because item exists and is identical to archive")
                if do_the_unwtarring:
                    utils.safe_remove_file_system_object(destination_path)
                    tar.extractall(destination_folder)

        if no_artifacts:
            for wtar_file in wtar_file_paths:
                os.remove(wtar_file)

    except OSError as e:
        print(f"Invalid stream on split file with {wtar_file_paths[0]}")
        raise e

    except tarfile.TarError:
        print("tarfile error while opening file", os.path.abspath(wtar_file_paths[0]))
        raise


class Wtar(PythonBatchCommandBase):
    def __init__(self, what_to_wtar: os.PathLike, where_to_put_wtar=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_wtar = os.fspath(what_to_wtar)
        self.where_to_put_wtar = os.fspath(where_to_put_wtar) if where_to_put_wtar else None

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}(what_to_wtar=r"{self.what_to_wtar}"'''
        if self.where_to_put_wtar:
            the_repr += f''', where_to_put_wtar=r"{self.where_to_put_wtar}"'''
        the_repr += ")"
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f""
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f""
        return the_repr

    def progress_msg_self(self) -> str:
        return ""

    def __call__(self, *args, **kwargs) -> None:
        """ Create a new wtar archive for a file or folder provided in self.what_to_wtar

            If self.where_to_put_wtar is None the new wtar file will be created
                next to the input with extension '.wtar'.
                e.g. the call:
                    Wtar(/a/b/c)
                will create the wtar file at path:
                    /a/b/c.wtar

            If self.where_to_put_wtar is an existing file, the new wtar will overwrite
                this existing file, wtar extension will NOT be added.
                e.g. assuming /d/e/f.txt is an existing file, the call:
                    Wtar(/a/b/c, /d/e/f.txt)
                will create the wtar file at path:
                    /d/e/f.txt

            if self.where_to_put_wtar is and existing folder the wtar file will be created
                inside this folder with extension '.wtar'.
                e.g. assuming /g/h/i is an existing folder, the call:
                    Wtar(/a/b/c, /g/h/i)
                will create the wtar file at path:
                    /g/h/i/c.wtar

            if self.where_to_put_wtar is not None but does not exists, the folder will be created
                and the wtar file will be created inside the new folder with extension
                 '.wtar'.
                e.g. assuming /j/k/l is a non existing folder, the call:
                    Wtar(/a/b/c, /j/k/l)
                will create the wtar file at path:
                    /j/k/l/c.wtar

            "total_checksum" field is added to the pax_headers. This checksum is a checksum of all individual
                file checksums as calculated by utils.get_recursive_checksums. See utils.get_recursive_checksums
                doc string for details on how checksums are calculated. Individual file checksums are not added
                to the pax_headers because during unwtarring tarfile code goes over all the pax_headers for each file
                making the process exponential slow for large archived.

            if wtar file(s) with the same base name as the self.what_to_wtar, the total_checksum of the existing wtar
                will be checked against the total_checksum of the self.what_to_wtar file/folder.
                If total_checksums are identical, the wtar
                will not be created. This will protect against new wtar being created when only the modification date of files
                in the self.what_to_wtar file/folder has changed.
                If total_checksums are no identical the old wtar files wil be removed and a new war created. Removing the old wtars
                ensures that if the number of new wtar split files is smaller than the number of old split files, not extra files wil remain. E.g. if before [a.wtar.aa, a.wtar.ab, a.wtar.ac] and after  [a.wtar.aa, a.wtar.ab] a.wtar.ac will be removed.
            Format of the tar is PAX_FORMAT.
            Compression is bzip2.

        """

        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(self.what_to_wtar)

        where_to_put_wtar = self.where_to_put_wtar
        if where_to_put_wtar is None:
            where_to_put_wtar = what_to_work_on_dir
            if not where_to_put_wtar:
                where_to_put_wtar = os.curdir

        if os.path.isfile(where_to_put_wtar):
            target_wtar_file = where_to_put_wtar
        else:  # assuming it's a folder
            os.makedirs(where_to_put_wtar, exist_ok=True)
            target_wtar_file = os.path.join(where_to_put_wtar, what_to_work_on_leaf+".wtar")

        tar_total_checksum = utils.get_wtar_total_checksum(target_wtar_file)
        ignore_files = list(config_vars.get("WTAR_IGNORE_FILES", []))
        with utils.ChangeDirIfExists(what_to_work_on_dir):
            pax_headers = {"total_checksum": utils.get_recursive_checksums(what_to_work_on_leaf, ignore=ignore_files)["total_checksum"]}

            def check_tarinfo(tarinfo):
                for ig in ignore_files:
                    if tarinfo.name.endswith(ig):
                        return None
                tarinfo.uid = tarinfo.gid = 0
                tarinfo.uname = tarinfo.gname = "waves"
                if os.path.isfile(tarinfo.path):
                    # wtar should to be idempotent. tarfile code adds "mtime" to
                    # each file's pax_headers. We add "checksum" to pax_headers.
                    # The result is that these two values are written to the tar
                    # file in no particular order and taring the same file twice
                    # might produce different results. By supplying the mtime
                    # ourselves AND passing an OrderedDict as the pax_headers
                    # hopefully the tar files will be the same each time.
                    file_pax_headers = OrderedDict()
                    file_pax_headers["checksum"] = utils.get_file_checksum(tarinfo.path)
                    mode_time = str(float(os.lstat(tarinfo.path)[stat.ST_MTIME]))
                    file_pax_headers["mtime"] = mode_time
                    tarinfo.pax_headers = file_pax_headers
                return tarinfo
            compresslevel = 1
            if pax_headers["total_checksum"] != tar_total_checksum:
                if utils.is_first_wtar_file(target_wtar_file):
                    existing_wtar_parts = utils.find_split_files_from_base_file(target_wtar_file)
                    [utils.safe_remove_file(f) for f in existing_wtar_parts]
                with tarfile.open(target_wtar_file, "w:bz2", format=tarfile.PAX_FORMAT, pax_headers=pax_headers, compresslevel=compresslevel) as tar:
                    tar.add(what_to_work_on_leaf, filter=check_tarinfo)
            else:
                print(f"{what_to_work_on} skipped since {what_to_work_on}.wtar already exists and has the same contents")


class Unwtar(PythonBatchCommandBase):
    def __init__(self, what_to_unwtar: os.PathLike, where_to_unwtar=None, no_artifacts=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_unwtar = os.fspath(what_to_unwtar)
        self.where_to_unwtar = os.fspath(where_to_unwtar) if where_to_unwtar else None
        self.no_artifacts = no_artifacts

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}(what_to_unwtar=r"{self.what_to_unwtar}"'''
        if self.where_to_unwtar:
            the_repr += f''', where_to_unwtar=r"{self.where_to_unwtar}"'''
        if self.no_artifacts:
            the_repr += f''', no_artifacts=True'''
        the_repr += ")"
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f""
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f""
        return the_repr

    def progress_msg_self(self) -> str:
        return ""

    def __call__(self, *args, **kwargs) -> None:

        ignore_files = list(config_vars.get("WTAR_IGNORE_FILES", []))

        if os.path.isfile(self.what_to_unwtar):
            if utils.is_first_wtar_file(self.what_to_unwtar):
                unwtar_a_file(self.what_to_unwtar, self.where_to_unwtar, no_artifacts=self.no_artifacts, ignore=ignore_files)
        elif os.path.isdir(self.what_to_unwtar):
            if not can_skip_unwtar(self.what_to_unwtar, self.where_to_unwtar):
                where_to_unwtar_the_file = None
                for root, dirs, files in os.walk(self.what_to_unwtar, followlinks=False):
                    # a hack to prevent unwtarring of the sync folder. Copy command might copy something
                    # to the top level of the sync folder.
                    if "bookkeeping" in dirs:
                        dirs[:] = []
                        print("skipping", root, "because bookkeeping folder was found")
                        continue

                    tail_folder = root[len(self.what_to_unwtar):].strip("\\/")
                    if self.where_to_unwtar is not None:
                        where_to_unwtar_the_file = os.path.join(self.where_to_unwtar, tail_folder)
                    for a_file in files:
                        a_file_path = os.path.join(root, a_file)
                        if utils.is_first_wtar_file(a_file_path):
                            unwtar_a_file(a_file_path, where_to_unwtar_the_file, no_artifacts=self.no_artifacts, ignore=ignore_files)
            else:
                print(f"unwtar {self.what_to_unwtar} to {self.where_to_unwtar} skipping unwtarring because both folders have the same Info.xml file")

        else:
            raise FileNotFoundError(self.what_to_unwtar)


class Wzip(PythonBatchCommandBase):
    """ Create a new wzip for a file  provided in '--in' command line option

        If --out is not supplied on the command line the new wzip file will be created
            next to the input with extension '.wzip'.
            e.g. the command:
                instl wzip --in /a/b/c
            will create the wzip file at path:
                /a/b/c.wzip

        If '--out' is supplied and it's an existing file, the new wzip will overwrite
            this existing file, wzip extension will NOT be added.
            e.g. assuming /d/e/f.txt is an existing file, the command:
                instl wzip --in /a/b/c --out /d/e/f.txt
            will create the wzip file at path:
                /d/e/f.txt

        if '--out' is supplied and is and existing folder the wzip file will be created
            inside this folder with extension '.wzip'.
            e.g. assuming /g/h/i is an existing folder, the command:
                instl wzip --in /a/b/c --out /g/h/i
            will create the wzip file at path:
                /g/h/i/c.wzip

        if '--out' is supplied and does not exists, the folder will be created
            and the wzip file will be created inside the new folder with extension
             '.wzip'.
            e.g. assuming /j/k/l is a non existing folder, the command:
                instl wzip --in /a/b/c --out /j/k/l
            will create the wzip file at path:
                /j/k/l/c.wzip

        configVar effecting wzip:
        ZLIB_COMPRESSION_LEVEL: will set the compression level, default is 8
        WZLIB_EXTENSION: .wzip extension is the default, the value is read from the configVar WZLIB_EXTENSION,
    """
    def __init__(self, what_to_wzip: os.PathLike, where_to_put_wzip=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_wzip = os.fspath(what_to_wzip)
        self.where_to_put_wzip = os.fspath(where_to_put_wzip) if where_to_put_wzip else None

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}(r"{self.what_to_wzip}"'''
        if self.where_to_put_wzip:
            the_repr += f''', r"{self.where_to_put_wzip}"'''
        the_repr += ")"
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(self.what_to_wzip)
        target_wzip_file = self.where_to_put_wzip
        if not target_wzip_file:
            target_wzip_file = what_to_work_on_dir
            if not target_wzip_file:  # os.path.split might return empty string
                target_wzip_file = os.curdir
        if not os.path.isfile(target_wzip_file):
            # assuming it's a folder
            os.makedirs(target_wzip_file, exist_ok=True)
            target_wzip_file = os.path.join(target_wzip_file, what_to_work_on_leaf+".wzip")

        zlib_compression_level = int(config_vars.get("ZLIB_COMPRESSION_LEVEL", "8"))
        with open(target_wzip_file, "wb") as wfd, open(self.what_to_wzip, "rb") as rfd:
            wfd.write(zlib.compress(rfd.read(), zlib_compression_level))


class Unwzip(PythonBatchCommandBase):
    def __init__(self, what_to_unwzip: os.PathLike, where_to_put_unwzip=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_unwzip = os.fspath(what_to_unwzip)
        self.where_to_put_unwzip = os.fspath(where_to_put_unwzip) if where_to_put_unwzip else None

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}(r"{self.what_to_unwzip}"'''
        if self.where_to_put_unwzip:
            the_repr += f''', r"{self.where_to_put_unwzip}"'''
        the_repr += ")"
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(self.what_to_unwzip)
        target_unwzip_file = self.where_to_put_unwzip
        if not target_unwzip_file:
            target_unwzip_file = what_to_work_on_dir
            if not target_unwzip_file:  # os.path.split might return empty string
                target_unwzip_file = os.curdir
        if not os.path.isfile(target_unwzip_file):
            # assuming it's a folder
            os.makedirs(target_unwzip_file, exist_ok=True)
            if what_to_work_on_leaf.endswith(".wzip"):
                what_to_work_on_leaf = what_to_work_on_leaf[:-len(".wzip")]
            target_unwzip_file = os.path.join(target_unwzip_file, what_to_work_on_leaf)

        with open(self.what_to_unwzip, "rb") as rfd, open(target_unwzip_file, "wb") as wfd:
            decompressed = zlib.decompress(rfd.read())
            wfd.write(decompressed)
