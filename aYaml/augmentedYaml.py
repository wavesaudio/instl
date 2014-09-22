#!/usr/bin/env python2.7
from __future__ import print_function

"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    argumentedYaml adds some functionality to PyYaml:
        Methods isScalar(), isSequence(), isMapping()
    for easier identification of
        ScalarNode SequenceNode, MappingNode.
    Method __len__ returns the number of items in value.
    Method __iter__ implement iteration on value, ScalarNode is than pretending
        to be a list of 1; For mapping there is also iterkeys to iterate on the
        list of keys.
    Method __getitem__ implements [] access, again ScalarNode is pretending to
        be a list of 1
    Method __contains__ for MappingNode, to implement is in ...
    For writing Yaml to text:
    Method writeAsYaml implements writing Yaml text, with proper indentation,
        for python basic data types: tuple, list; If tags and comments are
        needed, YamlDumpWrap can be used to wrap other data types.
        YamlDumpDocWrap adds tags and comments to a whole document.
        Object that are not basic or YamlDumpWrap, can implement repr_for_yaml
        method to properly represent them selves for yaml writing.
"""

import sys
import os
import yaml
from collections import OrderedDict

if __name__ == "__main__":
    sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))

yaml.Node.isNone = lambda self: self.tag.endswith(":null")

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

yaml.ScalarNode.yamlType = lambda self: "scalar"
yaml.SequenceNode.yamlType = lambda self: "sequence"
yaml.MappingNode.yamlType = lambda self: "mapping"

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
        if map_tuple[1].isNone():
            map_tuple[1].value = None
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
        if item.isNone():
            item.value = None
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
    raise IndexError


def get_mapping_item(self, key):
    """ operator[] for mapping will look for a key whose
        value as a string equal to the key argument. """
    key_as_str = str(key)
    for item in self.value:  # for mapping each item is a tuple of (key, value)
        if str(item[0].value) == key_as_str:
            return item[1]
    raise IndexError


def get_sequence_item(self, index):
    """ operator[] for sequence, support both positive and negative indexes """
    if len(self.value) > index >= -len(self.value):
        return self.value[index]
    raise IndexError

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
    """ implements C's test ? ifTrue : ifFalse """
    if test:
        return ifTrue
    else:
        return ifFalse


class YamlDumpWrap(object):
    """ Warps a python object or data structure to be written to Yaml.
        Overcomes some of PyYaml limitations, by adding the option to
        have comments and tags. Sorting mapping be key us also optional.
    """
    def __init__(self, value=None, tag="", comment="", sort_mappings=False):
         # sometimes tag's type is unicode, pyYaml is strange...
        self.tag = tag.encode('ascii', 'ignore')
        self.comment = comment
        self.value = value
        self.sort_mappings = sort_mappings

    def __lt__(self, other):
        return self.value < other.value

    def isMapping(self):
        return isMapping(self.value)

    def isSequence(self):
        return isSequence(self.value)

    def isScalar(self):
        return isScalar(self.value)

    def writePrefix(self, out_stream, indentor):
        if isinstance(self.value, (list, tuple, dict)):
            if self.tag or self.comment:
                indentor.lineSepAndIndent(out_stream)
                commentSep = ifTrueOrFalse(self.comment, "#", "")
                out_stream.write(" ".join((self.tag, commentSep, self.comment)))
        elif self.tag:
            out_stream.write(self.tag)
            out_stream.write(" ")

    def writePostfix(self, out_stream, indentor):
        if not isinstance(self.value, (list, tuple, dict)):
            if self.comment:
                out_stream.write(" # ")
                out_stream.write(self.comment)


class YamlDumpDocWrap(YamlDumpWrap):
    def __init__(
        self, value=None, tag="", comment="",
            explicit_start=True, explicit_end=False,
            sort_mappings=False):
        super(YamlDumpDocWrap, self).__init__(tag=tag, comment=comment,
                                              value=value,
                                              sort_mappings=sort_mappings)
        self.explicit_start = explicit_start
        self.explicit_end = explicit_end

    def writePrefix(self, out_stream, indentor):
        indentor.reset()
        if self.tag or self.comment or self.explicit_start:
            commentSep = ifTrueOrFalse(self.comment, "#", "")
            out_stream.write(" ".join(("---", self.tag, commentSep, self.comment)))
            indentor.lineSepAndIndent(out_stream)

    def writePostfix(self, out_stream, indentor):
        if self.explicit_end:
            indentor.lineSepAndIndent(out_stream,)
            out_stream.write("...")
        # document should end with new line:
        indentor.lineSepAndIndent(out_stream)


