
from sqlalchemy import Column, Integer, String, BOOLEAN
from sqlalchemy.ext.declarative import declarative_base
alchemy_base = declarative_base()


class SVNRow(alchemy_base):
    __tablename__ = 'svnitem'
    id = Column(Integer, primary_key=True)
    path = Column(String)
    name = Column(String)
    parent = Column(String, index=True)
    flags = Column(String(4))
    isDir = Column(BOOLEAN)
    isFile = Column(BOOLEAN)
    revision_remote = Column(Integer)
    revision_local = Column(Integer)
    checksum = Column(String)
    size = Column(Integer, default=-1)
    url = Column(String)
    props = Column(String)

    def __str__(self):
        """ __str__ representation - this is what will be written to info_map.txt files"""
        retVal = "{}, {}, {}".format(self.full_path(), self.flags, self.revision_remote)
        if self.checksum:
            retVal = "{}, {}".format(retVal, self.checksum)
        if self.size != -1:
            retVal = "{}, {}".format(retVal, self.size)
        if self.url:
            retVal = "{}, {}".format(retVal, self.url)
        return retVal

    def full_path(self):
        return self.path

    def isExecutable(self):
        return 'x' in self.flags

    def isSymlink(self):
        return 's' in self.flags
