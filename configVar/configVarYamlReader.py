#!/usr/bin/env python3

""" ConfigVarYamlReader
"""

import sys
import re

import aYaml
from configVar import var_stack

internal_identifier_re = re.compile("""
                                    __                  # dunder here
                                    (?P<internal_identifier>\w*)
                                    __                  # dunder there
                                    """, re.VERBOSE)


class ConfigVarYamlReader(aYaml.YamlReader):
    def __init__(self, path_searcher=None, url_translator=None):
        super().__init__()
        self.path_searcher = path_searcher
        self.url_translator = url_translator
        # only when allow_reading_of_internal_vars is true, variables who's name begins and ends with "__"
        # can be read from file
        self.allow_reading_of_internal_vars = False

    def init_specific_doc_readers(self):
        aYaml.YamlReader.init_specific_doc_readers(self)
        self.specific_doc_readers["__no_tag__"] = self.read_defines
        self.specific_doc_readers["__unknown_tag__"] = self.read_defines
        self.specific_doc_readers["!define"] = self.read_defines
        self.specific_doc_readers["!define_const"] = self.read_const_defines

    def read_defines(self, a_node, *args, **kwargs):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if self.allow_reading_of_internal_vars or not internal_identifier_re.match(
                        identifier):  # do not read internal state identifiers
                    var_stack.set_var(identifier, str(contents.start_mark)).extend([item.value for item in contents])
                elif identifier == '__include__':
                    self.read_include_node(contents)

    def read_const_defines(self, a_node, *args, **kwargs):
        """ Read a !define_const sub-doc. All variables will be made const.
            Reading of internal state identifiers is allowed.
            __include__ is not allowed.
        """
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier == "__include__":
                    raise ValueError("!define_const doc cannot except __include__")
                var_stack.add_const_config_variable(identifier, "from !define_const section",
                                                    *[item.value for item in contents])

    def read_include_node(self, i_node):
        pass  # override to handle __include__ nodes


if __name__ == "__main__":
    aReader = ConfigVarYamlReader()
    aReader.read_yaml_file("/p4client/dev_saa/ProAudio/XPlatform/Apps/SAA_Juce/audio plugin host/saa_post_build.yaml")
    aYaml.writeAsYaml(var_stack, sys.stdout, sort=True)
