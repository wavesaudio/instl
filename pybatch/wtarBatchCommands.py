import filecmp
import logging
import os
import stat
import tarfile
import zipfile
import concurrent.futures
from collections import OrderedDict
from pathlib import Path
from typing import List

import zlib

import utils
from configVar import config_vars
from .baseClasses import PythonBatchCommandBase
from .fileSystemBatchCommands import SplitFile, FixAllPermissions, MakeDir
from .removeBatchCommands import RmDir, RmFile

log = logging.getLogger(__name__)


def _unwtar_one_archive(wtar_file_path_str, destination_folder_str, no_artifacts, ignore, copy_owner):
    """ Extract a single (possibly split) wtar archive. This is a module-level,
        picklable function so it can run inside a ProcessPoolExecutor worker.

        It receives ONLY plain picklable data (strings/tuples/bools) - never the
        Unwtar command object nor config_vars. It performs the same extraction,
        copy_owner (Chown) and no_artifacts removal as the serial path, but it
        does NOT touch any process-global state (config_vars, the pybatch
        progress/stage stack, copyPhaseProgress). Progress reporting
        (report_copy_bytes) is intentionally left to the MAIN process which sums
        the returned wtar-file sizes after each archive completes.

        Returns the list of wtar file path strings that make up this archive so
        the caller (main process) can stat/sum their sizes for progress and so
        error reporting can list them.
    """
    wtar_file_path = Path(wtar_file_path_str)
    destination_folder = Path(destination_folder_str)
    if ignore is None:
        ignore = ()

    wtar_file_paths = utils.find_split_files(wtar_file_path)

    log.debug(f"unwtar {wtar_file_path} to {destination_folder}")

    destination_leaf_name = utils.original_name_from_wtar_name(wtar_file_paths[0].name)
    destination_path = destination_folder.joinpath(destination_leaf_name)

    do_the_unwtarring = True
    with utils.MultiFileReader("br", wtar_file_paths) as fd:
        with tarfile.open(fileobj=fd) as tar:
            tar_total_checksum = tar.pax_headers.get("total_checksum")
            if tar_total_checksum:
                try:
                    if destination_path.exists():
                        with utils.ChangeDirIfExists(destination_folder):
                            disk_total_checksum = utils.get_recursive_checksums(destination_leaf_name, ignore=ignore).get("total_checksum", "disk_total_checksum_was_not_found")

                        if disk_total_checksum == tar_total_checksum:
                            log.debug(f"{wtar_file_paths[0]} skipping unwtarring because item(s) exist and are identical to archive")
                            do_the_unwtarring = False
                except:
                    # if checking checksum failed for any reason -> do the unwtarring
                    pass
            if do_the_unwtarring:
                with RmDir(destination_path, report_own_progress=False, recursive=True) as dir_remover:
                    # RmDir will also remove a file and will not raise if destination_path does not exist
                    dir_remover()
                tar.extractall(destination_folder)

                if copy_owner:
                    from pybatch import Chown
                    first_wtar_file_st = wtar_file_paths[0].stat()
                    Chown(destination_folder, first_wtar_file_st[stat.ST_UID], first_wtar_file_st[stat.ST_GID], recursive=True)()
            else:
                log.info(f"skip uwtar of {destination_path} because it exists and matches wtar file checksum")

    if no_artifacts:
        for wtar_file in wtar_file_paths:
            with RmFile(wtar_file, report_own_progress=False) as wtar_remover:
                wtar_remover()

    return [os.fspath(p) for p in wtar_file_paths]


def can_skip_unwtar(what_to_work_on: Path, where_to_unwtar: Path):
    try:
        what_to_work_on_info_xml = what_to_work_on.joinpath("Contents", "Info.xml")
        where_to_unwtar_info_xml = where_to_unwtar.joinpath("Contents", "Info.xml")
        retVal = filecmp.cmp(what_to_work_on_info_xml, where_to_unwtar_info_xml, shallow=True)
        retVal = False  # disabled for now because Info.xml is copied before unwtarring take place
    except:
        retVal = False
    return retVal


