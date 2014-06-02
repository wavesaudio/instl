#!/usr/bin/env python2.7
from __future__ import print_function

"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    configVarList module has but a single class ConfigVarList
    import pyinstl.configVarList
"""

import os
import sys
import re
import logging

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))

from pyinstl import configVarList
from aYaml.augmentedYaml import YamlDumpWrap, YamlDumpDocWrap


value_ref_re = re.compile("""(
                            (?P<varref_pattern>
                            (?P<varref_marker>[$])      # $
                            \(                          # (
                            (?P<var_name>[\w\s]+?|[\w\s(]+[\w\s)]+?)           # value
                            \))                         # )
                            )""", re.X)
only_one_value_ref_re = re.compile("""
                            ^
                            (?P<varref_pattern>
                            (?P<varref_marker>[$])      # $
                            \(                          # (
                            (?P<var_name>[\w\s]+?|[\w\s(]+[\w\s)]+?)           # value
                            \))                         # )
                            $
                            """, re.X)


class ConfigVarStack(object):
    """ Keeps a list of named build config values.
        Help values resolve $() style references. """
    __slots__ = ("_ConfigVarList_objs", "__resolve_stack")

    def __init__(self):
        self._ConfigVarList_objs = [configVarList.ConfigVarList()] # ConfigVarLIsts objects are kept stacked.
        self.__resolve_stack = list() # for preventing circular references during resolve.

    #def __len__(self):
    #    """ return number of ConfigVars """
    #    return len(self._ConfigVarList_objs)

    # moonshine (::o>)
    def __getitem__(self, var_name):
        """ return a ConfigVar object by it's name """
        for level_var_list in reversed(self._ConfigVarList_objs):
            if var_name in level_var_list:
                return level_var_list[var_name]
        raise KeyError

    #def __delitem__(self, key):
    #    """ remove a ConfigVar object by it's name """
    #    if key in self._ConfigVarList_objs:
    #        del self._ConfigVarList_objs[key]

    # moonshine (::o>)
    def get_list(self, var_name, default=tuple()):
        """ get a list of values held by a ConfigVar. $() style references are resolved.
        To get unresolved values use get_configVar_obj() to get the ConfigVar object.
        If var_name is not found default will be returned, unless default is None,
        in which case KeyError will be raised.
        """
        try:
            configVar = self[var_name]
            retVal = resolve_list(
                configVar, self.resolve_value_callback)
            return retVal
        except KeyError:
            if KeyError is not None:
                return default
            raise

    # moonshine (::o>)
    def get_str(self, var_name, default="", sep=" "):
        retVal = default
        try:
            resolved_list = self.get_list(var_name, default=None) # default=None will raise KeyError if var_name was not found.
            retVal = sep.join(resolved_list)
        except KeyError:
            pass
        return retVal

    # moonshine (::o>)
    def defined(self, var_name):
        retVal = False
        try:
            var_obj = self[var_name]
            retVal = any(var_obj)
        except KeyError:
            pass
        return retVal

    # moonshine ?
    def __str__(self):
        var_names = [''.join((name, ": ", self.get_str(name))) for name in self.keys()]
        return '\n'.join(var_names)

    # moonshine iter lists or iter ConfigVar objects?
    def __iter__(self):
        return iter(self._ConfigVarList_objs)

    # moonshine revesed lists or reversed ConfigVar objects?
    def __reversed__(self):
        return reversed(self._ConfigVarList_objs)

    # moonshine (::o>)
    def __contains__(self, var_name):
        for level_var_list in self._ConfigVarList_objs:
            if var_name in level_var_list:
                return True
        return False

    # moonshine (::o>)
    def keys(self):
        unique_list the_keys;
        for a_var_list in reversed(self._ConfigVar_objs):
            the_keys.extend(a_var_list.keys())
        return list(the_keys)

    # moonshine (::o>)
    def description(self, var_name):
        """ Get description for variable """
        return self[var_name].description()

    # moonshine (::o>)
    def get_configVar_obj(self, var_name):
        retVal = None
        try:
            retVal = self[var_name]
        except KeyError:
            retVal = self._ConfigVarList_objs[-1].get_configVar_obj(var_name)
        return retVal

    # moonshine (::o>)
    def set_var(self, var_name, description=None):
        retVal = self.get_configVar_obj(var_name)
        retVal.clear_values()
        if description is not None:
            retVal.set_description(description)
        return retVal

    # moonshine (::o>)
    def set_value_if_var_does_not_exist(self, var_name, var_value, description=None):
        """ If variable does not exist it will be created and assigned the new value.
            Otherwise variable will remain as is. Good for setting defaults to variables
            that were not read from file.
        """
        try:
            var_obj = self[var_name]
        except KeyError:
            new_var = self._ConfigVarList_objs[-1].get_configVar_obj(var_name)
            new_var.append(var_value)
            if description is not None:
                new_var.set_description(description)

    # moonshine (::o>)
    def add_const_config_variable(self, name, description="", *values):
        """ add a const single value object """
        try:
            var_obj = self[var_name]
            if list(var_obj) != list(values):
                raise Exception("Const variable {} ({}) already defined: new values: {}, previous values: {}".format(name, self._ConfigVarList_objs[name].description(), str(values), str(list(self._ConfigVarList_objs[name]))))
            #else:
            #    print("Const variable {} ({}) already defined, with same value: {}".format(name, self._ConfigVarList_objs[name].description(), str(values)))
        except KeyError:
            addedValue = configVar.ConstConfigVar(name, description, *values)
            self._ConfigVarList_objs[-1][addedValue.name()] = addedValue
            logging.debug("... %s: %s", name, ", ".join(map(str, values)))

    # moonshine (::o>)
    def duplicate_variable(self, source_name, target_name):
        source_obj = self[source_name]
        self.set_var(target_name, source_obj.description()).extend(source_obj)

    # moonshine (::o>)
    def read_environment(self):
        """ Get values from environment """
        for env in os.environ:
            if env == "":  # not sure why I get an empty string
                continue
            self.set_var(env, "from environment").append(os.environ[env])

    def repr_for_yaml(self, which_vars=None, include_comments=True):
        retVal = dict()
        vars_list = list()
        if not which_vars:
            vars_list.extend(self.keys())
        elif isinstance(which_vars, basestring):
            vars_list.append(which_vars)
        else:
            vars_list = which_vars
        if not hasattr(vars_list, '__iter__'):  # if which_vars is a list
            ValueError("ConfigVarList.repr_for_yaml can except string, list or None, not "+type(which_vars)+" "+str(which_vars))
        theComment = ""
        for var_name in vars_list:
            if var_name in self:
                if include_comments:
                    theComment = self[var_name].description()
                var_value = self.get_list(var_name)
                if len(var_value) == 1:
                    var_value = var_value[0]
                retVal[var_name] = YamlDumpWrap(var_value, comment=theComment)
            else:
                retVal[var_name] = YamlDumpWrap(value="UNKNOWN VARIABLE", comment=var_name+" is not in variable list")
        return retVal

    def is_resolved(self, in_str):
        match = value_ref_re.search(in_str)
        retVal = match is None
        return retVal

    # moonshine (::o>)
    def resolve_value_callback(self, value_to_resolve):
        """ callback for configVar.ConfigVar.Resolve. value_to_resolve should
            be a single value name.
            If value_to_resolve is found and has no value, empty list is returned.
            If value_to_resolve is not found, None is returned.
        """
        retVal = None
        try:
            var_obj = self[value_to_resolve]
            if value_to_resolve in self.__resolve_stack:
                raise Exception("circular resolving of {}".format(value_to_resolve))

            var_obj.resolved_num += 1
            self.__resolve_stack.append(value_to_resolve)
            retVal = resolve_list(
                var_obj,
                self.resolve_value_callback)
            self.__resolve_stack.pop()
        except KeyError:
            pass # return retVal = None
        return retVal

