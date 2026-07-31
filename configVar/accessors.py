#!/usr/bin/env python3.12


"""
    Copyright (c) 2012, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.

    Typed, documented accessor helpers for the most-used config_vars keys.

    Rationale:
        `config_vars` is a process-wide mutable singleton read by ~50 modules.
        Removing it is a large, invasive change that is explicitly *not* in scope
        for this incremental pass. Instead these helpers create a thin, typed
        *seam* over the handful of hottest read keys (OS identity, the main input
        file path). Routing call sites through them:
          - documents the type/shape each key is expected to resolve to,
          - gives a single place to later swap the backing store (a RunContext)
            for an injected one,
          - improves readability at the call site.

        These helpers deliberately keep reading from the global `config_vars`
        default, so they are behavior-preserving and non-breaking. They take an
        optional `cv` parameter (defaulting to the global) so that future work
        can pass an injected stack without touching the call sites again.
"""

from typing import List, Optional, Tuple
from pathlib import Path

from .configVarStack import config_vars as _global_config_vars


def current_os(cv=None) -> str:
    """Return the current OS family name, e.g. "Mac", "Win", "Linux".

    Reads `__CURRENT_OS__`. This is the single OS-identity string used for
    per-OS branching across the codebase.
    """
    cv = _global_config_vars if cv is None else cv
    return cv["__CURRENT_OS__"].str()


def current_os_names(cv=None) -> List[str]:
    """Return the list of current OS names (family + aliases), e.g. ["Mac", "Mac64"].

    Reads `__CURRENT_OS_NAMES__`. Use `is_current_os(name)` for membership tests.
    """
    cv = _global_config_vars if cv is None else cv
    return list(cv["__CURRENT_OS_NAMES__"])


def is_current_os(name: str, cv=None) -> bool:
    """True if `name` is one of the current OS names (`__CURRENT_OS_NAMES__`).

    Equivalent to the common `'Win' in list(config_vars["__CURRENT_OS_NAMES__"])`
    idiom, but typed and named.
    """
    return name in current_os_names(cv=cv)


def main_input_file_path(resolve: bool = False, cv=None) -> Optional[Path]:
    """Return `__MAIN_INPUT_FILE__` as a Path (the primary command input file).

    `resolve=True` expands vars and resolves the path, matching
    `config_vars["__MAIN_INPUT_FILE__"].Path(resolve=True)`.
    """
    cv = _global_config_vars if cv is None else cv
    return cv["__MAIN_INPUT_FILE__"].Path(resolve=resolve)


def main_input_file_str(cv=None) -> str:
    """Return `__MAIN_INPUT_FILE__` as an os.fspath-style string.

    Mirrors the common `os.fspath(config_vars["__MAIN_INPUT_FILE__"])` idiom used
    where an API wants a plain `str`/path-like rather than a `Path`.
    """
    import os
    cv = _global_config_vars if cv is None else cv
    return os.fspath(cv["__MAIN_INPUT_FILE__"])


def main_out_file_path(resolve: bool = False, cv=None) -> Optional[Path]:
    """Return `__MAIN_OUT_FILE__` as a Path (the primary command output file).

    `resolve=True` expands vars and resolves the path, matching
    `config_vars["__MAIN_OUT_FILE__"].Path(resolve=True)`.
    """
    cv = _global_config_vars if cv is None else cv
    return cv["__MAIN_OUT_FILE__"].Path(resolve=resolve)


def run_batch(cv=None) -> bool:
    """True if the emitted batch file should be run after writing (`__RUN_BATCH__`).

    Mirrors the ubiquitous `bool(config_vars["__RUN_BATCH__"])` flag check used by
    the doit/client/admin command flows to decide whether to execute the script.
    """
    cv = _global_config_vars if cv is None else cv
    return bool(cv["__RUN_BATCH__"])


def repo_rev(cv=None) -> int:
    """Return the source repository revision (`REPO_REV`) as an int.

    `REPO_REV` is the revision instl is operating against; admin/sync flows read it
    when computing folder hierarchy and revision ranges.
    """
    cv = _global_config_vars if cv is None else cv
    return cv["REPO_REV"].int()


def target_repo_rev(cv=None) -> int:
    """Return the target repository revision (`TARGET_REPO_REV`) as an int.

    The revision being published/activated; distinct from `REPO_REV` (the source).
    """
    cv = _global_config_vars if cv is None else cv
    return cv["TARGET_REPO_REV"].int()


def instl_version(cv=None) -> Tuple[int, ...]:
    """Return the running instl version (`__INSTL_VERSION__`) as a tuple of ints.

    Matches `list(map(int, list(config_vars["__INSTL_VERSION__"])))`, used for
    minimum-version compatibility checks.
    """
    cv = _global_config_vars if cv is None else cv
    return tuple(int(part) for part in list(cv["__INSTL_VERSION__"]))


def target_os(cv=None) -> str:
    """Return the target OS family name (`TARGET_OS`), e.g. "Mac", "Win".

    The OS instl is *building for* (may differ from `current_os()`, the host).
    """
    cv = _global_config_vars if cv is None else cv
    return cv["TARGET_OS"].str()


def target_os_names(cv=None) -> List[str]:
    """Return the list of target OS names (`TARGET_OS_NAMES`).

    Family + aliases for the OS instl is building for, mirroring `current_os_names`.
    """
    cv = _global_config_vars if cv is None else cv
    return list(cv["TARGET_OS_NAMES"])


# Typed readers for optional keys: a key that was never defined reads as its default
# rather than raising, which is what tweakable settings (the DOWNLOAD_* family and
# friends) want. The accessors above are for keys instl always defines.

def config_var_str(name: str, default=None, cv=None):
    """Return `name` as a non-empty string, or `default`."""
    cv = _global_config_vars if cv is None else cv
    if name not in cv:
        return default
    try:
        value = cv[name].str()
    except Exception:
        value = str(cv[name])
    return value if value else default


def config_var_bool(name: str, default: bool = False, cv=None) -> bool:
    """Return `name` as a bool, or `default`. "yes"/"true"/"1" are true, "no"/"false"/"0" false."""
    cv = _global_config_vars if cv is None else cv
    if name not in cv:
        return default
    return cv[name].bool()


def config_var_int(name: str, default: int = 0, cv=None) -> int:
    """Return `name` as an int, or `default` if unset or not a number."""
    cv = _global_config_vars if cv is None else cv
    if name not in cv:
        return default
    try:
        return int(cv[name].str())
    except (ValueError, TypeError):
        return default


def config_var_list(name: str, cv=None) -> List[str]:
    """Return `name` as a list of non-empty, stripped strings ([] when unset).

    A single value containing commas is split on them, so a setting can be written
    either as a yaml list or as one "a, b, c" string.
    """
    cv = _global_config_vars if cv is None else cv
    if name not in cv:
        return []
    values = cv[name].list()
    if len(values) == 1:
        value = str(values[0])
        if "," in value:
            values = [part.strip() for part in value.split(",")]
    return [str(value).strip() for value in values if str(value).strip()]
