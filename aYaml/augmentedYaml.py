#!/usr/local/bin/python

"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
    
    argumentedYaml adds some functionality to PyYaml:
    Methods isScalar(), isSequence(), isMapping() for easier identification of ScalarNode
        SequenceNode, MappingNode.
    Method __len__ returns the number of items in value.
    Method __iter__ implement iteration on value, ScalarNode is than pretending to be 
        a list of 1; For mapping there is also iterkeys to iterate on the list of keys.
    Method __getitem__ implements [] access, again ScalarNode is pretending to be 
        a list of 1
    Method __contains__ for MappingNode, to implement is in ...
    For writing Yaml to text:
    Method writeAsYaml implements writing Yaml text, with proper indentation, for python 
        basic data types: tuple, list; If tags and comments are needed, YamlDumpWrap
        can be used to wrap other data types.  YamlDumpDocWrap adds tags and comments to 
        a whole document. Object that are not basic or YamlDumpWrap, can implement
        repr_for_yaml method to properly represent them selves for yaml writing.
"""

import sys
import os
import yaml

if __name__ == "__main__":
    sys.path.append("..")

# patch yaml.Node derivatives to identify themselves.
yaml.ScalarNode.isScalar = lambda self: True
yaml.SequenceNode.isScalar = lambda self: False
yaml.MappingNode.isScalar = lambda self: False

yaml.ScalarNode.isSequence = lambda self: False
yaml.SequenceNode.isSequence = lambda self: True
yaml.MappingNode.isSequence = lambda self: False

yaml.ScalarNode.isMapping = lambda self: False
yaml.SequenceNode.isMapping = lambda self: False
yaml.MappingNode.isMapping = lambda self: True

# patch yaml.Node derivatives to return their length
yaml.ScalarNode.__len__ = lambda self: 1
yaml.MappingNode.__len__ = lambda self: len(self.value)
yaml.SequenceNode.__len__ = lambda self: len(self.value)

# patch yaml.Node derivatives to iterate themselves
def iter_scalar(self):
    """ iterator for scalar will yield once - it's own value """
    yield self

def iter_mapping(self):
    """ iterator for mapping will yield two values
        the key as a string & the value. The assumption
        is that mapping key is a scalar
    """
    for map_tuple in self.value:
        yield str(map_tuple[0].value), map_tuple[1]

def iter_mapping_keys(self):
    """ iterator for mapping keys will yield
        the key as a string. The assumption
        is that mapping key is a scalar
    """
    for map_tuple in self.value:
        yield str(map_tuple[0].value)

def iter_sequence(self):
    """ iterator for sequence just iterates over the values """
    for item in self.value:
        yield item

yaml.ScalarNode.__iter__ = iter_scalar
yaml.MappingNode.__iter__ = iter_mapping
yaml.MappingNode.iterkeys = iter_mapping_keys
yaml.SequenceNode.__iter__ = iter_sequence

# patch yaml.Node derivatives to support []
def get_scalar_item(self, index):
    """ operator[] for scalar will return the value for index 0
        and throw an exception otherwise. """
    if index == 0 or index == -1:
        return self
    raise  IndexError
def get_mapping_item(self, key):
    """ operator[] for mapping will look for a key whose
        value as a string equal to the key argument. """
    key_as_str = str(key)
    for item in self.value: # for mapping each item is a tuple of (key, value)
        if str(item[0].value) == key_as_str:
            return item[1]
    raise  IndexError
def get_sequence_item(self, index):
    """ operator[] for sequence, support both positive and negative indexes """
    if index < len(self.value) and index >=  -len(self.value):
        return self.value[index]
    raise  IndexError

yaml.ScalarNode.__getitem__ = get_scalar_item
yaml.MappingNode.__getitem__ = get_mapping_item
yaml.SequenceNode.__getitem__ = get_sequence_item


def mappaing_containes(self, key):
    """ support 'if x in y:...' """
    try:
        self.__getitem__(key)
        return True
    except:
        return False
yaml.MappingNode.__contains__ = mappaing_containes


def ifTrueOrFalse(test, ifTrue, ifFalse):
    if test:
        return ifTrue
    else:
        return ifFalse

def lineSepAndIndent(out_stream, indent, indentSize=4):
    out_stream.write(os.linesep)
    out_stream.write(" " * indentSize * indent)
    
class YamlDumpWrap(object):
    def __init__(self, value=None, tag="", comment=""):
        self.tag = tag
        self.comment = comment
        self.value = value
    def writePrefix(self, out_stream, indent):
        if isinstance(self.value, (list, tuple, dict)):
            if self.tag or self.comment:
                lineSepAndIndent(out_stream, indent)
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
            lineSepAndIndent(out_stream, indent)
            commentSep = ifTrueOrFalse(self.comment, "#", "")
            out_stream.write(" ".join( ("---", self.tag, commentSep, self.comment) ))
    def writePostfix(self, out_stream, indent):
        if self.explicit_end:
            lineSepAndIndent(out_stream, 0)
            out_stream.write("...")

def writeAsYaml(pyObj, out_stream, indent=0):
    if pyObj is None:
        pass
    elif isinstance(pyObj, (list, tuple)):
        for item in pyObj:
            lineSepAndIndent(out_stream, indent)
            out_stream.write("- ")
            writeAsYaml(item, out_stream, indent)
    elif isinstance(pyObj, dict):
        for item in pyObj:
            lineSepAndIndent(out_stream, indent)
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
        if hasattr(pyObj, "repr_for_yaml"):
            writeAsYaml(pyObj.repr_for_yaml(), out_stream, indent)
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
