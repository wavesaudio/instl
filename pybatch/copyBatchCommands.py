import os

import utils
from .baseClasses import *


class CopyBase(RunProcessBase, essential=True):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore_patterns=None, preserve_dest_files=False,         ignore_if_not_exist = False, copy_file=False, copy_dir=False) -> None:
        super().__init__()
        self.src: os.PathLike = src
        self.trg: os.PathLike = trg
        self.link_dest = link_dest
        self.ignore_patterns = ignore_patterns
        self.preserve_dest_files = preserve_dest_files
        self.ignore_if_not_exist = ignore_if_not_exist
        self.copy_file = copy_file
        self.copy_dir = copy_dir

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(src={utils.quoteme_raw_string(os.fspath(self.src))}, trg={utils.quoteme_raw_string(os.fspath(self.trg))}, link_dest={self.link_dest}, ignore_patterns={self.ignore_patterns}, preserve_dest_files={self.preserve_dest_files})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f"{self}"
        return the_progress_msg

    @abc.abstractmethod
    def create_run_args(self):
        raise NotImplemented()

    @abc.abstractmethod
    def create_ignore_spec(self, ignore_patterns: bool):
        raise NotImplemented()


class RsyncCopyBase(CopyBase):
    def __init__(self, src: os.PathLike, trg: os.PathLike, *args, **kwargs) -> None:
        # not correct in case of a file
        #if not os.fspath(trg).endswith("/"):
        #    trg = os.fspath(trg) + "/"
        super().__init__(src, trg, *args, **kwargs)

    def create_run_args(self):
        run_args = list()
        ignore_spec = self.create_ignore_spec(self.ignore_patterns)
        if not self.preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""

        run_args.extend(["rsync", "--owner", "--group", "-l", "-r", "-E", "--hard-links", delete_spec, *ignore_spec])
        if self.link_dest:
            src_base, src_leaf = os.path.split(self.src)
            target_relative_to_source = os.path.relpath(src_base, self.trg)  # rsync expect --link-dest to be relative to target
            the_link_dest_arg = f'''--link-dest="{target_relative_to_source}"'''
            run_args.append(the_link_dest_arg)
        run_args.extend([self.src, self.trg])
        if self.ignore_if_not_exist:
            run_args.extend(["||", "true"])
        return run_args

    def create_ignore_spec(self, ignore_patterns: bool) -> None:
        retVal = []
        if self.ignore_patterns:
            if isinstance(self.ignore_patterns, str):
                self.ignore_patterns = (self.ignore_patterns,)
            retVal.extend(["--exclude=" + utils.quoteme_single(ignoree) for ignoree in self.ignore_patterns])
        return retVal


class RoboCopyBase(CopyBase):
    RETURN_CODES = {0:  '''
                            No errors occurred, and no copying was done.
                            The source and destination directory trees are completely synchronized.''',
                    1: '''One or more files were copied successfully (that is, new files have arrived).''',
                    2: '''
                            Some Extra files or directories were detected. No files were copied
                            Examine the output log for details.''',
                    # (2 + 1)
                    3: '''Some files were copied.Additional files were present.No failure was encountered.''',
                    4: '''
                            Some Mismatched files or directories were detected.
                            Examine the output log. Housekeeping might be required.''',
                    # (4 + 1)
                    5: '''Some files were copied. Some files were mismatched. No failure was encountered.''',
                    # (4 + 2)
                    6: '''
                            Additional files and mismatched files exist. No files were copied and no failures were encountered.
                            This means that the files already exist in the destination directory''',
                    # (4 + 1 + 2)
                    7: '''Files were copied, a file mismatch was present, and additional files were present.''',

                    # Any value greater than 7 indicates that there was at least one failure during the copy operation.
                    8: '''
                            Some files or directories could not be copied
                            (copy errors occurred and the retry limit was exceeded).
                            Check these errors further.''',
                    16: '''
                            Serious error. Robocopy did not copy any files.
                            Either a usage error or an error due to insufficient access privileges
                            on the source or destination directories.'''}

    def __call__(self, *args, **kwargs):
        try:
            super().__call__(*args, **kwargs)
        except subprocess.CalledProcessError as e:
            if e.returncode > 7 and not self.ignore_if_not_exist:
                raise e
            #     pass  # One or more files were copied successfully (that is, new files have arrived).
            # else:
            #     raise subprocess.SubprocessError(f'{self.RETURN_CODES[e.returncode]}') from e

    def create_run_args(self):
        run_args = ['robocopy', '/E', '/R:9', '/W:1', '/NS', '/NC', '/NFL', '/NDL', '/NP', '/NJS', '/256']
        if not self.preserve_dest_files:
            run_args.append('/purge')
        if self.copy_file:
            run_args.extend((os.path.dirname(self.src), self.trg, os.path.basename(self.src)))
        elif self.copy_dir:
            run_args.extend((self.src, os.path.join(self.trg, os.path.basename(self.src))))
        else:
            run_args.extend((self.src, self.trg))
        run_args.extend(self.create_ignore_spec(self.ignore_patterns))
        return run_args

    def create_ignore_spec(self, ignore_patterns: bool):
        try:
            ignore_patterns = [os.path.abspath(os.path.join(self.src, path)) for path in ignore_patterns]
        except TypeError:
            retVal = []
        else:
            retVal = ['/XF'] + ignore_patterns + ['/XD'] + ignore_patterns
        return retVal


