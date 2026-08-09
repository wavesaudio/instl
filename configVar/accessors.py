#!/usr/bin/env python3.12


"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    Typed readers for OPTIONAL config vars: a key that was never defined reads as
    its default rather than raising. The download settings (the DOWNLOAD_* family)
    are all optional and mostly absent, so their readers would otherwise each need
    a membership test and a conversion at every call site.

    For keys instl always defines, read config_vars directly - that is the house
    idiom and these add nothing to it.
"""

from typing import List

from .configVarStack import config_vars


def config_var_str(name: str, default=None):
    """Return `name` as a non-empty string, or `default`."""
    if name not in config_vars:
        return default
    try:
        value = config_vars[name].str()
    except Exception:
        value = str(config_vars[name])
    return value if value else default


def config_var_bool(name: str, default: bool = False) -> bool:
    """Return `name` as a bool, or `default`. "yes"/"true"/"1" are true, "no"/"false"/"0" false."""
    if name not in config_vars:
        return default
    return config_vars[name].bool()


def config_var_int(name: str, default: int = 0) -> int:
    """Return `name` as an int, or `default` if unset or not a number."""
    if name not in config_vars:
        return default
    try:
        return int(config_vars[name].str())
    except (ValueError, TypeError):
        return default


def config_var_list(name: str) -> List[str]:
    """Return `name` as a list of non-empty, stripped strings ([] when unset).

    A single value containing commas is split on them, so a setting can be written
    either as a yaml list or as one "a, b, c" string.
    """
    if name not in config_vars:
        return []
    values = config_vars[name].list()
    if len(values) == 1:
        value = str(values[0])
        if "," in value:
            values = [part.strip() for part in value.split(",")]
    return [str(value).strip() for value in values if str(value).strip()]
