import os
import stat
import tarfile
from collections import OrderedDict
import logging
from pathlib import Path
import filecmp
from typing import List

from configVar import config_vars
import utils
import zlib

from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import SplitFile

log = logging.getLogger(__name__)


def can_skip_unwtar(what_to_work_on: Path, where_to_unwtar: Path):
    try:
        what_to_work_on_info_xml = what_to_work_on.joinpath("Contents", "Info.xml")
        where_to_unwtar_info_xml = where_to_unwtar.joinpath("Contents", "Info.xml")
        retVal = filecmp.cmp(what_to_work_on_info_xml, where_to_unwtar_info_xml, shallow=True)
        retVal = False  # disabled for now because Info.xml is copied before unwtarring take place
    except:
        retVal = False
    return retVal


def unwtar_a_file(wtar_file_path: Path, destination_folder: Path, no_artifacts=False, ignore=None, copy_owner=False):
    try:
        wtar_file_paths = utils.find_split_files(wtar_file_path)

        log.debug(f"unwtar {wtar_file_path} to {destination_folder}")
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
                        with utils.ChangeDirIfExists(destination_folder):
                            disk_total_checksum = utils.get_recursive_checksums(destination_leaf_name, ignore=ignore).get("total_checksum", "disk_total_checksum_was_not_found")

                        if disk_total_checksum == tar_total_checksum:
                            do_the_unwtarring = False
                            log.debug(f"{wtar_file_paths[0]} skipping unwtarring because item exists and is identical to archive")
                if do_the_unwtarring:
                    utils.safe_remove_file_system_object(destination_path)
                    tar.extractall(destination_folder)

                    if copy_owner:
                        from pybatch import Chown
                        first_wtar_file_st = os.stat(wtar_file_paths[0])
                        Chown(destination_folder, first_wtar_file_st[stat.ST_UID], first_wtar_file_st[stat.ST_GID], recursive=True)()

        if no_artifacts:
            for wtar_file in wtar_file_paths:
                os.remove(wtar_file)

    except OSError as e:
        log.warning(f"Invalid stream on split file with {wtar_file_paths[0]}")
        raise e

    except tarfile.TarError:
        log.warning(f"tarfile error while opening file {os.path.abspath(wtar_file_paths[0])}")
        raise


