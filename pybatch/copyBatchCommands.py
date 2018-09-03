import os
import shutil
from collections import defaultdict
from pathlib import Path

# ToDo: add unwtar ?


from .batchCommands import *
log = logging.getLogger(__name__)


class RsyncClone(PythonBatchCommandBase, essential=True):
    def __init__(self,
                 src,
                 dst,
                 ignore_if_not_exist=False,
                 symlinks_as_symlinks=True,
                 ignore_patterns=[],
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
        self.ignore_patterns = ignore_patterns
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

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        params = []
        params.append(self.unnamed__init__param(os.fspath(self.src)))
        params.append(self.unnamed__init__param(os.fspath(self.dst)))
        params.append(self.optional_named__init__param("ignore_if_not_exist", self.ignore_if_not_exist, False))
        params.append(self.optional_named__init__param("symlinks_as_symlinks", self.symlinks_as_symlinks, True))
        params.append(self.optional_named__init__param("ignore_patterns", self.ignore_patterns, []))
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

    def get_ignored_files(self, root: Path, names_in_root):
        ignored_names = []
        if self.ignore_patterns:
            if self._get_ignored_files_func is None:
                self._get_ignored_files_func = shutil.ignore_patterns(*self.ignore_patterns)
            ignored_names.extend(self._get_ignored_files_func(root, names_in_root))
        return ignored_names

    def remove_extraneous_files(self, dst: Path, src_names):
        """ remove files in destination that are not in source.
            files in the ignore list are not removed even if they do not
            appear in the source.
        """
        dst_names = os.listdir(dst)
        dst_ignored_names = self.get_ignored_files(dst, dst_names)

        for dst_name in dst_names:
            if dst_name not in src_names and dst_name not in dst_ignored_names:
                dst_path = dst.joinpath(dst_name)
                self.last_step, self.last_src, self.last_dst = "remove redundant file", "", dst_path
                log.info(f"delete {dst_path}")
                if dst_path.is_symlink() or dst_path.is_file():
                    self.dry_run or dst_path.unlink()
                else:
                    self.dry_run or shutil.rmtree(dst_path)

    def copy_symlink(self, src_path: Path, dst_path: Path):
        self.last_src, self.last_dst = src_path, dst_path
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
        if retVal:
            log.debug(f"no skip copy file '{src}' to '{dst}'")
        return retVal

    def copy_file_to_file(self, src: Path, dst: Path, follow_symlinks=True):
        """ copy the file src to the file dst. dst should either be an existing file
            or not exists at all - i.e. dst cannot be a folder. The parent folder of dst
            is assumed to exist
        """
        self.last_src, self.last_dst = src, dst
        self.doing = f"""copy file '{self.last_src}' to '{self.last_dst}'"""

        if self.should_copy_file(src, dst):
            if not self.hard_links or src.is_symlink():
                log.debug(f"copy file '{src}' to '{dst}'")
                self.dry_run or shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
            else:  # try to create hard link
                try:
                    self.dry_run or os.link(src, dst)
                    log.debug(f"hard link file '{src}' to '{dst}'")
                    self.statistics['hard_links'] += 1
                except OSError as ose:
                    self.dry_run or shutil.copy2(src, dst, follow_symlinks=True)
                    log.debug(f"copy file '{src}' to '{dst}'")
            if self.copy_owner and hasattr(os, 'chown'):
                src_st = src.stat()
                os.chown(dst, src_st[stat.ST_UID], src_st[stat.ST_GID])
        else:
            self.statistics['skipped_files'] += 1
        return dst

    def copy_file_to_dir(self, src: Path, dst: Path, follow_symlinks=True):
        self.last_src, self.last_dst = src, dst
        self.doing = f"""copy file '{self.last_src}' to '{self.last_dst}'"""

        dst.mkdir(parents=True, exist_ok=True)
        final_dst = dst.joinpath(src.name)
        retVal = self.copy_file_to_file(src, final_dst, follow_symlinks)
        return retVal

    def copy_tree(self, src: Path, dst: Path):
        """ based on shutil.copytree
        """
        self.last_src, self.last_dst = src, dst
        self.doing = f"""copy folder '{self.last_src}' to '{self.last_dst}'"""

        self.statistics['dirs'] += 1
        log.debug(f"copy folder '{src}' to '{dst}'")
        src_names = os.listdir(src)
        dst.mkdir(parents=True, exist_ok=True)
        if self.copy_owner and hasattr(os, 'chown'):
            src_st = src.stat()
            os.chown(dst, src_st[stat.ST_UID], src_st[stat.ST_GID])

        if self.delete_extraneous_files:
            self.remove_extraneous_files(dst, src_names)

        src_ignored_names = self.get_ignored_files(src, src_names)
        errors = []
        for src_name in src_names:
            src_path = src.joinpath(src_name)
            if src_name in src_ignored_names:
                self.statistics['ignored'] += 1
                log.debug(f"ignoring '{src_path}'")
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
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        resolved_src: Path = utils.ResolvedPath(self.src)
        resolved_dst: Path = utils.ResolvedPath(self.dst)
        final_dst: Path = resolved_dst.joinpath(resolved_src.name)
        self.copy_tree(resolved_src, final_dst)


class CopyDirContentsToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)


class CopyFileToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs):
        resolved_src: Path = utils.ResolvedPath(self.src)
        resolved_dst: Path = utils.ResolvedPath(self.dst)
        self.copy_file_to_dir(resolved_src, resolved_dst)


class CopyFileToFile(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        resolved_src: Path = utils.ResolvedPath(self.src)
        resolved_dst: Path = utils.ResolvedPath(self.dst)
        resolved_dst.parent.mkdir(parents=True, exist_ok=True)
        self.copy_file_to_file(resolved_src, resolved_dst)
