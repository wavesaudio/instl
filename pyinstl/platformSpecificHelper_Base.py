#!/usr/bin/env python2.7
from __future__ import print_function
import abc

def DefaultCopyToolName(target_os):
    retVal = None
    if target_os == "Win":
        retVal = "robocopy"
    elif target_os == "Mac":
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

    @abc.abstractmethod
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        """ Copy src_dir as a folder into trg_dir.
            Example: create_copy_dir_to_dir_command("a", "/d/c/b") creates the folder:
            "/d/c/b/a"
        """
        pass

    @abc.abstractmethod
    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        """ Copy the file src_file into trg_dir.
            Example: create_copy_file_to_dir_command("a.txt", "/d/c/b") creates the file:
            "/d/c/b/a.txt"
        """
        pass

    @abc.abstractmethod
    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        """ Copy the contents of src_dir into trg_dir.
            Example: create_copy_dir_contents_to_dir_command("a", "/d/c/b") copies
            everything from a into "/d/c/b"
        """
        pass

    @abc.abstractmethod
    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        """ Copy the files of src_dir into trg_dir.
            Example: create_copy_dir_contents_to_dir_command("a", "/d/c/b") copies
            all files from a into "/d/c/b", subfolders of a are not copied
        """
        pass

class PlatformSpecificHelperBase(object):

    def __init__(self):
        self.copy_tool = None
        self.dl_tool = None

    @abc.abstractmethod
    def get_install_instructions_prefix(self):
        """ platform specific """
        pass

    @abc.abstractmethod
    def get_install_instructions_postfix(self):
        """ platform specific last lines of the install script """
        pass

    @abc.abstractmethod
    def make_directory_cmd(self, directory):
        """ platform specific mkdir for install script """
        pass

    @abc.abstractmethod
    def change_directory_cmd(self, directory):
        """ platform specific cd for install script """
        pass

    @abc.abstractmethod
    def get_svn_folder_cleanup_instructions(self, directory):
        """ platform specific cleanup of svn locks """
        pass

    @abc.abstractmethod
    def create_var_assign(self, identifier, value):
        pass

    @abc.abstractmethod
    def create_echo_command(self, message):
        pass

    @abc.abstractmethod
    def create_remark_command(self, remark):
        pass

    @abc.abstractmethod
    def use_copy_tool(self, tool):
        pass

    @abc.abstractmethod
    def create_copy_file_to_file_command(self, src_file, trg_file):
        """ Copy src_file to trg_file.
            Example: create_copy_file_to_file("a.txt", "/d/c/bt.txt") copies
            the file a.txt into "/d/c/bt.txt".
        """
        pass

def PlatformSpecificHelperFactory(in_os):
    retVal = None
    if in_os == "Mac":
        import platformSpecificHelper_Mac
        retVal = platformSpecificHelper_Mac.PlatformSpecificHelperMac()
    elif in_os == "Win":
        import platformSpecificHelper_Win
        retVal = platformSpecificHelper_Win.PlatformSpecificHelperWin()
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

    @abc.abstractmethod
    def create_download_file_to_file_command(self, src_url, trg_file):
        pass
