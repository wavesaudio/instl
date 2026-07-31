#!/usr/bin/env python3.12

"""Retry matrix and backoff for the bulk download engine.

Consumes the normalized :class:`DownloadFailureClass` taxonomy from
``downloadFailures.py`` and produces retry decisions plus structured
retry-decision log payloads.

A decision is one of ``resume``, ``restart``, or ``fail_terminal``; choosing
between ``resume`` and ``restart`` is the caller's combined view of the matrix
(``restart_required``) and the ``resume_decision`` capability gate. Backoff is
exponential with jitter, bounded per class; ``Retry-After`` (RFC 9110) is
honored when the class is configured to respect it.

The module never logs or persists raw URLs, cookies, headers, or signed-URL
material — its output is enum + ints + a small literal reason string.
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

    ``RESUME`` and ``RESTART`` both mean "try again"; they differ in whether
    the partial temp artifact can be appended to or must be discarded and
    re-transferred from byte zero.
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


# Terminal classes (max_attempts == 0) never retry. The matrix is the single
# source of truth for retryability, so telemetry and Central UX can derive
# next-action labels from the failure class alone.
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

    ``retry_after_seconds`` wins when the policy honors it and the server asked
    for a longer wait.
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
        """Build the ``download.retry_decision`` event payload; field shape
        matches ``telemetry-diagnostics.md``."""
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

    ``previous_retry_count`` is the retries already made for this file, so
    ``0`` means only the original transfer has failed and the next decision is
    attempt ``1``. ``resume_eligible`` is what
    ``resume_decision_for_download_item`` said about appending to the partial
    temp artifact; it is ignored when the matrix forces ``restart_required``.
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
    # dropped by the formatter rather than emit auth/header material
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

    The literal prefix :data:`DOWNLOAD_RETRY_DECISION_LOG_PREFIX`, a space,
    then a compact JSON object. ``repo_path`` is the in-repo logical path from
    the manifest (e.g. ``foo/bar.bundle``), not a local user path, so it is
    safe to emit.
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

    Central can send ``{"cmd":"try_now"}`` to skip the remaining backoff. With
    ``channel`` at ``None`` the process-wide :mod:`downloadControlChannel`
    singleton is used. Returns ``True`` when a ``try_now`` interrupted the
    sleep, ``False`` when the full ``delay_seconds`` elapsed.
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
        # drain the consume-once flag, so a later spurious wake is not read as try_now
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
