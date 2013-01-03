import sys
import os

def ifTrueOrFalse(test, ifTrue, ifFalse):
    if test:
        return ifTrue
    else:
        return ifFalse
    
class YamlDumpWrap(object):
    def __init__(self, value=None, tag="", comment=""):
        self.tag = tag
        self.comment = comment
        self.value = value
    def writePrefix(self, out_stream, indent):
        if isinstance(self.value, (list, tuple, dict)):
            if self.tag or self.comment:
                lineSepIndent(out_stream, indent)
                commentSep = ifTrueOrFalse(self.comment, "#", "")
                out_stream.write(" ".join( (self.tag, commentSep, self.comment) ))
        elif self.tag:
            out_stream.write(self.tag)
            out_stream.write(" ")
    def writePostfix(self, out_stream, indent):
        if not isinstance(self.value, (list, tuple, dict)):
           if self.comment:
                out_stream.write(" # ")
                out_stream.write(self.comment)

class YamlDumpDocWrap(YamlDumpWrap):
    def __init__(self, value=None, tag='!', comment="", explicit_start=False, explicit_end=False):
        super(YamlDumpDocWrap, self).__init__(tag=tag, comment=comment, value=value)    
        self.explicit_start = explicit_start
        self.explicit_end = explicit_end
    def writePrefix(self, out_stream, indent):
        if self.tag or self.comment or explicit_start:
            lineSepIndent(out_stream, indent)
            commentSep = ifTrueOrFalse(self.comment, "#", "")
            out_stream.write(" ".join( ("---", self.tag, commentSep, self.comment) ))
    def writePostfix(self, out_stream, indent):
        if self.explicit_end:
            lineSepIndent(out_stream, 0)
            out_stream.write("...")

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
        pyObj.writePrefix(out_stream, indent)
        writeAsYaml(pyObj.value, out_stream, indent)
        pyObj.writePostfix(out_stream, indent)
    else:
        out_stream.write(str(pyObj))
           
if __name__ == "__main__": 
    tup = ("tup1", YamlDumpWrap("tup2", '!tup_tag', "tup comment"), "tup3")
    lis = ["list1", "list2"]
    lisWithTag = YamlDumpWrap(lis, "!lisTracy", "lisComments")
    dic = {"theTup" : tup, "theList" : lisWithTag}

    dicWithTag = YamlDumpWrap(dic, "!dickTracy", "dickComments")

    doc = YamlDumpDocWrap(tag="!myDoc", comment="just a comment", value=dicWithTag)

    writeAsYaml(doc, sys.stdout)
