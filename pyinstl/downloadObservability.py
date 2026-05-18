#!/usr/bin/env python3.12

"""Throughput and error sampling for the bulk download engine.

Phase 4 work item ``P4-001``. The adaptive concurrency controller in
``downloadConcurrency.py`` consumes the per-session summary written by
this module to choose ``PARALLEL_SYNC`` for the next run.

Design goals (kept aligned with the workspace docs in
``download-system-enhancement``):

* Aggregation runs in-process during a single ``instl`` invocation. It
  has no network or threading dependency; callers feed it normalized
  outcomes from the existing ``CheckDownloadFolderChecksum`` and
  ``_emit_retry_decision`` choke points.
* The persisted summary is a small JSON sidecar next to ``session.json``
  under ``$(LOCAL_REPO_BOOKKEEPING_DIR)/download-state``. It is
  client-owned local state; the controller is the only consumer.
* Privacy: hosts are stored as bare hostnames (no path, query, or
  fragment). No URLs, cookies, headers, signed-URL material, or local
  user paths flow through this module. ``D-014``/``D-016`` redaction
  rules apply.
* The module never raises during ``record_*`` calls — instrumentation
  must never break a sync run.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from downloadFailures import DownloadFailureClass


DOWNLOAD_OBSERVABILITY_SCHEMA_VERSION = 1
SESSION_SUMMARY_FILE_NAME = "session-summary.json"
STATE_DIR_NAME = "download-state"


# -- Outcome enum -----------------------------------------------------------


class DownloadOutcome(str):
    """Outcome of a single per-file attempt.

    Kept as a small string subclass so JSON serialization is trivial and
    callers can compare against literal strings without importing the
    type. Listed here so the controller can rely on a fixed vocabulary.
    """

    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    RESTART_FORCED = "restart_forced"


_VALID_OUTCOMES = frozenset({
    DownloadOutcome.SUCCESS,
    DownloadOutcome.FAILED_RETRYABLE,
    DownloadOutcome.FAILED_TERMINAL,
    DownloadOutcome.RESTART_FORCED,
})


# -- Host classification ----------------------------------------------------


def host_from_url(in_url: str | None) -> str | None:
    """Return the lowercase host of ``in_url`` or ``None``.

    Strips userinfo, port, query, fragment. Safe to log: hosts are not
    secret in this workspace's threat model and are needed by the
    capability matrix to bucket throughput/error signal per CDN host.
    """
    if not in_url:
        return None
    try:
        parsed = urlsplit(in_url)
    except ValueError:
        return None
    host = parsed.hostname
    if not host:
        # Treat as a relative path or malformed input; do not invent a host.
        return None
    return host.lower()


# -- Counters ---------------------------------------------------------------


@dataclass
class _HostCounters:
    attempts: int = 0
    successes: int = 0
    failures_retryable: int = 0
    failures_terminal: int = 0
    restarts: int = 0
    bytes_received: int = 0
    transfer_time_seconds: float = 0.0
    failure_classes: dict[str, int] = field(default_factory=dict)

    def record(self, outcome: str, *,
               failure_class: str | None,
               bytes_received: int,
               transfer_time_seconds: float) -> None:
        self.attempts += 1
        if bytes_received > 0:
            self.bytes_received += int(bytes_received)
        if transfer_time_seconds and transfer_time_seconds > 0:
            self.transfer_time_seconds += float(transfer_time_seconds)
        if outcome == DownloadOutcome.SUCCESS:
            self.successes += 1
        elif outcome == DownloadOutcome.FAILED_RETRYABLE:
            self.failures_retryable += 1
        elif outcome == DownloadOutcome.FAILED_TERMINAL:
            self.failures_terminal += 1
        elif outcome == DownloadOutcome.RESTART_FORCED:
            self.restarts += 1
        if failure_class:
            self.failure_classes[failure_class] = self.failure_classes.get(failure_class, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        # Round seconds to milliseconds so JSON diffs stay readable across
        # platforms and timer precisions.
        transfer_ms = int(round(self.transfer_time_seconds * 1000))
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "failuresRetryable": self.failures_retryable,
            "failuresTerminal": self.failures_terminal,
            "restarts": self.restarts,
            "bytesReceived": self.bytes_received,
            "transferMs": transfer_ms,
            "failureClasses": dict(self.failure_classes),
        }


# -- Observability session --------------------------------------------------


class DownloadObservability:
    """Per-session in-memory aggregator.

    Methods are safe to call from any code that already has a normalized
    outcome and (optionally) a source URL. Callers must not pass headers,
    cookies, signed-URL query strings, or local user paths — only the
    URL is consumed and only its host is retained.
    """

    def __init__(self, session_id: str | None = None,
                 concurrency_planned: int | None = None,
                 started_at: str | None = None,
                 wall_clock: "_WallClock | None" = None) -> None:
        self.session_id = session_id or "unknown"
        self.concurrency_planned = concurrency_planned
        self.started_at = started_at or _utc_now_iso()
        self._wall_clock = wall_clock or _WallClock()
        self._wall_start = self._wall_clock.monotonic()
        self._totals = _HostCounters()
        self._per_host: dict[str, _HostCounters] = {}
        self._files_planned: int = 0
        self._bytes_planned: int = 0
        self._finished_at: str | None = None
        self._wall_seconds: float | None = None

    # --- planning hooks ----------------------------------------------------

    def set_plan(self, files_planned: int | None, bytes_planned: int | None) -> None:
        try:
            if files_planned is not None:
                self._files_planned = max(0, int(files_planned))
            if bytes_planned is not None:
                self._bytes_planned = max(0, int(bytes_planned))
        except (TypeError, ValueError):
            # Planning data is best-effort; do not raise from instrumentation.
            return

    # --- recording hooks ---------------------------------------------------

    def record_outcome(self,
                       *,
                       outcome: str,
                       url: str | None = None,
                       host: str | None = None,
                       failure_class: DownloadFailureClass | str | None = None,
                       bytes_received: int | None = None,
                       transfer_time_seconds: float | None = None) -> None:
        """Record one per-file attempt outcome.

        ``url`` is consumed only to derive the host; nothing else is
        stored. ``host`` may be passed directly when the caller already
        has the bare host.
        """
        try:
            if outcome not in _VALID_OUTCOMES:
                return
            host_key = host or host_from_url(url) or "unknown"
            failure_value = _failure_class_value(failure_class)
            byte_count = int(bytes_received) if bytes_received is not None and bytes_received > 0 else 0
            transfer_seconds = float(transfer_time_seconds) if transfer_time_seconds and transfer_time_seconds > 0 else 0.0
            self._totals.record(
                outcome,
                failure_class=failure_value,
                bytes_received=byte_count,
                transfer_time_seconds=transfer_seconds,
            )
            host_counters = self._per_host.setdefault(host_key, _HostCounters())
            host_counters.record(
                outcome,
                failure_class=failure_value,
                bytes_received=byte_count,
                transfer_time_seconds=transfer_seconds,
            )
        except Exception:  # pragma: no cover - instrumentation must never raise
            return

    def record_retry_decision(self,
                              decision,
                              *,
                              url: str | None = None,
                              host: str | None = None,
                              bytes_received: int | None = None) -> None:
        """Map a ``RetryDecision`` to an outcome and record it.

        Used by ``_emit_retry_decision`` so retry events feed the sampler
        with no extra plumbing on the caller side. Successful transfers
        flow through ``record_outcome(outcome=SUCCESS, ...)`` separately.
        """
        try:
            action = getattr(decision, "action", None)
            failure_class = getattr(decision, "failure_class", None)
            action_value = getattr(action, "value", action)
            if action_value == "fail_terminal":
                outcome = DownloadOutcome.FAILED_TERMINAL
            elif action_value == "restart":
                outcome = DownloadOutcome.RESTART_FORCED
            else:
                outcome = DownloadOutcome.FAILED_RETRYABLE
            self.record_outcome(
                outcome=outcome,
                url=url,
                host=host,
                failure_class=failure_class,
                bytes_received=bytes_received,
            )
        except Exception:  # pragma: no cover
            return

    # --- snapshot/persist --------------------------------------------------

    def mark_finished(self) -> None:
        if self._finished_at is None:
            self._finished_at = _utc_now_iso()
            self._wall_seconds = max(0.0, self._wall_clock.monotonic() - self._wall_start)

    def snapshot(self) -> dict[str, Any]:
        wall_seconds = self._wall_seconds
        if wall_seconds is None:
            wall_seconds = max(0.0, self._wall_clock.monotonic() - self._wall_start)
        total_bytes = self._totals.bytes_received
        observed_throughput_bps = 0
        if wall_seconds > 0 and total_bytes > 0:
            observed_throughput_bps = int(total_bytes / wall_seconds)
        error_rate = 0.0
        if self._totals.attempts > 0:
            non_success = self._totals.attempts - self._totals.successes
            error_rate = round(non_success / self._totals.attempts, 4)
        retryable_rate = 0.0
        if self._totals.attempts > 0:
            retryable_rate = round(self._totals.failures_retryable / self._totals.attempts, 4)
        return {
            "schemaVersion": DOWNLOAD_OBSERVABILITY_SCHEMA_VERSION,
            "sessionId": self.session_id,
            "startedAt": self.started_at,
            "finishedAt": self._finished_at,
            "wallMs": int(round(wall_seconds * 1000)),
            "concurrencyPlanned": self.concurrency_planned,
            "filesPlanned": self._files_planned,
            "bytesPlanned": self._bytes_planned,
            "totals": self._totals.to_dict(),
            "observedThroughputBytesPerSecond": observed_throughput_bps,
            "errorRate": error_rate,
            "retryableErrorRate": retryable_rate,
            "hosts": {
                host: counters.to_dict()
                for host, counters in sorted(self._per_host.items())
            },
        }

    def save(self, bookkeeping_dir: str | Path | None) -> Path | None:
        """Persist the snapshot to ``download-state/session-summary.json``.

        Returns the output path on success, ``None`` on any failure
        (including missing or non-writable bookkeeping dir).
        """
        if not bookkeeping_dir:
            return None
        try:
            self.mark_finished()
            state_dir = Path(bookkeeping_dir).joinpath(STATE_DIR_NAME)
            state_dir.mkdir(parents=True, exist_ok=True)
            target = state_dir.joinpath(SESSION_SUMMARY_FILE_NAME)
            _atomic_write_json(target, self.snapshot())
            return target
        except Exception:  # pragma: no cover - persistence is best-effort
            return None


# -- Module-level singleton -------------------------------------------------


_active_observability: DownloadObservability | None = None


def start_session(session_id: str | None = None,
                  concurrency_planned: int | None = None) -> DownloadObservability:
    """Begin a new session-scoped sampler and install it as the active one.

    Subsequent ``record_*`` module functions delegate to this instance
    until the next ``start_session`` call. Safe to call repeatedly; the
    previous instance is dropped without persistence.
    """
    global _active_observability
    _active_observability = DownloadObservability(
        session_id=session_id,
        concurrency_planned=concurrency_planned,
    )
    return _active_observability


def active() -> DownloadObservability | None:
    return _active_observability


def end_session(bookkeeping_dir: str | Path | None = None) -> Path | None:
    """Finalize and persist the active sampler. Returns the file path."""
    global _active_observability
    if _active_observability is None:
        return None
    target = _active_observability.save(bookkeeping_dir)
    _active_observability = None
    return target


def record_outcome(**kwargs) -> None:
    """Module-level convenience: record on the active session if any."""
    if _active_observability is None:
        return
    _active_observability.record_outcome(**kwargs)


def record_retry_decision(decision, **kwargs) -> None:
    if _active_observability is None:
        return
    _active_observability.record_retry_decision(decision, **kwargs)


def set_plan(files_planned: int | None, bytes_planned: int | None) -> None:
    if _active_observability is None:
        return
    _active_observability.set_plan(files_planned, bytes_planned)


# -- Summary load (read-side, for the controller) ---------------------------


def load_session_summary(bookkeeping_dir: str | Path | None) -> dict[str, Any] | None:
    """Read the previous session-summary.json, or ``None`` if absent.

    Returns the raw dict (not a typed object) so the controller can
    tolerate added fields between versions without a migration.
    """
    if not bookkeeping_dir:
        return None
    target = Path(bookkeeping_dir).joinpath(STATE_DIR_NAME, SESSION_SUMMARY_FILE_NAME)
    if not target.is_file():
        return None
    try:
        with open(target, "r", encoding="utf-8", errors="backslashreplace") as rfd:
            data = json.load(rfd)
        if not isinstance(data, dict):
            return None
        if int(data.get("schemaVersion", 0)) != DOWNLOAD_OBSERVABILITY_SCHEMA_VERSION:
            # Unknown schema: caller should treat it as "no data" and
            # fall back to defaults.
            return None
        return data
    except (OSError, ValueError):
        return None


# -- Internal helpers -------------------------------------------------------


class _WallClock:
    """Indirection so tests can inject a deterministic clock."""

    def monotonic(self) -> float:
        return time.monotonic()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _failure_class_value(failure_class: DownloadFailureClass | str | None) -> str | None:
    if failure_class is None:
        return None
    if isinstance(failure_class, DownloadFailureClass):
        return failure_class.value
    try:
        return DownloadFailureClass(failure_class).value
    except (TypeError, ValueError):
        return None


def _atomic_write_json(target: Path, payload: Mapping[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".session-summary-", suffix=".json", dir=os.fspath(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as wfd:
            json.dump(payload, wfd, sort_keys=True)
            wfd.flush()
            os.fsync(wfd.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


__all__ = [
    "DOWNLOAD_OBSERVABILITY_SCHEMA_VERSION",
    "DownloadObservability",
    "DownloadOutcome",
    "active",
    "end_session",
    "host_from_url",
    "load_session_summary",
    "record_outcome",
    "record_retry_decision",
    "set_plan",
    "start_session",
]
