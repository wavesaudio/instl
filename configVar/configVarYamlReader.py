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
        self.specific_doc_readers["!define_if_not_exist"] = self.read_defines_if_not_exist

    def read_defines(self, a_node, *args, **kwargs):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier.startswith("__if"):
                    self.read_conditional_node(identifier, contents, *args, **kwargs)
                elif identifier == '__include__':
                    self.read_include_node(contents, *args, **kwargs)
                elif identifier == "__include_if_exist__":
                    kwargs.update({'ignore_if_not_exist': True})
                    self.read_include_node(contents, *args, **kwargs)
                elif identifier == "__environment__":
                    contents_list = [c.value for c in contents]
                    var_stack.read_environment(contents_list)
                elif self.allow_reading_of_internal_vars or not internal_identifier_re.match(
                        identifier):  # do not read internal state identifiers
                    new_var = var_stack.set_var(identifier, str(contents.start_mark))
                    if contents.tag == '!non_freeze':
                        new_var.non_freeze = True
                    new_var.extend([item.value for item in contents])

    def read_const_defines(self, a_node, *args, **kwargs):
        """ Read a !define_const sub-doc. All variables will be made const.
            Reading of internal state identifiers is allowed.
            __include__ is not allowed.
        """
        del args, kwargs
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier in ("__include__", "__include_if_exist__"):
                    raise ValueError("!define_const doc cannot except __include__ and __include_if_exist__")
                var_stack.add_const_config_variable(identifier, "from !define_const section",
                                                    *[item.value for item in contents])

    def read_defines_if_not_exist(self, a_node, *args, **kwargs):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                if identifier in ("__include__", "__include_if_exist__"):
                    raise ValueError("!define_if_not_exist doc cannot except __include__ and __include_if_exist__")
                if self.allow_reading_of_internal_vars or not internal_identifier_re.match(identifier):  # do not read internal state identifiers
                    if identifier not in var_stack:
                        var_stack.set_var(identifier, str(contents.start_mark)).extend([item.value for item in contents])

    def read_include_node(self, i_node, *args, **kwargs):
        pass  # override to handle __include__, __include_if_exist__ nodes

    # regex to find conditinals e.g. __ifndef__(S3_BUCKET_NAME)
    conditional_re = re.compile("""__if(?P<if_type>.*)__\s*\((?P<condition>.+)\)""")

    def read_conditional_node(self, identifier, contents, *args, **kwargs):
        match = self.conditional_re.match(identifier)
        if match:
            condition = match.group('condition')
            if_type = match.group('if_type')
            if if_type == "def":     # __ifdef__: if configVar is defined
                if condition in var_stack:
                    self.read_defines(contents)
            elif if_type == "ndef":  # __ifndef__: if configVar is not defined
                if condition not in var_stack:
                    self.read_defines(contents)
            elif if_type == "":      # "__if__: eval the condition
                resolved_condition = var_stack.ResolveStrToStr(condition)
                condition_result = eval(resolved_condition)
                if condition_result:
                    self.read_defines(contents)
        else:
            print("unknown conditional {}".format(identifier))


if __name__ == "__main__":
    aReader = ConfigVarYamlReader()
    aReader.read_yaml_file("/p4client/dev_saa/ProAudio/XPlatform/Apps/SAA_Juce/audio plugin host/saa_post_build.yaml")
    aYaml.writeAsYaml(var_stack, sys.stdout, sort=True)
