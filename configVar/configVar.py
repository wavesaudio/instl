#!/usr/bin/env python2.7

from __future__ import print_function

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
    __slots__ = ("__name", "__description", "__values", "resolved_num")
    # variables with name ending with these endings will have their value passed through os.path.normpath
    variable_name_endings_to_normpath = ("_PATH", "_DIR", "_DIR_NAME", "_FILE_NAME", "_PATH__", "_DIR__", "_DIR_NAME__", "_FILE_NAME__")

    def __init__(self, name, description="", *values):
        self.__name = name
        self.__description = description
        self.__values = map(str, values)
        self.resolved_num = 0

    @property
    def name(self):
        """ return the name of this variable """
        return self.__name

    @property
    def description(self):
        """ return the description of this variable """
        return self.__description

    @description.setter
    def description(self, description):
        """ Assign new description """
        self.__description = str(description)

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

    def append(self, value):
        if self.__name.endswith(self.variable_name_endings_to_normpath):
            self.__values.append(os.path.normpath(value))
        else:
            self.__values.append(utils.convert_to_str_unless_None(value))

    def extend(self, values):
        if values:
            if not hasattr(values, '__iter__'):
                raise TypeError(str(values)+" is not a iterable")
        if self.__name.endswith(self.variable_name_endings_to_normpath):
            normed_values = [os.path.normpath(value) for value in values]
            self.__values.extend(normed_values)
        else:
            self.__values.extend([utils.convert_to_str_unless_None(value) for value in values])


class ConstConfigVar(ConfigVar):
    """ ConfigVar override where values cannot be changed after construction """
    __slots__ = ()

    def __init__(self, name, description="", *values):
        if sys.version_info < (3, 0):
            super(ConstConfigVar, self).__init__(name, description, *values)
        else:
            raise "Python version too advanced, need 2.X not "+str(sys.version_info)
        #    super().__init__(name, description, *values)

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