def replace_all_from_dict(in_text, *in_replace_only_these, **in_replacement_dic):
    """ replace all occurrences of the values in in_replace_only_these
        with the values in in_replacement_dic. If in_replace_only_these is empty
        use in_replacement_dic.keys() as the list of values to replace."""
    retVal = in_text
    if not in_replace_only_these:
        # use the keys of of the replacement_dic as replace_only_these
        in_replace_only_these = list(in_replacement_dic.keys())[:]
    # sort the list by size (longer first) so longer string will be replace before their shorter sub strings
    for look_for in sorted(in_replace_only_these, key=lambda s: -len(s)):
        retVal = retVal.replace(look_for, in_replacement_dic[look_for])
    return retVal


def resolve_list(needsResolveList, resolve_callback):
    """ resolve a list, possibly with $() style references with the help of a resolving function.
        needsResolveList could be of type that emulates list, specifically configVar.ConfigVar.
    """
    replace_dic = dict()
    resolved_list = list()
    need_to_resolve_again = False
    for valueText in needsResolveList:
        # if the value is only a single $() reference, no quotes,
        # the resolved values are extending the resolved list
        single_value_ref_match = only_one_value_ref_re.match(valueText)
        if single_value_ref_match:
            var_name = single_value_ref_match.group('var_name')
            new_values = resolve_callback(var_name)
            if new_values is not None:
                resolved_list.extend(new_values)
                need_to_resolve_again = True
            else: # var was not found, leave $() reference as is
                resolved_list.extend( (valueText, ) )
            continue
        # if the value is more than a single $() reference,
        # the resolved values are joined and appended to the resolved list
        for value_ref_match in value_ref_re.finditer(valueText):
            # group 'varref_pattern' is the full $(X), group 'var_name' is the X
            replace_ref, value_ref = value_ref_match.group('varref_pattern', 'var_name')
            if replace_ref not in replace_dic:
                resolved_vals = resolve_callback(value_ref)
                if resolved_vals is not None:
                    replace_dic[replace_ref] = " ".join(resolved_vals)
                    need_to_resolve_again = True
        value_text_resolved = replace_all_from_dict(valueText, **replace_dic)
        resolved_list.append(value_text_resolved)
    if need_to_resolve_again:  # another resolve round until no ref-in-ref are left
        resolved_list = resolve_list(resolved_list, resolve_callback)
    return tuple(resolved_list)

# This is the global variable list serving all parts of instl
var_stack = ConfigVarStack()
