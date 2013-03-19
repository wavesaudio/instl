#!/usr/local/bin/python2.7
from __future__ import print_function

import abc
import os

def DefaultCopyToolName(target_os):
    retVal = None
    if target_os == "Win":
        retVal = "robocopy"
    elif target_os == "Mac":
        retVal = "rsync"
    else:
        raise ValueError(target_os, "has no valid default copy tool")
    return retVal

def CopyCommanderFactory(target_os, tool):
    retVal = None
    if target_os == "Win":
        if tool == "robocopy":
            retVal = CopyCommander_win_robocopy()
        if tool == "xcopy":
            retVal = CopyCommander_win_xcopy()
        else:
            raise ValueError(tool, "is not a valid copy tool for", target_os)
    elif target_os == "Mac":
        if tool == "rsync":
            retVal = CopyCommander_mac_rsync()
        else:
            raise ValueError(tool, "is not a valid copy tool for", target_os)
    return retVal;

class CopyCommanderBase(object):
    """ Create copy commands. Each function should be overriden to inplement the copying
        on specific platform using a specific copying tool. All functions return
        a list of commands, even if tere is only one. This will allow to return 
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


class CopyCommander_win_robocopy(CopyCommanderBase):
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E /XD .svn".format(**locals())
        retVal.append(copy_command)
        return retVal

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        src_dir, src_file = os.path.split(src_file)
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" \"{src_file}\"".format(**locals())
        return (copy_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /E /XD .svn".format(**locals())
        return (copy_command, )
    
    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        copy_command = "robocopy \"{src_dir}\" \"{trg_dir}\" /LEV:1 /XD .svn".format(**locals())
        return (copy_command, )

class CopyCommander_win_xcopy(CopyCommanderBase):
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        retVal = list()
        _, dir_to_copy = os.path.split(src_dir)
        trg_dir = "/".join( (trg_dir, dir_to_copy) )
        mkdir_command  = "mkdir \"{trg_dir}\"".format(**locals())
        retVal.append(mkdir_command)
        retVal.extend(self.create_copy_dir_contents_to_dir_command(src_dir, trg_dir))
        return retVal

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        #src_dir, src_file = os.path.split(src_file)
        copy_command = "xcopy  /R /Y \"{src_file}\" \"{trg_dir}\"".format(**locals())
        copy_command.replace("\\", "/")
        return (copy_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        copy_command = "xcopy /E /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (copy_command, )
    
    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        copy_command = "xcopy  /R /Y \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (copy_command, )

class CopyCommander_mac_rsync(CopyCommanderBase):
    def create_copy_dir_to_dir_command(self, src_dir, trg_dir):
        if src_dir.endswith("/"):
            src_dir.rstrip("/")
        sync_command = "rsync -r -E --exclude=\'.svn/\' --link-dest=\"{src_dir}/..\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (sync_command, )

    def create_copy_file_to_dir_command(self, src_file, trg_dir):
        assert not src_file.endswith("/")
        sync_command = "rsync -r -E --exclude=\'.svn/\' --link-dest=\"{src_file}\" \"{src_file}\" \"{trg_dir}\"".format(**locals())
        return (sync_command, )

    def create_copy_dir_contents_to_dir_command(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        sync_command = "rsync -r -E --exclude=\'.svn/\' --link-dest=\"{src_dir}..\" \"{src_dir}\" \"{trg_dir}\"".format(**locals())
        return (sync_command, )

    def create_copy_dir_files_to_dir_command(self, src_dir, trg_dir):
        if not src_dir.endswith("/"):
            src_dir += "/"
        sync_command = "rsync -E --exclude=\'.svn/\' --link-dest=\"{src_dir}..\" \"{src_dir}*\" \"{trg_dir}\"".format(**locals())
        return (sync_command, )

if __name__ == "__main__":
    src_dir = "a/b/c"
    trg_dir = "x"
    src_file = "d.txt"

    rsyncier = CopyCommander_rsync()
    print("create_copy_dir_to_dir_command:", rsyncier.create_copy_dir_to_dir_command(src_dir, trg_dir)[0])
    print("create_copy_file_to_dir_command:", rsyncier.create_copy_file_to_dir_command(src_file, trg_dir)[0])
    print("create_copy_dir_contents_to_dir_command:", rsyncier.create_copy_dir_contents_to_dir_command(src_dir, trg_dir)[0])
    print("create_copy_dir_files_to_dir_command:", rsyncier.create_copy_dir_files_to_dir_command(src_dir, trg_dir)[0])
