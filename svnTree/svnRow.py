#!/usr/bin/env python3

#import os
#import sys
import re

from sqlalchemy import Column, Integer, String, BOOLEAN
#from sqlalchemy.ext.declarative import declarative_base

#sys.path.append(os.path.realpath(os.path.join(__file__, ".." "..")))

from pyinstl.db_alchemy import get_declarative_base, get_engine
#alchemy_base = declarative_base()

wtar_file_re = re.compile(r"""^(?P<original_name>.+)\.wtar(\...)?$""")


fields_relevant_to_dirs = ('path', 'parent', 'level', 'flags', 'revision', 'required')
fields_relevant_to_str = ('path', 'flags', 'revision', 'checksum', 'size', 'url')


class SVNRow(get_declarative_base()):
    __tablename__ = 'svnitem'
    _id = Column(Integer, primary_key=True)
    path = Column(String, index=True)
    parent = Column(String)  # todo: this should be in another table
    level = Column(Integer)
    flags = Column(String)
    revision = Column(Integer, default=0)
    fileFlag = Column(BOOLEAN, default=False)
    dirFlag = Column(BOOLEAN, default=False)
    checksum = Column(String(40), default=None)
    size = Column(Integer, default=-1)
    url = Column(String, default=None)
    required = Column(BOOLEAN, default=False)
    need_download = Column(BOOLEAN, default=False)
    extra_props = Column(String,default="")

    def __repr__(self):
        return ("<{self.level}, {self.path}, '{self.flags}'"
                ", rev-remote:{self.revision}, f:{self.fileFlag}, d:{self.dirFlag}"
                ", checksum:{self.checksum}, size:{self.size}"
                ", url:{self.url}"
                ", required:{self.required}, need_download:{self.need_download}"
                ", extra_props:{self.extra_props}, parent:{self.parent}>"
                ).format(**locals())

    def __str__(self):
        """ __str__ representation - this is what will be written to info_map.txt files"""
        retVal = "{}, {}, {}".format(self.path, self.flags, self.revision)
        if self.checksum:
            retVal = "{}, {}".format(retVal, self.checksum)
        if self.size != -1:
            retVal = "{}, {}".format(retVal, self.size)
        if self.url:
            retVal = "{}, {}".format(retVal, self.url)
        return retVal

    def str_specific_fields(self, fields_to_repr):
        """ represent self as a string and limiting the fields written to those in fields_to_repr.
        :param fields_to_repr: only fields whose name is on this list will be written.
                if list is empty or None, fall back to __str__
        :return: string of comma separated values
        """
        if fields_to_repr is None or len(fields_to_repr) == 0:
            retVal = self.__str__()
        else:
            value_list = list()
            if self.isDir():
                for name in fields_to_repr:
                    if name in fields_relevant_to_dirs:
                        value_list.append(str(getattr(self, name, "no member named "+name)))
            else:
                for name in fields_to_repr:
                    value_list.append(str(getattr(self, name, "no member named "+name)))
            retVal = ", ".join(value_list)
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
        return self.dirFlag

    def isFile(self):
        return self.fileFlag

    def isExecutable(self):
        return 'x' in self.flags

    def isSymlink(self):
        return 's' in self.flags

    def name_without_wtar_extension(self):
        retVal = self.name()
        match = wtar_file_re.match(retVal)
        if match:
            retVal = match.group('original_name')
        return retVal

    def path_without_wtar_extension(self):
        retVal = self.path
        match = wtar_file_re.match(retVal)
        if match:
            retVal = match.group('original_name')
        return retVal

    def is_wtar_file(self):
        match = wtar_file_re.match(self.path)
        retVal = match is not None
        return retVal

    def is_first_wtar_file(self):
        retVal = self.path.endswith((".wtar", ".wtar.aa"))
        return retVal

    def extra_props_list(self):
        retVal = self.extra_props.split(";")
        retVal = [prop for prop in retVal if prop]  # split will return [""] for empty list
        return retVal

    def chmod_spec(self):
        retVal = "a+rw"
        if self.isExecutable() or self.isDir():
            retVal += "x"
        return retVal

    def path_starting_from_dir(self, starting_dir):
        retVal = None
        if starting_dir == "":
            retVal = self.path
        else:
            if not starting_dir.endswith("/"):
                starting_dir += "/"
            if self.path.startswith(starting_dir):
                retVal = self.path[len(starting_dir):]
        return retVal

SVNRow.__table__.create(bind=get_engine(), checkfirst=True)
