#!/usr/bin/env python3.6

""" ConfigVarYamlReader
"""

import sys
import re
from contextlib import contextmanager

import aYaml
from configVar import config_vars

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
        self._allow_reading_of_internal_vars = False

    @contextmanager
    def allow_reading_of_internal_vars(self, allow=True):
        previous_allow_reading_of_internal_vars = self._allow_reading_of_internal_vars
        self._allow_reading_of_internal_vars = allow
        yield
        self._allow_reading_of_internal_vars = previous_allow_reading_of_internal_vars

    def init_specific_doc_readers(self):
        aYaml.YamlReader.init_specific_doc_readers(self)
        self.specific_doc_readers["__no_tag__"] = self.read_defines
        self.specific_doc_readers["__unknown_tag__"] = self.read_defines
        self.specific_doc_readers["!define"] = self.read_defines
        # !define_const is deprecated and read as non-const
        self.specific_doc_readers["!define_const"] = self.read_defines
        # !define_const is deprecated - use __ifndef__ instead
        self.specific_doc_readers["!define_if_not_exist"] = self.read_defines_if_not_exist

    def read_defines(self, a_node, *args, **kwargs):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier.startswith("__if"):  # __if__, __ifdef__, __ifndef__
                    self.read_conditional_node(identifier, contents, *args, **kwargs)
                elif identifier == '__include__':
                    self.read_include_node(contents, *args, **kwargs)
                elif identifier == "__include_if_exist__":
                    kwargs.update({'ignore_if_not_exist': True})
                    self.read_include_node(contents, *args, **kwargs)
                elif identifier == "__environment__":
                    contents_list = [c.value for c in contents]
                    config_vars.read_environment(contents_list)
                elif self._allow_reading_of_internal_vars or not internal_identifier_re.match(
                        identifier):  # do not read internal state identifiers
                    config_vars[identifier] = [item.value for item in contents]
                    #if contents.tag == '!non_freeze':
                    #    new_var.non_freeze = True

    def read_defines_if_not_exist(self, a_node, *args, **kwargs):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier in ("__include__", "__include_if_exist__"):
                    raise ValueError("!define_if_not_exist doc cannot except __include__ and __include_if_exist__")
                if self._allow_reading_of_internal_vars or not internal_identifier_re.match(identifier):  # do not read internal state identifiers
                    if identifier not in config_vars:
                        config_vars[identifier] = [item.value for item in contents]

    def read_include_node(self, i_node, *args, **kwargs):
        pass  # override to handle __include__, __include_if_exist__ nodes

    # regex to find conditionals e.g. __ifndef__(S3_BUCKET_NAME)
    conditional_re = re.compile("""__if(?P<if_type>.*)__\s*\((?P<condition>.+)\)""")

    def read_conditional_node(self, identifier, contents, *args, **kwargs):
        match = self.conditional_re.match(identifier)
        if match:
            condition = match['condition']
            if_type = match['if_type']
            if if_type == "def":     # __ifdef__: if configVar is defined
                if condition in config_vars:
                    self.read_defines(contents)
            elif if_type == "ndef":  # __ifndef__: if configVar is not defined
                if condition not in config_vars:
                    self.read_defines(contents)
            elif if_type == "":      # "__if__: eval the condition
                resolved_condition = config_vars.resolve_str(condition)
                condition_result = eval(resolved_condition)
                if condition_result:
                    self.read_defines(contents)
        else:
            print(f"unknown conditional {identifier}")

