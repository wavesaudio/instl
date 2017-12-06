#!/usr/bin/env python3


import os
import abc
import itertools
import pathlib

import utils
from configVar import var_stack
from . import connectionBase


class CopyToolBase(object, metaclass=abc.ABCMeta):
    """ Create copy commands. Each function should be overridden to implement the copying
        on specific platform using a specific copying tool. All functions return
        a list of commands, even if there is only one. This will allow to return
        multiple commands if needed.
    """

    def __init__(self, platform_helper):
        self.platform_helper = platform_helper

    @abc.abstractmethod
    def finalize(self):
        pass

    @abc.abstractmethod
    def begin_copy_folder(self):
        pass

    @abc.abstractmethod
    def end_copy_folder(self):
        pass

    @abc.abstractmethod
    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=False):
        """ Copy src_dir as a folder into trg_dir.
            Example: copy_dir_to_dir("a", "/d/c/b") creates the folder:
            "/d/c/b/a"
        """
        pass

    @abc.abstractmethod
    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
        """ Copy the file src_file into trg_dir.
            Example: copy_file_to_dir("a.txt", "/d/c/b") creates the file:
            "/d/c/b/a.txt"
        """
        pass

    @abc.abstractmethod
    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=True):
        """ Copy the contents of src_dir into trg_dir.
            Example: copy_dir_contents_to_dir("a", "/d/c/b") copies
            everything from a into "/d/c/b"
        """
        pass

    @abc.abstractmethod
    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None):
        """ Copy the files of src_dir into trg_dir.
            Example: copy_dir_contents_to_dir("a", "/d/c/b") copies
            all files from a into "/d/c/b", subfolders of a are not copied
        """
        pass

    @abc.abstractmethod
    def copy_file_to_file(self, src_file, trg_file, link_dest=False, ignore=None):
        """ Copy file src_file into trg_file.
            Example: copy_file_to_file("a", "/d/c/b") copies
            the file a to the file "/d/c/b".
        """
        pass

    @abc.abstractmethod
    def remove_file(self, file_to_remove):
        pass

    @abc.abstractmethod
    def remove_dir(self, dir_to_remove):
        pass