if sys.platform == 'darwin':
    CopyClass = RsyncCopyBase
elif sys.platform == 'win32':
    CopyClass = RoboCopyBase


class CopyDirToDir(CopyClass):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore_patterns=None, preserve_dest_files=False) -> None:
        src = os.fspath(src).rstrip("/")
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore_patterns=ignore_patterns, preserve_dest_files=preserve_dest_files, copy_dir=True)

    def repr_batch_win(self):
        retVal = list()
        _, dir_to_copy = os.path.split(self.src)
        self.trg = "/".join((self.trg, dir_to_copy))
        ignore_spec = self._create_ignore_spec_batch_win(self.ignore_patterns)
        norm_src_dir = os.path.normpath(self.src)
        norm_trg_dir = os.path.normpath(self.trg)
        if not self.preserve_dest_files:
            delete_spec = "/PURGE"
        else:
            delete_spec = ""
        copy_command = f""""$(ROBOCOPY_PATH)" "{norm_src_dir}" "{norm_trg_dir}" {ignore_spec} /E /R:9 /W:1 /NS /NC /NFL /NDL /NP /NJS {delete_spec}"""
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def repr_batch_mac(self):
        if self.src.endswith("/"):
            self.src.rstrip("/")
        ignore_spec = self.create_ignore_spec(self.ignore_patterns)
        if not self.preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""
        if self.link_dest:
            the_link_dest = os.path.join(self.src, "..")
            sync_command = f"""rsync --owner --group -l -r -E {delete_spec} {ignore_spec} --link-dest="{the_link_dest}" "{self.src}" "{self.trg}" """
        else:
            sync_command = f"""rsync --owner --group -l -r -E {delete_spec} {ignore_spec} "{self.src}" "{self.trg}" """

        return sync_command


class CopyDirContentsToDir(CopyClass):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore_patterns=None, preserve_dest_files=False) -> None:
        if not os.fspath(src).endswith("/"):
            src = os.fspath(src)+"/"
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore_patterns=ignore_patterns, preserve_dest_files=preserve_dest_files)

    def repr_batch_win(self):
        retVal = list()
        ignore_spec = self.create_ignore_spec(self.ignore_patterns)
        delete_spec = ""
        if not self.preserve_dest_files:
            delete_spec = "/PURGE"
        else:
            delete_spec = ""
        norm_src_dir = os.path.normpath(self.src)
        norm_trg_dir = os.path.normpath(self.trg)
        copy_command = f""""$(ROBOCOPY_PATH)" "{norm_src_dir}" "{norm_trg_dir}" /E {delete_spec} {ignore_spec} /R:9 /W:1 /NS /NC /NFL /NDL /NP /NJS"""
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def repr_batch_mac(self):
        if not self.src.endswith("/"):
            self.src += "/"
        ignore_spec = self.create_ignore_spec(self.ignore_patterns)
        delete_spec = ""
        if not self.preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""
        if self.link_dest:
            relative_link_dest = os.path.relpath(self.src, self.trg)
            sync_command = f"""rsync --owner --group -l -r -E {delete_spec} {ignore_spec} --link-dest="{relative_link_dest}" "{self.src}" "{self.trg}" """
        else:
            sync_command = f"""rsync --owner --group -l -r -E {delete_spec} {ignore_spec} "{self.src}" "{self.trg}" """

        return sync_command


