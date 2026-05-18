#!/usr/bin/env python3.12

"""Phase 6 rollout cohort assignment for the download enhancement work.

The Phase 6 rollout plan (see
``download-system-enhancement/rollout-plan.md``) defines a small set of
named cohorts so completion/retry/resume/restart/checksum metrics can be
compared cohort-against-cohort during rollout. Each cohort layers one
additional behavior on top of the previous (atomicity -> resume ->
retry -> adaptive -> ux).

This module exposes :func:`normalize_cohort` and
:func:`resolve_cohort_from_config` so callers can derive a cohort label
deterministically from the configured ``DOWNLOAD_COHORT`` value plus the
rollout flag set. The output is one of :data:`COHORTS`. Unknown or
missing values fall back to :data:`CONTROL_COHORT` so untagged installs
always appear in the baseline cohort.

The cohort is emitted on the structured ``download.capability`` event
and consumed by Central (and any external telemetry pipeline) without
any further interpretation. There is no per-user assignment here: that
is owned by whichever rollout tool sets ``DOWNLOAD_COHORT``. This module
only normalizes the label and keeps it consistent with the active flag
set so a misconfigured rollout cannot, for example, claim a "resume"
cohort while the resume flag is off.
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
    # Atomicity is structural and always-on in shipped builds, so the
    # gate here is "the state schema exists." The cohort label is still
    # useful to distinguish installs that opted in to the rollout queue
    # from genuinely untagged installs in `control`.
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
    """Return one of :data:`COHORTS`.

    Unknown or empty values fall back to :data:`CONTROL_COHORT` so the
    structured capability event always carries a known label.
    """
    if raw is None:
        return CONTROL_COHORT
    label = str(raw).strip().lower()
    if label in COHORTS:
        return label
    return CONTROL_COHORT


def required_flags_for(cohort: str) -> tuple[str, ...]:
    """Return the rollout flags that must be ``yes`` for ``cohort``.

    Used by :func:`resolve_cohort_from_config` to downgrade a label when
    the corresponding flag set is not fully enabled. Returns an empty
    tuple for unknown cohorts.
    """
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
        # `config_vars` here is the instl ConfigVarStack-like object: it
        # supports `__contains__` and `__getitem__` returning a variable
        # with `.bool()`. Fall back to mapping-style access for tests.
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
    """Resolve the active cohort label from ``config_vars``.

    The label is taken from ``DOWNLOAD_COHORT``. If a flag required by
    the requested cohort is off, the cohort is downgraded one step at a
    time until every required flag is satisfied. This keeps telemetry
    honest: an install labelled ``resume`` with ``DOWNLOAD_RESUME_ENABLED=no``
    is recorded as ``control`` instead.
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