class CopyToolRsync(CopyToolBase):
    def __init__(self, platform_helper):
        super().__init__(platform_helper)

    def finalize(self):
        pass

    def begin_copy_folder(self):
        return ()

    def end_copy_folder(self):
        return ()

    def create_ignore_spec(self, ignore):
        retVal = ""
        if ignore:
            if isinstance(ignore, str):
                ignore = (ignore,)
            retVal = " ".join(["--exclude=" + utils.quoteme_single(ignoree) for ignoree in ignore])
        return retVal

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=False):
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        ignore_spec = self.create_ignore_spec(ignore)
        if not preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""
        if link_dest:
            the_link_dest = os.path.join(src_dir, "..")
            sync_command = """rsync --owner --group -l -r -E {delete_spec} {ignore_spec} --link-dest="{the_link_dest}" "{src_dir}" "{trg_dir}" """.format(**locals())
        else:
            sync_command = """rsync --owner --group -l -r -E {delete_spec} {ignore_spec} "{src_dir}" "{trg_dir}" """.format(**locals())

        return sync_command

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=False, ignore=None):
        assert not src_file.endswith("/")
        ignore_spec = self.create_ignore_spec(ignore)
        permissions_spec = var_stack.ResolveVarToStr("RSYNC_PERM_OPTIONS", default="")
        if link_dest:
            the_link_dest, src_file_name = os.path.split(src_file)
            relative_link_dest = os.path.relpath(the_link_dest, trg_dir)
            sync_command = """rsync --owner --group -l -r -E {ignore_spec} --link-dest="{relative_link_dest}" "{src_file}" "{trg_dir}" """.format(**locals())
        else:
            sync_command = """rsync --owner --group -l -r -E {ignore_spec} "{src_file}" "{trg_dir}" """.format(**locals())

        return sync_command

    def copy_file_to_file(self, src_file, trg_file, link_dest=False, ignore=None):
        assert not src_file.endswith("/")
        ignore_spec = self.create_ignore_spec(ignore)
        if link_dest:
            src_folder_name, src_file_name = os.path.split(src_file)
            trg_folder_name, trg_file_name = os.path.split(trg_file)
            relative_link_dest = os.path.relpath(src_folder_name, trg_folder_name)
            sync_command = """rsync --owner --group -l -r -E {ignore_spec} --link-dest="{relative_link_dest}" "{src_file}" "{trg_file}" """.format(**locals())
        else:
            sync_command = """rsync --owner --group -l -r -E {ignore_spec} "{src_file}" "{trg_file}" """.format(**locals())

        return sync_command

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None, preserve_dest_files=True):
        if not src_dir.endswith("/"):
            src_dir += "/"
        ignore_spec = self.create_ignore_spec(ignore)
        delete_spec = ""
        if not preserve_dest_files:
            delete_spec = "--delete"
        else:
            delete_spec = ""
        if link_dest:
            relative_link_dest = os.path.relpath(src_dir, trg_dir)
            sync_command = """rsync --owner --group -l -r -E {delete_spec} {ignore_spec} --link-dest="{relative_link_dest}" "{src_dir}" "{trg_dir}" """.format(**locals())
        else:
            sync_command = """rsync --owner --group -l -r -E {delete_spec} {ignore_spec} "{src_dir}" "{trg_dir}" """.format(**locals())

        return sync_command

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=False, ignore=None):
        if not src_dir.endswith("/"):
            src_dir += "/"
        # in order for * to correctly expand, it must be outside the quotes, e.g. to copy all files in folder a: A=a ; "${A}"/* and not "${A}/*"
        ignore_spec = self.create_ignore_spec(ignore)
        if link_dest:
            relative_link_dest = os.path.relpath(src_dir, trg_dir)
            sync_command = """rsync --owner --group -l -E -d --exclude='*/' {ignore_spec} --link-dest="{relative_link_dest}" "{src_dir}" "{trg_dir}" """.format(**locals())
        else:
            sync_command = """rsync --owner --group -l -E -d --exclude='*/' {ignore_spec} "{src_dir}"/* "{trg_dir}" """.format(**locals())

        return sync_command

    def remove_file(self, file_to_remove):
        remove_command = """rm -f -v "{file_to_remove}" """.format(**locals())
        return remove_command

    def remove_dir(self, dir_to_remove):
        remove_command = """rm -f -v -r "{dir_to_remove}" """.format(**locals())
        return remove_command