class Wtar(PythonBatchCommandBase):
    """ create a new wtar archive for a file or folder
    """
    def __init__(self, what_to_wtar: os.PathLike, where_to_put_wtar=None, split_threshold=0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_wtar = what_to_wtar
        self.where_to_put_wtar = where_to_put_wtar if where_to_put_wtar else None
        self.split_threshold = split_threshold

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f'''what_to_wtar={utils.quoteme_raw_by_type(self.what_to_wtar)}''')
        if self.where_to_put_wtar:
            all_args.append(f'''where_to_put_wtar={utils.quoteme_raw_by_type(self.where_to_put_wtar)}''')
        if self.split_threshold > 0:
            all_args.append(f'''split_threshold={utils.quoteme_raw_by_type(self.split_threshold)}''')

    def progress_msg_self(self) -> str:
        return f"""Compress '{self.what_to_wtar}' to '{self.where_to_put_wtar}'"""

    def __call__(self, *args, **kwargs) -> None:
        """ Create a new wtar archive for a file or folder provided in self.what_to_wtar

            If self.resolved_where_to_put_wtar is None the new wtar file will be created
                next to the input with extension '.wtar'.
                e.g. the call:
                    Wtar(/a/b/c)
                will create the wtar file at path:
                    /a/b/c.wtar

            If self.resolved_where_to_put_wtar is an existing file, the new wtar will overwrite
                this existing file, wtar extension will NOT be added.
                e.g. assuming /d/e/f.txt is an existing file, the call:
                    Wtar(/a/b/c, /d/e/f.txt)
                will create the wtar file at path:
                    /d/e/f.txt

            if self.resolved_where_to_put_wtar is and existing folder the wtar file will be created
                inside this folder with extension '.wtar'.
                e.g. assuming /g/h/i is an existing folder, the call:
                    Wtar(/a/b/c, /g/h/i)
                will create the wtar file at path:
                    /g/h/i/c.wtar

            if self.resolved_where_to_put_wtar is not None but does not exists, the folder will be created
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

        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_what_to_wtar = utils.ResolvedPath(self.what_to_wtar)

        if self.where_to_put_wtar is not None:
            resolved_where_to_put_wtar = utils.ResolvedPath(self.where_to_put_wtar)
        else:
            resolved_where_to_put_wtar = resolved_what_to_wtar.parent
            if not resolved_where_to_put_wtar:
                resolved_where_to_put_wtar = Path(os.curdir).resolve()

        if resolved_where_to_put_wtar.is_file():
            target_wtar_file = resolved_where_to_put_wtar
        else:  # assuming it's a folder
            resolved_where_to_put_wtar.mkdir(parents=True, exist_ok=True)
            target_wtar_file = resolved_where_to_put_wtar.joinpath(resolved_what_to_wtar.name+".wtar")

        # remove previous wtarred files
        if target_wtar_file.is_file():
            target_wtar_file.unlink()
        # also look for parts
        target_wtar_dir = target_wtar_file.parent
        parts = target_wtar_dir.glob(target_wtar_file.name+".wtar.??")
        [p.unlink() for p in parts]

        tar_total_checksum = utils.get_wtar_total_checksum(target_wtar_file)
        ignore_files = list(config_vars.get("WTAR_IGNORE_FILES", []))

        self._doing = f"""wtarring '{resolved_what_to_wtar}' to '{target_wtar_file}''"""
        with utils.ChangeDirIfExists(resolved_what_to_wtar.parent):
            pax_headers = {"total_checksum": utils.get_recursive_checksums(resolved_what_to_wtar.name, ignore=ignore_files)["total_checksum"]}

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
                    tar.add(resolved_what_to_wtar.name, filter=check_tarinfo)

                with SplitFile(target_wtar_file, max_size=self.split_threshold, own_progress_count=0) as sf:
                    sf()
            else:
                log.debug(f"{resolved_what_to_wtar.name} skipped since {resolved_what_to_wtar.name}.wtar already exists and has the same contents")


