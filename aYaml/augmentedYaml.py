#!/usr/bin/env python3.6


"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    augmentedYaml adds some functionality to PyYaml:
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
from typing import Any, List

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
    yield from map(lambda map_tuple: str(map_tuple[0].value), self.value)


def iter_sequence(self):
    """ iterator for sequence just iterates over the values """
    for item in self.value:
        if item.isNone():
            item.value = None
        yield item

yaml.ScalarNode.__iter__ = iter_scalar
yaml.MappingNode.items = iter_mapping
yaml.MappingNode.__iter__ = iter_mapping_keys
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


def mapping_contains(self, key):
    """ support 'if x in y:...' """
    try:
        self.__getitem__(key)
        return True
    except Exception:
        return False
yaml.MappingNode.__contains__ = mapping_contains


def ifTrueOrFalse(test: bool, ifTrue: Any, ifFalse: Any) -> Any:
    """ implements C's test ? ifTrue : ifFalse """
    if test:
        return ifTrue
    else:
        return ifFalse


class YamlDumpWrap(object):
    """ Warps a python object or data structure to be written to Yaml.
        Overcomes some of PyYaml limitations, by adding the option to
        have comments and tags. Sorting mapping by key is also optional.
    """
    def __init__(self, value=None, tag="", comment="", sort_mappings=False, include_comments=True) -> None:
        self.tag = tag
        self.comment = comment
        self.value = value
        self.sort_mappings = sort_mappings
        self.include_comments = include_comments

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
            if self.tag or (self.comment and self.include_comments):
                indentor.lineSepAndIndent(out_stream)
                if self.tag:
                    out_stream.write(self.tag)
                if self.comment and self.include_comments:
                    out_stream.write(f" # {self.comment}")
        elif self.tag:
            out_stream.write(f"{self.tag} ")

    def writePostfix(self, out_stream, indentor):
        if not isinstance(self.value, (list, tuple, dict)):
            if self.comment and self.include_comments:
                out_stream.write(f" # {self.comment}")

    def ReduceOneItemLists(self, curr_node=None):
        if curr_node is None:
            curr_node = self.value
        if isMapping(curr_node):
            for n, i in curr_node.items():
                self.ReduceOneItemLists(i)
                if isSequence(i) and len(i) == 1:
                    curr_node[n] = i[0]
        elif isSequence(curr_node):
            for i in curr_node:
                self.ReduceOneItemLists(i)


class YamlDumpDocWrap(YamlDumpWrap):
    def __init__(
        self, value=None, tag="", comment="",
            explicit_start=True, explicit_end=False,
            sort_mappings=False, include_comments=True):
        super().__init__(tag=tag, comment=comment,
                        value=value,
                        sort_mappings=sort_mappings,
                        include_comments=include_comments)
        self.explicit_start = explicit_start
        self.explicit_end = explicit_end

    def writePrefix(self, out_stream, indentor):
        indentor.reset()
        if self.explicit_start or self.tag:
            out_stream.write("---")
            if self.tag:
                out_stream.write(f" {self.tag}")
        if self.comment and self.include_comments:
            out_stream.write(f" # {self.comment}")
        indentor.lineSepAndIndent(out_stream)

    def writePostfix(self, out_stream, indentor):
        if self.explicit_end:
            indentor.lineSepAndIndent(out_stream,)
            out_stream.write("...")
        # document should end with new line:
        indentor.lineSepAndIndent(out_stream)


class Indentor(object):
    def __init__(self, indent_size) -> None:
        self.indent_size = indent_size
        self.cur_indent = 0
        self.num_extra_chars = 0
        self.item_type_stack: List = []

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
    retVal = False
    if isinstance(item, (str, int, float, complex, bool, bytes, type(None))):
        retVal = True
    elif isinstance(item, YamlDumpWrap):
        retVal = item.isScalar()
    return retVal


def alias_for_dict(pyObj, alias_indicator):
    retVal = None
    for k, v in pyObj.items():
        if k == alias_indicator:
            retVal = v
            pyObj.pop(k)
            break
    return retVal


def writeAsYaml(pyObj, out_stream=None, indentor=None, sort=False, alias_indicator=None):
    if out_stream is None:
        out_stream = sys.stdout
    if indentor is None:
        indentor = Indentor(4)
    if pyObj is None:
        out_stream.write("~")
    elif isinstance(pyObj, (list, tuple)):
        if not pyObj:
            out_stream.write("~")
        else:
            indentor.push('l')
            for item in pyObj:
                if isinstance(item, YamlDumpDocWrap):
                    indentor.push(None)  # doc should have no parent
                    writeAsYaml(item, out_stream, indentor, sort, alias_indicator)
                    indentor.pop()
                else:
                    indentor.lineSepAndIndent(out_stream)
                    indentor.write_extra_chars(out_stream, "- ")
                    indentor += 1
                    writeAsYaml(item, out_stream, indentor, sort, alias_indicator)
                    indentor -= 1
        indentor.pop()
    elif isinstance(pyObj, (dict, OrderedDict)):
        alias = alias_indicator and alias_for_dict(pyObj, alias_indicator)
        parent_item = indentor.top()
        indentor.push('m')
        if sort and not isinstance(pyObj, OrderedDict):
            theKeys = sorted(pyObj.keys())
        else:
            theKeys = list(pyObj.keys())
        if alias:
            out_stream.write(f"&{alias}")
        for item in theKeys:
            nl_before_key = (parent_item != 'l')
            if nl_before_key:
                indentor.lineSepAndIndent(out_stream)
            writeAsYaml(item, out_stream, indentor, sort, alias_indicator)
            indentor.write_extra_chars(out_stream, ":")
            if isScalar(pyObj[item]):
                indentor.write_extra_chars(out_stream, " ")
            indentor += 1
            writeAsYaml(pyObj[item], out_stream, indentor, sort, alias_indicator)
            indentor -= 1
        indentor.pop()
    elif isinstance(pyObj, YamlDumpWrap):
        pyObj.writePrefix(out_stream, indentor)
        writeAsYaml(pyObj.value, out_stream, indentor, sort or pyObj.sort_mappings, alias_indicator)
        pyObj.writePostfix(out_stream, indentor)
    else:
        if hasattr(pyObj, "repr_for_yaml"):
            writeAsYaml(pyObj.repr_for_yaml(), out_stream, indentor, sort, alias_indicator)
        else:
            if pyObj is None:
                pyObj_as_string = '~'
            else:
                pyObj_as_string = str(pyObj)
                if not pyObj_as_string: # it's a string but an empty one
                    pyObj_as_string = '""'
            out_stream.write(pyObj_as_string)
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
        import utils
        for afile in sys.argv[1:]:
            with utils.open_for_read_file_or_url(afile, config_vars=None) as open_file:
                for a_node in yaml.compose_all(open_file.fd):
                    a_node_as_tdw = nodeToYamlDumpWrap(a_node)
                    docWrap = YamlDumpDocWrap(a_node_as_tdw)
                    writeAsYaml(docWrap)
    except Exception as ex:
        import traceback
        tb = traceback.format_exc()
        print(tb)
