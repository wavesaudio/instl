#!/usr/bin/env python3.12

"""Adaptive download concurrency controller.

Phase 4 work items ``P4-002`` (bounds), ``P4-003`` (controller), and
``P4-004`` (manual override). The controller is intentionally
**between-session**: it inspects the persisted ``session-summary.json``
written by ``downloadObservability`` for the previous ``instl``
invocation and produces a ``PARALLEL_SYNC`` recommendation for the
next run.

Why not within-session? Today ``instl`` writes N curl config files at
plan time and hands them to ``ParallelRun``; reducing or growing the
process pool mid-run would require restructuring the curl driver. A
between-session adapter is the smallest correct step that ``D-005``
(independent feature flags) and ``D-017`` (this decision) allow us to
ship.

Design contract:

* The matrix of (signal -> action) is data and unit-testable per branch.
* The recommendation never goes below ``min``, never above ``max``, and
  never moves by more than the configured step in a single decision.
* Manual user overrides (``PARALLEL_SYNC_USER_OVERRIDE``) bypass the
  controller entirely. The feature flag
  ``DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED`` is the kill switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


# Defaults are conservative: 8 processes is the documented safe baseline
# for CloudFront with signed cookies; the historical PARALLEL_SYNC=50 is
# kept as the absolute ceiling so a healthy run can climb back to it.
DEFAULT_MIN_CONCURRENCY = 2
DEFAULT_MAX_CONCURRENCY = 50
DEFAULT_START_CONCURRENCY = 8
DEFAULT_INCREASE_STEP = 2
DEFAULT_DECREASE_STEP = 4
DEFAULT_ERROR_RATE_BACKOFF_THRESHOLD = 0.15  # 15% retryable errors -> back off
DEFAULT_ERROR_RATE_GROW_THRESHOLD = 0.02  # under 2% errors and healthy throughput -> grow


class AdaptiveAction(str, Enum):
    KEEP = "keep"
    INCREASE = "increase"
    DECREASE = "decrease"
    OVERRIDE = "override"
    DISABLED = "disabled"
    FRESH_START = "fresh_start"


@dataclass(frozen=True)
class ConcurrencyBounds:
    """Bounds and step sizes for the controller.

    All values are positive integers. ``min`` and ``max`` define the
    closed range; ``start`` is the recommendation when there is no
    prior session summary. ``increase_step`` and ``decrease_step``
    bound how far a single decision can move from the previous run.
    """

    min_concurrency: int = DEFAULT_MIN_CONCURRENCY
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    start_concurrency: int = DEFAULT_START_CONCURRENCY
    increase_step: int = DEFAULT_INCREASE_STEP
    decrease_step: int = DEFAULT_DECREASE_STEP
    error_rate_backoff_threshold: float = DEFAULT_ERROR_RATE_BACKOFF_THRESHOLD
    error_rate_grow_threshold: float = DEFAULT_ERROR_RATE_GROW_THRESHOLD

    def __post_init__(self) -> None:
        # Use object.__setattr__ because the dataclass is frozen but we
        # still want post-init normalization. This catches misconfigured
        # YAML values without surprising the caller.
        normalized_min = max(1, int(self.min_concurrency))
        normalized_max = max(normalized_min, int(self.max_concurrency))
        normalized_start = max(normalized_min, min(normalized_max, int(self.start_concurrency)))
        object.__setattr__(self, "min_concurrency", normalized_min)
        object.__setattr__(self, "max_concurrency", normalized_max)
        object.__setattr__(self, "start_concurrency", normalized_start)
        object.__setattr__(self, "increase_step", max(1, int(self.increase_step)))
        object.__setattr__(self, "decrease_step", max(1, int(self.decrease_step)))

    def clamp(self, value: int) -> int:
        return max(self.min_concurrency, min(self.max_concurrency, int(value)))


@dataclass(frozen=True)
class ConcurrencyDecision:
    """Output of one controller decision."""

    action: AdaptiveAction
    recommended: int
    previous: int | None
    reason: str
    bounds: ConcurrencyBounds


# -- Controller -------------------------------------------------------------


def decide_next_concurrency(
        previous_summary: Mapping[str, Any] | None,
        *,
        bounds: ConcurrencyBounds | None = None,
        adaptive_enabled: bool = True,
        user_override: int | None = None,
        configured_default: int | None = None) -> ConcurrencyDecision:
    """Return the recommended PARALLEL_SYNC for the next run.

    Parameters
    ----------
    previous_summary:
        Output of ``downloadObservability.load_session_summary`` for the
        previous ``instl`` invocation. ``None`` means cold start.
    bounds:
        ``ConcurrencyBounds`` to apply. Defaults to module defaults.
    adaptive_enabled:
        Feature-flag kill switch. When ``False``, the controller falls
        back to ``user_override`` if present, then ``configured_default``,
        then ``bounds.start_concurrency``.
    user_override:
        If a non-``None`` positive integer, the controller honors it
        verbatim (clamped to bounds for safety). This implements ``P4-004``
        and ``D-017`` — user overrides bypass adaptation entirely.
    configured_default:
        The YAML/config baseline ``PARALLEL_SYNC`` value. Used only when
        adaptation is disabled and no override is set.
    """
    effective_bounds = bounds or ConcurrencyBounds()

    if user_override is not None:
        clamped = effective_bounds.clamp(int(user_override))
        return ConcurrencyDecision(
            action=AdaptiveAction.OVERRIDE,
            recommended=clamped,
            previous=int(previous_summary["concurrencyPlanned"]) if _has_previous_concurrency(previous_summary) else None,
            reason="user_override",
            bounds=effective_bounds,
        )

    if not adaptive_enabled:
        baseline = configured_default if configured_default is not None else effective_bounds.start_concurrency
        return ConcurrencyDecision(
            action=AdaptiveAction.DISABLED,
            recommended=effective_bounds.clamp(int(baseline)),
            previous=int(previous_summary["concurrencyPlanned"]) if _has_previous_concurrency(previous_summary) else None,
            reason="adaptive_disabled",
            bounds=effective_bounds,
        )

    if not previous_summary or not _has_previous_concurrency(previous_summary):
        return ConcurrencyDecision(
            action=AdaptiveAction.FRESH_START,
            recommended=effective_bounds.start_concurrency,
            previous=None,
            reason="no_prior_session",
            bounds=effective_bounds,
        )

    previous = int(previous_summary["concurrencyPlanned"])
    totals = previous_summary.get("totals") or {}
    attempts = int(totals.get("attempts", 0) or 0)
    successes = int(totals.get("successes", 0) or 0)
    failures_terminal = int(totals.get("failuresTerminal", 0) or 0)
    failures_retryable = int(totals.get("failuresRetryable", 0) or 0)
    restarts = int(totals.get("restarts", 0) or 0)
    retryable_error_rate = float(previous_summary.get("retryableErrorRate", 0.0) or 0.0)
    total_error_rate = float(previous_summary.get("errorRate", 0.0) or 0.0)

    # Empty run: nothing transferred, nothing to learn from.
    if attempts == 0:
        return ConcurrencyDecision(
            action=AdaptiveAction.KEEP,
            recommended=effective_bounds.clamp(previous),
            previous=previous,
            reason="no_attempts_recorded",
            bounds=effective_bounds,
        )

    # Strong distress: terminal failures or restart-required clusters
    # mean recent throughput was unhealthy. Back off by the full step.
    if failures_terminal > 0 or restarts >= max(1, attempts // 5):
        return ConcurrencyDecision(
            action=AdaptiveAction.DECREASE,
            recommended=effective_bounds.clamp(previous - effective_bounds.decrease_step),
            previous=previous,
            reason="terminal_or_restart_cluster",
            bounds=effective_bounds,
        )

    # Elevated retryable error rate: back off (slow/lossy network signal).
    if retryable_error_rate >= effective_bounds.error_rate_backoff_threshold:
        return ConcurrencyDecision(
            action=AdaptiveAction.DECREASE,
            recommended=effective_bounds.clamp(previous - effective_bounds.decrease_step),
            previous=previous,
            reason="retryable_error_rate_above_backoff_threshold",
            bounds=effective_bounds,
        )

    # Healthy run with headroom: nudge concurrency up.
    if total_error_rate <= effective_bounds.error_rate_grow_threshold and successes >= max(4, attempts // 2):
        if previous < effective_bounds.max_concurrency:
            return ConcurrencyDecision(
                action=AdaptiveAction.INCREASE,
                recommended=effective_bounds.clamp(previous + effective_bounds.increase_step),
                previous=previous,
                reason="healthy_throughput_with_headroom",
                bounds=effective_bounds,
            )

    # Otherwise hold steady; the controller never moves without a signal.
    return ConcurrencyDecision(
        action=AdaptiveAction.KEEP,
        recommended=effective_bounds.clamp(previous),
        previous=previous,
        reason="signal_within_band",
        bounds=effective_bounds,
    )


def _has_previous_concurrency(previous_summary: Mapping[str, Any] | None) -> bool:
    if not previous_summary:
        return False
    value = previous_summary.get("concurrencyPlanned")
    try:
        return value is not None and int(value) > 0
    except (TypeError, ValueError):
        return False


# -- Config var bridge (used by instlInstanceSync_url) ---------------------


def resolve_concurrency_from_config(config_vars, summary_loader=None) -> ConcurrencyDecision:
    """Read the relevant config vars and run the controller.

    ``config_vars`` is the runtime ``configVar.ConfigVarStack`` instance
    used by ``instl``. ``summary_loader`` is injectable for tests; in
    production it is :func:`downloadObservability.load_session_summary`.

    The function is forgiving: missing or malformed config falls back
    to module defaults so an old ``InstlClient.yaml`` keeps working.
    """
    bounds = _bounds_from_config(config_vars)
    adaptive_enabled = _bool_var(config_vars, "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED", default=False)
    user_override = _optional_positive_int(config_vars, "PARALLEL_SYNC_USER_OVERRIDE")
    configured_default = _optional_positive_int(config_vars, "PARALLEL_SYNC")

    previous_summary = None
    bookkeeping_dir = _str_var(config_vars, "LOCAL_REPO_BOOKKEEPING_DIR")
    if bookkeeping_dir and summary_loader is not None:
        try:
            previous_summary = summary_loader(bookkeeping_dir)
        except Exception:
            previous_summary = None

    return decide_next_concurrency(
        previous_summary,
        bounds=bounds,
        adaptive_enabled=adaptive_enabled,
        user_override=user_override,
        configured_default=configured_default,
    )


def _bounds_from_config(config_vars) -> ConcurrencyBounds:
    return ConcurrencyBounds(
        min_concurrency=_optional_positive_int(config_vars, "DOWNLOAD_CONCURRENCY_MIN") or DEFAULT_MIN_CONCURRENCY,
        max_concurrency=_optional_positive_int(config_vars, "DOWNLOAD_CONCURRENCY_MAX") or DEFAULT_MAX_CONCURRENCY,
        start_concurrency=_optional_positive_int(config_vars, "DOWNLOAD_CONCURRENCY_START") or DEFAULT_START_CONCURRENCY,
        increase_step=_optional_positive_int(config_vars, "DOWNLOAD_CONCURRENCY_INCREASE_STEP") or DEFAULT_INCREASE_STEP,
        decrease_step=_optional_positive_int(config_vars, "DOWNLOAD_CONCURRENCY_DECREASE_STEP") or DEFAULT_DECREASE_STEP,
        error_rate_backoff_threshold=_optional_positive_float(
            config_vars, "DOWNLOAD_CONCURRENCY_ERROR_BACKOFF") or DEFAULT_ERROR_RATE_BACKOFF_THRESHOLD,
        error_rate_grow_threshold=_optional_positive_float(
            config_vars, "DOWNLOAD_CONCURRENCY_ERROR_GROW") or DEFAULT_ERROR_RATE_GROW_THRESHOLD,
    )


def _bool_var(config_vars, name: str, default: bool = False) -> bool:
    try:
        if name not in config_vars:
            return default
        return bool(config_vars[name].bool())
    except Exception:
        return default


def _str_var(config_vars, name: str) -> str | None:
    try:
        if name not in config_vars:
            return None
        value = config_vars[name].str()
        return value or None
    except Exception:
        return None


def _optional_positive_int(config_vars, name: str) -> int | None:
    try:
        if name not in config_vars:
            return None
        raw = config_vars[name].str()
        if raw is None or raw == "":
            return None
        value = int(raw)
        return value if value > 0 else None
    except Exception:
        return None


def _optional_positive_float(config_vars, name: str) -> float | None:
    try:
        if name not in config_vars:
            return None
        raw = config_vars[name].str()
        if raw is None or raw == "":
            return None
        value = float(raw)
        return value if value > 0 else None
    except Exception:
        return None


__all__ = [
    "AdaptiveAction",
    "ConcurrencyBounds",
    "ConcurrencyDecision",
    "DEFAULT_DECREASE_STEP",
    "DEFAULT_ERROR_RATE_BACKOFF_THRESHOLD",
    "DEFAULT_ERROR_RATE_GROW_THRESHOLD",
    "DEFAULT_INCREASE_STEP",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_MIN_CONCURRENCY",
    "DEFAULT_START_CONCURRENCY",
    "decide_next_concurrency",
    "resolve_concurrency_from_config",
]
