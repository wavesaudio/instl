#!/usr/bin/env python3.12
"""Backwards-compatible shim.

pyinstl/instlClient.py was decomposed into the pyinstl/client/ package (a pure
structural extract-module refactor with zero behavior change). This module is
kept so that the historical public surface keeps resolving identically:

    import pyinstl.instlClient
    from pyinstl.instlClient import InstlClient
    from pyinstl.instlClient import InstlClientFactory

The sibling client mixins (instlClientSync/Copy/Remove/Report/Uninstall) still
import `from .instlClient import InstlClient` through this shim.
"""
from .client import (
    InstlClient,
    InstlClientFactory,
)
