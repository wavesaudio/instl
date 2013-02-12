#!/usr/local/bin/python2.7

from __future__ import print_function

"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    configVarList module has but a single class ConfigVarList
    import config.configVarList
"""

import os
import sys
import re

if __name__ == "__main__":
    sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))

from pyinstl import configVar
from aYaml.augmentedYaml import YamlDumpWrap


value_ref_re = re.compile("""(
                            (?P<varref_pattern>
                            (?P<varref_marker>[$])      # $
                            \(                          # (
                            (?P<var_name>\w+)           # value
                            \))                         # )
                            )""", re.X)
only_one_value_ref_re = re.compile("""
                            ^
                            (?P<varref_pattern>
                            (?P<varref_marker>[$])      # $
                            \(                          # (
                            (?P<var_name>\w+)           # value
                            \))                         # )
                            $
                            """, re.X)

class ConfigVarList(object):
    """ Keeps a list of named build config values.
        Help values resolve $() style references. """

    parser = None

    __slots__ = ("_resolved_vars", "_ConfigVar_objs", "__dirty", "__resolve_stack")
    def __init__(self):
        self._resolved_vars = dict()       # map config var name to list of resolved values
        self._ConfigVar_objs = dict()   # map config var name to list of objects representing unresolved values
        self.__dirty = False            # True is _ConfigVar_objs was changed but resolved not re-done
        self.__resolve_stack = list()

    def __len__(self):
        if self.__dirty:
            raise Exception("config varaibles were not resolved")
        return len(self._resolved_vars)

    def __getitem__(self, var_name):
        if self.__dirty:
            raise Exception("config varaibles were not resolved")
        # the value of non existant var_name is an empty tuple
        return self._resolved_vars[var_name]

    def __delitem__(self, key):
        if key in self._ConfigVar_objs:
            del self._ConfigVar_objs[key]
            self.__dirty = True
        if key in self._resolved_vars:
            del self._resolved_vars[key]
            self.__dirty = True

    def get(self, var_name, default=tuple()):
        if self.__dirty:
            raise Exception("config varaibles were not resolved")
        # the value of non existant var_name is an empty tuple
        return self._resolved_vars.get(var_name, default)

    def get_str(self, var_name, default="", sep=" "):
        retVal = default
        if var_name in self._ConfigVar_objs:
            if not self.__dirty:
                retVal = sep.join(self.get(var_name))
            else:
                resolved_list = resolve_list(self._ConfigVar_objs[var_name], self.resolve_value_callback)
                retVal = sep.join(resolved_list)
        return retVal

    def __str__(self):
        [name+": "+ " ".join(self._resolved_vars[name]) for name in self._resolved_vars]
        return os.linesep.join([name+": "+ " ".join(self._resolved_vars[name]) for name in self._resolved_vars])

    def __iter__(self):
        if self.__dirty:
            raise Exception("config varaibles were not resolved")
        return iter(self._resolved_vars)

    def __reversed__(self):
        if self.__dirty:
            raise Exception("config varaibles were not resolved")
        return reversed(self._resolved_vars)

    def __contains__(self, var_name):
        if self.__dirty:
            raise Exception("config varaibles were not resolved")
        if var_name in self._resolved_vars:
            return True
        else:
            return False

    def keys(self):
        return self._resolved_vars.keys()

    def description(self, var_name):
        """ Get description for variable """
        return self._ConfigVar_objs[var_name].description()

    def get_configVar_obj(self, var_name):
        self.__dirty = True # if someone asked for a configVar.ConfigVar, assume it was changed
        retVal = self._ConfigVar_objs.setdefault(var_name, configVar.ConfigVar(var_name))
        return retVal

    def set_variable(self, var_name, description=None):
        self.__dirty = True # if someone asked for a configVar.ConfigVar, assume it was changed
        retVal = self.get_configVar_obj(var_name)
        retVal.clear_values()
        if description is not None:
            retVal.set_description(description)
        return retVal

    def add_const_config_variable(self, name, description="", *values):
        """ add a const single value object """
        if name in self._ConfigVar_objs:
            raise Exception("Const variable {} already defined".format(name))
        addedValue = configVar.ConstConfigVar(name, description, *values)
        self._ConfigVar_objs[addedValue.name()] = addedValue
        if not self.__dirty: # if not already dirty, try to keep it clean
            if value_ref_re.search(" ".join(values)):
                self.__dirty = True # dirty because a $() reference(s) found
            else: # no need to resolve, copy values to _resolved_vars
                self._resolved_vars[addedValue.name()] = values

    def duplicate_variable(self, source_name, target_name):
        if source_name in self._ConfigVar_objs:
            self.set_variable(target_name, self._ConfigVar_objs[source_name].description()).extend(self._ConfigVar_objs[source_name])
        else:
            raise KeyError("UNKNOWN VARIABLE "+source_name)

    def read_environment(self):
        """ Get values from environment """
        for env in os.environ:
            if env == "": # not sure why I get an empty string
                continue
            self.set_variable(env, "from envirnment").append(os.environ[env])

    def repr_for_yaml(self, vars=None):
        retVal = dict()
        if not vars:
            vars = self._resolved_vars
        if hasattr(vars, '__iter__'): # if vars is a list
            for name in vars:
                if name in self._resolved_vars:
                    theComment = self._ConfigVar_objs[name].description()
                    retVal[name] = YamlDumpWrap(value=self._resolved_vars[name], comment=theComment)
                else:
                    retVal[name] = YamlDumpWrap(value="UNKNOWN VARIABLE", comment=name+" is not in variable list")
        else:   # if vars is a single variable name
            retVal.update(self.repr_for_yaml((vars,)))
        return retVal

    def resolve_string(self, in_str, sep=" "):
        """ resolve a string that might contain references to values """
        resolved_list = resolve_list((in_str,), self.resolve_value_callback)
        retVal = sep.join(resolved_list)
        return retVal

    def resolve(self):
        """ Resolve all values """
        try:
            self._resolved_vars = dict()
            self.__resolve_stack = list()
            for var_name in self._ConfigVar_objs:
                if var_name in self.__resolve_stack:
                    raise Exception("circular resolving of {}".format(value_to_resolve))
                self.__resolve_stack.append(var_name)
                self._resolved_vars[var_name] = resolve_list(self._ConfigVar_objs[var_name],
                                                        self.resolve_value_callback)
                self.__resolve_stack.pop()
            self.__dirty = False
            self.__resolve_stack = list()
        except Exception as excptn:
            print("Exception while resolving variable '"+var_name+"':", excptn)
            raise

    def resolve_value_callback(self, value_to_resolve):
        """ callback for configVar.ConfigVar.Resolve. value_to_resolve should
            be a single value name.
        """
        if value_to_resolve not in self._resolved_vars:
            if value_to_resolve in self._ConfigVar_objs:
                if value_to_resolve in self.__resolve_stack:
                    raise Exception("circular resolving of {}".format(value_to_resolve))

                self.__resolve_stack.append(value_to_resolve)
                self._resolved_vars[value_to_resolve] = resolve_list(self._ConfigVar_objs[value_to_resolve],
                                                            self.resolve_value_callback)
                self.__resolve_stack.pop()
        return self._resolved_vars.get(value_to_resolve, tuple())

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

def resolve_list(needsResolveList, resolve_func):
    """ resolve a list, possibly with $() style references with the help of a resolving function.
        needsResolveList could be of type that emulates list, specifically configVar.ConfigVar.
    """
    replaceDic = dict()
    resolvedList = list()
    for valueText in needsResolveList:
        # if the value is only a single $() reference, no quotes,
        # the resolved values are extending the resolved list
        single_value_ref_match = only_one_value_ref_re.match(valueText)
        if single_value_ref_match: #
            new_values = resolve_func(single_value_ref_match.group('var_name'))
            resolvedList.extend(new_values)
            continue
        # if the value is more than a single $() reference,
        # the resolved values are joined and appended to the resolved list
        for value_ref_match in value_ref_re.finditer(valueText):
            # group 'varref_pattern' is the full $(X), group 'var_name' is the X
            replace_ref, value_ref = value_ref_match.group('varref_pattern', 'var_name')
            if replace_ref not in replaceDic:
                replaceDic[replace_ref] = " ".join(resolve_func(value_ref))
        valueTextResolved = replace_all_from_dict(valueText, **replaceDic)
        resolvedList.append(valueTextResolved)
    if False:
        self.__resolving_in_progress = False
    return tuple(resolvedList)

if __name__ == "__main__":
    varList = ConfigVarList()
    cv = varList.get_configVar_obj("itzik")
    cv.extend( ("$(shabat)", "$(shalom)") )
    cv.append("$(U) $(mevorach)")
    varList.get_configVar_obj("shabat").append("saturday")
    varList.get_configVar_obj("shalom").append("$(salam) aleykum")
    varList.get_configVar_obj("salam").append("$(peace)")
    varList.get_configVar_obj("peace").append("no more war")
    varList.get_configVar_obj("mevorach").append("blessed")
    varList.get_configVar_obj("U").append("and")
    varList.get_configVar_obj("you").append("ata")

    varList.set_variable("mergoza", "stam").append("pinochio")

    varList.read_environment()
    varList.resolve()

    for var in sorted(varList):
        print (var, "=", " ".join(varList[var]))

    to_re = "on $(shabat) morning, i told $(you) and you told me $(itzik)"
    print(varList.resolve_string(to_re))
