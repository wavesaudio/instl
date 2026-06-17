#!/usr/bin/env python3.12
"""Backwards-compatible shim.

pyinstl/instlAdmin.py was decomposed into the pyinstl/admin/ package (a pure
structural extract-module refactor with zero behavior change). This module is
kept so that the historical public surface keeps resolving identically:

    import pyinstl.instlAdmin
    from pyinstl.instlAdmin import InstlAdmin

re-export the same names that used to live here.
"""
from .admin import (
    InstlAdmin,
    start_redis_heartbeat_thread,
    smart_merge_dicts,
    dict_in_canonical_order,
)