class Wtar(PythonBatchCommandBase):
    """ create a new wtar archive for a file or folder
    """
    def __init__(self, what_to_wtar: os.PathLike, where_to_put_wtar=None, split_threshold=0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.what_to_wtar = what_to_wtar
        self.where_to_put_wtar = where_to_put_wtar if where_to_put_wtar else None
        self.split_threshold = split_threshold

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("what_to_wtar", self.what_to_wtar))
        all_args.append(self.optional_named__init__param("where_to_put_wtar", self.where_to_put_wtar))
        all_args.append(self.optional_named__init__param("split_threshold", self.split_threshold, 0))

    def progress_msg_self(self) -> str:
        if self.where_to_put_wtar:
            return f"""Compress '{self.what_to_wtar}' to '{self.where_to_put_wtar}'"""
        else:
            return f"""Compress '{self.what_to_wtar}' inplace"""

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
        resolved_what_to_wtar = utils.ExpandAndResolvePath(self.what_to_wtar)

        if self.where_to_put_wtar is not None:
            resolved_where_to_put_wtar = utils.ExpandAndResolvePath(self.where_to_put_wtar)
        else:
            resolved_where_to_put_wtar = resolved_what_to_wtar.parent
            if not resolved_where_to_put_wtar:
                resolved_where_to_put_wtar = Path(os.curdir).resolve()

        if resolved_where_to_put_wtar.is_file():
            target_wtar_file = resolved_where_to_put_wtar
        else:  # assuming it's a folder
            with MakeDir(resolved_where_to_put_wtar.parent, report_own_progress=False) as md:
                md()
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

        self.doing = f"""wtarring '{resolved_what_to_wtar}' to '{target_wtar_file}''"""
        with FixAllPermissions(resolved_what_to_wtar, report_own_progress=False, recursive=resolved_what_to_wtar.is_dir()) as perm_fixer:
            perm_fixer()
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
                    # hopefully the final tar will be the same for different runs.
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
        self.wtar_file_paths = None

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("what_to_unwtar", self.what_to_unwtar))
        all_args.append(self.optional_named__init__param("where_to_unwtar", self.where_to_unwtar, None))
        all_args.append(self.optional_named__init__param("no_artifacts", self.no_artifacts, False))

    def progress_msg_self(self) -> str:
        return f"""Expand '{self.what_to_unwtar}' to '{self.where_to_unwtar}'"""

    def error_dict_self(self, exc_type, exc_val, exc_tb) -> None:
        super().error_dict_self(exc_type, exc_val, exc_tb)
        # replace plain paths with detailed info such as size, permissions, mod date, user, group
        self.wtar_file_paths = [utils.single_disk_item_listing(wtar_file_path, "PuUgGRTfC") for wtar_file_path in self.wtar_file_paths]

    def _report_archive_bytes(self, wtar_file_path_strs) -> None:
        """ Workstream 3 option b: report an archive's bytes toward the
            copy-phase progress (no-op unless an install copy phase is armed).
            MUST run on the MAIN process - copyPhaseProgress is process-global,
            non-reentrant state. Best-effort; never breaks a sync. The size is
            summed from the wtar files; if no_artifacts already removed them the
            stat will fail and we simply skip (best-effort). """
        try:
            from pybatch.copyPhaseProgress import report_copy_bytes
            total = 0
            for p in wtar_file_path_strs:
                try:
                    total += Path(p).stat().st_size
                except OSError:
                    pass
            report_copy_bytes(total)
        except Exception:
            pass

    def unwtar_a_file(self, wtar_file_path: Path, destination_folder: Path, no_artifacts=False, ignore=None, copy_owner=False):
        if ignore is None:
            ignore = ()
        self.wtar_file_paths = utils.find_split_files(wtar_file_path)
        destination_leaf_name = utils.original_name_from_wtar_name(self.wtar_file_paths[0].name)
        destination_path = destination_folder.joinpath(destination_leaf_name)
        self.doing = f"""unwtar file '{wtar_file_path}' to '{destination_folder} ({"already exists" if destination_path.exists() else "not exists"})'"""
        try:
            # report bytes BEFORE no_artifacts removal so the wtar files can still
            # be stat'd; done here (main process) for both serial and parallel paths.
            done_paths = _unwtar_one_archive(os.fspath(wtar_file_path), os.fspath(destination_folder),
                                             no_artifacts=False, ignore=ignore, copy_owner=copy_owner)
            self._report_archive_bytes(done_paths)
            if no_artifacts:
                for wtar_file in self.wtar_file_paths:
                    with RmFile(wtar_file, report_own_progress=False) as wtar_remover:
                        wtar_remover()

        except OSError as e:
            log.warning(f"Invalid stream on split file with {self.wtar_file_paths[0]}")
            raise e

        except tarfile.TarError:
            log.warning(f"tarfile error while unwtarring file {self.wtar_file_paths[0]}")
            raise

    @staticmethod
    def _resolve_worker_count() -> int:
        """ Number of worker processes for parallel unwtar. DOWNLOAD_PARALLEL_WORKERS=0
            means auto (os.cpu_count()). Returns >=1; 1 means "run serial". """
        try:
            configured = int(config_vars.get("DOWNLOAD_PARALLEL_WORKERS", 0))
        except (ValueError, TypeError):
            configured = 0
        if configured <= 0:
            configured = os.cpu_count() or 1
        return max(1, configured)

    @staticmethod
    def _partition_independent(jobs):
        """ jobs is a list of (wtar_file_path, destination_folder). Partition into
            two groups: those whose destination_folder is clearly independent of
            every other job's destination (no equal/nested/overlapping destination
            subtree) - safe to run concurrently - and the rest, which must run
            serially. When in doubt a job is treated as NOT independent. """
        # resolve destination folders once for comparison
        resolved = []
        for wtar_file_path, destination_folder in jobs:
            try:
                resolved.append(Path(destination_folder).resolve())
            except OSError:
                resolved.append(Path(destination_folder))

        def overlaps(a: Path, b: Path) -> bool:
            # a and b overlap if equal or one is an ancestor of the other
            if a == b:
                return True
            try:
                a.relative_to(b)
                return True
            except ValueError:
                pass
            try:
                b.relative_to(a)
                return True
            except ValueError:
                pass
            return False

        independent_idx = []
        serial_idx = []
        for i in range(len(jobs)):
            collides = False
            for j in range(len(jobs)):
                if i == j:
                    continue
                if overlaps(resolved[i], resolved[j]):
                    collides = True
                    break
            if collides:
                serial_idx.append(i)
            else:
                independent_idx.append(i)
        parallel_jobs = [jobs[i] for i in independent_idx]
        serial_jobs = [jobs[i] for i in serial_idx]
        return parallel_jobs, serial_jobs

    def _unwtar_jobs_parallel(self, jobs, ignore_files):
        """ Run a list of (wtar_file_path, destination_folder) extraction jobs.
            Honors DOWNLOAD_PARALLEL_UNWTAR / DOWNLOAD_PARALLEL_WORKERS, falls
            back to serial when the flag is off, workers<=1, or <2 independent
            jobs. All progress emission and shared-state mutation
            (self.wtar_file_paths, report_copy_bytes, no_artifacts removal) happen
            on the MAIN process; workers only extract+chown and return paths. """
        parallel_enabled = bool(config_vars.get("DOWNLOAD_PARALLEL_UNWTAR", "no"))
        workers = self._resolve_worker_count()

        parallel_jobs, serial_jobs = ([], jobs)
        if parallel_enabled and workers > 1 and len(jobs) > 1:
            parallel_jobs, serial_jobs = self._partition_independent(jobs)

        if len(parallel_jobs) < 2:
            # not worth a pool / nothing independent -> everything serial
            serial_jobs = jobs
            parallel_jobs = []

        if parallel_jobs:
            workers = min(workers, len(parallel_jobs))
            futures = {}
            try:
                # ThreadPoolExecutor (not ProcessPoolExecutor): instl ships as a
                # FROZEN PyInstaller binary, where a process pool uses 'spawn' on
                # macOS/Windows -- it would re-exec the instl binary AND the
                # workers would not inherit the parent's populated config_vars /
                # DB state, breaking extraction. Threads run in-process (config_vars
                # available, no pickling, no freeze_support needed) and still
                # parallelize: tarfile's bz2 decompression and the file I/O release
                # the GIL, so independent archives extract concurrently. Worker
                # archives target disjoint destinations (see _partition_independent),
                # so concurrent extraction is safe.
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    for wtar_file_path, destination_folder in parallel_jobs:
                        fut = executor.submit(_unwtar_one_archive,
                                              os.fspath(wtar_file_path), os.fspath(destination_folder),
                                              False, tuple(ignore_files), self.copy_owner)
                        futures[fut] = (wtar_file_path, destination_folder)
                    for fut in concurrent.futures.as_completed(futures):
                        wtar_file_path, destination_folder = futures[fut]
                        # re-raise worker errors so a failed extract fails the command
                        done_paths = fut.result()
                        # main-thread-only shared-state mutation + progress
                        self.wtar_file_paths = utils.find_split_files(wtar_file_path)
                        self._report_archive_bytes(done_paths)
                        if self.no_artifacts:
                            for wtar_file in done_paths:
                                with RmFile(wtar_file, report_own_progress=False) as wtar_remover:
                                    wtar_remover()
            except Exception as pool_ex:
                # pool unavailable -> fall back to serial for everything not yet done
                log.warning(f"parallel unwtar thread pool unavailable, falling back to serial: {pool_ex}")
                serial_jobs = jobs
                parallel_jobs = []

        for wtar_file_path, destination_folder in serial_jobs:
            self.unwtar_a_file(wtar_file_path, destination_folder, no_artifacts=self.no_artifacts, ignore=ignore_files, copy_owner=self.copy_owner)

    def __call__(self, *args, **kwargs) -> None:

        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        ignore_files = list(config_vars.get("WTAR_IGNORE_FILES", []))

        self.what_to_unwtar = utils.ExpandAndResolvePath(self.what_to_unwtar)

        if self.what_to_unwtar.is_file():
            if utils.is_first_wtar_file(self.what_to_unwtar):
                if self.where_to_unwtar:
                    destination_folder: Path = utils.ExpandAndResolvePath(self.where_to_unwtar)
                else:
                    destination_folder = self.what_to_unwtar.parent

                self.unwtar_a_file(self.what_to_unwtar, destination_folder, no_artifacts=self.no_artifacts, ignore=ignore_files, copy_owner=self.copy_owner)

        elif self.what_to_unwtar.is_dir():
            if self.where_to_unwtar:
                destination_folder = Path(self.where_to_unwtar, self.what_to_unwtar.name)
            else:
                destination_folder = self.what_to_unwtar
            self.doing = f"""unwtar folder '{self.what_to_unwtar}' to '{destination_folder}''"""
            if not can_skip_unwtar(self.what_to_unwtar, destination_folder):
                # collect all independent archive-extraction jobs first, then
                # dispatch them (parallel when enabled, else serial). Each job is
                # (first_wtar_file_path, destination_folder_for_that_archive).
                jobs = []
                for root, dirs, files in os.walk(self.what_to_unwtar, followlinks=False):
                    # a hack to prevent unwtarring of the sync folder. Copy command might copy something
                    # to the top level of the sync folder.
                    if "bookkeeping" in dirs:
                        dirs[:] = []
                        log.debug(f"skipping {root} because bookkeeping folder was found")
                        continue

                    root_Path = Path(root)
                    tail_folder = root_Path.relative_to(self.what_to_unwtar)
                    for a_file in files:
                        a_file_path = root_Path.joinpath(a_file)
                        if utils.is_first_wtar_file(a_file_path):
                            where_to_unwtar_the_file = destination_folder.joinpath(tail_folder)
                            jobs.append((a_file_path, where_to_unwtar_the_file))
                self._unwtar_jobs_parallel(jobs, ignore_files)
            else:
                log.debug(f"unwtar {self.what_to_unwtar} to {self.where_to_unwtar} skipping unwtarring because both folders have the same Info.xml file")

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

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.what_to_wzip))
        all_args.append(self.optional_named__init__param("where_to_put_wzip", self.where_to_put_wzip))

    def progress_msg_self(self) -> str:
        if self.where_to_put_wzip:
            return f"""Zip '{self.what_to_wzip}' to '{self.where_to_put_wzip}'"""
        else:
            return f"""Zip '{self.what_to_wzip}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)
        resolved_what_to_zip = utils.ExpandAndResolvePath(self.what_to_wzip)

        if self.where_to_put_wzip:
            target_wzip_file = utils.ExpandAndResolvePath(self.where_to_put_wzip)
        else:
            target_wzip_file = resolved_what_to_zip.parent
            if not target_wzip_file:  # os.path.split might return empty string
                target_wzip_file = Path.cwd()
        if not target_wzip_file.is_file():
            # assuming it's a folder
            with MakeDir(target_wzip_file.parent, report_own_progress=False) as md:
                md()
            target_wzip_file = target_wzip_file.joinpath(resolved_what_to_zip.name+".wzip")

        self.doing = f"""wziping '{resolved_what_to_zip}' to '{target_wzip_file}'"""
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
        all_args.append(self.unnamed__init__param(self.what_to_unwzip))
        all_args.append(self.optional_named__init__param("where_to_put_unwzip", self.where_to_put_unwzip))

    def progress_msg_self(self) -> str:
        return f"""Unzip '{self.what_to_unwzip}' to '{self.where_to_put_unwzip}'"""

    def __call__(self, *args, **kwargs) -> None:
        resolved_what_to_unwzip = utils.ExpandAndResolvePath(self.what_to_unwzip)
        target_unwzip_file = utils.ExpandAndResolvePath(self.where_to_put_unwzip)
        what_to_work_on_dir, what_to_work_on_leaf = os.path.split(resolved_what_to_unwzip)
        if not target_unwzip_file:
            target_unwzip_file = resolved_what_to_unwzip.parent
            if not target_unwzip_file:  # os.path.split might return empty string
                target_unwzip_file = Path.cwd()
        if not target_unwzip_file.is_file():
            # assuming it's a folder to unzip into - make the folder itself
            # (not just its parent) so the joined target file can be written
            with MakeDir(target_unwzip_file, report_own_progress=False) as md:
                md()
            if resolved_what_to_unwzip.name.endswith(".wzip"):
                what_to_work_on_leaf = resolved_what_to_unwzip.stem
            target_unwzip_file = os.path.join(target_unwzip_file, what_to_work_on_leaf)

        self.doing = f"""unzipping '{resolved_what_to_unwzip}' to '{target_unwzip_file}''"""
        with open(resolved_what_to_unwzip, "rb") as rfd, open(target_unwzip_file, "wb") as wfd:
            decompressed = zlib.decompress(rfd.read())
            wfd.write(decompressed)


