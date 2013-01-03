import sys
import os

class YamlDumpWrap(object):
    def __init__(self, value=None, tag='!', comment=""):
        self.tag = tag
        self.comment = comment
        self.value = value
    def writePrefix(self, out_stream):
        if self.tag != '!':
            out_stream.write(self.tag)
            out_stream.write(" ")
    def writePostfix(self, out_stream):
        if self.comment:
            out_stream.write(" # ")
            out_stream.write(self.comment)

class YamlDumpDocWrap(YamlDumpWrap):
    def __init__(self, value=None, tag='!', comment=""):
        super(YamlDumpDocWrap, self).__init__(tag=tag, comment=comment, value=value)    
        self.before = "---"
        self.after = "..."
    def writePrefix(self, out_stream):
        if self.before:
            out_stream.write(self.before)
        if self.tag != '!':
            out_stream.write(" ")
            out_stream.write(self.tag)
        if self.comment:
            out_stream.write(" # ")
            out_stream.write(self.comment)
    def writePostfix(self, out_stream):
        if self.after:
            lineSepIndent(out_stream, 0)
            out_stream.write(self.after)

def isScalar(pyObj):
    retVal = True
    if isinstance(pyObj, (list, tuple, dict)):
        retVal = False
    elif isinstance(pyObj, YamlDumpWrap):
        retVal = isScalar(pyObj.value)
    else:
        retVal = True

def lineSepIndent(out_stream, indent, indentSize=4):
    out_stream.write(os.linesep)
    out_stream.write(" " * indentSize * indent)

def writeAsYaml(pyObj, out_stream, indent=0):
    if pyObj is None:
        pass
    elif isinstance(pyObj, (list, tuple)):
        for item in pyObj:
            lineSepIndent(out_stream, indent)
            out_stream.write("- ")
            writeAsYaml(item, out_stream, indent)
    elif isinstance(pyObj, dict):
        for item in pyObj:
            lineSepIndent(out_stream, indent)
            writeAsYaml(item, out_stream, indent)
            out_stream.write(": ")
            indent += 1
            writeAsYaml(pyObj[item], out_stream, indent)
            indent -= 1
    elif isinstance(pyObj, YamlDumpWrap):
        pyObj.writePrefix(out_stream)
        writeAsYaml(pyObj.value, out_stream, indent)
        pyObj.writePostfix(out_stream)
    else:
        out_stream.write(str(pyObj))
            
tup = ("tup1", YamlDumpWrap("tup2", '!tup_tag', "tup comment"), "tup3")
lis = ["list1", "list2"]
dic = {"theTup" : tup, "theList" : lis}

dicWithTag = YamlDumpWrap(dic, "!dickTracy")

doc = YamlDumpDocWrap(tag="!myDoc", comment="just a comment", value=dicWithTag)

writeAsYaml(doc, sys.stdout)