class Indentor(object):
    def __init__(self, indent_size):
        self.indent_size = indent_size
        self.cur_indent = 0
        self.num_extra_chars = 0
        self.item_type_stack = []

    def push(self, val):
        self.item_type_stack.append(val)

    def pop(self):
        if self.item_type_stack:
            return self.item_type_stack.pop()
        else:
            return None

    def top(self):
        if self.item_type_stack:
            return self.item_type_stack[-1]
        else:
            return None

    def __iadd__(self, i):
        self.cur_indent += i
        return self

    def __isub__(self, i):
        self.cur_indent -= i
        return self

    def reset(self):
        self.cur_indent = 0
        self.num_extra_chars = 0

    def lineSepAndIndent(self, out_stream):
        out_stream.write('\n')
        numSpaces = self.indent_size * self.cur_indent
        out_stream.write(" " * numSpaces)
        self.num_extra_chars = 0

    def write_extra_chars(self, out_stream, extra_chars):
        if extra_chars:
            self.num_extra_chars += len(extra_chars)
            out_stream.write(extra_chars)

    def fill_to_next_indent(self, out_stream):
        num_chars_to_fill = self.num_extra_chars % self.indent_size
        if num_chars_to_fill:
            out_stream.write(" " * num_chars_to_fill)
            self.num_extra_chars = 0


def isMapping(item):
    retVal = False
    if isinstance(item, dict):
        retVal = True
    elif isinstance(item, YamlDumpWrap):
        retVal = item.isMapping()
    return retVal


def isSequence(item):
    retVal = False
    if isinstance(item, (list, tuple)):
        retVal = True
    elif isinstance(item, YamlDumpWrap):
        retVal = item.isSequence()
    return retVal


def isScalar(item):
    retVal = True
    if isinstance(item, (list, tuple, dict)):
        retVal = False
    elif isinstance(item, YamlDumpWrap):
        retVal = item.isScalar()
    return retVal


def writeAsYaml(pyObj, out_stream=None, indentor=None, sort=False):
    if out_stream is None:
        out_stream = sys.stdout
    if indentor is None:
        indentor = Indentor(4)
    if pyObj is None:
        out_stream.write("~")
    elif isinstance(pyObj, (list, tuple)):
        indentor.push('l')
        for item in pyObj:
            if isinstance(item, YamlDumpDocWrap):
                indentor.push(None)  # doc should have no parent
                writeAsYaml(item, out_stream, indentor, sort)
                indentor.pop()
            else:
                indentor.lineSepAndIndent(out_stream)
                indentor.write_extra_chars(out_stream, "- ")
                indentor += 1
                writeAsYaml(item, out_stream, indentor, sort)
                indentor -= 1
        indentor.pop()
    elif isinstance(pyObj, (dict, OrderedDict)):
        parent_item = indentor.top()
        indentor.push('m')
        if sort and not isinstance(pyObj, OrderedDict):
            theKeys = sorted(pyObj.keys())
        else:
            theKeys = pyObj.keys()
        for item in theKeys:
            nl_before_key = (parent_item != 'l')
            if nl_before_key:
                indentor.lineSepAndIndent(out_stream)
            writeAsYaml(item, out_stream, indentor, sort)
            indentor.write_extra_chars(out_stream, ": ")
            indentor += 1
            writeAsYaml(pyObj[item], out_stream, indentor, sort)
            indentor -= 1
        indentor.pop()
    elif isinstance(pyObj, YamlDumpWrap):
        pyObj.writePrefix(out_stream, indentor)
        writeAsYaml(pyObj.value, out_stream, indentor, sort or pyObj.sort_mappings)
        pyObj.writePostfix(out_stream, indentor)
    else:
        if hasattr(pyObj, "repr_for_yaml"):
            writeAsYaml(pyObj.repr_for_yaml(), out_stream, indentor, sort)
        else:
            out_stream.write(str(pyObj))
    # add the final end-of-line. But if writeAsYaml is recursed from outside writeAsYaml
    # this will not work.
    if sys._getframe(0).f_code.co_name != sys._getframe(1).f_code.co_name:
        indentor.lineSepAndIndent(out_stream)


def nodeToPy(a_node):
    retVal = None
    if a_node.isScalar():
        retVal = str(a_node.value)
    elif a_node.isSequence():
        retVal = [nodeToPy(item) for item in a_node.value]
    elif a_node.isMapping():
        retVal = {str(_key.value): nodeToPy(_val) for (_key, _val) in a_node.value}
    return retVal


def nodeToYamlDumpWrap(a_node):
    retVal = None
    if a_node.isScalar():
        retVal = YamlDumpWrap(str(a_node.value))
    elif a_node.isSequence():
        seq = [nodeToYamlDumpWrap(item) for item in a_node.value]
        retVal = YamlDumpWrap(seq)
    elif a_node.isMapping():
        amap = {str(_key.value): nodeToYamlDumpWrap(_val) for (_key, _val) in a_node.value}
        retVal = YamlDumpWrap(amap)
    return retVal


if __name__ == "__main__":
    try:
        import pyinstl.utils
        for afile in sys.argv[1:]:
            with pyinstl.utils.open_for_read_file_or_url(afile) as fd:
                for a_node in yaml.compose_all(fd):
                    a_node_as_tdw = nodeToYamlDumpWrap(a_node)
                    docWrap = YamlDumpDocWrap(a_node_as_tdw)
                    writeAsYaml(docWrap)
    except Exception as ex:
        import traceback
        tb = traceback.format_exc()
        print(tb)
