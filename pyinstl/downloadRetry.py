#!/usr/bin/env python3.12

"""Retry matrix and backoff for the bulk download engine.

Phase 3 work item ``P3-004`` and ``P3-005``. This module consumes the
normalized :class:`DownloadFailureClass` taxonomy from
``downloadFailures.py`` and produces deterministic, testable retry
decisions and structured retry-decision log payloads.

Design goals (kept aligned with the workspace docs in
``download-system-enhancement``):

* The retry matrix is data; retry behavior must be derivable from
  ``DownloadFailureClass`` alone so it can be unit-tested per class.
* Decisions are one of ``resume``, ``restart``, or ``fail_terminal``.
  ``resume`` and ``restart`` are both "retry" outcomes; the choice
  between them is the caller's combined view of the matrix
  (``restart_required``) and the existing Phase 2 ``resume_decision``
  capability gate.
* Backoff is exponential with jitter, bounded by class-specific
  ``base_delay_seconds`` and ``max_delay_seconds``. ``Retry-After``
  (RFC 9110) is honored when the class is configured to respect it.
* The module never logs or persists raw URLs, cookies, headers, or
  signed-URL material — its output is enum + ints + a small literal
  reason string.
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping

_log = logging.getLogger(__name__)

try:
    from .downloadFailures import (
        DownloadFailureClass,
        DownloadFailureInfo,
        is_retryable_failure_class,
    )
except ImportError:  # tests import via sys.path without the pyinstl package context
    from downloadFailures import (  # type: ignore[no-redef]
        DownloadFailureClass,
        DownloadFailureInfo,
        is_retryable_failure_class,
    )

DOWNLOAD_RETRY_DECISION_LOG_PREFIX = "DOWNLOAD_RETRY_DECISION"


# -- Decision action --------------------------------------------------------


class RetryAction(str, Enum):
    """Caller-visible retry decision.

    ``RESUME`` and ``RESTART`` both mean "try again." They differ only in
    whether the partial temp artifact can be appended to (``RESUME``) or
    must be discarded and re-transferred from byte zero (``RESTART``).
    """

    RESUME = "resume"
    RESTART = "restart"
    FAIL_TERMINAL = "fail_terminal"


# -- Per-class policy -------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 0
    base_delay_seconds: float = 0.0
    max_delay_seconds: float = 0.0
    jitter_fraction: float = 0.0
    restart_required: bool = False
    respect_retry_after: bool = False


# Terminal classes (max_attempts == 0) intentionally never retry. The matrix
# is the single source of truth for retryability so that Phase 5 telemetry
# and Central UX can derive next-action labels from class alone.
DEFAULT_RETRY_MATRIX: Mapping[DownloadFailureClass, RetryPolicy] = {
    DownloadFailureClass.DNS_RESOLUTION: RetryPolicy(
        max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.25),
    DownloadFailureClass.TCP_CONNECT: RetryPolicy(
        max_attempts=5, base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.25),
    DownloadFailureClass.TLS: RetryPolicy(),  # terminal: usually configuration/cert issue
    DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE: RetryPolicy(
        max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=30.0, jitter_fraction=0.25,
        respect_retry_after=True),
    DownloadFailureClass.TIMEOUT_DURING_TRANSFER: RetryPolicy(
        max_attempts=5, base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.25),
    DownloadFailureClass.HTTP_429: RetryPolicy(
        max_attempts=5, base_delay_seconds=5.0, max_delay_seconds=60.0, jitter_fraction=0.20,
        respect_retry_after=True),
    DownloadFailureClass.HTTP_5XX: RetryPolicy(
        max_attempts=5, base_delay_seconds=2.0, max_delay_seconds=60.0, jitter_fraction=0.25,
        respect_retry_after=True),
    DownloadFailureClass.HTTP_AUTH_POLICY: RetryPolicy(),  # terminal: requires user/auth action
    DownloadFailureClass.HTTP_4XX: RetryPolicy(),  # terminal: client-side
    DownloadFailureClass.HTTP_ERROR: RetryPolicy(
        max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=30.0, jitter_fraction=0.25,
        respect_retry_after=True),
    DownloadFailureClass.DISK_WRITE: RetryPolicy(),
    DownloadFailureClass.DISK_SPACE: RetryPolicy(),
    DownloadFailureClass.PERMISSION_DENIED: RetryPolicy(),
    DownloadFailureClass.CHECKSUM_MISMATCH: RetryPolicy(
        max_attempts=2, base_delay_seconds=0.0, max_delay_seconds=0.0, restart_required=True),
    DownloadFailureClass.PARTIAL_TRANSFER: RetryPolicy(
        max_attempts=5, base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.25),
    DownloadFailureClass.PROCESS_TERMINATED: RetryPolicy(
        max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=15.0, jitter_fraction=0.25),
    DownloadFailureClass.CANCELLED: RetryPolicy(),  # user-initiated
    DownloadFailureClass.MISSING_AFTER_TRANSFER: RetryPolicy(
        max_attempts=2, base_delay_seconds=0.0, max_delay_seconds=0.0, restart_required=True),
    DownloadFailureClass.MALFORMED_URL: RetryPolicy(),  # terminal: bad input
    DownloadFailureClass.NETWORK_SEND_ERROR: RetryPolicy(
        max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.25),
    DownloadFailureClass.NETWORK_RECEIVE_ERROR: RetryPolicy(
        max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=30.0, jitter_fraction=0.25),
    DownloadFailureClass.UNKNOWN_DOWNLOAD_ERROR: RetryPolicy(),  # conservative: fail terminally
}


def policy_for(
        failure_class: DownloadFailureClass | str,
        matrix: Mapping[DownloadFailureClass, RetryPolicy] = DEFAULT_RETRY_MATRIX) -> RetryPolicy:
    if not isinstance(failure_class, DownloadFailureClass):
        try:
            failure_class = DownloadFailureClass(failure_class)
        except ValueError:
            return RetryPolicy()
    return matrix.get(failure_class, RetryPolicy())


# -- Backoff ----------------------------------------------------------------


def compute_backoff_seconds(
        attempt: int,
        policy: RetryPolicy,
        retry_after_seconds: int | None = None,
        random_unit_fn: Callable[[], float] | None = None) -> float:
    """Return the delay in seconds before retry attempt ``attempt`` (1-indexed).

    ``retry_after_seconds`` wins when the policy honors it and the server
    asked for a longer wait. Jitter is full-jitter style multiplied by
    ``policy.jitter_fraction`` and pulled from ``random_unit_fn`` (default
    :func:`random.random`).
    """
    if policy.max_attempts <= 0 or attempt < 1:
        return 0.0

    exponent = max(0, attempt - 1)
    base = policy.base_delay_seconds * (2 ** exponent)
    delay = min(base, policy.max_delay_seconds) if policy.max_delay_seconds > 0 else base

    if policy.jitter_fraction > 0:
        random_unit_fn = random_unit_fn or random.random
        unit = max(0.0, min(1.0, float(random_unit_fn())))
        delay = delay * (1.0 + policy.jitter_fraction * unit)
        if policy.max_delay_seconds > 0:
            delay = min(delay, policy.max_delay_seconds * (1.0 + policy.jitter_fraction))

    if (policy.respect_retry_after
            and retry_after_seconds is not None
            and retry_after_seconds >= 0
            and retry_after_seconds > delay):
        delay = float(retry_after_seconds)

    return max(0.0, float(delay))


# -- Decision ---------------------------------------------------------------


@dataclass(frozen=True)
class RetryDecision:
    action: RetryAction
    failure_class: DownloadFailureClass
    attempt: int
    delay_seconds: float
    reason: str
    restart_required: bool = False
    retry_after_seconds: int | None = None
    http_status: int | None = None
    curl_exit_code: int | None = None

    @property
    def will_retry(self) -> bool:
        return self.action in (RetryAction.RESUME, RetryAction.RESTART)

    def to_event(
            self,
            session_id: str | None = None,
            file_id: str | None = None,
            received_bytes: int | None = None,
            concurrency: int | None = None,
            timestamp: str | None = None) -> dict:
        """Build the structured ``download.retry_decision`` event payload.

        Field shape matches ``telemetry-diagnostics.md``. Only enum/int
        fields are emitted; no URLs, headers, or auth material flow
        through this helper.
        """
        event = {
            "event": "download.retry_decision",
            "sessionId": session_id,
            "fileId": file_id,
            "failureClass": self.failure_class.value,
            "attempt": self.attempt,
            "decision": self.action.value,
            "delayMs": int(round(self.delay_seconds * 1000)),
            "restartRequired": self.restart_required,
            "reason": self.reason,
            "receivedBytes": received_bytes,
            "concurrency": concurrency,
            "retryAfterSeconds": self.retry_after_seconds,
            "httpStatus": self.http_status,
            "curlExitCode": self.curl_exit_code,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
        }
        return event


def decide_retry(
        failure: DownloadFailureInfo,
        previous_retry_count: int,
        *,
        resume_eligible: bool = False,
        matrix: Mapping[DownloadFailureClass, RetryPolicy] = DEFAULT_RETRY_MATRIX,
        random_unit_fn: Callable[[], float] | None = None) -> RetryDecision:
    """Decide whether and how to retry after ``failure``.

    Parameters
    ----------
    failure:
        Normalized failure metadata from ``downloadFailures.classify_*``.
    previous_retry_count:
        Number of retry attempts already made for this file. ``0`` means
        we have only seen the original transfer fail; the next decision
        would be attempt ``1``.
    resume_eligible:
        Whether the Phase 2 ``resume_decision_for_download_item`` said
        the partial temp artifact is safe to append to. Ignored when the
        matrix forces ``restart_required``.
    matrix:
        Override matrix for tests. Defaults to :data:`DEFAULT_RETRY_MATRIX`.
    random_unit_fn:
        Injectable RNG returning a value in ``[0, 1)``. Defaults to
        :func:`random.random`. Used only when the policy has jitter.
    """
    policy = policy_for(failure.failure_class, matrix)
    next_attempt = max(1, int(previous_retry_count) + 1)

    if policy.max_attempts <= 0 or not is_retryable_failure_class(failure.failure_class):
        return RetryDecision(
            action=RetryAction.FAIL_TERMINAL,
            failure_class=failure.failure_class,
            attempt=next_attempt,
            delay_seconds=0.0,
            reason="terminal_failure_class",
            retry_after_seconds=failure.retry_after_seconds,
            http_status=failure.http_status,
            curl_exit_code=failure.curl_exit_code,
        )

    if next_attempt > policy.max_attempts:
        return RetryDecision(
            action=RetryAction.FAIL_TERMINAL,
            failure_class=failure.failure_class,
            attempt=next_attempt,
            delay_seconds=0.0,
            reason="max_attempts_exhausted",
            retry_after_seconds=failure.retry_after_seconds,
            http_status=failure.http_status,
            curl_exit_code=failure.curl_exit_code,
        )

    delay = compute_backoff_seconds(
        next_attempt,
        policy,
        retry_after_seconds=failure.retry_after_seconds,
        random_unit_fn=random_unit_fn,
    )

    if policy.restart_required:
        action = RetryAction.RESTART
        reason = "restart_required_by_class"
    elif resume_eligible:
        action = RetryAction.RESUME
        reason = "resume_eligible_partial"
    else:
        action = RetryAction.RESTART
        reason = "resume_not_eligible"

    return RetryDecision(
        action=action,
        failure_class=failure.failure_class,
        attempt=next_attempt,
        delay_seconds=delay,
        reason=reason,
        restart_required=policy.restart_required,
        retry_after_seconds=failure.retry_after_seconds,
        http_status=failure.http_status,
        curl_exit_code=failure.curl_exit_code,
    )


# -- Structured log line ----------------------------------------------------


_DISALLOWED_EVENT_FIELDS = frozenset({
    # Defense-in-depth: callers must not pass any of these. The formatter
    # drops them rather than emit auth/header material in a retry log.
    "url", "URL", "urlRedacted", "headers", "cookie", "cookies",
    "authorization", "Authorization", "policy", "signature",
    "Signed-URL", "signedUrl", "tempPath", "finalPath",
})


def format_retry_decision_log_line(
        decision: RetryDecision,
        *,
        session_id: str | None = None,
        file_id: str | None = None,
        repo_path: str | None = None,
        received_bytes: int | None = None,
        concurrency: int | None = None,
        timestamp: str | None = None,
        extra: Mapping[str, Any] | None = None) -> str:
    """Return a single-line, ingest-friendly log record for a retry decision.

    The output is the literal prefix :data:`DOWNLOAD_RETRY_DECISION_LOG_PREFIX`
    followed by a space and a compact JSON object. Privacy review:
    callers must not pass raw URLs, cookies, headers, signed URL policies,
    or local user paths in ``extra``; the formatter additionally drops a
    fixed denylist of keys before serializing.

    ``repo_path`` is the in-repo logical path (e.g. ``foo/bar.bundle``)
    from the manifest, not a local user path, and is safe.
    """
    payload = decision.to_event(
        session_id=session_id,
        file_id=file_id,
        received_bytes=received_bytes,
        concurrency=concurrency,
        timestamp=timestamp,
    )
    if repo_path is not None:
        payload["repoPath"] = repo_path
    if extra:
        for key, value in extra.items():
            if key in _DISALLOWED_EVENT_FIELDS:
                continue
            payload[key] = value
    return f"{DOWNLOAD_RETRY_DECISION_LOG_PREFIX} {json.dumps(payload, sort_keys=True)}"


def sleep_backoff(delay_seconds: float, *, channel=None) -> bool:
    """Sleep for ``delay_seconds`` or return early on ``try_now``.

    Phase 7 control channel hook. Replaces a naked ``time.sleep`` in
    retry loops so Central can send ``{"cmd":"try_now"}`` and skip
    the remaining backoff. When ``channel`` is ``None``, the function
    falls back to the process-wide singleton from
    :mod:`downloadControlChannel`; tests inject a stub channel
    directly.

    Returns ``True`` when the sleep was interrupted by a ``try_now``
    command, ``False`` when the full ``delay_seconds`` elapsed (or
    when ``delay_seconds`` was non-positive).
    """
    if delay_seconds is None or delay_seconds <= 0:
        return False
    if channel is None:
        try:
            from .downloadControlChannel import get_global_channel  # local import: cycle-safe
        except ImportError:  # tests import without pyinstl package context
            try:
                from downloadControlChannel import get_global_channel  # type: ignore[no-redef]
            except ImportError:
                # Control channel not available; fall back to a plain sleep.
                time.sleep(float(delay_seconds))
                return False
        try:
            channel = get_global_channel()
        except Exception as ex:  # pragma: no cover - defensive
            _log.debug(f"control channel unavailable, falling back to time.sleep: {ex}")
            time.sleep(float(delay_seconds))
            return False
    woke = channel.sleep_or_wake(float(delay_seconds))
    if woke:
        # Drain the consume-once flag so future spurious wakes don't
        # masquerade as another try_now.
        try:
            channel.try_now_requested()
        except Exception:  # pragma: no cover - defensive
            pass
    return woke


__all__ = [
    "DEFAULT_RETRY_MATRIX",
    "DOWNLOAD_RETRY_DECISION_LOG_PREFIX",
    "RetryAction",
    "RetryDecision",
    "RetryPolicy",
    "compute_backoff_seconds",
    "decide_retry",
    "format_retry_decision_log_line",
    "policy_for",
    "sleep_backoff",
]
