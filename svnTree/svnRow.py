#!/usr/bin/env python2.7
from __future__ import print_function

import re

from sqlalchemy import Column, Integer, String, BOOLEAN
from sqlalchemy.ext.declarative import declarative_base
alchemy_base = declarative_base()

wtar_file_re = re.compile(r"""^.+\.wtar(\...)?$""")

class SVNRow(alchemy_base):
    __tablename__ = 'svnitem'
    path = Column(String, primary_key=True)
    level = Column(Integer)
    flags = Column(String)
    revision_remote = Column(Integer, default=0)
    fileFlag = Column(BOOLEAN, default=False)
    checksum = Column(String, default=None)
    size = Column(Integer, default=-1)
    url = Column(String, default=None)
    required = Column(BOOLEAN, default=False)
    need_download = Column(BOOLEAN, default=False)

    #execFlag = Column(BOOLEAN, default=False)
    #wtar_file = Column(BOOLEAN, default=False) # any .wtar or .wtar.?? file
    #wtar_first_file = Column(BOOLEAN, default=False) # .wtar or wtar.aa file
    #revision_local = Column(Integer, default=0)

    def __repr__(self):
        return ("<{self.level}, {self.path}, '{self.flags}'"
                ", rev-remote:{self.revision_remote}, f:{self.fileFlag}"
                ", checksum:{self.checksum}, size:{self.size}"
                ", url:{self.checksum}"
                ", required:{self.required}, need_download:{self.need_download}>"
                ).format(**locals())

    def __str__(self):
        """ __str__ representation - this is what will be written to info_map.txt files"""
        retVal = "{}, {}, {}".format(self.path, self.flags, self.revision_remote)
        if self.checksum:
            retVal = "{}, {}".format(retVal, self.checksum)
        if self.size != -1:
            retVal = "{}, {}".format(retVal, self.size)
        if self.url:
            retVal = "{}, {}".format(retVal, self.url)
        return retVal

    def name(self):
        retVal = self.path.split("/")[-1]
        return retVal

    def get_ancestry(self):
        ancestry = list()
        split_path = self.path.split("/")
        for i in range(1, len(split_path)+1):
            ancestry.append("/".join(split_path[:i]))
        return ancestry

    def isDir(self):
        return not self.fileFlag

    def isFile(self):
        return self.fileFlag

    def isExecutable(self):
        return 'x' in self.flags

    def isSymlink(self):
        return 's' in self.flags

    def is_wtar_file(self):
        match = wtar_file_re.match(self.path)
        retVal = match is not None
        return retVal

    def is_first_wtar_file(self):
        retVal = self.path.endswith((".wtar", ".wtar.aa"))
        return retVal
