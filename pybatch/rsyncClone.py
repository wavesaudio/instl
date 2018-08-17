import os
import shutil

class RsyncClone(object):
    def __init__(self,
                 symlinks_as_symlinks=True,
                 patterns_to_ignore=None,
                 hard_links=True,
                 ignore_dangling_symlinks=False,
                 delete_extraneous_files=False,
                 verbose=0,
                 dry_run=False):
        self.symlinks_as_symlinks = symlinks_as_symlinks
        self.patterns_to_ignore = patterns_to_ignore
        self.get_ignored_files = shutil.ignore_patterns(*self.patterns_to_ignore)
        self.hard_links = hard_links
        self.ignore_dangling_symlinks = ignore_dangling_symlinks
        self.delete_extraneous_files = delete_extraneous_files
        self.verbose = verbose
        self.dry_run = dry_run

    def print_if_level(self, message_level, *messages):
        if message_level <= self.verbose:
            print(*messages)

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
            # otherwise let the copy occurs. copy_file will raise an error
            self.print_if_level(2, f"copy symlink contents '{src_path}' to '{dst_path}'")
            if os.path.isdir(src_path):
                self.copytree(src_path, dst_path)
            else:
                self.copy_file(src_path, dst_path)

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

    def copy_file(self, src, dst, follow_symlinks=True):
        if self.should_copy_file(src, dst):
            if not self.hard_links or os.path.islink(src):
                self.print_if_level(1, f"copy file '{src}' to '{dst}'")
                self.dry_run or shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
            else:  # try to create hard link
                try:
                    self.dry_run or os.link(src, dst)
                    self.print_if_level(1, f"hard link file '{src}' to '{dst}'")
                except OSError as ose:
                    self.dry_run or shutil.copy2(src, dst, follow_symlinks=True)
                    self.print_if_level(1, f"copy file '{src}' to '{dst}'")
        return dst

    def copytree(self, src, dst):
        """ based on shutil.copytree
        """

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
                self.print_if_level(1, f"ignoring '{src_path}'")
                continue
            dst_path = os.path.join(dst, src_name)
            try:
                if os.path.islink(src_path):
                    self.copy_symlink(src_path, dst_path)
                elif os.path.isdir(src_path):
                    self.copytree(src_path, dst_path)
                else:
                    # Will raise a SpecialFileError for unsupported file types
                    self.copy_file(src_path, dst_path)
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
