import os
import shutil
from collections import defaultdict

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
        params.append(self.optional_named__init__param("verbose", self.verbose, 0))
        params.append(self.optional_named__init__param("dry_run", self.dry_run, False))
        params_text = ", ".join(filter(None, params))
        if params_text:
            the_repr += params_text
        the_repr += ")"
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f"""Copy '{self.src}' to '{self.dst}'"""

    def __call__(self, *args, **kwargs) -> None:
        expanded_src = os.path.expandvars(self.src)
        expanded_dst = os.path.expandvars(self.dst)
        self.copy_tree(expanded_src, expanded_dst)

    def get_ignored_files(self, root, names_in_root):
        ignored_names = []
        if self.ignore_patterns:
            if self._get_ignored_files_func is None:
                self._get_ignored_files_func = shutil.ignore_patterns(*self.ignore_patterns)
            ignored_names.extend(self._get_ignored_files_func(root, names_in_root))
        return ignored_names

    def remove_extraneous_files(self, dst, src_names):
        """ remove files in destination that are not in source.
            files in the ignore list are not removed even if they do not
            appear in the source.
        """
        dst_names = os.listdir(dst)
        dst_ignored_names = self.get_ignored_files(dst, dst_names)

        for dst_name in dst_names:
            if dst_name not in src_names and dst_name not in dst_ignored_names:
                dst_path = os.path.join(dst, dst_name)
                self.last_step, self.last_src, self.last_dst = "remove_extraneous_files", "", dst_path
                log.info(f"delete {dst_path}")
                if os.path.islink(dst_path) or os.path.isfile(dst_path):
                    self.dry_run or os.unlink(dst_path)
                else:
                    self.dry_run or shutil.rmtree(dst_path)

    def copy_symlink(self, src_path, dst_path):
        self.last_step, self.last_src, self.last_dst = "copy_symlink", src_path, dst_path
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
            if os.path.isdir(src_path):
                self.copy_tree(src_path, dst_path)
            else:
                self.copy_file_to_file(src_path, dst_path)

    def should_copy_file(self, src, dst):
        retVal = True
        if os.path.isfile(dst):
            src_stats = os.stat(src)
            dst_stats = os.stat(dst)
            if src_stats.st_ino == dst_stats.st_ino:
                retVal = False
                log.info(f"{self.progress_msg()} skip copy file, same inode '{src}' to '{dst}'")
            elif src_stats.st_size == dst_stats.st_size and src_stats.st_mtime == dst_stats.st_mtime:
                retVal = False
                log.info(f"{self.progress_msg()} skip copy file, same time and size '{src}' to '{dst}'")
        if retVal:
            log.debug(f"no skip copy file '{src}' to '{dst}'")
        return retVal

    def copy_file_to_file(self, src, dst, follow_symlinks=True):
        """ copy the file src to the file dst. dst should either be an existing file
            or not exists at all - i.e. dst cannot be a folder. The parent folder of dst
            is assumed to exist
        """
        self.last_step, self.last_src, self.last_dst = "copy_file_to_file", src, dst
        if self.should_copy_file(src, dst):
            if not self.hard_links or os.path.islink(src):
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
        else:
            self.statistics['skipped_files'] += 1
        return dst

    def copy_file_to_dir(self, src, dst, follow_symlinks=True):
        self.last_step, self.last_src, self.last_dst = "copy_file_to_dir", src, dst

        os.makedirs(dst, exist_ok=True)
        dst = os.path.join(dst, os.path.basename(src))
        retVal = self.copy_file_to_file(src, dst, follow_symlinks)
        return retVal

    def copy_tree(self, src, dst):
        """ based on shutil.copytree
        """
        self.last_step, self.last_src, self.last_dst = "copy_tree", src, dst

        self.statistics['dirs'] += 1
        log.debug(f"copy folder '{src}' to '{dst}'")
        src_names = os.listdir(src)
        os.makedirs(dst, exist_ok=True)

        if self.delete_extraneous_files:
            self.remove_extraneous_files(dst, src_names)

        src_ignored_names = self.get_ignored_files(src, src_names)
        errors = []
        for src_name in src_names:
            src_path = os.path.join(src, src_name)
            if src_name in src_ignored_names:
                self.statistics['ignored'] += 1
                log.debug(f"ignoring '{src_path}'")
                continue
            dst_path = os.path.join(dst, src_name)
            try:
                if os.path.islink(src_path):
                    self.statistics['symlinks'] += 1
                    self.copy_symlink(src_path, dst_path)
                elif os.path.isdir(src_path):
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

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update(
            {'copy_from': os.fspath(self.src),
             'copy_to': os.fspath(self.dst),
             'last_step': self.last_step,
             'last_src': os.fspath(self.last_src),
             'last_dst': os.fspath(self.last_dst),
             'errno': getattr(exc_val, 'errno', "unknown"),
             'strerror': getattr(exc_val, 'strerror', "unknown")})


class CopyDirToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        expanded_src = os.path.expandvars(self.src)
        dst = os.path.join(self.dst, os.path.basename(self.src))
        expanded_dst = os.path.expandvars(dst)
        self.copy_tree(expanded_src, expanded_dst)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class CopyDirContentsToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class CopyFileToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs):
        expanded_src = os.path.expandvars(self.src)
        expanded_dst = os.path.expandvars(self.dst)
        self.copy_file_to_dir(expanded_src, expanded_dst)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class CopyFileToFile(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        expanded_src = os.path.expandvars(self.src)
        #if self.ignore_if_not_exist and not os.path.isfile():

        expanded_dst = os.path.expandvars(self.dst)
        os.makedirs(os.path.dirname(expanded_dst), exist_ok=True)
        self.copy_file_to_file(expanded_src, expanded_dst)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})