class CopyFileToDir(CopyClass):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore_patterns=None, ignore_if_not_exist=False) -> None:
        src = os.fspath(src).rstrip("/")
        if not os.fspath(trg).endswith("/"):
            trg = os.fspath(trg)+"/"
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore_patterns=ignore_patterns, ignore_if_not_exist=ignore_if_not_exist, copy_file=True)

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(src={utils.quoteme_raw_string(self.src)}, trg={utils.quoteme_raw_string(self.trg)}, link_dest={self.link_dest}, ignore_patterns={self.ignore_patterns})"""
        return the_repr

    def repr_batch_win(self):
        retVal = list()
        norm_src_dir, norm_src_file = os.path.split(os.path.normpath(self.src))
        norm_trg_dir = os.path.normpath(self.trg)
        copy_command = f""""$(ROBOCOPY_PATH)" "{norm_src_dir}" "{norm_trg_dir}" "{norm_src_file}" /R:9 /W:1 /NS /NC /NFL /NDL /NP /NJS"""
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error(self.robocopy_error_threshold))
        return retVal

    def repr_batch_mac(self):
        assert not self.src.endswith("/")
        if not self.trg.endswith("/"):
            self.trg += "/"
        ignore_spec = self.create_ignore_spec(self.ignore_patterns)
        permissions_spec = str(config_vars.get("RSYNC_PERM_OPTIONS", ""))
        if self.link_dest:
            the_link_dest, src_file_name = os.path.split(self.src)
            relative_link_dest = os.path.relpath(the_link_dest, self.trg)
            sync_command = f"""rsync --owner --group -l -r -E {ignore_spec} --link-dest="{relative_link_dest}" "{self.src}" "{self.trg}" """
        else:
            sync_command = f"""rsync --owner --group -l -r -E {ignore_spec} "{self.src}" "{self.trg}" """

        return sync_command


class CopyFileToFile(CopyClass):
    def __init__(self, src: os.PathLike, trg: os.PathLike, link_dest=False, ignore_patterns=None, preserve_dest_files=False, **kwargs) -> None:
        src = os.fspath(src).rstrip("/")
        trg = os.fspath(trg).rstrip("/")
        super().__init__(src=src, trg=trg, link_dest=link_dest, ignore_patterns=ignore_patterns, preserve_dest_files=preserve_dest_files, copy_file=True, **kwargs)

    def repr_batch_win(self):
        retVal = list()
        norm_src_file = os.path.normpath(self.src)
        norm_trg_file = os.path.normpath(self.trg)
        copy_command = f"""copy "{norm_src_file}" "{norm_trg_file}" """
        retVal.append(copy_command)
        retVal.append(self.platform_helper.exit_if_error())
        return retVal

    def repr_batch_mac(self):
        assert not self.src.endswith("/")
        ignore_spec = self.create_ignore_spec(self.ignore_patterns)
        if self.link_dest:
            src_folder_name, src_file_name = os.path.split(self.src)
            trg_folder_name, trg_file_name = os.path.split(self.trg)
            relative_link_dest = os.path.relpath(src_folder_name, trg_folder_name)
            sync_command = f"""rsync --owner --group -l -r -E {ignore_spec} --link-dest="{relative_link_dest}" "{self.src}" "{self.trg}" """
        else:
            sync_command = f"""rsync --owner --group -l -r -E {ignore_spec} "{self.src}" "{self.trg}" """

        return sync_command
