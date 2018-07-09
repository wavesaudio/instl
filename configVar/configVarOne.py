#!/usr/bin/env python3

"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""
import collections
from typing import List, Optional, Union

def str_to_bool(the_str, default=False):
    retVal = default
    if the_str.lower() in ("yes", "true", "y", 't'):
        retVal = True
    elif the_str.lower() in ("no", "false", "n", "f"):
        retVal = False
    return retVal


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
    __slots__ = ("owner", "name", "values")
    def __init__(self, owner, name: str, *values):
        self.owner = owner
        self.name = name
        self.values = list()
        self.extend(values)  # extend will flatten hierarchical lists

    def __len__(self) -> int:
        """ :return: number of values """
        retVal = len(self.values)
        return retVal

    def __repr__(self) -> str:
        """ :return: string that can be eval()'ed to recreate the ConfigVar """
        repr_str = f"""ConfigVar("{self.name}", *{self.values})"""
        return repr_str

    def __bool__(self):
        """ From RafeKettler/magicmethods: Defines behavior for when bool() is called on an instance of your class. Should return True or False, depending on whether you would want to consider the instance to be True or False.
        :return: True if there is a single value and when converted to lower case
        is one of ("yes", "true", "y", 't')
        False otherwise
        """
        retVal = False
        if len(self.values) == 1:
            retVal = str_to_bool(self.values[0], False)
        return retVal

    def __contains__(self, val: str) -> bool:
        retVal = val in (self.owner.resolve_str(val) for val in self.values)
        return retVal

    def join(self, sep: str) -> str:
        retVal = sep.join((self.owner.resolve_str(val) for val in self.values))
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
        retVal = self.join(sep='')
        return retVal

    def __int__(self) -> int:
        retVal = int(self.join(sep=''))
        return retVal

    def __float__(self) -> float:
        retVal = float(self.join(sep=''))
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
            yield from self.owner.resolve_str_to_list(val)

    def str(self):
        return str(self)

    def list(self):
        return list(iter(self))

    def int(self):
        return int(self)

    def bool(self):
        return bool(self)

    def float(self):
        return float(self)

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
        retVal = self.owner.resolve_str(self.values[index])
        return retVal

    def append(self, value):
        """
            append a single value to the ConfigVar's values
            :param value: either str or int (TBD is limitations needed ?)
            None values are ignored and not appended (TBD should we allow None values? or is empty list enough?)
        """
        if value is not None:
            self.values.append(str(value))

    def extend(self, values):
        """
            append a multiple value to the ConfigVar's values
            but if string is passed it will not be treated like a list
            of characters and will be added as a single value.
        """
        if isinstance(values, (str, int, type(None))):
            # so str will not be treated as a list of characters
            self.append(values)
        elif isinstance(values, collections.Sequence):
            for val in values:
                self.extend(val)  # flatten nested lists
        else:
            raise TypeError(f"type of values '{values}' should be str int or sequence not {type(values)}")

    def clear(self):
        """ erase all values """
        self.values.clear()

    def raw(self, join_sep: Optional[str]=None) -> Union[str, List[str]]:
        """ return the list of values unresolved"""
        if join_sep is None:
            return self.values
        else:
            return join_sep.join(self.values)
