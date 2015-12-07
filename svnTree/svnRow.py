
from sqlalchemy import Column, Integer, String, BOOLEAN
from sqlalchemy.ext.declarative import declarative_base
alchemy_base = declarative_base()


class SVNRow(alchemy_base):
    __tablename__ = 'svnitem'
    path = Column(String, primary_key=True)
    name = Column(String)
    parent = Column(String, index=True)
    fileFlag = Column(BOOLEAN, default=False)
    execFlag = Column(BOOLEAN, default=False)
    symlinkFlag = Column(BOOLEAN, default=False)
    revision_remote = Column(Integer)
    revision_local = Column(Integer)
    checksum = Column(String)
    size = Column(Integer, default=-1)
    url = Column(String)
    props = Column(String)

    def __str__(self):
        """ __str__ representation - this is what will be written to info_map.txt files"""
        retVal = "{}, {}, {}".format(self.full_path(), self.flag_str(), self.revision_remote)
        if self.checksum:
            retVal = "{}, {}".format(retVal, self.checksum)
        if self.size != -1:
            retVal = "{}, {}".format(retVal, self.size)
        if self.url:
            retVal = "{}, {}".format(retVal, self.url)
        return retVal

    def flag_str(self):
        retVal = 'f' if self.fileFlag else 'd'
        if self.symlinkFlag:
            retVal += 's'
        if self.execFlag:
            retVal += 'x'
        return retVal

    def full_path(self):
        return self.path

    def isDir(self):
        return not self.fileFlag

    def isFile(self):
        return self.fileFlag

    def isExecutable(self):
        return self.execFlag

    def isSymlink(self):
        return self.symlinkFlag
