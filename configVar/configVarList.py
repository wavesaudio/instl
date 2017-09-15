#!/usr/bin/env python3


"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    configVarList module has but a single class ConfigVarList
"""

import os
import re
from contextlib import contextmanager
import pathlib

import utils
import aYaml
from . import configVarOne
from . import configVarParser

value_ref_re = re.compile("""
                            (?P<varref_pattern>
                                (?P<varref_marker>[$])      # $
                                \(                          # (
                                    (?P<var_name>[\w\s]+?|[\w\s(]+[\w\s)]+?)           # value
                                    (?P<varref_array>\[
                                        (?P<array_index>\d+)
                                    \])?
                                \)
                            )                         # )
                            """, re.X)
only_one_value_ref_re = re.compile("""
                            ^
                            (?P<varref_pattern>
                                (?P<varref_marker>[$])      # $
                                \(                          # (
                                    (?P<var_name>[\w\s]+?|[\w\s(]+[\w\s)]+?)           # value
                                    (?P<varref_array>\[
                                        (?P<array_index>\d+)
                                    \])?
                                \)
                            )                         # )
                            $
                            """, re.X)


class ConfigVarList(object):
    """ Keeps a list of named build config values.
        Help values resolve $() style references. """

    __resolve_stack = list()  # for preventing circular references during resolve.
    __non_freeze_counter = 0  # to force resolving even of frozen variables increment this
    variable_name_endings_to_normpath = ("_PATH", "_DIR", "_DIR_NAME", "_FILE_NAME", "_PATH__", "_DIR__", "_DIR_NAME__", "_FILE_NAME__")

    def __init__(self):
        self._ConfigVar_objs = dict()  # ConfigVar objects are kept here mapped by their name.

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
        var_names = [''.join((name, ": ", self.ResolveVarToStr(name))) for name in sorted(list(self.keys()))]
        return '\n'.join(var_names)

    def __iter__(self):
        return iter(self._ConfigVar_objs)

    def __contains__(self, var_name):
        return var_name in self._ConfigVar_objs

    def keys(self):
        return list(self._ConfigVar_objs.keys())

    def description(self, var_name):
        """ Get description for variable """
        return self[var_name].description

    def get_configVar_obj(self, var_name):
        retVal = self._ConfigVar_objs.setdefault(var_name, configVarOne.ConfigVar(var_name))
        return retVal

    def set_var(self, var_name, description=None, non_freeze=False):
        retVal = self.get_configVar_obj(var_name)
        retVal.non_freeze = non_freeze
        retVal.clear_values()
        if description is not None:
            retVal.description = description
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
                new_var.description = description

    def add_const_config_variable(self, name, description="", *values):
        """ add a const single value object """
        if name in self._ConfigVar_objs:
            if list(self._ConfigVar_objs[name]) != list(map(str, values)):
                raise Exception("Const variable {} ({}) already defined: new values: {}"\
                            ", previous values: {}".format(name, self._ConfigVar_objs[name].description,
                                                           str(values), str(list(self._ConfigVar_objs[name]))))
        else:
            addedValue = configVarOne.ConstConfigVar(name, description, *values)
            self._ConfigVar_objs[addedValue.name] = addedValue

    def duplicate_variable(self, source_name, target_name):
        source_obj = self[source_name]
        self.set_var(target_name, source_obj.description).extend(source_obj)

    def read_environment(self, vars_to_read_from_environ=None):
        """ Get values from environment. Get all values if regex is None.
            Get values matching regex otherwise """
        if vars_to_read_from_environ is None:
            for env_key, env_value in os.environ.items():
                if env_key == "":  # not sure why, sometimes I get an empty string as env variable name
                    continue
                self.set_var(env_key, "from environment").append(env_value)
        else:
            # windows environ variables are not case sensitive, but instl vars are
            if 'Win' in self.ResolveVarToList("__CURRENT_OS_NAMES__"):
                lower_case_environ = dict(zip(map(lambda z:z.lower(), os.environ.keys()), os.environ.values()))
                for env_key_to_read in vars_to_read_from_environ:
                    if env_key_to_read.lower() in lower_case_environ:
                        self.set_var(env_key_to_read, "from environment").append(lower_case_environ[env_key_to_read.lower()])
            else:
                for env_key_to_read in vars_to_read_from_environ:
                    if env_key_to_read in os.environ:
                        self.set_var(env_key_to_read, "from environment").append(os.environ[env_key_to_read])

    def repr_for_yaml(self, which_vars=None, include_comments=True, ignore_unknown_vars=False):
        retVal = dict()
        vars_list = list()
        if not which_vars:
            vars_list.extend(list(self.keys()))
        elif isinstance(which_vars, str):
            vars_list.append(which_vars)
        else:
            vars_list = which_vars
        if not hasattr(vars_list, '__iter__'):  # if which_vars is a list
            ValueError("ConfigVarList.repr_for_yaml can except string, list or None, not "+type(which_vars)+" "+str(which_vars))
        theComment = ""
        for var_name in vars_list:
            if var_name in self:
                if include_comments:
                    theComment = self[var_name].description
                var_value = self.resolve_var(var_name)
                if len(var_value) == 1:
                    var_value = var_value[0]
                retVal[var_name] = aYaml.YamlDumpWrap(var_value, comment=theComment)
            elif not ignore_unknown_vars:
                retVal[var_name] = aYaml.YamlDumpWrap(value="UNKNOWN VARIABLE", comment=var_name+" is not in variable list")
        return retVal

    def is_resolved(self, in_str):
        match = value_ref_re.search(in_str)
        retVal = match is None
        return retVal

    def unresolved_var(self, var_name, list_sep=" ", default=None):
        retVal = default
        if var_name in self:
            retVal = list_sep.join([str(val) for val in self[var_name] if val is not None])
        return retVal

    def unresolved_var_to_list(self, var_name, default=None):
        retVal = default
        if var_name in self:
            retVal = [val for val in self[var_name]]
        return retVal

    def update(self, update_dict):
        for var_name, var_value in update_dict.items():
            self.set_var(var_name).append(var_value)

    @contextmanager
    def circular_resolve_check(self, var_name):
        if var_name in self.__resolve_stack:
            raise Exception("circular resolving of variable '{}', resolve stack: {}".format(var_name, self.__resolve_stack))
        self.__resolve_stack.append(var_name)
        yield self
        self.__resolve_stack.pop()

    def ResolveStrToListWithStatistics(self, str_to_resolve):
        """ resolve a string to a list, return the list and also the number of variables and literal in the list.
            Returning these statistic will help
        """
        resolved_parts = list()
        num_literals = 0
        num_variables = 0
        for parser_retVal in configVarParser.var_parse_imp(str_to_resolve):
            if parser_retVal.literal_text:
                resolved_parts.append(parser_retVal.literal_text)
                num_literals += 1
            if parser_retVal.variable_name:
                resolved_parts.extend(self.ResolveVarWithParamsToList(parser_retVal))
                num_variables += 1
        return resolved_parts, num_literals, num_variables

    def ResolveStrToListIfSingleVar(self, str_to_resolve):
        resolved_parts, num_literals, num_variables = self.ResolveStrToListWithStatistics(str_to_resolve)
        if num_literals == 0 and num_variables == 1:
            retVal = resolved_parts
        else:
            retVal = ["".join(resolved_parts)]
        return retVal

    def ResolveStrToStr(self, str_to_resolve, list_sep=""):
        resolved_parts = self.ResolveStrToListIfSingleVar(str_to_resolve)
        resolved_str = list_sep.join(resolved_parts)
        return resolved_str

    def ResolveVarToStr(self, in_var, list_sep="", default=None):
        value_list = self.ResolveVarToList(in_var, default=[default])
        if all(x is None for x in value_list):
            return default
        else:
            retVal = list_sep.join(value_list)
            return retVal

    def ResolveVarToList(self, in_var, default=None):
        retVal = list()
        if in_var in self:
            if self.__non_freeze_counter == 0 and self[in_var].frozen_value:
                retVal.extend(value for value in self[in_var])
                return retVal
            with self.circular_resolve_check(in_var):
                for value in self[in_var]:
                    if value is None:
                        retVal.append(None)
                    else:
                        resolved_list_for_value = self.ResolveStrToListIfSingleVar(value)
                        # special handling of variables tha end with _DIR etc...
                        # see configVarOne.ConfigVar.variable_name_endings_to_normpath for full list
                        if in_var.endswith(self.variable_name_endings_to_normpath):
                            # python 3.6 warning: pathlib.Path.resolve() works differently in 3.6
                            # resolving file name to current directory
                            for unresolved_path in resolved_list_for_value:
                                try:  # if it's a real path this will get the absolute path
                                    resolved_path = pathlib.Path(unresolved_path).resolve()
                                    resolved_path_str = str(resolved_path)
                                    retVal.append(resolved_path_str)
                                except:  # not really path? path does not exist? no matter,
                                    # str(PurePath) should change the path separator to local value
                                    pure_path = str(pathlib.PurePath(unresolved_path))
                                    retVal.append(pure_path)
                        else:
                            retVal.extend(resolved_list_for_value)
            if self.__non_freeze_counter == 0 and self[in_var].freeze_values_on_first_resolve:
                self[in_var].set_frozen_values(*retVal)
        else:
            if utils.is_iterable_but_not_str(default):
                retVal = default
            else:
                raise ValueError("Variable {} was not found and default given {} is not a list".format(in_var, default))
        return retVal

    def ResolveListToList(self, strs_to_resolve_list, default=None):
        retVal = list()
        for a_str in strs_to_resolve_list:
            retVal.extend(self.ResolveStrToListIfSingleVar(a_str))
        return retVal

    def ResolveVarWithParamsToList(self, parser_retVal):
        with self.push_scope_context():
            evaluated_params = {}
            if parser_retVal.positional_params:
                for i_param in range(len(parser_retVal.positional_params)):
                    # create __1__ positional params
                    pos_param_name = "".join(("__", parser_retVal.variable_name, "_", str(i_param+1), "__"))
                    evaluated_params[pos_param_name] = parser_retVal.positional_params[i_param]
            if parser_retVal.key_word_params:
                evaluated_params.update(parser_retVal.key_word_params)
            if evaluated_params:
                self.__non_freeze_counter += 1
                self.update(evaluated_params)
            retVal = self.ResolveVarToList(parser_retVal.variable_name, [parser_retVal.variable_str])
            if evaluated_params:
                self.__non_freeze_counter -= 1
            array_range = (0, None)
            if parser_retVal.array_index_int is not None:
                if parser_retVal.array_index_int < 0:
                    # convert negative indexes to positive because a[-1:0] returns an empty list
                    normalized_index = len(retVal) + parser_retVal.array_index_int
                    array_range = (normalized_index, normalized_index+1)
                else:
                    array_range = (parser_retVal.array_index_int, parser_retVal.array_index_int + 1)
        return retVal[array_range[0]:array_range[1]]

    def freeze_vars_on_first_resolve(self):
        for var_obj in self._ConfigVar_objs.values():
            var_obj.freeze_values_on_first_resolve = True

    def ResolveVarToBool(self, in_var, default=False):
        retVal = default
        try:
            resolved_var = self.ResolveVarToStr(in_var)
            retVal = utils.str_to_bool(resolved_var, default)
        except:
            pass
        return retVal
