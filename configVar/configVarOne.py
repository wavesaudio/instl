#!/usr/bin/env python3



"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""

import sys
import os

import utils


class ConfigVar(object):
    """ Keep a single, named, config variable and it's values.
        Also info about where it came from (file, line).
        value may have $() style references to other variables.
        Values are always a list - even a single value is a list of size 1.
        Values are kept as strings and are converted to strings upon append/extend.
        ConfigVar Emulates a list container
    """
    __slots__ = ("__name", "__description", "__values", "resolved_num", "__non_freeze", "__values_are_frozen", "__freeze_values_on_first_resolve")
    # variables with name ending with these endings will have their value passed through os.path.normpath
    variable_name_endings_to_normpath = ("_PATH", "_DIR", "_DIR_NAME", "_FILE_NAME", "_PATH__", "_DIR__", "_DIR_NAME__", "_FILE_NAME__")

    def __init__(self, name, description="", *values):
        self.__name = utils.unicodify(name)
        self.__description = utils.unicodify(description)
        self.resolved_num = 0
        self.__values = list()
        self.__non_freeze = False
        self.__values_are_frozen = False
        self.__freeze_values_on_first_resolve = False
        ConfigVar.extend(self, values) # explicit call so ConstConfigVar can be initialized

    @property
    def name(self):
        """ return the name of this variable """
        return self.__name

    @property
    def description(self):
        """ return the description of this variable """
        return self.__description

    @property
    def unresolved_values(self):
        """ return the unresolved values of this variable """
        return self.__values

    @description.setter
    def description(self, description):
        """ Assign new description """
        self.__description = str(description)

    @property
    def frozen_value(self):
        return self.__values_are_frozen

    @property
    def freeze_values_on_first_resolve(self):
        return self.__freeze_values_on_first_resolve

    @freeze_values_on_first_resolve.setter
    def freeze_values_on_first_resolve(self, new_value):
        if self.__non_freeze:
            self.__freeze_values_on_first_resolve = False
        else:
            self.__freeze_values_on_first_resolve = new_value

    @property
    def non_freeze(self):
        return self.__non_freeze

    @non_freeze.setter
    def non_freeze(self, new_value):
        self.__non_freeze = new_value
        if self.__non_freeze:
            self.__values_are_frozen = False
            self.__freeze_values_on_first_resolve = False

    def __str__(self):
        ln = '\n'
        indent = "    "
        retVal = "{self._ConfigVar__name}:{ln}{indent}"\
                "values:{self._ConfigVar__values}{ln}{indent}"\
                "description:{self._ConfigVar__description})".format(**locals())
        return retVal

    def __repr__(self):
        retVal = self.__str__()
        return retVal

    def __len__(self):
        return len(self.__values)

    def __getitem__(self, key):
        # if key is of invalid type or value, the list values will raise the error
        return self.__values[key]

    def __setitem__(self, key, value):
        self.__values[key] = str(value)

    def __delitem__(self, key):
        del self.__values[key]

    def __iter__(self):
        return iter(self.__values)

    def __reversed__(self):
        return reversed(self.__values)

    def clear_values(self):
        self.__values = list()

    def norm_values(self, *values):
        normed_values = list(map(utils.unicodify, values))
        # normalization of paths moved to configVarList.ResolveVarToList
        # if self.__name.endswith(self.variable_name_endings_to_normpath):
        #     normed_values = list(map(os.path.normpath, normed_values))
        return normed_values

    def append(self, value):
        normed_value = self.norm_values(value)[0]
        if normed_value is not None and not self.__non_freeze:
            if "$(" in normed_value:
                self.__values_are_frozen = False
            else:
                if len(self.__values) == 0:
                    self.__values_are_frozen = True
        self.__values.append(normed_value)

    def extend(self, values):
        for value in values:
            ConfigVar.append(self, value)

    def set_frozen_values(self, *values):
        if not self.__non_freeze:
            self.__values = values
            self.__values_are_frozen = True


class ConstConfigVar(ConfigVar):
    """ ConfigVar override where values cannot be changed after construction """
    __slots__ = ()

    def __init__(self, name, description="", *values):
        super().__init__(name, description, *values)

    @ConfigVar.description.setter
    def description(self, unused_description):
        raise Exception("Cannot change a const value", self.name)

    def __setitem__(self, unused_key, unused_value):
        raise Exception("Cannot change a const value", self.name)

    def __delitem__(self, unused_key):
        raise Exception("Cannot change a const value", self.name)

    def append(self, unused_value):
        raise Exception("Cannot change a const value", self.name)

    def extend(self, unused_value):
        raise Exception("Cannot change a const value", self.name)

if __name__ == "__main__":
    pass
