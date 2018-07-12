#!/usr/bin/env python3


"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""

import os
from contextlib import contextmanager
import re
import time
from typing import Dict, List

import aYaml
from .configVarOne import ConfigVar
from .configVarParser import var_parse_imp


class ConfigVarStack:
    """
        ConfigVarStack represent a stack of ConfigVar dicts.
        this allows to override a ConfigVar by an inner context

        caching:
        ConfigVarStack maintains a cache of resolved strings.
        This proved to save resolve time, however at the cost of some complexity
        Whenever a ConfigVar is added, removed or changed the cache needs to be
        cleared.
        But resolving a ConfigVar with params is done by adding a level to the stack
        and adding temporary variables - which would invalidate the cache.
        Since this is done a lot it would make the number of cache hits very small.
        To overcome this self.use_cache is set to False when resolving
        a ConfigVar with params. When self.use_cache is False cache is not used
        while resolving and cache is not purged
    """
    def __init__(self) -> None:
        self.var_list: List[Dict] = [dict()]
        self.use_cache = True
        self.resolve_counter: int = 0
        self.simple_resolve_counter: int = 0
        self.resolve_cache_hits: int = 0
        self.resolve_time: float = 0.0
        self.resolve_cache: Dict[str,str] = dict()
        self.max_cached_strings = 0

    def __len__(self) -> int:
        """ From RafeKettler/magicmethods: Returns the length of the container. Part of the protocol for both immutable and mutable containers.

            :return: number of ConfigVars, if a specific ConfigVar name
            exist on multiple stack levels, all occurrences are counted.
        """
        retVal = sum(len(var_dict) for var_dict in self.var_list)
        return retVal

    def keys(self):
        the_keys = set()
        for var_dict in self.var_list:
            the_keys.update(var_dict.keys())
        return list(sorted(the_keys))

    def __getitem__(self, key: str) -> ConfigVar:
        """From RafeKettler/magicmethods: Defines behavior for when an item is accessed, using the notation self[key]. This is also part of both the mutable and immutable container protocols. It should also raise appropriate exceptions: TypeError if the type of the key is wrong and KeyError if there is no corresponding value for the key.

         gets a ConfigVar object by name. if key
         exist on multiple stack levels the higher (later, inner) one is returned.
        """
        if not isinstance(key, str):
            raise TypeError(f"'key' param of __getitem__() should be str not {type(key)},  '{key}'")
        for var_dict in reversed(self.var_list):
            if key in var_dict:
                return var_dict[key]
        else:
            raise KeyError(f"{key}")

    def __setitem__(self, key: str, *values):
        """From RafeKettler/magicmethods: Defines behavior for when an item is assigned to, using the notation self[key] = value. This is part of the mutable container protocol. Again, you should raise KeyError and TypeError where appropriate.

            sets the values for a ConfigVar on the top of the stack.
            If ConfigVar exists it's current values are replaced.
            Otherwise a new ConfigVar is created with the values.
            NOTE: if ConfigVar with same name exists on lower level,
            it is NOT changed and a new one is created on the top stack level
        """
        if not isinstance(key, str):
            raise TypeError(f"'key' param of __setitem__() should be str not {type(key)},  '{key}'")
        config_var = None
        try:
            config_var = self.var_list[-1][key]
        except KeyError:
            config_var = ConfigVar(self, key)
            self.var_list[-1][key] = config_var
        else:
            # clear the ConfigVar if its already in self.var_list[-1]
            config_var.clear()
        finally:
            config_var.extend(values)
            if self.use_cache:
                self.resolve_cache.clear()

    def update(self, update_dict):
        """ create new ConfigVars from a dict"""
        for var_name, var_value in update_dict.items():
            self[var_name] = var_value

    def __delitem__(self, key: str):
        """Defines behavior for when an item is deleted (e.g. del self[key]). This is only part of the mutable container protocol. You must raise the appropriate exceptions when an invalid key is used.

         deletes a ConfigVar object by name. if key
          exist on multiple stack levels only the higher (later, inner) one is deleted.
        """
        if not isinstance(key, str):
            raise TypeError(f"'key' param of __delitem__() should be str not {type(key)},  '{key}'")
        for var_dict in reversed(self.var_list):
            try:
                del var_dict[key]
                self.resolve_cache.clear()
                return
            except KeyError:
                continue
        else:
            raise KeyError

    def __contains__(self, key: str):
        """__contains__ defines behavior for membership tests using in and not in. Why isn't this part of a sequence protocol, you ask? Because when __contains__ isn't defined, Python just iterates over the sequence and returns True if it comes across the item it's looking for."""
        if not isinstance(key, str):
            raise TypeError(f"'key' param of __contains__() should be str not {type(key)},  '{key}'")
        for var_dict in self.var_list:
            if key in var_dict:
                return True
        return False

    def defined(self, key):
        """ return True only if the configVar, has values, and they are not all None or empty """
        if not isinstance(key, str):
            raise TypeError(f"'key' param of defined() should be str not {type(key)},  '{key}'")
        retVal = False
        try:
            var_obj = self[key]
            retVal = any(list(var_obj))
        except KeyError:
            pass
        return retVal

    def get(self, key: str, default=""):
        """
         gets a ConfigVar object by name. if key
         exist on multiple stack levels the higher (later, inner) one is returned.
         if ConfigVar does not exist on any stack level a new one is created
         so converting to str and list will work as expected, but the new ConfigVar is NOT added to self.var_list
         """
        if not isinstance(key, str):
            raise TypeError(f"'key' param of get() should be str not {type(key)},  '{key}'")
        try:
            retVal = self[key]
        except KeyError:
            # return a ConfigVar object so converting to str and list will work as expected
            # but the new ConfigVar is not added to self.var_list
            retVal = ConfigVar(self, key, default)
        return retVal

    def setdefault(self, key: str, default):
        """
        gets a ConfigVar object by name. if key
        exist on multiple stack levels the higher (later, inner) one is returned.
        if ConfigVar does not exist on any stack level a new one is created
        so converting to str and list will work as expected, and the new ConfigVar
        is  added to self.var_list[-1].
        """
        if not isinstance(key, str):
            raise TypeError(f"'key' param of setdefault() should be str not {type(key)},  '{key}'")
        if key not in self:
            self[key] = default
        retVal = self[key]
        return retVal

    def clear(self):
        """ clear all stack levels"""
        self.var_list.clear()
        self.var_list.append(dict())
        self.resolve_cache.clear()

    def variable_params_to_config_vars(self, parser_retVal):
        """ parse positional and/or key word params and create
            ConfigVar entries from each. This method should run
            under it's own push_scope_context so when exiting
            these new ConfigVars will disappear, as they are
            only useful for resolving a specific variable
        """
        evaluated_params = {}
        if parser_retVal.positional_params:
            for i_param in range(len(parser_retVal.positional_params)):
                # create __1__ positional params
                pos_param_name = "".join(("__", parser_retVal.variable_name, "_", str(i_param+1), "__"))
                evaluated_params[pos_param_name] = parser_retVal.positional_params[i_param]

        if parser_retVal.key_word_params:
            evaluated_params.update(parser_retVal.key_word_params)

        self.update(evaluated_params)

        # if array reference was found return the range - , e.g. for $(A[2]) return (2:3)
        # otherwise return (0, None) which is the whole array
        array_range = (0, None)
        if parser_retVal.array_index_int is not None:
            if parser_retVal.array_index_int < 0:
                # convert negative indexes to positive because a[-1:0] returns an empty list
                normalized_index = len(self[parser_retVal.variable_name]) + parser_retVal.array_index_int
                array_range = (normalized_index, normalized_index+1)
            else:
                array_range = (parser_retVal.array_index_int, parser_retVal.array_index_int + 1)

        return array_range

    def resolve_str_to_list_with_statistics(self, str_to_resolve):
        """ resolve a string to a list, return the list and also the number of variables and literal in the list.
            Returning these statistic can help with debugging
        """
        resolved_parts = list()
        num_literals = 0
        num_variables = 0
        for parser_retVal in var_parse_imp(str_to_resolve):
            if parser_retVal.literal_text:
                resolved_parts.append(parser_retVal.literal_text)
                num_literals += 1
            if parser_retVal.variable_name:
                if parser_retVal.variable_name in self:
                    with self.push_scope_context(use_cache=False):
                        array_range = self.variable_params_to_config_vars(parser_retVal)
                        resolved_parts.extend(list(self[parser_retVal.variable_name])[array_range[0]:array_range[1]])
                else:
                    resolved_parts.append(parser_retVal.variable_str)
                num_variables += 1
        return resolved_parts, num_literals, num_variables

    def resolve_str(self, val_to_resolve: str) -> str:
        start_time = time.perf_counter()

        if "$" not in val_to_resolve:
            # strings without $ do not need resolving
            result = val_to_resolve
            self.simple_resolve_counter += 1
        elif self.use_cache and val_to_resolve in self.resolve_cache:
            result = self.resolve_cache[val_to_resolve]
            self.resolve_cache_hits += 1
        else:
            res_list, num_literals, num_variables = self.resolve_str_to_list_with_statistics(val_to_resolve)
            result = "".join(res_list)
            if self.use_cache:
                self.resolve_cache[val_to_resolve] = result
                self.max_cached_strings = max(self.max_cached_strings, len(self.resolve_cache))
            else:
                self.resolve_cache.pop(val_to_resolve, None)

        end_time = time.perf_counter()
        self.resolve_counter += 1
        self.resolve_time += end_time - start_time
        return result

    def resolve_str_to_list(self, val_to_resolve: str) -> List:
        """
            if val_to_resolve is referencing a single configVar
            return the resolved list of value for that var
            otherwise return a list containing 1 item which
            is the resolved string
            :param val_to_resolve:
            :return: list
        """
        start_time = time.perf_counter()

        retVal = list()
        if "$" not in val_to_resolve:
            # strings without $ do not need resolving
            retVal.append(val_to_resolve)
            self.simple_resolve_counter += 1
        else:
            res_list, num_literals, num_variables = self.resolve_str_to_list_with_statistics(val_to_resolve)
            if num_literals == 0 and num_variables == 1:
                retVal.extend(res_list)
            else:
                retVal.append("".join(res_list))

        end_time = time.perf_counter()
        self.resolve_counter += 1
        self.resolve_time += end_time - start_time
        return retVal

    def repr_var_for_yaml(self, var_name, resolve=True):
        if resolve:
            var_value = list(self[var_name])
        else:
            var_value = self[var_name].raw()
        if len(var_value) == 1:
            var_value = var_value[0]
        retVal = aYaml.YamlDumpWrap(var_value)
        return retVal

    def repr_for_yaml(self, which_vars=None, resolve=True, ignore_unknown_vars=False):
        retVal = dict()
        vars_list = list()
        if not which_vars:
            vars_list.extend(self.keys())
        elif isinstance(which_vars, str):
            vars_list.append(which_vars)
        else:
            vars_list = which_vars
        if not hasattr(vars_list, '__iter__'):  # if which_vars is a list
            ValueError("ConfigVarStack.repr_for_yaml can except string, list or None, not "+type(which_vars)+" "+str(which_vars))
        for var_name in vars_list:
            if var_name in self:
                 retVal[var_name] = self.repr_var_for_yaml(var_name, resolve=resolve)
            elif not ignore_unknown_vars:
                retVal[var_name] = aYaml.YamlDumpWrap(value="UNKNOWN VARIABLE", comment=var_name+" is not in variable list")
        return retVal

    def resolve_list_to_list(self, strs_to_resolve_list):
        """ A list of string is given and resolved according to the rules:
            if string is a name of existing ConfigVar the ConfigVar is resolved to a list and each item on the list added to the returned list.
            otherwise the string is resolved to a string and added to the returned list.
            """
        retVal = list()
        for a_str in strs_to_resolve_list:
            if a_str in self:
                retVal.extend(list(self[a_str]))
            else:
                retVal.append(self.resolve_str(a_str))
        return retVal

    def push_scope(self):
        self.var_list.append(dict())

    def pop_scope(self):
        self.var_list.pop()
        if self.use_cache:
            self.resolve_cache.clear()

    @contextmanager
    def push_scope_context(self, use_cache=True):
        save_use_cache = self.use_cache
        self.use_cache = use_cache
        self.push_scope()
        yield self
        self.pop_scope()
        self.use_cache = save_use_cache

    def read_environment(self, vars_to_read_from_environ=None):
        """ Get values from environment. Get all values if regex is None.
            Get values matching regex otherwise """
        if vars_to_read_from_environ is None:
            for env_key, env_value in os.environ.items():
                # not sure why, sometimes I get an empty string as env variable name
                if env_key:
                    self[env_key] = env_value
        else:
            # windows environ variables are not case sensitive, but instl vars are
            if 'Win' in list(self["__CURRENT_OS_NAMES__"]):
                lower_case_environ = dict(zip(map(lambda z:z.lower(), os.environ.keys()), os.environ.values()))
                for env_key_to_read in vars_to_read_from_environ:
                    if env_key_to_read.lower() in lower_case_environ:
                        self[env_key_to_read] = lower_case_environ[env_key_to_read.lower()]
            else:
                for env_key_to_read in vars_to_read_from_environ:
                    if env_key_to_read in os.environ:
                        self[env_key_to_read] = os.environ[env_key_to_read]

    def print_statistics(self):
        if bool(self.get("PRINT_CONFIG_VAR_STATISTICS", "False")):
            print(f"{len(self)} ConfigVars")
            print(f"{self.resolve_counter} resolves")
            print(f"{self.simple_resolve_counter} simple resolves")
            print(f"{len(self.resolve_cache)} cached strings ({self.max_cached_strings} max)")
            print(f"{self.resolve_cache_hits} cache hits")
            print(f"{self.resolve_cache_hits/len(self.resolve_cache):.3} hits per cached string")
            average_resolve_ms = (self.resolve_time / self.resolve_counter)*1000
            print(f"{average_resolve_ms:.4}ms per resolve")
            print(f"{self.resolve_time:.3}sec total resolve time")

# This is the global variable list serving all parts of instl
config_vars = ConfigVarStack()
