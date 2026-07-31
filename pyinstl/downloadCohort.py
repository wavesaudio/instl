#!/usr/bin/env python3.12

"""Rollout cohort assignment for the download enhancement work.

Named cohorts let completion/retry/resume/restart/checksum metrics be compared
cohort-against-cohort during rollout. Each cohort layers one more behavior on
top of the previous (atomicity -> resume -> retry -> adaptive -> ux).

The label is derived from the configured ``DOWNLOAD_COHORT`` value plus the
rollout flag set, and is always one of :data:`COHORTS`; unknown or missing
values fall back to :data:`CONTROL_COHORT` so untagged installs appear in
the baseline cohort. Per-user assignment is owned by whichever rollout tool
sets ``DOWNLOAD_COHORT`` — this module only normalizes the label and keeps
it consistent with the active flags, so a misconfigured rollout cannot claim
a "resume" cohort while the resume flag is off.

The cohort is emitted on the ``download.capability`` event and consumed by
Central without further interpretation.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

CONTROL_COHORT = "control"
ATOMICITY_COHORT = "atomicity"
RESUME_COHORT = "resume"
RETRY_COHORT = "retry"
ADAPTIVE_COHORT = "adaptive"
UX_COHORT = "ux"

COHORTS: tuple[str, ...] = (
    CONTROL_COHORT,
    ATOMICITY_COHORT,
    RESUME_COHORT,
    RETRY_COHORT,
    ADAPTIVE_COHORT,
    UX_COHORT,
)


_REQUIRED_FLAGS_BY_COHORT: dict[str, tuple[str, ...]] = {
    CONTROL_COHORT: (),
    # atomicity is always-on in shipped builds, so there is no flag to gate on;
    # the label still separates rollout-queue installs from untagged `control`
    ATOMICITY_COHORT: (),
    RESUME_COHORT: ("DOWNLOAD_RESUME_ENABLED",),
    RETRY_COHORT: ("DOWNLOAD_RESUME_ENABLED", "DOWNLOAD_RETRY_POLICY_ENABLED"),
    ADAPTIVE_COHORT: (
        "DOWNLOAD_RESUME_ENABLED",
        "DOWNLOAD_RETRY_POLICY_ENABLED",
        "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED",
    ),
    UX_COHORT: (
        "DOWNLOAD_RESUME_ENABLED",
        "DOWNLOAD_RETRY_POLICY_ENABLED",
        "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED",
        "DOWNLOAD_CENTRAL_UX_ENABLED",
    ),
}


def normalize_cohort(raw: Any) -> str:
    """Return one of :data:`COHORTS`, or :data:`CONTROL_COHORT` if unknown."""
    if raw is None:
        return CONTROL_COHORT
    label = str(raw).strip().lower()
    if label in COHORTS:
        return label
    return CONTROL_COHORT


def required_flags_for(cohort: str) -> tuple[str, ...]:
    """Return the rollout flags that must be ``yes`` for ``cohort``, if any."""
    return _REQUIRED_FLAGS_BY_COHORT.get(normalize_cohort(cohort), ())


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("yes", "true", "1", "on"):
        return True
    if text in ("no", "false", "0", "off", ""):
        return False
    return False


def _read_flag(config_vars: Any, name: str, default: bool) -> bool:
    try:
        if config_vars is None:
            return default
        # `config_vars` is the instl ConfigVarStack-like object: `__getitem__`
        # returns a variable with `.bool()`. Mapping-style access is for tests.
        if hasattr(config_vars, "__contains__") and name not in config_vars:
            return default
        var = config_vars[name]
        if hasattr(var, "bool"):
            return bool(var.bool())
        return _coerce_bool(var)
    except Exception:
        return default


def _read_str(config_vars: Any, name: str, default: str) -> str:
    try:
        if config_vars is None:
            return default
        if hasattr(config_vars, "__contains__") and name not in config_vars:
            return default
        var = config_vars[name]
        if hasattr(var, "str"):
            return str(var.str())
        return str(var)
    except Exception:
        return default


def resolve_cohort_from_config(config_vars: Any) -> str:
    """Resolve the active cohort label from ``DOWNLOAD_COHORT``.

    When a flag required by the requested cohort is off, the cohort is
    downgraded one step at a time until every required flag is satisfied: an
    install labelled ``resume`` with ``DOWNLOAD_RESUME_ENABLED=no`` is
    recorded as ``control``.
    """
    raw = _read_str(config_vars, "DOWNLOAD_COHORT", CONTROL_COHORT)
    cohort = normalize_cohort(raw)
    flags = active_flags_from_config(config_vars)
    return downgrade_cohort_to_active_flags(cohort, flags)


def downgrade_cohort_to_active_flags(cohort: str, active_flags: Mapping[str, bool]) -> str:
    """Walk ``cohort`` down :data:`COHORTS` until every required flag is set."""
    normalized = normalize_cohort(cohort)
    index = COHORTS.index(normalized)
    while index >= 0:
        candidate = COHORTS[index]
        required = required_flags_for(candidate)
        if all(bool(active_flags.get(flag, False)) for flag in required):
            return candidate
        index -= 1
    return CONTROL_COHORT


_TRACKED_FLAGS: tuple[tuple[str, bool], ...] = (
    ("DOWNLOAD_TELEMETRY_ENABLED", True),
    ("DOWNLOAD_RESUME_ENABLED", False),
    ("DOWNLOAD_RETRY_POLICY_ENABLED", True),
    ("DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED", False),
    ("DOWNLOAD_CENTRAL_UX_ENABLED", False),
    # connectivity-loss recovery layers, so rollout can retreat one behavior
    # at a time without a code change
    ("DOWNLOAD_RECONCILE_MISSING_OUTPUTS", True),
    ("DOWNLOAD_OFFLINE_HOLD_ENABLED", True),
    ("DOWNLOAD_CURL_STALL_DETECTION", True),
    # set to true only by a NEW Central, which treats backend-hold evidence as
    # informational and never auto-pauses on it; default FALSE so an old
    # Central sees only the legacy event stream while the engine still recovers
    ("DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD", False),
    # checksum-verify counts ALL bad files and the redownload pass always runs,
    # budget-bounded (see InstlClient.yaml)
    ("DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES", True),
)


def active_flags_from_config(config_vars: Any) -> dict[str, bool]:
    """Return the tracked rollout flag map for telemetry/capability emission."""
    return {name: _read_flag(config_vars, name, default) for name, default in _TRACKED_FLAGS}


def tracked_flag_names() -> tuple[str, ...]:
    """Return the rollout flag names tracked by the capability event."""
    return tuple(name for name, _ in _TRACKED_FLAGS)


__all__ = [
    "ADAPTIVE_COHORT",
    "ATOMICITY_COHORT",
    "CONTROL_COHORT",
    "COHORTS",
    "RESUME_COHORT",
    "RETRY_COHORT",
    "UX_COHORT",
    "active_flags_from_config",
    "downgrade_cohort_to_active_flags",
    "normalize_cohort",
    "required_flags_for",
    "resolve_cohort_from_config",
    "tracked_flag_names",
]
