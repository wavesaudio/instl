#!/usr/bin/env python3.12

import os
from contextlib import contextmanager


_DENIED_ENV_NAMES = {
    "PYTHONBREAKPOINT",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONHOME",
    "PYTHONINSPECT",
    "PYTHONNOUSERSITE",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "PYTHONWARNINGS",
}

_DENIED_ENV_PREFIXES = (
    "LD_",
    "DYLD_",
)


def _extra_deny_patterns(config_vars):
    if config_vars is None:
        return []
    if "ENV_VARS_DENYLIST" not in config_vars:
        return []
    return [str(val).strip() for val in config_vars["ENV_VARS_DENYLIST"] if str(val).strip()]


def is_env_var_denied(var_name, config_vars=None):
    normalized_name = str(var_name).strip().upper()
    if not normalized_name:
        return False
    if normalized_name in _DENIED_ENV_NAMES:
        return True
    if normalized_name.startswith(_DENIED_ENV_PREFIXES):
        return True

    for deny_pattern in _extra_deny_patterns(config_vars):
        deny_pattern = deny_pattern.upper()
        if deny_pattern.endswith("*"):
            if normalized_name.startswith(deny_pattern[:-1]):
                return True
        elif normalized_name == deny_pattern:
            return True

    return False


def build_sanitized_env(base_env=None, config_vars=None):
    source_env = dict(os.environ) if base_env is None else dict(base_env)
    sanitized_env = {
        env_name: env_value
        for env_name, env_value in source_env.items()
        if not is_env_var_denied(env_name, config_vars=config_vars)
    }
    return sanitized_env


@contextmanager
def temporary_sanitized_env(config_vars=None):
    original_env = dict(os.environ)
    os.environ.clear()
    os.environ.update(build_sanitized_env(original_env, config_vars=config_vars))
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original_env)
