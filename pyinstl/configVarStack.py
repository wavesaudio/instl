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

from pyinstl.utils import *
from pyinstl import configVarList
from aYaml.augmentedYaml import YamlDumpWrap, YamlDumpDocWrap

class ConfigVarStack(configVarList.ConfigVarList):
    """ Keeps a list of named build config values.
        Help values resolve $() style references. """

    def __init__(self):
        super(ConfigVarStack, self).__init__()
        self._ConfigVarList_objs = [configVarList.ConfigVarList()] # ConfigVarLIsts objects are kept stacked.

    #def __len__(self):
    #    """ return number of ConfigVars """
    #    return len(self._ConfigVarList_objs)

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

    def __iter__(self):
        return iter(self.keys())

    def __reversed__(self):
        return reversed(self.keys())

    def __contains__(self, var_name):
        for level_var_list in self._ConfigVarList_objs:
            if var_name in level_var_list:
                return True
        return False

    def keys(self):
        the_keys = unique_list()
        for a_var_list in reversed(self._ConfigVarList_objs):
            the_keys.extend(a_var_list.keys())
        return list(the_keys)

    def get_configVar_obj(self, var_name):
        retVal = None
        try:
            retVal = self[var_name]
        except KeyError:
            retVal = self._ConfigVarList_objs[-1].get_configVar_obj(var_name)
        return retVal

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

    def add_const_config_variable(self, var_name, description="", *values):
        """ add a const single value object """
        try:
            var_obj = self[var_name]
            if list(var_obj) != list(values):
                raise Exception("Const variable {} ({}) already defined: new values: {}, previous values: {}".format(name, self._ConfigVarList_objs[name].description(), str(values), str(list(self._ConfigVarList_objs[name]))))
            #else:
            #    print("Const variable {} ({}) already defined, with same value: {}".format(name, self._ConfigVarList_objs[name].description(), str(values)))
        except KeyError:
            self._ConfigVarList_objs[-1].add_const_config_variable(var_name, description, *values)

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

    def push_scope(self, scope=None):
        if scope is None:
            scope = configVarList.ConfigVarList()
        if type(scope) is not configVarList.ConfigVarList:
            raise TypeError("scope must be of type ConfigVarList")
        self._ConfigVarList_objs.append(scope)

    def pop_scope(self):
        self._ConfigVarList_objs.pop()


# This is the global variable list serving all parts of instl
var_stack = ConfigVarStack()
