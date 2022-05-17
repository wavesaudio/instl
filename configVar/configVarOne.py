#!/usr/bin/env python3.9

"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""
import collections
import os
from pathlib import PurePath, Path
from typing import List, Optional, Union

import utils


def something_to_bool(something, default=False):
    retVal = default
    if isinstance(something, bool):
        retVal = something
    elif isinstance(something, int):
        if something == 0:
            retVal = False
        else:
            retVal = True
    elif isinstance(something, str):
        if something.lower() in ("yes", "true", "y", 't', '1'):
            retVal = True
        elif something.lower() in ("no", "false", "n", "f", '0'):
            retVal = False
    return retVal


def value_is_set(name, value):
    """ for debugging 'set' of specific config var.
        in ConfigVar.__init__ call:
        if self.name == 'ExternalVersion_underscore':
            self.set_callback_when_value_is_set(value_is_set)
            self.set_callback_when_value_is_get(value_is_get)
    """
    pass


def value_is_get(value):
    """ see doc string of value_is_set above"""
    return value


class ConfigVar:
    """ ConfigVar represents 1 configuration variable that can hold
        zero or more values. ConfigVar can be used as either str or
        list depending on the context and therefor has some methods
        implementing list interface.
        self.values - list of values. Values must be strings because self.values is *not* hierarchical list.
        self.owner - is a reference to ConfigVarStack object that holds this
            ConfigVar and is used for resolving the values that might refer to other ConfigVars
        self.name - the name under which the owner keeps the ConfigVar
             name is useful for debugging, but in runtime ConfigVar has
             no (and should have no) use for it's own name
    """
    __slots__ = ("owner", "name", "values", "callback_when_value_is_set", "callback_when_value_is_get", "dynamic")

    def __init__(self, owner, name: str, *values, callback_when_value_is_set=None, callback_when_value_is_get=None) -> None:
        self.owner = owner
        self.name = name
        self.dynamic = False
        self.set_callback_when_value_is_get(callback_when_value_is_get)
        self.set_callback_when_value_is_set(callback_when_value_is_set)
        self.values: List[str] = list()
        self.extend(values)  # extend will flatten hierarchical lists

    def _do_nothing_callback_when_value_is_set(self, *argv, **kwargs):
        pass

    def set_callback_when_value_is_set(self, new_callback_when_value_is_set):
        if new_callback_when_value_is_set is None:
            self.callback_when_value_is_set = self._do_nothing_callback_when_value_is_set
        else:
            self.callback_when_value_is_set = new_callback_when_value_is_set

    def set_callback_when_value_is_get(self, new_callback_when_value_is_get):
        if new_callback_when_value_is_get is None:
            self.callback_when_value_is_get = self.owner.resolve_str
        else:
            self.callback_when_value_is_get = new_callback_when_value_is_get
            self.dynamic = True

    def __len__(self) -> int:
        """ :return: number of values """
        retVal = len(self.values)
        return retVal

    def __repr__(self) -> str:
        """ :return: string that can be eval()'ed to recreate the ConfigVar """
        repr_str = f"""{self.__class__.__name__}("{self.name}", *{self.values})"""
        return repr_str

    def __bool__(self):
        """ From RafeKettler/magicmethods: Defines behavior for when bool() is called on an instance of your class. Should return True or False, depending on whether you would want to consider the instance to be True or False.
        :return: True if there is a single value and when converted to lower case
        is one of ("yes", "true", "y", 't')
        False otherwise
        """
        retVal = False
        if len(self.values) == 1:
            retVal = something_to_bool(self.values[0], False)
        return retVal

    def __contains__(self, val: str) -> bool:
        retVal = val in self.resolve_values()
        return retVal

    def resolve_values(self) -> List:
        resolved_values = [self.callback_when_value_is_get(val) for val in self.values]
        return resolved_values

    def join(self, sep: str) -> str:
        retVal = sep.join(val for val in self.resolve_values())
        return retVal

    def __str__(self) -> str:
        """
        calls the owner to resolve each of the values and joins them.
        this is the main method to resolve and use a ConfigVar as a single value
        e.g.:
            var_list["a"].extend("a", "b")
            print(str(var_list["a"]))
        will print:
            ab
        :return: a single string that is resolved representation of the values.
                if self.values is empty an empty string is returned
        """
        if len(self.values) == 1 and self.values[0] is None:
            retVal = None
        else:
            retVal = self.join(sep='')
        return retVal

    def is_path_var(self):
        retVal = self.name.endswith("_DIR") or self.name.endswith("_PATH")
        return retVal

    def __fspath__(self) -> str:
        """ implements os.PathLike - https://docs.python.org/3.6/library/os.html#os.PathLike
            so configVar can be passed to pathlib, os.path, etc
            we do not really know if the configVar actually represents
            a path, we just return is as a string, hoping to cut redundant slashes and such.
        """
        retVal = os.fspath(PurePath(self.str()))
        return retVal

    def Path(self, resolve: bool=False) -> Optional[Path]:
        retVal = None
        if self.values and self.values[0]:
            if resolve:
                expanded_path = os.path.expandvars(self.str())
                path_path = Path(expanded_path)
                retVal = path_path.resolve()
            else:
                retVal = Path(self.str())
        return retVal

    def PurePath(self) -> Optional[PurePath]:
        retVal = None
        if self.values and self.values[0]:
            retVal = PurePath(self.str())
        return retVal

    def __int__(self) -> int:
        retVal = utils.str_to_int(self.join(sep=''))
        return retVal

    def __float__(self) -> float:
        retVal = utils.str_to_float(self.join(sep=''))
        return retVal

    def __iter__(self):
        """
        calls the owner to resolve each of the values.
        this is the method to resolve and use a ConfigVar as a list of values
        e.g.:
            var_list["a"].extend("a", "b")
            for val in var_list["a"]:
                print(val)
        will print:
            a
            b
        :return: iterator on resolved representation of the values
        """
        for val in self.values:
            if self.dynamic:
                val = self.callback_when_value_is_get(val)
            yield_vals = self.owner.resolve_str_to_list(val)
            yield from yield_vals

    def str(self) -> str:
        return str(self)

    def list(self) -> List:
        return list(iter(self))

    def set(self) -> List:
        return set(iter(self))

    def int(self) -> int:
        return int(self)  # will call ConfiVar.__int__

    def bool(self) -> bool:
        return bool(self)

    def float(self) -> float:
        return float(self)  # will call ConfiVar.__float__

    def __getitem__(self, index: int) -> str:
        """
        calls the owner to resolve one of the values by it's index.
        e.g.:
            var_list["a"].extend("a", "b")
            print(str(var_list["a"][1]))
        will print:
            b
        :return: resolved representation of one of the values
        """
        retVal = self.callback_when_value_is_get(self.values[index])
        return retVal

    def append(self, value):
        """
            append a single value to the ConfigVar's values
            :param value: either str or int (TBD is limitations needed ?)
            None values are ignored and not appended (TBD should we allow None values? or is empty list enough?)
        """
        if value is not None:
            self.values.append(str(value))
            self.callback_when_value_is_set(self.name, value)

    def extend(self, values):
        """
            append a multiple value to the ConfigVar's values
            but if string is passed it will not be treated like a list
            of characters and will be added as a single value.
        """
        if isinstance(values, (str, int, float, type(None))):
            # so str will not be treated as a list of characters
            self.append(values)
        elif isinstance(values, collections.abc.Sequence):
            for val in values:
                self.extend(val)  # flatten nested lists
        elif isinstance(values, os.PathLike):
            self.append(os.fspath(values))
        else:
            raise TypeError(f"configVar('{self.name}') type of values '{values}' should be str int or sequence not {type(values)}")

    def clear(self):
        """ erase all values """
        if self.values:
            self.values.clear()

    def raw(self, join_sep: Optional[str] = "") -> Union[str, List[str]]:
        """ return the list of values unresolved"""
        if join_sep is None:
            return self.values
        else:
            return join_sep.join(self.values)
