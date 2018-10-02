import os
import shutil
from collections import defaultdict
from pathlib import Path

# ToDo: add unwtar ?


from .batchCommands import *
log = logging.getLogger()


class RsyncClone(PythonBatchCommandBase, essential=True):

    __global_ignore_patterns = list()        # files and folders matching these patterns will not be copied. Applicable for all instances of RsyncClone
    __global_no_hard_link_patterns = list()  # files and folders matching these patterns will not be hard-linked. Applicable for all instances of RsyncClone
    __global_avoid_copy_markers = list()     # if a file with one of these names exists in the folders and is identical to destination, copy will be avoided

    @classmethod
    def add_global_ignore_patterns(cls, more_copy_ignore_patterns: List):
        cls.__global_ignore_patterns.extend(more_copy_ignore_patterns)

    @classmethod
    def add_global_no_hard_link_patterns(cls, more_no_hard_link_patterns: List):
        cls.__global_no_hard_link_patterns.extend(more_no_hard_link_patterns)

    @classmethod
    def add_global_avoid_copy_markers(cls, more_avoid_copy_markers: List):
        cls.__global_avoid_copy_markers.extend(more_avoid_copy_markers)

    def __init__(self,
                 src,
                 dst,
                 ignore_if_not_exist=False,
                 symlinks_as_symlinks=True,
                 ignore_patterns=[],        # files and folders matching this patterns will not be copied. Applicable only for this instance of RsyncClone
                 no_hard_link_patterns=[],  # files and folders matching this patterns will not be hard-linked. Applicable only for this instance of RsyncClone
                 hard_links=True,
                 ignore_dangling_symlinks=False,
                 delete_extraneous_files=False,
                 copy_owner=True,
                 verbose=0,
                 dry_run=False,
                 **kwargs):
        super().__init__(**kwargs)
        self.src = src
        self.dst = dst
        self.ignore_if_not_exist = ignore_if_not_exist
        self.symlinks_as_symlinks = symlinks_as_symlinks
        self.local_ignore_patterns = ignore_patterns
        self.local_no_hard_link_patterns = no_hard_link_patterns
        self.hard_links = hard_links
        self.ignore_dangling_symlinks = ignore_dangling_symlinks
        self.delete_extraneous_files = delete_extraneous_files
        self.copy_owner = copy_owner
        self.verbose = verbose
        self.dry_run = dry_run

        self._get_ignored_files_func = None
        self.statistics = defaultdict(int)
        self.last_step = None
        self.last_src = None
        self.last_dst = None

        if self.ignore_if_not_exist:
            self.exceptions_to_ignore.append(FileNotFoundError)

        self.__all_ignore_patterns = list(set(self.__global_ignore_patterns + self.local_ignore_patterns))
        self.__all_no_hard_link_patterns = list(set(self.__global_no_hard_link_patterns + self.local_no_hard_link_patterns))

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        params = []
        params.append(self.unnamed__init__param(os.fspath(self.src)))
        params.append(self.unnamed__init__param(os.fspath(self.dst)))
        params.append(self.optional_named__init__param("ignore_if_not_exist", self.ignore_if_not_exist, False))
        params.append(self.optional_named__init__param("symlinks_as_symlinks", self.symlinks_as_symlinks, True))
        params.append(self.optional_named__init__param("ignore_patterns", self.local_ignore_patterns, []))
        params.append(self.optional_named__init__param("no_hard_link_patterns", self.local_no_hard_link_patterns, []))
        params.append(self.optional_named__init__param("hard_links", self.hard_links, True))
        params.append(self.optional_named__init__param("ignore_dangling_symlinks", self.ignore_dangling_symlinks, False))
        params.append(self.optional_named__init__param("delete_extraneous_files", self.delete_extraneous_files, False))
        params.append(self.optional_named__init__param("copy_owner", self.copy_owner, True))
        params.append(self.optional_named__init__param("verbose", self.verbose, 0))
        params.append(self.optional_named__init__param("dry_run", self.dry_run, False))
        params_text = ", ".join(filter(None, params))
        if params_text:
            the_repr += params_text
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""Copy '{os.path.expandvars(self.src)}' to '{os.path.expandvars(self.dst)}'"""

    def __call__(self, *args, **kwargs) -> None:
        resolved_src: Path = utils.ResolvedPath(self.src)
        resolved_dst: Path = utils.ResolvedPath(self.dst)
        self.copy_tree(resolved_src, resolved_dst)

    def should_ignore_file(self, file_path: Path):
        retVal = False
        for ignore_pattern in self.__all_ignore_patterns:
            if file_path.match(ignore_pattern):
                log.debug(f"ignoring {file_path} because it matches pattern {ignore_pattern}")
                retVal = True
                break
        return retVal

    def should_hard_link_file(self, file_path: Path):
        retVal = False
        if self.hard_links and not file_path.is_symlink():
            for no_hard_link_pattern in self.__all_no_hard_link_patterns:
                if file_path.match(no_hard_link_pattern):
                    log.debug(f"not hard linking {file_path} because it matches pattern {no_hard_link_pattern}")
                    break
            else:
                retVal = True
        return retVal

    def remove_extraneous_files(self, dst: Path, src_names):
        """ remove files in destination that are not in source.
            files in the ignore list are not removed even if they do not
            appear in the source.
        """
        dst_names = os.listdir(dst)

        for dst_path in dst.iterdir():
            if dst_path.name not in src_names and  not self.should_ignore_file(dst_path):
                #dst_path = dst.joinpath(dst_name)
                self.last_step, self.last_src, self.last_dst = "remove redundant file", "", os.fspath(dst_path)
                log.info(f"delete {dst_path}")
                if dst_path.is_symlink() or dst_path.is_file():
                    self.dry_run or dst_path.unlink()
                else:
                    self.dry_run or shutil.rmtree(dst_path)

    def copy_symlink(self, src_path: Path, dst_path: Path):
        self.last_src, self.last_dst = os.fspath(src_path), os.fspath(dst_path)
        self.doing = f"""copy symlink '{self.last_src}' to '{self.last_dst}'"""

        link_to = os.readlink(src_path)
        if self.symlinks_as_symlinks:
            self.dry_run or os.symlink(link_to, dst_path)
            self.dry_run or shutil.copystat(src_path, dst_path, follow_symlinks=False)
            log.info(f"create symlink '{dst_path}'")
        else:
            # ignore dangling symlink if the flag is on
            if not os.path.exists(link_to) and self.ignore_dangling_symlinks:
                return
            # otherwise let the copy occur. copy_file_to_file will raise an error
            log.debug(f"copy symlink contents '{src_path}' to '{dst_path}'")
            if src_path.is_dir():
                self.copy_tree(src_path, dst_path)
            else:
                self.copy_file_to_file(src_path, dst_path)

    def should_copy_file(self, src: Path, dst: Path):
        retVal = True
        if dst.is_file():
            src_stats = src.stat()
            dst_stats = dst.stat()
            if src_stats.st_ino == dst_stats.st_ino:
                retVal = False
                log.info(f"{self.progress_msg()} skip copy file, same inode '{src}' to '{dst}'")
            elif src_stats.st_size == dst_stats.st_size and src_stats.st_mtime == dst_stats.st_mtime:
                retVal = False
                log.info(f"{self.progress_msg()} skip copy file, same time and size '{src}' to '{dst}'")
            if retVal:  # destination exists and file should be copied, so make sure it's writable
                Chmod(dst, "u+w")()
        return retVal

    def should_copy_dir(self, src: Path, dst: Path):
        for avoid_copy_marker in self.__global_avoid_copy_markers:
            src_marker = Path(src, avoid_copy_marker)
            dst_marker = Path(dst, avoid_copy_marker)
            retVal = not utils.compare_files_by_checksum(src_marker, dst_marker)
            if not retVal:
                log.info(f"{self.progress_msg()} skip copy folder, same checksum '{src_marker}' and '{dst_marker}'")
                break
        else:
            retVal = True
        return retVal

    def copy_file_to_file(self, src: Path, dst: Path, follow_symlinks=True):
        """ copy the file src to the file dst. dst should either be an existing file
            or not exists at all - i.e. dst cannot be a folder. The parent folder of dst
            is assumed to exist
        """
        self.last_src, self.last_dst = os.fspath(src), os.fspath(dst)
        self.doing = f"""copy file '{self.last_src}' to '{self.last_dst}'"""

        if self.should_copy_file(src, dst):
            if not self.should_hard_link_file(src):
                log.debug(f"copy file '{src}' to '{dst}'")
                self.dry_run or shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
            else:  # try to create hard link
                try:
                    self.dry_run or os.link(src, dst)
                    log.debug(f"hard link file '{src}' to '{dst}'")
                    self.statistics['hard_links'] += 1
                except OSError as ose:
                    log.debug(f"copy file '{src}' to '{dst}'")
                    self.dry_run or shutil.copy2(src, dst, follow_symlinks=True)
            if self.copy_owner and hasattr(os, 'chown'):
                src_st = src.stat()
                os.chown(dst, src_st[stat.ST_UID], src_st[stat.ST_GID])
        else:
            self.statistics['skipped_files'] += 1
        return dst

    def copy_file_to_dir(self, src: Path, dst: Path, follow_symlinks=True):
        self.last_src, self.last_dst = os.fspath(src), os.fspath(dst)
        self.doing = f"""copy file '{self.last_src}' to '{self.last_dst}'"""

        dst.mkdir(parents=True, exist_ok=True)
        final_dst = dst.joinpath(src.name)
        retVal = self.copy_file_to_file(src, final_dst, follow_symlinks)
        return retVal

    def copy_tree(self, src: Path, dst: Path):
        """ based on shutil.copytree
        """
        self.last_src, self.last_dst = os.fspath(src), os.fspath(dst)

        self.doing = f"""copy folder '{self.last_src}' to '{self.last_dst}'"""

        if not self.should_copy_dir(src, dst):
            self.statistics['skipped_dirs'] += 1
            return

        self.statistics['dirs'] += 1
        log.debug(f"copy folder '{src}' to '{dst}'")
        src_names = os.listdir(src)
        dst.mkdir(parents=True, exist_ok=True)
        if self.copy_owner and hasattr(os, 'chown'):
            src_st = src.stat()
            os.chown(dst, src_st[stat.ST_UID], src_st[stat.ST_GID])

        if self.delete_extraneous_files:
            self.remove_extraneous_files(dst, src_names)

        errors = []
        for src_name in src_names:
            src_path = src.joinpath(src_name)
            if self.should_ignore_file(src_path):
                self.statistics['ignored'] += 1
                continue
            dst_path = dst.joinpath(src_name)
            try:
                if src_path.is_symlink():
                    self.statistics['symlinks'] += 1
                    self.copy_symlink(src_path, dst_path)
                elif src_path.is_dir():
                    self.copy_tree(src_path, dst_path)
                else:
                    self.statistics['files'] += 1
                    # Will raise a SpecialFileError for unsupported file types
                    self.copy_file_to_file(src_path, dst_path)
            # catch the Error from the recursive copytree so that we can
            # continue with other files
            except shutil.Error as err:
                errors.append(err.args[0])
            except OSError as why:
                errors.append((src_path, dst_path, str(why)))
        try:
            shutil.copystat(src, dst)
        except OSError as why:
            # Copying file access times may fail on Windows
            if getattr(why, 'winerror', None) is None:
                errors.append((src, dst, str(why)))
        if errors:
            raise shutil.Error(errors)
        return dst

    def error_dict_self(self, exc_type, exc_val, exc_tb) -> None:
        super().error_dict_self(exc_type, exc_val, exc_tb)
        last_src_stat = os.lstat(self.last_src)
        last_dst_stat = os.lstat(self.last_dst)
        self._error_dict.update(
            {'last_src':  {"path": os.fspath(self.last_src), "mode": utils.unix_permissions_to_str(last_src_stat.st_mode)},
             'last_dst':  {"path": os.fspath(self.last_dst), "mode": utils.unix_permissions_to_str(last_dst_stat.st_mode)}})


class CopyDirToDir(RsyncClone):
    """ copy a folder into another
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        resolved_src: Path = utils.ResolvedPath(self.src)
        resolved_dst: Path = utils.ResolvedPath(self.dst)
        final_dst: Path = resolved_dst.joinpath(resolved_src.name)
        self.copy_tree(resolved_src, final_dst)


