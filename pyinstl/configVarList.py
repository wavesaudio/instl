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

from pyinstl import configVar
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


class ConfigVarList(object):
    """ Keeps a list of named build config values.
        Help values resolve $() style references. """
    __slots__ = ("_ConfigVar_objs", "__resolve_stack")

    def __init__(self):
        self._ConfigVar_objs = dict() # ConfigVar objects are kept here mapped by their name.
        self.__resolve_stack = list() # for preventing circular references during resolve.

    def __len__(self):
        """ return number of ConfigVars """
        return len(self._ConfigVar_objs)

    def __getitem__(self, var_name):
        """ return a ConfigVar object by it's name """
        return self._ConfigVar_objs[var_name]

    def __delitem__(self, key):
        """ remove a ConfigVar object by it's name """
        if key in self._ConfigVar_objs:
            del self._ConfigVar_objs[key]

    def defined(self, var_name):
        retVal = False
        try:
            var_obj = self[var_name]
            retVal = any(var_obj)
        except KeyError:
            pass
        return retVal

    def __str__(self):
        var_names = [''.join((name, ": ", self.resolve_var(name))) for name in self.keys()]
        return '\n'.join(var_names)

    def __iter__(self):
        return iter(self._ConfigVar_objs)

    def __reversed__(self):
        return reversed(self._ConfigVar_objs)

    def __contains__(self, var_name):
        return var_name in self._ConfigVar_objs

    def keys(self):
        return self._ConfigVar_objs.keys()

    def description(self, var_name):
        """ Get description for variable """
        return self[var_name].description()

    def get_configVar_obj(self, var_name):
        retVal = self._ConfigVar_objs.setdefault(var_name, configVar.ConfigVar(var_name))
        return retVal

    def set_var(self, var_name, description=None):
        retVal = self.get_configVar_obj(var_name)
        retVal.clear_values()
        if description is not None:
            retVal.set_description(description)
        return retVal

    def set_value_if_var_does_not_exist(self, var_name, var_value, description=None):
        """ If variable does not exist it will be created and assigned the new value.
            Otherwise variable will remain as is. Good for setting defaults to variables
            that were not read from file.
        """
        if var_name not in self._ConfigVar_objs:
            new_var = self.get_configVar_obj(var_name)
            new_var.append(var_value)
            if description is not None:
                new_var.set_description(description)

    def add_const_config_variable(self, name, description="", *values):
        """ add a const single value object """
        if name in self._ConfigVar_objs:
            if list(self._ConfigVar_objs[name]) != list(values):
                raise Exception("Const variable {} ({}) already defined: new values: {}, previous values: {}".format(name, self._ConfigVar_objs[name].description(), str(values), str(list(self._ConfigVar_objs[name]))))
            #else:
            #    print("Const variable {} ({}) already defined, with same value: {}".format(name, self._ConfigVar_objs[name].description(), str(values)))
        else:
            addedValue = configVar.ConstConfigVar(name, description, *values)
            self._ConfigVar_objs[addedValue.name()] = addedValue
            logging.debug("... %s: %s", name, ", ".join(map(str, values)))

    def duplicate_variable(self, source_name, target_name):
        source_obj = self[source_name]
        self.set_var(target_name, source_obj.description()).extend(source_obj)

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
                var_value = self.resolve_var(var_name)
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

    def resolve(self, str_to_resolve, list_sep=" ", default=None):
        """ Resolve a string, possibly with $() style references.
            For Variables that hold more than one value, the values are connected with list_sep
            which defaults to a single space.
            None existant variables are left as is if default==None, otherwise valie of default is inserted
        """
        resolved_str = str_to_resolve
        search_start_pos = 0
        while True:
            match = value_ref_re.search(resolved_str, search_start_pos)
            if not match:
                break
            var_name = match.group('var_name')
            if var_name in self:
                if var_name in self.__resolve_stack:
                    raise Exception("circular resolving of '$({})', resolve stack: {}".format(var_name, self.__resolve_stack))
                self.__resolve_stack.append(var_name)
                var_joint_values = list_sep.join([val for val in self[var_name]])
                replacement = self.resolve(var_joint_values, list_sep)
                resolved_str = resolved_str.replace(match.group('varref_pattern'), replacement)
                self.__resolve_stack.pop()
            else:
                # if var_name was not found skip it on the next search
                if default is None:
                    search_start_pos = match.end('varref_pattern')
                else:
                    resolved_str = resolved_str.replace(match.group('varref_pattern'), default)
        return resolved_str

    def resolve_to_list(self, str_to_resolve, list_sep=" ", default=None):
        """ Resolve a string, possibly with $() style references.
            If the string is a single reference to a variable, a list of resolved values is returned.
            If the values themselves are a single reference to a variable, their own values extend teh list
            list_sep is used to combine values which are not part of single reference to a variable.
            otherwise if the string is NOT a single reference to a variable, a list with single value is returned.
         """
        resolved_list = list()
        match = only_one_value_ref_re.search(str_to_resolve)
        if match:
            var_name = match.group('var_name')
            if var_name in self.__resolve_stack:
                raise Exception("circular resolving of '$({})', resolve stack: {}".format(var_name, self.__resolve_stack))
            self.__resolve_stack.append(var_name)
            if var_name in self:
                for value in self[var_name]:
                    resolved_list.extend(self.resolve_to_list(value, list_sep))
            else:
                if default is None:
                    resolved_list.append(str_to_resolve)
                else:
                    resolved_list.append(default)
            self.__resolve_stack.pop()
        else:
            resolved_list.append(self.resolve(str_to_resolve, list_sep))
        return resolved_list

    def resolve_var(self, var_name, list_sep=" ", default=""):
        retVal = self.resolve( "".join( ("$(", var_name, ")") ))
        return retVal

    def resolve_var_to_list(self, var_name, list_sep=" ", default=""):
        retVal = self.resolve_to_list( "".join( ("$(", var_name, ")") ))
        return retVal

# This is the global variable list serving all parts of instl
var_list = ConfigVarList()
