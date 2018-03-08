#!/usr/bin/env python3

import re
import sqlite3

from sqlalchemy import Column, Integer, String, BOOLEAN, ForeignKey, Index
from pyinstl import db_alchemy
from configVar import var_stack

wtar_file_re = re.compile(r"""^(?P<original_name>.+)\.wtar(\...)?$""")


fields_relevant_to_dirs = ('path', 'parent', 'level', 'flags', 'revision', 'required')
fields_relevant_to_str = ('path', 'flags', 'revision', 'checksum', 'size', 'url')


class SVNRow(db_alchemy.get_declarative_base()):
    __tablename__ = 'svnitem'
    _id = Column(Integer, primary_key=True)
    path = Column(String)
    flags = Column(String)   # the flags in text format f,d,x
    revision = Column(Integer, default=0)  # SVN revision
    checksum = Column(String(40), default=None)
    size = Column(Integer, default=-1)
    url = Column(String, default=None)
    fileFlag = Column(BOOLEAN, default=False)  # 1/True->file, 0/False->dir
    wtarFlag = Column(Integer, default=0)
    leaf = Column(String)
    parent = Column(String)  # todo: this should be in another table
    level = Column(Integer)     # levels deep in the folders hierarchy
    required = Column(BOOLEAN, default=False)       # is required for install
    need_download = Column(BOOLEAN, default=False)
    download_path = Column(String)
    download_root = Column(String, default=None)  # top folder for direct sync items not the same as parent
    extra_props = Column(String,default="")  # SVN properties
    alternative_required = Column(BOOLEAN, default=False)

    def __repr__(self):
        isDir = not self.fileFlag
        return ("<{self.level}, {self.path}, '{self.flags}'"
                ", rev-remote:{self.revision}, f:{self.fileFlag}, d:{isDir}"
                ", checksum:{self.checksum}, size:{self.size}"
                ", url:{self.url}"
                ", required:{self.required}, need_download:{self.need_download}"
                ", extra_props:{self.extra_props}, parent:{self.parent}>"
                ", download_path:{self.download_path}"
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
        if self.download_path:
            retVal = "{}, dl_path:'{}'".format(retVal, self.download_path)
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
        return not self.fileFlag

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
        retVal = self.wtarFlag > 0
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

    def __eq__(self, other):
        """Overrides the default implementation"""
        retVal = False
        if isinstance(self, other.__class__):
            retVal = self.__dict__ == other.__dict__
        elif isinstance(other, sqlite3.Row): \
            retVal= (other['_id'] == self._id
            and     other['path'] == self.path
            and     other['flags'] == self.flags
            and     other['revision'] == self.revision
            and     other['checksum'] == self.checksum
            and     other['size'] == self.size
            and     other['url'] == self.url
            and     other['fileFlag'] == self.fileFlag
            and     other['wtarFlag'] == self.wtarFlag
            and     other['leaf'] == self.leaf
            and     other['parent'] == self.parent
            and     other['level'] == self.level
            and     other['required'] == self.required
            and     other['need_download'] == self.need_download
            and     other['download_path'] == self.download_path
            and     other['download_root'] == self.download_root
            and     other['alternative_required'] == self.alternative_required
                    )
        elif isinstance(other, tuple): \
            retVal= (other[0] == self._id
            and     other[1] == self.path
            and     other[2] == self.flags
            and     other[3] == self.revision
            and     other[4] == self.checksum
            and     other[5] == self.size
            and     other[6] == self.url
            and     other[7] == self.fileFlag
            and     other[8] == self.wtarFlag
            and     other[9] == self.leaf
            and     other[10] == self.parent
            and     other[11] == self.level
            and     other[12] == self.required
            and     other[13] == self.need_download
            and     other[14] == self.download_path
            and     other[15] == self.download_root
            and     other[16] == self.extra_props
            and     other[17] == self.alternative_required
                    )
        return retVal

SVNRow.__table__.create(bind=db_alchemy.get_engine(), checkfirst=True)