class PlatformSpecificHelperBase(object):
    def __init__(self, instlObj):
        self.instlObj = instlObj
        self.copy_tool = None
        self.dl_tool = None
        self.num_items_for_progress_report = 0
        self.progress_staccato_period = int(var_stack.ResolveVarToStr("PROGRESS_STACCATO_PERIOD", default="128"))
        self.progress_staccato_count = 0
        self.no_progress_messages = False

    def DefaultCopyToolName(self, target_os):
        if target_os == "Win":
            retVal = "robocopy"
        elif target_os == "Mac":
            retVal = "rsync"
        elif target_os == 'Linux':
            retVal = "rsync"
        else:
            raise ValueError(target_os, "has no valid default copy tool")
        return retVal

    @abc.abstractmethod
    def init_platform_tools(self):
        """ platform specific initialization of the download tool object.
            Can be done only after the definitions for index have been read."""
        pass

    def init_copy_tool(self):
        copy_tool_name = self.DefaultCopyToolName(var_stack.ResolveVarToStr("__CURRENT_OS__")) # copy instructions are always produced for the current os
        if "COPY_TOOL" in var_stack:
            copy_tool_name = var_stack.ResolveVarToStr("COPY_TOOL")
        self.use_copy_tool(copy_tool_name)

    @abc.abstractmethod
    def get_install_instructions_prefix(self):
        """ platform specific """
        pass

    @abc.abstractmethod
    def get_install_instructions_postfix(self):
        """ platform specific last lines of the install script """
        pass

    @abc.abstractmethod
    def mkdir(self, directory):
        """ platform specific mkdir """
        pass

    def mkdir_with_owner(self, directory):
        return self.mkdir(directory)

    @abc.abstractmethod
    def cd(self, directory):
        """ platform specific cd """
        pass

    @abc.abstractmethod
    def pushd(self, directory):
        pass

    @abc.abstractmethod
    def popd(self):
        pass

    @abc.abstractmethod
    def save_dir(self, var_name):
        """ platform specific save current dir """
        pass

    @abc.abstractmethod
    def restore_dir(self, var_name):
        """ platform specific restore current dir """
        pass

    @abc.abstractmethod
    def rmdir(self, directory, recursive=False, check_exist=False):
        """ platform specific rmdir """
        pass

    @abc.abstractmethod
    def rmfile(self, a_file, check_exist=False):
        """ platform specific rm file """
        pass

    @abc.abstractmethod
    def rm_file_or_dir(self, file_or_dir):
        """ platform specific rm file or a dir """
        pass

    def new_line(self):
        return ""  # empty string because write_batch_file adds \n to each line

    def progress(self, msg, num_items=0):
        self.num_items_for_progress_report += num_items + 1
        if not self.no_progress_messages:
            prog_msg = "Progress: {} of $(TOTAL_ITEMS_FOR_PROGRESS_REPORT); {}".format(self.num_items_for_progress_report, msg)
            return self.echo(prog_msg)
        else:
            return ()

    def progress_percent(self, msg, percent):
        """ create progress message and increase progress items by a percentage
        """
        inc_by = max(1, int(self.num_items_for_progress_report / 100) * int(percent))
        self.num_items_for_progress_report += inc_by
        if not self.no_progress_messages:
            prog_msg = "Progress: {} of $(TOTAL_ITEMS_FOR_PROGRESS_REPORT); {}".format(self.num_items_for_progress_report, msg)
            return self.echo(prog_msg)
        else:
            return ()

    def progress_staccato(self, msg):
        retVal = ()
        self.progress_staccato_count = (self.progress_staccato_count + 1) % self.progress_staccato_period
        if self.progress_staccato_count == 0:
            retVal = self.progress(msg)
        return retVal

    def increment_progress(self, num_items=1):
        self.num_items_for_progress_report += num_items
        return self.num_items_for_progress_report

    @abc.abstractmethod
    def get_svn_folder_cleanup_instructions(self):
        """ platform specific cleanup of svn locks """
        pass

    @abc.abstractmethod
    def var_assign(self, identifier, value):
        pass

    def setup_echo(self):
        return ()

    @abc.abstractmethod
    def echo(self, message):
        pass

    @abc.abstractmethod
    def remark(self, remark):
        pass

    @abc.abstractmethod
    def use_copy_tool(self, tool):
        pass

    @abc.abstractmethod
    def copy_file_to_file(self, src_file, trg_file):
        """ Copy src_file to trg_file.
            Example: create_copy_file_to_file("a.txt", "/d/c/bt.txt") copies
            the file a.txt into "/d/c/bt.txt".
        """
        pass

    def svn_add_item(self, item_path):
        svn_command = " ".join(("$(SVN_CLIENT_PATH)", "add", '"' + item_path + '"'))
        return svn_command

    def svn_remove_item(self, item_path):
        svn_command = " ".join(("$(SVN_CLIENT_PATH)", "rm", "--force", '"' + item_path + '"'))
        return svn_command

    @abc.abstractmethod
    def check_checksum_for_file(self, a_file, checksum):
        pass

    def check_checksum_for_folder(self, info_map_file):
        check_checksum_for_folder_command = " ".join((self.run_instl(),
                                                      "check-checksum",
                                                      "--in", utils.quoteme_double(info_map_file),
                                                      "--start-progress", str(self.num_items_for_progress_report),
                                                      "--total-progress", "$(TOTAL_ITEMS_FOR_PROGRESS_REPORT)",
        ))
        return check_checksum_for_folder_command

    def create_folders(self, info_map_file):
        create_folders_command = " ".join((self.run_instl(),
                                           "create-folders",
                                           "--in", utils.quoteme_double(info_map_file),
                                           "--start-progress", str(self.num_items_for_progress_report),
                                           "--total-progress", "$(TOTAL_ITEMS_FOR_PROGRESS_REPORT)",
        ))
        return create_folders_command

    def set_exec_for_folder(self, info_map_file):
        set_exec_for_folder_command = " ".join((self.run_instl(),
                                                "set-exec",
                                                "--in", utils.quoteme_double(info_map_file),
                                                "--start-progress", str(self.num_items_for_progress_report),
                                                "--total-progress", "$(TOTAL_ITEMS_FOR_PROGRESS_REPORT)",
        ))
        return set_exec_for_folder_command

    @abc.abstractmethod
    def ls(self, format='*', folder='.'):
        pass

    def tar(self, to_tar_name):
        pass

    def unwtar_something(self, what_to_unwtar, no_artifacts=False, where_to_unwtar=None):
        unwtar_command_parts = [self.instlObj.platform_helper.run_instl(),
                                "unwtar",
                                "--in",
                                utils.quoteme_double(what_to_unwtar)]
        if no_artifacts:
            unwtar_command_parts.append("--no-artifacts")

        if where_to_unwtar:
            unwtar_command_parts.extend(["--out", utils.quoteme_double(where_to_unwtar)])

        unwtar_command = " ".join(unwtar_command_parts)
        return unwtar_command

    def unwtar_current_folder(self, no_artifacts=False, where_to_unwtar=None):
        unwtar_command = self.unwtar_something(".", no_artifacts, where_to_unwtar)
        return unwtar_command

    def run_instl_command_list(self, command_file_path, parallel=False):
        command_parts = [self.instlObj.platform_helper.run_instl(),
                         "command-list",
                         "--config-file",
                         utils.quoteme_double(command_file_path)]
        if parallel:
            command_parts.append("--parallel")
        instl_batch_command = " ".join(command_parts)
        return instl_batch_command

    @abc.abstractmethod
    def wait_for_child_processes(self):
        pass

    @abc.abstractmethod
    def chmod(self, new_mode, file_path):
        pass

    @abc.abstractmethod
    def make_executable(self, file_path):
        pass

    @abc.abstractmethod
    def unlock(self, file_path, recursive=False, ignore_errors=True):
        """ Remove the system's read-only flag, this is different from permissions.
            For changing permissions use chmod.
        """
        pass

    @abc.abstractmethod
    def touch(self, file_path):
        pass

    def run_instl(self):
        return '"$(__INSTL_EXE_PATH__)"'

    @abc.abstractmethod
    def append_file_to_file(self, source_file, target_file):
        pass

    # overridden only on windows, unix shell scripts have set -e to auto exit if any subprocess returns exit code != 0
    def exit_if_any_error(self):
        return ()

    @abc.abstractmethod
    def chown(self, user_id, group_id, target_path, recursive=False):
        pass