class ZipFlat(PythonBatchCommandBase):
    """ Create a new zip from a list files, do not compress
        files are added "flat" i.e. the original folder structure is not
        kept
    """

    def __init__(self, target_zip, files_to_zip, **kwargs) -> None:
        super().__init__(**kwargs)
        self.target_zip = Path(target_zip)
        self.files_to_zip = [Path(f) for f in files_to_zip]

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("target_zip", self.target_zip))
        all_args.append(self.named__init__param("files_to_zip", self.files_to_zip))

    def progress_msg_self(self) -> str:
        return f"""Zip '{len(self.files_to_zip)}' files to '{self.target_zip}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)

        if not self.target_zip.is_file():
            # create parent folder
            with MakeDir(self.target_zip.parent, report_own_progress=False) as md:
                md()

        self.doing = f"""zipping '{len(self.files_to_zip)}' items to '{self.target_zip}'"""
        with zipfile.ZipFile(self.target_zip, "w") as zfd:
            for item_to_zip in self.files_to_zip:
                zfd.write(os.fspath(item_to_zip), arcname=item_to_zip.name)


class UnZip(PythonBatchCommandBase):
    """ unzip .zip file (source_zip) to target_folder
        if source_zip is a folder, all .zip files will be unzipped
        if no_artifacts is true the zip files will be deleted
    """

    def __init__(self, source_zip, target_folder, no_artifacts=False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.source_zip = Path(source_zip)
        self.target_folder = Path(target_folder)
        self.no_artifacts = no_artifacts

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("source_zip", self.source_zip))
        all_args.append(self.named__init__param("target_folder", self.target_folder))
        all_args.append(self.optional_named__init__param("no_artifacts", self.no_artifacts, False))

    def progress_msg_self(self) -> str:
        return f"""UnZip '{self.source_zip}' to '{self.target_folder}'"""

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.__call__(self, *args, **kwargs)

        if not self.target_folder.is_dir():
            with MakeDir(self.target_folder, report_own_progress=False) as md:
                md()

        if self.source_zip.is_file():
            self.doing = f"""UnZipping '{self.source_zip}' to '{self.target_folder}'"""
            with zipfile.ZipFile(self.source_zip, "r") as zfd:
                zfd.extractall(path=self.target_folder)
            if self.no_artifacts:
                with RmFile(self.source_zip, report_own_progress=False) as rm_file:
                    rm_file()
        elif self.source_zip.is_dir():

            for zip_file in self.source_zip.glob("*.zip"):
                self.doing = f"""UnZipping '{zip_file}' to '{self.target_folder}'"""
                with zipfile.ZipFile(zip_file, "r") as zfd:
                    zfd.extractall(path=self.target_folder)
                if self.no_artifacts:
                    with RmFile(zip_file, report_own_progress=False) as rm_file:
                        rm_file()
