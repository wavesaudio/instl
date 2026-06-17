#!/usr/bin/env python3.12
"""Backwards-compatible shim.

pyinstl/instlGui.py was decomposed into the pyinstl/gui/ package (a pure
structural extract-module refactor with zero behavior change). This module is
kept so that the historical public surface keeps resolving identically:

    import pyinstl.instlGui
    from pyinstl.instlGui import InstlGui

instl_main dispatches the 'gui' mode via `from pyinstl.instlGui import InstlGui`,
which still resolves through this shim. The rest of the names that used to live
at module top-level (the controllers, the Tk<->ConfigVar bridge, the ToolTip
widget, the shared singletons) are re-exported below so any historical importer
keeps working.
"""
from .gui import (
    InstlGui,
    tk_global_master,
    default_font_size,
    CreateTkConfigClass,
    TkConfigVarStr,
    TkConfigVarInt,
    TkConfigVarBool,
    ToolTip,
    FrameController,
    ClientFrameController,
    AdminFrameController,
    ActivateFrameController,
    admin_command_template_variables,
)