class Unwtar(PythonBatchCommandBase):
    """ uncompress a wtar archive
    """
    def __init__(self, what_to_unwtar: os.PathLike, where_to_unwtar=None, no_artifacts=False, copy_owner=True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_unwtar = what_to_unwtar
        self.where_to_unwtar = where_to_unwtar if where_to_unwtar else None
        self.no_artifacts = no_artifacts
        self.copy_owner = copy_owner

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f'''what_to_unwtar={utils.quoteme_raw_by_type(self.what_to_unwtar)}''')
        if self.where_to_unwtar:
            all_args.append(f'''where_to_unwtar={utils.quoteme_raw_by_type(self.where_to_unwtar)}''')
        if self.no_artifacts:
            all_args.append(f'''no_artifacts=True''')

    def progress_msg_self(self) -> str:
        return f"""Expand '{self.what_to_unwtar}' to '{self.where_to_unwtar}'"""

    def __call__(self, *args, **kwargs) -> None:

        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        ignore_files = list(config_vars.get("WTAR_IGNORE_FILES", []))

        what_to_unwtar: Path = utils.ResolvedPath(self.what_to_unwtar)
        destination_folder: Path = utils.ResolvedPath(self.where_to_unwtar) if self.where_to_unwtar else what_to_unwtar.parent

        self._doing = f"""unwtar '{what_to_unwtar}' to '{destination_folder}''"""

        if what_to_unwtar.is_file():
            if utils.is_first_wtar_file(what_to_unwtar):
                unwtar_a_file(what_to_unwtar, destination_folder, no_artifacts=self.no_artifacts, ignore=ignore_files)

        elif what_to_unwtar.is_dir():
            if not can_skip_unwtar(what_to_unwtar, destination_folder):
                for root, dirs, files in os.walk(what_to_unwtar, followlinks=False):
                    # a hack to prevent unwtarring of the sync folder. Copy command might copy something
                    # to the top level of the sync folder.
                    if "bookkeeping" in dirs:
                        dirs[:] = []
                        log.debug(f"skipping {root} because bookkeeping folder was found")
                        continue

                    root_Path = Path(root)
                    tail_folder =root_Path.relative_to(what_to_unwtar)
                    where_to_unwtar_the_file = destination_folder.joinpath(tail_folder)
                    for a_file in files:
                        a_file_path = root_Path.joinpath(a_file)
                        if utils.is_first_wtar_file(a_file_path):
                            self._doing = f"""unwtarring '{a_file_path}' to '{where_to_unwtar_the_file}''"""
                            unwtar_a_file(a_file_path, where_to_unwtar_the_file, no_artifacts=self.no_artifacts, ignore=ignore_files)
            else:
                log.debug(f"unwtar {what_to_unwtar} to {self.where_to_unwtar} skipping unwtarring because both folders have the same Info.xml file")

        else:
            raise FileNotFoundError(what_to_unwtar)


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

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.what_to_wzip))
        if self.where_to_put_wzip:
            all_args.append(utils.quoteme_raw_by_type(self.where_to_put_wzip))

    def progress_msg_self(self) -> str:
        return f"""Zip '{self.what_to_wzip}' to '{self.where_to_put_wzip}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_what_to_zip = utils.ResolvedPath(self.what_to_wzip)

        if self.where_to_put_wzip:
            target_wzip_file = utils.ResolvedPath(self.where_to_put_wzip)
        else:
            target_wzip_file = resolved_what_to_zip.parent
            if not target_wzip_file:  # os.path.split might return empty string
                target_wzip_file = Path.cwd()
        if not target_wzip_file.is_file():
            # assuming it's a folder
            target_wzip_file.mkdir(parents=True, exist_ok=True)
            target_wzip_file = target_wzip_file.joinpath(resolved_what_to_zip.name+".wzip")

        self._doing = f"""wziping '{resolved_what_to_zip}' to '{target_wzip_file}'"""
        zlib_compression_level = int(config_vars.get("ZLIB_COMPRESSION_LEVEL", "8"))
        with open(target_wzip_file, "wb") as wfd, open(resolved_what_to_zip, "rb") as rfd:
            wfd.write(zlib.compress(rfd.read(), zlib_compression_level))


class Unwzip(PythonBatchCommandBase):
    def __init__(self, what_to_unwzip: os.PathLike, where_to_put_unwzip=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_unwzip = os.fspath(what_to_unwzip)
        self.where_to_put_unwzip = os.fspath(where_to_put_unwzip) if where_to_put_unwzip else None
        self.resolved_what_to_unwzip = None
        self.target_unwzip_file = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.what_to_unwzip))
        if self.where_to_put_unwzip:
            all_args.append(utils.quoteme_raw_by_type(self.where_to_put_unwzip))

    def progress_msg_self(self) -> str:
        return f"""Unzip '{self.what_to_unwzip}' to '{self.where_to_put_unwzip}'"""

    def __call__(self, *args, **kwargs) -> None:
        resolved_what_to_unwzip = utils.ResolvedPath(self.what_to_unwzip)
        target_unwzip_file = utils.ResolvedPath(self.where_to_put_unwzip)
        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(resolved_what_to_unwzip)
        if not target_unwzip_file:
            target_unwzip_file = resolved_what_to_unwzip.parent
            if not target_unwzip_file:  # os.path.split might return empty string
                target_unwzip_file = Path.cwd()
        if not target_unwzip_file.is_file():
            # assuming it's a folder
            target_unwzip_file.mkdir(parents=True, exist_ok=True)
            if resolved_what_to_unwzip.name.endswith(".wzip"):
                what_to_work_on_leaf = resolved_what_to_unwzip.stem
            target_unwzip_file = os.path.join(target_unwzip_file, what_to_work_on_leaf)

        self._doing = f"""unzipping '{resolved_what_to_unwzip}' to '{target_unwzip_file}''"""
        with open(resolved_what_to_unwzip, "rb") as rfd, open(target_unwzip_file, "wb") as wfd:
            decompressed = zlib.decompress(rfd.read())
            wfd.write(decompressed)
