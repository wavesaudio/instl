#!/usr/bin/env python3


"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    configVarList module has but a single class ConfigVarList
    import pyinstl.configVarList
"""

import os
import ast
import re
from contextlib import contextmanager

import utils
import aYaml
from . import configVarOne
from . import configVarParser

value_ref_re = re.compile("""(
                            (?P<varref_pattern>
                                (?P<varref_marker>[$])      # $
                                \(                          # (
                                    (?P<var_name>[\w\s]+?|[\w\s(]+[\w\s)]+?)           # value
                                    (?P<varref_array>\[
                                        (?P<array_index>\d+)
                                    \])?
                                \)
                            )                         # )
                            )""", re.X)
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

    __resolve_stack = list() # for preventing circular references during resolve.

    def __init__(self):
        self._ConfigVar_objs = dict() # ConfigVar objects are kept here mapped by their name.

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
        var_names = [''.join((name, ": ", self.resolve_var(name))) for name in list(self.keys())]
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

    def set_var(self, var_name, description=None):
        retVal = self.get_configVar_obj(var_name)
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

    def read_environment(self, regex=None):
        """ Get values from environment. Get all values if regex is None.
            Get values matching regex otherwise """
        if regex is None:
            for env_key, env_value in os.environ.items():
                if env_key == "":  # not sure why, sometimes I get an empty string as env variable name
                    continue
                self.set_var(env_key, "from environment").append(env_value)
        else:
            for env_key, env_value in os.environ.items():
                if re.match(regex, env_key):
                    self.set_var(env_key, "from environment").append(env_value)

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

    def resolve_deprecated(self, str_to_resolve, list_sep=" ", default=None, raise_on_fail=False):
        """ Resolve a string, possibly with $() style references.
            For Variables that hold more than one value, the values are connected with list_sep
            which defaults to a single space.
            None existent variables are left as is if default==None, otherwise value of default is inserted
        """
        resolved_str = str_to_resolve
        try:
            search_start_pos = 0
            #print("resolving:", str_to_resolve)
            while True:
                match = value_ref_re.search(resolved_str, search_start_pos)
                if not match:
                    break
                replacement = default
                var_name = match.group('var_name')
                if var_name in self:
                    if var_name in self.__resolve_stack:
                        raise Exception("circular resolving of '$({})', resolve stack: {}".format(var_name, self.__resolve_stack))
                    self.__resolve_stack.append(var_name)
                    if match.group('varref_array'):
                        array_index = int(match.group('array_index'))
                        if array_index < len(self[var_name]):
                            replacement = self[var_name][array_index]
                    else:
                        var_joint_values = list_sep.join([val for val in self[var_name] if val])
                        replacement = self.resolve(var_joint_values, list_sep)

                    self.__resolve_stack.pop()

                # if var_name was not found skip it on the next search
                if replacement is None:
                    search_start_pos = match.end('varref_pattern')
                else:
                    resolved_str = resolved_str.replace(match.group('varref_pattern'), replacement)
                #print("    ", resolved_str)
        except TypeError:
            print("TypeError while resolving", str_to_resolve)
            if raise_on_fail:
                raise
        if raise_on_fail and not self.is_resolved(resolved_str):
            raise ValueError("Cannot fully resolve "+str_to_resolve+ ": "+resolved_str)

        testRetVal = self.ResolveStrToStr(str_to_resolve, list_sep=list_sep)
        if resolved_str != testRetVal:
            print(str_to_resolve, resolved_str, testRetVal)
            raise ValueError(str_to_resolve, resolved_str, testRetVal)
        return resolved_str

    def resolve_to_list_deprecated(self, str_to_resolve, list_sep=" ", default=None):
        """ Resolve a string, possibly with $() style references.
            If the string is a single reference to a variable, a list of resolved values is returned.
            If the values themselves are a single reference to a variable, their own values extend the list
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
                    if value is None:
                        resolved_list.append(None)
                    else:
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

    def resolve_var_deprecated(self, var_name, list_sep=" ", default=""):
        retVal = self.resolve( "".join( ("$(", var_name, ")") ))
        return retVal

    def resolve_var_to_list_deprecated(self, var_name, list_sep=" ", default=""):
        retVal = self.resolve_to_list( "".join( ("$(", var_name, ")") ))
        return retVal

    def resolve_var_to_list_if_exists_deprecated(self, var_name, list_sep=" ", default=""):
        retVal = []
        if var_name in self:
            var_reference = "".join( ("$(", var_name, ")") )
            retVal = self.resolve_to_list(var_reference)
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
        for literal_text, variable_name, variable_params_str, original_variable_str in configVarParser.var_parse_imp(str_to_resolve):
            if literal_text:
                resolved_parts.append(literal_text)
                num_literals += 1
            if variable_name:
                positional_params, key_word_params = configVarParser.parse_var_params(variable_params_str)
                resolved_parts.extend(self.ResolveVarWithParamsToList(variable_name, positional_params, key_word_params, original_variable_str))
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
        retVal = list_sep.join(value_list)
        return retVal

    def ResolveVarToList(self, in_var, default=None):
        retVal = list()
        if in_var in self:
            with self.circular_resolve_check(in_var):
                for value in self[in_var]:
                    if value is None:
                        retVal.append(None)
                    else:
                        resolved_list_for_value = self.ResolveStrToListIfSingleVar(value)
                        retVal.extend(resolved_list_for_value)
        else:
            if utils.is_iterable_but_not_str(default):
                retVal = default
            else:
                raise ValueError("Variable {} was not found and default given {} is not a list".format(in_var, default))
        return retVal

    def ResolveVarWithParamsToList(self, in_var, positional_params, key_word_params, original_variable_str):
        with self.push_scope_context():
            evaluated_params = {}
            for i_param in range(len(positional_params)):
                # create __1__ positional params
                pos_param_name = "".join(("__", in_var, "_", str(i_param+1), "__"))
                evaluated_params[pos_param_name] = positional_params[i_param]
            evaluated_params.update(key_word_params)
            self.update(evaluated_params)
            retVal = self.ResolveVarToList(in_var, [original_variable_str])
        return retVal

