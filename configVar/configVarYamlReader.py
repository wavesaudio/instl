#!/usr/bin/env python3.9

""" ConfigVarYamlReader
"""

import os  # do not remove, might be used in eval
import sys # do not remove, might be used in eval
import re
from contextlib import contextmanager
import logging
log = logging.getLogger()

import aYaml

internal_identifier_re = re.compile("""
                                    __                  # dunder here
                                    (?P<internal_identifier>\w*)
                                    __                  # dunder there
                                    """, re.VERBOSE)

# regex to find conditionals e.g. __ifndef__(S3_BUCKET_NAME)
conditional_re = re.compile(r"""__if(?P<if_type>.*)__\s*\((?P<condition>.+)\)""")


def eval_conditional(conditional_text, config_vars):
    """ read __if...(conditional) and return True is the conditional is True, False otherwise"""
    retVal = False
    match = conditional_re.match(conditional_text)
    if match:
        condition = match['condition']
        if_type = match['if_type']
        if if_type == "def":  # __ifdef__: if configVar is defined
            if condition in config_vars:
                retVal = True
        elif if_type == "ndef":  # __ifndef__: if configVar is not defined
            if condition not in config_vars:
                retVal = True
        elif if_type == "":  # "__if__: eval the condition
            resolved_condition = config_vars.resolve_str(condition)
            condition_result = eval(resolved_condition, globals(), locals())
            if condition_result:
                retVal = True
    else:
        log.warning(f"unknown conditional {conditional_text}")
    return retVal


class ConfigVarYamlReader(aYaml.YamlReader):
    def __init__(self, config_vars, path_searcher=None, url_translator=None) -> None:
        super().__init__(config_vars)
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
        self.specific_doc_readers["__unknown_tag__"] = self.do_nothing_node_reader
        self.specific_doc_readers["!define"] = self.read_defines
        # !define_const is deprecated and read as non-const
        self.specific_doc_readers["!define_const"] = self.read_defines
        # !define_const is deprecated - use __ifndef__ instead
        self.specific_doc_readers["!define_if_not_exist"] = self.read_defines_if_not_exist

    def read_defines(self, a_node, *args, **kwargs):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                with kwargs['node-stack'](contents):
                    if identifier.startswith("__if"):  # __if__, __ifdef__, __ifndef__
                        self.read_conditional_node(identifier, contents, *args, **kwargs)
                    elif identifier == '__include__':
                        self.read_include_node(contents, *args, **kwargs)
                    elif identifier == "__include_if_exist__":
                        kwargs.update({'ignore_if_not_exist': True})
                        self.read_include_node(contents, *args, **kwargs)
                    elif identifier == "__environment__":
                        contents_list = [c.value for c in contents]
                        self.config_vars.read_environment(contents_list)
                    elif self._allow_reading_of_internal_vars or not internal_identifier_re.match(
                            identifier):  # do not read internal state identifiers
                        values = self.read_values_for_config_var(contents, identifier, **kwargs)
                        the_config_var = self.config_vars.setdefault(key=identifier, default=None, callback_when_value_is_set=None)
                        if contents.tag != "!+=":
                            the_config_var.clear()
                        the_config_var.extend(values)

    def read_defines_if_not_exist(self, a_node, *args, **kwargs):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node.items():
                with kwargs['node-stack'](contents):
                    if identifier in ("__include__", "__include_if_exist__"):
                        raise ValueError("!define_if_not_exist doc cannot except __include__ and __include_if_exist__")
                    if self._allow_reading_of_internal_vars or not internal_identifier_re.match(identifier):  # do not read internal state identifiers
                        if identifier not in self.config_vars:
                            values = self.read_values_for_config_var(contents, identifier, **kwargs)
                            self.config_vars[identifier] = values

    def read_values_for_config_var(self, _contents, _identifier, **kwargs):
        values = list()

        for item in _contents:
            with kwargs['node-stack'](item):
                if isinstance(item.value, (str, int, type(None))):
                    values.append(item.value)
                else:
                    raise TypeError(f"Values for configVar {_identifier} should be of type str or int not {type(item.value)}")
        return values

    def read_include_node(self, i_node, *args, **kwargs):
        pass  # override to handle __include__, __include_if_exist__ nodes

    def read_conditional_node(self, identifier, contents, *args, **kwargs):
        if eval_conditional(identifier, self.config_vars):
            self.read_defines(contents, **kwargs)


def smart_resolve_yaml(a_node, config_vars):
    """ read yaml node and resolve $() references
        the main shtick is that a $() reference in a yaml sequence that itself resolves into a list will
        extend the sequence. See doc string for class ResolveConfigVarsInYamlFile for an example
        Note: tags that begin with ! (such as !file, !dir_cont) are preserved
    """
    tag = getattr(a_node, "tag", "")
    if tag and not tag.startswith("!"):
        tag = ""
    if isinstance(a_node, str):
        retVal = aYaml.YamlDumpWrap(config_vars.resolve_str(a_node))
    elif a_node.isScalar():
        if a_node.value:
            retVal = aYaml.YamlDumpWrap(config_vars.resolve_str(a_node.value), tag=tag)
        else:
            retVal = aYaml.YamlDumpWrap(a_node.value, tag=tag)
    elif a_node.isSequence():
        seq = list()
        for sub_node in a_node:
            if sub_node.isScalar():
                sub_item_values = config_vars.resolve_str_to_list(sub_node.value)
                if len(sub_item_values) == 1:  # did not resolve to multiple values
                    seq.append(smart_resolve_yaml(sub_node, config_vars))
                else:
                    seq.extend([smart_resolve_yaml(sub_item_value, config_vars) for sub_item_value in sub_item_values])
            else:
                seq.append(smart_resolve_yaml(sub_node, config_vars))
        retVal = aYaml.YamlDumpWrap(seq, tag=tag)
    elif a_node.isMapping():
        retVal = {smart_resolve_yaml(key, config_vars): smart_resolve_yaml(mapped_node, config_vars) for key, mapped_node in a_node.items()}
    return retVal
