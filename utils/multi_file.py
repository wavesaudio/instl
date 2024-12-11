#!/usr/bin/env python3.9

import io
import os
import stat
import tarfile
from typing import Union


"""
    MultiFileReader opens one or more files and reads them as if they
    were one continuous file. Open mode parameter can either be
    'r' for text files or 'rb' for binary files. readline is not supported
    nor is writing.
    MultiFileReader implements the io.RawIOBase interface.

    Example:
        fd = MultiFileReader('r', ['a.txt', 'b.txt'])
        the_text = fd.read()
        fd.close()

    Or as context manager:
        with MultiFileReader('rb', ['a.bin', 'b.bin']) as fd:
            buff = fd.read(20)
            while buff:
                do_something(buff)
                buff = fd.read(20)
"""


class MultiFileReader(io.RawIOBase):
    class OpenFileData(object):
        def __init__(self, path_to_file) -> None:
            self.path_to_file = path_to_file
            self.size = 0
            self.starting_pos = 0
            self.fd = None

        def open(self, mode):
            the_stats = os.lstat(self.path_to_file)
            self.size = the_stats[stat.ST_SIZE]
            self.fd = open(self.path_to_file, mode)

        def close(self):
            if self.fd is not None:
                self.fd.close()
                self.fd = None
            self.size = 0
            self.starting_pos = 0

    def __init__(self, mode, paths) -> None:
        super().__init__()
        self.mode = mode
        self.the_files = [MultiFileReader.OpenFileData(path) for path in paths]
        self.num_files = len(self.the_files)
        self.total_size = -1
        self.current_fd_index = -1
        self.empty_buffer: Union[str, bytes] = ''
        if 'b' in self.mode:
            self.empty_buffer = b''

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, etype, value, traceback):
        self.close()

    def open(self):
        running_size = 0
        for a_file in self.the_files:
            a_file.open(self.mode)
            a_file.starting_pos = running_size
            running_size += a_file.size
        self.total_size = running_size
        self.current_fd_index = 0

    def close(self):
        for a_file in self.the_files:
            a_file.close()
        del self.the_files[:]
        self.total_size = -1
        self.current_fd_index = -1
        self.num_files = -1

    def isatty(self):
        return False

    def fileno(self):
        raise io.UnsupportedOperation("MultiFileReader does not have a fileno")

    def truncate(self, size=None):
        raise io.UnsupportedOperation("MultiFileReader does not support truncate")

    def seekable(self):
        return -1 < self.current_fd_index

    def writable(self):
        return False

    def readable(self):
        retVal = -1 < self.current_fd_index < self.num_files
        return retVal

    def readline(self, size=-1):
        raise io.UnsupportedOperation("MultiFileReader.readline is not implemented (yet)")

    def readlines(self, hint=-1):
        raise io.UnsupportedOperation("MultiFileReader.readlines is not implemented (yet)")

    def tell(self):
        if self.current_fd_index < self.num_files:
            retVal = self.the_files[self.current_fd_index].starting_pos + self.the_files[self.current_fd_index].fd.tell()
        else:
            retVal = self.total_size
        return retVal

    def seek(self, offset, whence=io.SEEK_SET):
        abs_pos = offset
        if whence == io.SEEK_CUR:
            abs_pos += self.tell()
        elif whence == io.SEEK_END:  # offset should be negative
            abs_pos += self.total_size

        for i_file in range(len(self.the_files)):
            if self.the_files[i_file].starting_pos <= abs_pos <= self.the_files[i_file].starting_pos + self.the_files[i_file].size:
                new_pos_in_file = abs_pos - self.the_files[i_file].starting_pos
                self.the_files[i_file].fd.seek(new_pos_in_file)
                self.current_fd_index = i_file
                break
        return abs_pos

    def __next_file(self):
        self.current_fd_index += 1
        if self.current_fd_index < len(self.the_files):
            self.the_files[self.current_fd_index].fd.seek(0)

    def read(self, size=-1):
        buff = self.empty_buffer
        if size == -1:  # read everything
            while self.current_fd_index < len(self.the_files):
                buff += self.the_files[self.current_fd_index].fd.read(-1)
                self.__next_file()
        else:
            if self.current_fd_index < len(self.the_files):
                a_file = self.the_files[self.current_fd_index]
                buff = a_file.fd.read(size)
                if not buff:
                    self.__next_file()
                    buff = self.read(size)
                else:
                    bytes_read = len(buff)
                    if bytes_read < size:
                        self.__next_file()
                        buff += self.read(size-len(buff))
        return buff

    def readall(self):
        buff = self.read(size=-1)
        return buff


if __name__ == "__main__":
    files_to_read = ["1.txt", "2.txt", "1.txt"]

    def read_some_files(in_files_to_read):
        mfd = MultiFileReader("r", in_files_to_read)
        mfd.open()
        try:
            while True:
                buff = mfd.read(8)
                len_buff = len(buff)
                if len_buff == 8:
                    mfd.seek(-1, io.SEEK_CUR)
                if buff:
                    print(str(buff), end="")
                else:
                    break
            mfd.flush()
        except Exception as ex:
            print("\nException!", ex)
            raise
        mfd.close()

    files_to_read = ["/repositories/betainstl/stage/Mac/Plugins/NX.bundle/Contents/Resources.wtar.xx",
"/repositories/betainstl/stage/Mac/Plugins/NX.bundle/Contents/Resources.wtar.xx",
                     "/repositories/betainstl/stage/Mac/Plugins/NX.bundle/Contents/Resources.wtar.aa",
                      "/repositories/betainstl/stage/Mac/Plugins/NX.bundle/Contents/Resources.wtar.xx",
                     "/repositories/betainstl/stage/Mac/Plugins/NX.bundle/Contents/Resources.wtar.ab",
                     "/repositories/betainstl/stage/Mac/Plugins/NX.bundle/Contents/Resources.wtar.xx"]

    def unwtar_some_files(in_files_to_unwtar):
        wtar_folder_path = "/Users/shai/Desktop"
        with MultiFileReader("br", in_files_to_unwtar) as fd:
            with tarfile.open(fileobj=fd) as tar:
                tar.extractall(wtar_folder_path)

    unwtar_some_files(files_to_read)