def PlatformSpecificHelperFactory(in_os, instlObj):
    if in_os == "Mac":
        from . import platformSpecificHelper_Mac

        retVal = platformSpecificHelper_Mac.PlatformSpecificHelperMac(instlObj)
    elif in_os == "Win":
        from . import platformSpecificHelper_Win

        retVal = platformSpecificHelper_Win.PlatformSpecificHelperWin(instlObj)
    elif in_os == "Linux":
        from . import platformSpecificHelper_Linux

        retVal = platformSpecificHelper_Linux.PlatformSpecificHelperLinux(instlObj)
    else:
        raise ValueError(in_os, "has no PlatformSpecificHelper")
    return retVal


class DownloadToolBase(object, metaclass=abc.ABCMeta):
    """ Create download commands. Each function should be overridden to implement the download
        on specific platform using a specific copying tool. All functions return
        a list of commands, even if there is only one. This will allow to return
        multiple commands if needed.
    """
    curl_write_out_str = r'%{url_effective}, %{size_download} bytes, %{time_total} sec., %{speed_download} bps.\n'
    # for debugging:
    curl_extra_write_out_str = r'    num_connects:%{num_connects}, time_namelookup: %{time_namelookup}, time_connect: %{time_connect}, time_pretransfer: %{time_pretransfer}, time_redirect: %{time_redirect}, time_starttransfer: %{time_starttransfer}\n\n'

    def __init__(self, platform_helper):
        self.platform_helper = platform_helper
        self.urls_to_download = list()

    @abc.abstractmethod
    def download_url_to_file(self, src_url, trg_file):
        pass

    def add_download_url(self, url, path, verbatim=False, size=0):
        if verbatim:
            translated_url = url
        else:
            translated_url = connectionBase.connection_factory().translate_url(url)
        self.urls_to_download.append((translated_url, path, size))

    def get_num_urls_to_download(self):
        return len(self.urls_to_download)

    def download_from_config_file(self, config_file):
        pass

    @abc.abstractmethod
    def download_from_config_files(self, parallel_run_config_file_path, config_files):
        pass

    def create_config_files(self, curl_config_file_path, num_config_files):
        file_name_list = list()
        num_urls_to_download = len(self.urls_to_download)
        if num_urls_to_download > 0:
            connect_time_out = var_stack.ResolveVarToStr("CURL_CONNECT_TIMEOUT", "16")
            max_time = var_stack.ResolveVarToStr("CURL_MAX_TIME", "180")
            retries = var_stack.ResolveVarToStr("CURL_RETRIES", "2")
            retry_delay = var_stack.ResolveVarToStr("CURL_RETRY_DELAY", "8")

            sync_urls_cookie = var_stack.ResolveVarToStr("COOKIE_FOR_SYNC_URLS", default=None)

            actual_num_config_files = int(max(0, min(num_urls_to_download, num_config_files)))
            num_digits = len(str(actual_num_config_files))
            file_name_list = ["-".join((curl_config_file_path, str(file_i).zfill(num_digits))) for file_i in range(actual_num_config_files)]

            # open the files make sure they have r/w permissions and are utf-8
            wfd_list = list()
            for file_name in file_name_list:
                wfd = utils.utf8_open(file_name, "w")
                utils.make_open_file_read_write_for_all(wfd)
                wfd_list.append(wfd)

            # write the header in each file
            for wfd in wfd_list:
                basename = os.path.basename(wfd.name)
                if sync_urls_cookie:
                    cookie_text = "cookie = {sync_urls_cookie}\n".format(**locals())
                else:
                    cookie_text = ""
                curl_write_out_str = DownloadToolBase.curl_write_out_str
                file_header_text = """
insecure
raw
fail
silent
show-error
compressed
create-dirs
connect-timeout = {connect_time_out}
max-time = {max_time}
retry = {retries}
retry-delay = {retry_delay}
{cookie_text}
write-out = "Progress: ... of ...; {basename}: {curl_write_out_str}


""".format(**locals())
                wfd.write(file_header_text)

            wfd_cycler = itertools.cycle(wfd_list)
            url_num = 0
            sorted_by_size = sorted(self.urls_to_download, key=lambda dl_item: dl_item[2])
            for url, path, size in sorted_by_size:
                fixed_path = str(pathlib.PurePath(path)).replace("\\", "\\\\")  # for windows
                wfd = next(wfd_cycler)
                wfd.write('''url = "{url}"\noutput = "{fixed_path}"\n\n'''.format(**locals()))
                url_num += 1

            for wfd in wfd_list:
                wfd.close()

        return file_name_list
