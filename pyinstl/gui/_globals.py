#!/usr/bin/env python3.12
"""Module-level GUI singletons extracted verbatim from pyinstl/instlGui.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.

`tk_global_master` is the single Tk() root, created at import time exactly as
it was when it lived at the top of pyinstl/instlGui.py. `default_font_size`
selects the platform-appropriate font size. Both live in this leaf module so
the focused frame submodules can import them without a circular dependency on
the package __init__.
"""
import os
from tkinter import *

tk_global_master = Tk()

if getattr(os, "setsid", None):
    default_font_size = 17  # for Mac
else:
    default_font_size = 12  # for Windows