class MoveDirToDir(CopyDirToDir):
    """ copy a folder into another and erase the source
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs):
        super().__call__(*args, **kwargs)
        self.doing = f"""removing dir '{self.src}'"""
        self.dry_run or shutil.rmtree(self.src, ignore_errors=self.ignore_if_not_exist)


class CopyDirContentsToDir(RsyncClone):
    """ copy the contents of a folder into another and erase the sources
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)


class MoveDirContentsToDir(CopyDirContentsToDir):
    """ copy the contents of a folder into another and erase the sources
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs):
        super().__call__(*args, **kwargs)
        self.doing = f"""removing contents dir '{self.src}'"""
        if not self.dry_run:
            for child_item in Path(self.src).iterdir():
                if child_item.is_file():
                    child_item.unlink()
                elif child_item.is_dir():
                    shutil.rmtree(child_item, ignore_errors=self.ignore_if_not_exist)


class CopyFileToDir(RsyncClone):
    """ copy a file into a folder
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs):
        resolved_src: Path = utils.ResolvedPath(self.src)
        resolved_dst: Path = utils.ResolvedPath(self.dst)
        self.copy_file_to_dir(resolved_src, resolved_dst)


class MoveFileToDir(CopyFileToDir):
    """ copy a file into a folder and erase the source
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs):
        super().__call__(*args, **kwargs)
        self.doing = f"""removing file '{self.src}'"""
        self.dry_run or Path(self.src).unlink()


class CopyFileToFile(RsyncClone):
    """ copy a file into another location
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        resolved_src: Path = utils.ResolvedPath(self.src)
        resolved_dst: Path = utils.ResolvedPath(self.dst)
        resolved_dst.parent.mkdir(parents=True, exist_ok=True)
        self.copy_file_to_file(resolved_src, resolved_dst)


class MoveFileToFile(CopyFileToFile):
    """ copy a file into another location and erase the source
        intermediate folders will be created as needed
    """
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        super().__call__(*args, **kwargs)
        self.doing = f"""removing file '{self.src}'"""
        self.dry_run or Path(self.src).unlink()
