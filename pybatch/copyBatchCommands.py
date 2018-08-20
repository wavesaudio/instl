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
                 symlinks_as_symlinks=True,
                 patterns_to_ignore=[],
                 hard_links=True,
                 ignore_dangling_symlinks=False,
                 delete_extraneous_files=False,
                 verbose=0,
                 dry_run=False,
                 **kwargs):
        super().__init__(**kwargs)
        self.src = src
        self.dst = dst
        self.symlinks_as_symlinks = symlinks_as_symlinks
        self.patterns_to_ignore = patterns_to_ignore
        self.hard_links = hard_links
        self.ignore_dangling_symlinks = ignore_dangling_symlinks
        self.delete_extraneous_files = delete_extraneous_files
        self.verbose = verbose
        self.dry_run = dry_run

        self._get_ignored_files_func = None
        self.statistics = defaultdict(int)

    def unnamed__init__param(self, value):
        value_str = utils.quoteme_raw_if_string(value)
        return value_str

    def named__init__param(self, name, value):
        value_str = utils.quoteme_raw_if_string(value)
        param_repr = f"{name}={value_str}"
        return param_repr

    def optional_named__init__param(self, name, value, default=None):
        param_repr = None
        if value != default:
            value_str = utils.quoteme_raw_if_string(value)
            param_repr = f"{name}={value_str}"
        return param_repr

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        params = []
        params.append(self.unnamed__init__param(os.fspath(self.src)))
        params.append(self.unnamed__init__param(os.fspath(self.dst)))
        params.append(self.optional_named__init__param("symlinks_as_symlinks", self.symlinks_as_symlinks, True))
        params.append(self.optional_named__init__param("patterns_to_ignore", self.patterns_to_ignore, []))
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
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        self.copy_tree(self.src, self.dst)

    def print_if_level(self, message_level, *messages):
        if message_level <= self.verbose:
            log.info(' '.join(messages))

    def get_ignored_files(self, root, names_in_root):
        ignored_names = []
        if self.patterns_to_ignore:
            if self._get_ignored_files_func is None:
                self._get_ignored_files_func = shutil.ignore_patterns(*self.patterns_to_ignore)
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
                self.print_if_level(1, f"delete {dst_path}")
                if os.path.islink(dst_path) or os.path.isfile(dst_path):
                    self.dry_run or os.unlink(dst_path)
                else:
                    self.dry_run or shutil.rmtree(dst_path)

    def copy_symlink(self, src_path, dst_path):
        link_to = os.readlink(src_path)
        if self.symlinks_as_symlinks:
            self.dry_run or os.symlink(link_to, dst_path)
            self.dry_run or shutil.copystat(src_path, dst_path, follow_symlinks=False)
            self.print_if_level(1, f"create symlink '{dst_path}'")
        else:
            # ignore dangling symlink if the flag is on
            if not os.path.exists(link_to) and self.ignore_dangling_symlinks:
                return
            # otherwise let the copy occur. copy_file_to_file will raise an error
            self.print_if_level(2, f"copy symlink contents '{src_path}' to '{dst_path}'")
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
                self.print_if_level(2, f"same inode, skip copy file '{src}' to '{dst}'")
            elif src_stats.st_size == dst_stats.st_size and src_stats.st_mtime == dst_stats.st_mtime:
                retVal = False
                self.print_if_level(2, f"same time and size, skip copy file '{src}' to '{dst}'")
        if retVal:
            self.print_if_level(3, f"no skip copy file '{src}' to '{dst}'")
        else:
            self.print_if_level(1, f"skip copy file '{src}' to '{dst}'")
        return retVal

    def copy_file_to_file(self, src, dst, follow_symlinks=True):
        """ copy the file src to the file dst. dst should either be an existing file
            or not exists at all - i.e. dst cannot be a folder. The parent folder of dst
            is assumed to exist
        """
        if self.should_copy_file(src, dst):
            if not self.hard_links or os.path.islink(src):
                self.print_if_level(1, f"copy file '{src}' to '{dst}'")
                self.dry_run or shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
            else:  # try to create hard link
                try:
                    self.dry_run or os.link(src, dst)
                    self.print_if_level(1, f"hard link file '{src}' to '{dst}'")
                    self.statistics['hard_links'] += 1
                except OSError as ose:
                    self.dry_run or shutil.copy2(src, dst, follow_symlinks=True)
                    self.print_if_level(1, f"copy file '{src}' to '{dst}'")
        else:
            self.statistics['skipped_files'] += 1
        return dst

    def copy_file_to_dir(self, src, dst, follow_symlinks=True):
        os.makedirs(dst, exist_ok=True)
        dst = os.path.join(dst, os.path.basename(src))
        retVal = self.copy_file_to_file(src, dst, follow_symlinks)
        return retVal

    def copy_tree(self, src, dst):
        """ based on shutil.copytree
        """
        self.statistics['dirs'] += 1
        self.print_if_level(2, f"copy folder '{src}' to '{dst}'")
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
                self.print_if_level(1, f"ignoring '{src_path}'")
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

    def exit_self(self, exit_return):
        log.info("\n".join([os.fspath(self.src), os.fspath(self.dst)]+[f"{stat}={num}" for stat, num in sorted(self.statistics.items())]))


class CopyDirToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        dst = os.path.join(self.dst, os.path.basename(self.src))
        self.copy_tree(self.src, dst)


class CopyDirContentsToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)


class CopyFileToDir(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs):
        self.copy_file_to_dir(self.src, self.dst)


class CopyFileToFile(RsyncClone):
    def __init__(self, src, dst, **kwargs):
        super().__init__(src, dst, **kwargs)

    def __call__(self, *args, **kwargs) -> None:
        os.makedirs(os.path.dirname(self.dst), exist_ok=True)
        self.copy_file_to_file(self.src, self.dst)
