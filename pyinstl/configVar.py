#!/usr/bin/env python2.7

from __future__ import print_function

"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""

import sys

import platform
current_os = platform.system()
if current_os == 'Darwin':
    def dereference_var(in_var):
        return "".join(("${", in_var, "}"))
elif current_os == 'Windows':
    def dereference_var(in_var):
        return "".join(("%", in_var, "%"))
elif current_os == 'Linux':
    def dereference_var(in_var):
        return "".join(("${", in_var, "}"))


class ConfigVar(object):
    """ Keep a single, named, config variable and it's values.
        Also info about where it came from (file, line).
        value may have $() style references to other variables.
        Values are always a list - even a single value is a list of size 1.
        Values are kept as strings and are converted to strings upon append/extend.
        ConfigVar Emulates a list container
    """
    __slots__ = ("__name", "__description", "__values", "__resolving_in_progress")

    def __init__(self, name, description="", *values):
        self.__name = name
        self.__description = description
        self.__values = map(str, values)
        self.__resolving_in_progress = False  # prevent circular resolves

    def name(self):
        """ return the name of this variable """
        return self.__name

    def description(self):
        """ return the description of this variable """
        return self.__description

    def set_description(self, description):
        """ Assign new description """
        self.__description = str(description)

    def __str__(self):
        ln = '\n'
        indent = "    "
        retVal = "{self._ConfigVar__name}:{ln}{indent}description:{self._ConfigVar__description}{ln}{indent}values:{self._ConfigVar__values})".format(**locals())
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
        self.__values.append(str(value))

    def extend(self, values):
        if values:
            if not hasattr(values, '__iter__'):
                raise TypeError(str(values)+" is not a iterable")
        self.__values.extend([str(value) for value in values])


class ConstConfigVar(ConfigVar):
    """ ConfigVar override where values cannot be changed after construction """
    __slots__ = ()

    def __init__(self, name, description="", *values):
        if sys.version_info < (3, 0):
            super(ConstConfigVar, self).__init__(name, description, *values)
        else:
            super().__init__(name, description, *values)

    def set_description(self, unused_description):
        raise Exception("Cannot change a const value", self.__name)

    def __setitem__(self, unused_key, unused_value):
        raise Exception("Cannot change a const value", self.__name)

    def __delitem__(self, unused_key):
        raise Exception("Cannot change a const value", self.__name)

    def append(self, unused_value):
        raise Exception("Cannot change a const value", self.__name)

    def extend(self, unused_value):
        raise Exception("Cannot change a const value", self.__name)

if __name__ == "__main__":
    pass
