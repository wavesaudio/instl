#!/usr/bin/env python3.12
"""TkConfigVar bridge (config-var editing) extracted verbatim from
pyinstl/instlGui.py.

Pure structural decomposition: code MOVED verbatim, no logic changes. This is
the bridge that keeps a Tk Variable (StringVar/IntVar/BooleanVar) and an instl
ConfigVar in sync via "double callback".
"""
from tkinter import *

from configVar import config_vars


def CreateTkConfigClass(TkBase, convert_type_func):
    """ creates a class that connects between Tk Variable class (StringVar, intVar,...)
        and ConfigVar. The value is kept in the Tk Variable but the ConfigVar is updated whenever
        the tk variable updated. Implementation is is "double callback" where callbacks to tk and to configVar
        do the work of adjusting the values. This is done so because tk variables cannot be inherited.
    """
    class TkConfigVar(TkBase):
        """ bridge between tkinter StringVar to instl ConfigVar."""

        def __init__(self, config_var_name, master=None, value=None, debug_var=False):
            TkBase.__init__(self, master, value, config_var_name)
            self.debug_var = debug_var
            self.convert_type_func = convert_type_func
            self.config_var_name = config_var_name
            self.__internal_update = False
            config_vars.setdefault(self.config_var_name, value)  # create a ConfigVar is one does not exists
            # call set_callback_when_value_is_set because config_vars.setdefault will not assign the callback is the confiVar already exists
            config_vars[self.config_var_name].set_callback_when_value_is_set(self._config_var_set_value_callback)
            self._our_trace_write_callback = None
            self.trace("w", self._internal_trace_write_callback)
            if self.debug_var:
                print(f"TkConfigVar.__init__({self.config_var_name})")

        def _internal_trace_write_callback(self, *args, **kwargs):
            """
                this function will be set as the tk var trace
                if tk var was written, pass the value to the configVar
            """
            if not self.__internal_update:
                value = self._tk.globalgetvar(self.config_var_name)
                self.__internal_update = True
                config_vars[self.config_var_name] = value
                self.__internal_update = False
                if self._our_trace_write_callback:
                    self._our_trace_write_callback(*args, **kwargs)

        def _config_var_set_value_callback(self, var_name, new_var_value):
            """ ConfigVar will call this callback every time a value has been assigned """
            if not self.__internal_update:  # called from _trace_write_callback so need to avoid circular callback calls
                if self.debug_var:
                    print(f"TkConfigVar._config_var_set_value_callback({self.config_var_name}) <- {new_var_value}")
                TkBase.set(self, self.convert_type_func(new_var_value))
            else:  # configVar was changed, pass value to tk var
                self.__internal_update = True
                self._tk.globalsetvar(self.config_var_name, new_var_value)
                self.__internal_update = False

        def _get_value_from_config_var(self):
            retVal = self.convert_type_func(config_vars.get(self.config_var_name, self.convert_type_func()))
            return retVal

        def set_trace_write_callback(self, trace_write_callback):
            """ this is our way to set the callback"""
            self._our_trace_write_callback = trace_write_callback

    return TkConfigVar


TkConfigVarStr  = CreateTkConfigClass(StringVar, str)
TkConfigVarInt  = CreateTkConfigClass(IntVar, int)
TkConfigVarBool = CreateTkConfigClass(BooleanVar, bool)
