#!/usr/bin/env python2.7
from __future__ import print_function
import os
import abc

def quoteme_single(to_qoute):
    return "".join( ("'", to_qoute, "'") )
def quoteme_double(to_qoute):
    return "".join( ('"', to_qoute, '"') )

def DefaultCopyToolName(target_os):
    retVal = None
    if target_os == "Win":
        retVal = "robocopy"
    elif target_os == "Mac":
        retVal = "rsync"
    elif target_os == 'Linux':
        retVal = "rsync"
    else:
        raise ValueError(target_os, "has no valid default copy tool")
    return retVal

class CopyToolBase(object):
    """ Create copy commands. Each function should be overridden to implement the copying
        on specific platform using a specific copying tool. All functions return
        a list of commands, even if there is only one. This will allow to return
        multiple commands if needed.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, platformHelper):
        self.platformHelper = platformHelper

    @abc.abstractmethod
    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        """ Copy src_dir as a folder into trg_dir.
            Example: copy_dir_to_dir("a", "/d/c/b") creates the folder:
            "/d/c/b/a"
        """
        pass

    @abc.abstractmethod
    def copy_file_to_dir(self, src_file, trg_dir, link_dest=None, ignore=None):
        """ Copy the file src_file into trg_dir.
            Example: copy_file_to_dir("a.txt", "/d/c/b") creates the file:
            "/d/c/b/a.txt"
        """
        pass

    @abc.abstractmethod
    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        """ Copy the contents of src_dir into trg_dir.
            Example: copy_dir_contents_to_dir("a", "/d/c/b") copies
            everything from a into "/d/c/b"
        """
        pass

    @abc.abstractmethod
    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        """ Copy the files of src_dir into trg_dir.
            Example: copy_dir_contents_to_dir("a", "/d/c/b") copies
            all files from a into "/d/c/b", subfolders of a are not copied
        """
        pass


class CopyToolRsync(CopyToolBase):
    def __init__(self, platformHelper):
        super(CopyToolRsync, self).__init__(platformHelper)

    def create_ignore_spec(self, ignore):
        retVal = ""
        if ignore:
            if isinstance(ignore, basestring):
                ignore = (ignore,)
            retVal = " ".join(["--exclude="+quoteme_single(ignoree) for ignoree in ignore])
        return retVal

    def copy_dir_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        ignore_spec = self.create_ignore_spec(ignore)
        if link_dest is None:
            sync_command = "rsync -l -r -E {ignore_spec} \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -r -E {ignore_spec} --link-dest=\"{relative_link_dest}\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())

        return sync_command

    def copy_file_to_dir(self, src_file, trg_dir, link_dest=None, ignore=None):
        assert not src_file.endswith("/")
        ignore_spec = self.create_ignore_spec(ignore)
        if link_dest is None:
            sync_command = "rsync -l -r -E {ignore_spec} \"{src_file}\" \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -r -E {ignore_spec} --link-dest=\"{relative_link_dest}\" \"{src_file}\" \"{trg_dir}\"".format(**locals())
        return sync_command

    def copy_dir_contents_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        if not src_dir.endswith("/"):
            src_dir += "/"
        ignore_spec = self.create_ignore_spec(ignore)
        if link_dest is None:
            sync_command = "rsync -l -r -E {ignore_spec} \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -r -E {ignore_spec} --link-dest=\"{relative_link_dest}\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return sync_command

    def copy_dir_files_to_dir(self, src_dir, trg_dir, link_dest=None, ignore=None):
        if not src_dir.endswith("/"):
            src_dir += "/"
        # in order for * to correctly expand, it must be outside the quotes, e.g. to copy all files in folder a: A=a ; "${A}"/* and not "${A}/*"
        ignore_spec = self.create_ignore_spec(ignore)
        if link_dest is None:
            sync_command = "rsync -l -E -d {ignore_spec} \"{src_dir}\"/* \"{trg_dir}\"".format(**locals())
        else:
            relative_link_dest = os.path.relpath(link_dest, trg_dir)
            sync_command = "rsync -l -E -d {ignore_spec} --link-dest=\"{relative_link_dest}..\" \"{src_dir}\"/* \"{trg_dir}\"".format(**locals())

        return sync_command

class PlatformSpecificHelperBase(object):

    def __init__(self, instlObj):
        self.instlObj = instlObj
        self.copy_tool = None
        self.dl_tool = None
        self.num_items_for_progress_report = 0

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

    @abc.abstractmethod
    def cd(self, directory):
        """ platform specific cd """
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
    def rmdir(self, directory, recursive=False):
        """ platform specific rmdir """
        pass

    @abc.abstractmethod
    def rmfile(self, file):
        """ platform specific rm file """
        pass

    def new_line(self):
        return "" # empty string because write_batch_file adds \n to each line

    def progress(self, msg):
        self.num_items_for_progress_report += 1
        prog_msg = "Progress: {} of $(TOTAL_ITEMS_FOR_PROGRESS_REPORT); ".format(str(self.num_items_for_progress_report)) + msg
        return self.echo(prog_msg)

    @abc.abstractmethod
    def get_svn_folder_cleanup_instructions(self):
        """ platform specific cleanup of svn locks """
        pass

    @abc.abstractmethod
    def var_assign(self, identifier, value, comment=None):
        pass

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
        svn_command = " ".join( ("svn", "add", '"'+item_path+'"') )
        return svn_command

    def svn_remove_item(self, item_path):
        svn_command = " ".join( ("svn", "rm", "--force", '"'+item_path+'"') )
        return svn_command

    @abc.abstractmethod
    def check_checksum(self, file, checksum):
        pass

    @abc.abstractmethod
    def tar(self, to_tar_name):
        pass

    @abc.abstractmethod
    def unwtar(self, filepath):
        pass

def PlatformSpecificHelperFactory(in_os, instlObj):
    retVal = None
    if in_os == "Mac":
        import platformSpecificHelper_Mac
        retVal = platformSpecificHelper_Mac.PlatformSpecificHelperMac(instlObj)
    elif in_os == "Win":
        import platformSpecificHelper_Win
        retVal = platformSpecificHelper_Win.PlatformSpecificHelperWin(instlObj)
    elif in_os == "Linux":
        import platformSpecificHelper_Linux
        retVal = platformSpecificHelper_Linux.PlatformSpecificHelperLinux(instlObj)
    else:
        raise ValueError(in_os, "has no PlatformSpecificHelper")
    return retVal

class DownloadToolBase(object):
    """ Create download commands. Each function should be overridden to implement the download
        on specific platform using a specific copying tool. All functions return
        a list of commands, even if there is only one. This will allow to return
        multiple commands if needed.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, platformHelper):
        self.platformHelper = platformHelper
        self.urls_to_download = list()

    @abc.abstractmethod
    def download_url_to_file(self, src_url, trg_file):
        pass

    def add_download_url(self, url, path):
        self.urls_to_download.append( (urllib.quote(url, "$()/:"), path) )

    @abc.abstractmethod
    def download_from_config_file(self, config_file):
        pass

    @abc.abstractmethod
    def create_config_file(self, curl_config_file_path):
        pass
