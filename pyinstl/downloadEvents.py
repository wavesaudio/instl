#!/usr/bin/env python3.12

"""Structured event contract from instl to Central.

Phase 5 work item ``P5-001``. This module is the single source of truth
for the JSON-line event channel that Central consumes instead of
parsing free-text progress (per ``D-004`` and ``D-007``). It does not
replace the existing legacy progress text; it runs alongside it so
older Central builds and the new structured consumer can both work
during rollout.

Transport
---------

Every event is emitted as one log line of the form::

    DOWNLOAD_EVENT {compact-json-with-sorted-keys}

The literal prefix :data:`DOWNLOAD_EVENT_LOG_PREFIX` lets Central
identify structured events without parsing every output line. The line
is written via Python ``logging`` at INFO so the existing instl log
handlers (which Central captures from stdout) carry it without any
additional plumbing.

The existing ``DOWNLOAD_RETRY_DECISION`` log line from
``downloadRetry.format_retry_decision_log_line`` is part of the same
family. ``format_retry_decision_event`` wraps the same payload in the
``DOWNLOAD_EVENT`` envelope so consumers can choose to ingest either
channel; the legacy prefix remains emitted unchanged for backward
compatibility per ``D-016``.

Privacy (``D-014``, ``D-016``, ``NFR-005``)
-------------------------------------------

* Every helper drops a fixed denylist of keys before serializing.
* Callers must pass redacted URLs only (use
  :func:`downloadState.redact_url_for_state` upstream).
* Hosts may be passed verbatim; the rest of a URL must not flow
  through this module.
* Local user paths (``finalPath``, ``tempPath``) are denylisted: they
  may appear in local diagnostic state but not in structured events.

Event types
-----------

``download.session_state``
    Session lifecycle transitions. Fields: ``state`` (one of
    :class:`DownloadSessionState`), ``previousState`` (optional),
    ``filesPlanned``, ``bytesPlanned``, ``concurrencyPlanned``,
    ``actionId``, ``repositoryMajorVersion``, ``repositoryRevision``,
    ``reason`` (optional, short literal string).

``download.file_state``
    Per-file transitions. Fields: ``fileId``, ``repoPath``, ``state``
    (one of :class:`DownloadFileState`), ``previousState`` (optional),
    ``expectedSize``, ``receivedBytes``, ``retryCount``,
    ``lastFailureClass`` (optional, :class:`DownloadFailureClass`
    value), ``resumed`` (bool), ``host`` (optional, bare host).

``download.retry_decision``
    Wrapped form of the legacy
    ``downloadRetry.format_retry_decision_log_line`` payload. Fields
    match the existing retry-decision JSON (``failureClass``,
    ``attempt``, ``decision``, ``delayMs``, ``restartRequired``,
    ``reason``, ``receivedBytes``, ``concurrency``,
    ``retryAfterSeconds``, ``httpStatus``, ``curlExitCode``,
    ``repoPath``, ``fileId``).

``download.capability``
    One-shot snapshot of the backend feature flags Central must use
    for UX gating per ``D-004``. Fields: ``resumeEnabled``,
    ``adaptiveConcurrencyEnabled``, ``validatedHosts`` (list, bare
    hosts only), ``retryMatrixVersion`` (int), ``stateSchemaVersion``
    (int), ``eventSchemaVersion`` (int).

``download.session_summary``
    The aggregated session totals already written by
    ``downloadObservability`` as ``session-summary.json``. Emitted as
    an event so Central does not have to read the sidecar to render
    end-of-session UI.

Envelope
--------

All events share the same envelope::

    {
        "event":             <event-type>,
        "schemaVersion":     <int>,
        "sessionId":         <opaque-id>,
        "timestamp":         <ISO-8601 UTC, seconds resolution>,
        ...event-specific fields...
    }

``timestamp`` is computed at line-format time (not on the caller's
behalf) so retries through the formatter remain deterministic when
the caller supplies an explicit value.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

DOWNLOAD_EVENT_LOG_PREFIX = "DOWNLOAD_EVENT"
DOWNLOAD_EVENT_SCHEMA_VERSION = 1

_log = logging.getLogger(__name__)


class DownloadEventType(str, Enum):
    """Canonical event identifiers. Consumers must accept unknown values
    and treat them as forward-compatible no-ops (``D-007``)."""

    SESSION_STATE = "download.session_state"
    FILE_STATE = "download.file_state"
    RETRY_DECISION = "download.retry_decision"
    CAPABILITY = "download.capability"
    SESSION_SUMMARY = "download.session_summary"


# Denylist of keys callers must never pass through this module. The
# formatter drops these rather than emit auth/header/local-path material.
# Kept compatible with ``downloadRetry._DISALLOWED_EVENT_FIELDS``.
_DISALLOWED_EVENT_FIELDS = frozenset({
    "url", "URL", "urlRedacted", "headers", "cookie", "cookies",
    "authorization", "Authorization", "policy", "signature",
    "Signed-URL", "signedUrl", "tempPath", "finalPath",
    "localPath", "downloadPath",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _drop_disallowed(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    if not mapping:
        return {}
    return {k: v for k, v in mapping.items() if k not in _DISALLOWED_EVENT_FIELDS}


def _enum_value(value: Any) -> Any:
    """Best-effort flatten of enum values for JSON serialization.

    Accepts ``Enum`` instances, plain strings, or ``None``. Anything else
    is returned verbatim.
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    return value


def make_envelope(event_type: DownloadEventType | str,
                  *,
                  session_id: str | None,
                  timestamp: str | None = None,
                  schema_version: int = DOWNLOAD_EVENT_SCHEMA_VERSION) -> dict[str, Any]:
    """Build the shared envelope used by every event type."""
    return {
        "event": _enum_value(event_type) or DownloadEventType.SESSION_STATE.value,
        "schemaVersion": int(schema_version),
        "sessionId": session_id or "unknown",
        "timestamp": timestamp or _utc_now_iso(),
    }


def format_event_line(event: Mapping[str, Any]) -> str:
    """Return the single-line log record for ``event``.

    The returned string starts with :data:`DOWNLOAD_EVENT_LOG_PREFIX`,
    followed by a space and a compact JSON object with sorted keys.
    Denylisted keys are removed in-line so any caller forgetting the
    redaction contract cannot leak auth material.
    """
    safe = _drop_disallowed(event)
    return f"{DOWNLOAD_EVENT_LOG_PREFIX} {json.dumps(safe, sort_keys=True)}"


def emit_event(event: Mapping[str, Any]) -> str | None:
    """Format and emit ``event`` via the module logger. Returns the line.

    Instrumentation must never break a sync run, so all errors are
    swallowed and logged at debug level only.

    Phase 6 (``P6-002``) adds a process-level kill switch: when
    :func:`set_telemetry_enabled` has been called with ``False`` the
    emitter returns ``None`` and does not write anything. This lets
    rollout disable the structured channel without code changes.
    """
    if not _telemetry_enabled:
        return None
    try:
        line = format_event_line(event)
    except Exception as fmt_ex:  # pragma: no cover - defensive
        _log.debug(f"could not format download event: {fmt_ex}")
        return None
    try:
        _log.info(line)
    except Exception as log_ex:  # pragma: no cover - defensive
        _log.debug(f"could not write download event: {log_ex}")
    return line


# -- Phase 6 telemetry kill switch (P6-002) ---------------------------------
#
# The structured channel is privacy-safe by construction (D-007, D-016) so
# the default is ON in shipped builds. The kill switch exists purely so
# rollout/support can disable the channel out-of-band if a downstream
# parser regresses or telemetry needs to pause without a code change.

_telemetry_enabled: bool = True


def set_telemetry_enabled(enabled: bool) -> None:
    """Toggle the structured-event kill switch.

    Called from ``do_check_checksum`` based on ``DOWNLOAD_TELEMETRY_ENABLED``.
    Tests may toggle it directly; the default (``True``) is restored when
    the test resets the flag. The legacy ``DOWNLOAD_RETRY_DECISION`` text
    line is emitted by ``downloadRetry`` and is NOT affected by this
    switch — that path remains on for backward compatibility (``D-016``).
    """
    global _telemetry_enabled
    _telemetry_enabled = bool(enabled)


def is_telemetry_enabled() -> bool:
    return _telemetry_enabled


# -- Builders ---------------------------------------------------------------


def make_session_state_event(*,
                             session_id: str | None,
                             state: Any,
                             previous_state: Any = None,
                             files_planned: int | None = None,
                             bytes_planned: int | None = None,
                             concurrency_planned: int | None = None,
                             action_id: str | None = None,
                             repository_major_version: int | None = None,
                             repository_revision: int | None = None,
                             reason: str | None = None,
                             timestamp: str | None = None) -> dict[str, Any]:
    payload = make_envelope(DownloadEventType.SESSION_STATE,
                            session_id=session_id, timestamp=timestamp)
    payload.update({
        "state": _enum_value(state),
        "previousState": _enum_value(previous_state),
        "filesPlanned": int(files_planned) if files_planned is not None else None,
        "bytesPlanned": int(bytes_planned) if bytes_planned is not None else None,
        "concurrencyPlanned": int(concurrency_planned) if concurrency_planned is not None else None,
        "actionId": action_id,
        "repositoryMajorVersion": int(repository_major_version) if repository_major_version is not None else None,
        "repositoryRevision": int(repository_revision) if repository_revision is not None else None,
        "reason": reason,
    })
    return payload


def make_file_state_event(*,
                          session_id: str | None,
                          file_id: str | None,
                          repo_path: str | None,
                          state: Any,
                          previous_state: Any = None,
                          expected_size: int | None = None,
                          received_bytes: int | None = None,
                          retry_count: int | None = None,
                          last_failure_class: Any = None,
                          resumed: bool | None = None,
                          host: str | None = None,
                          timestamp: str | None = None) -> dict[str, Any]:
    payload = make_envelope(DownloadEventType.FILE_STATE,
                            session_id=session_id, timestamp=timestamp)
    payload.update({
        "fileId": file_id,
        "repoPath": repo_path,
        "state": _enum_value(state),
        "previousState": _enum_value(previous_state),
        "expectedSize": int(expected_size) if expected_size is not None else None,
        "receivedBytes": int(received_bytes) if received_bytes is not None else None,
        "retryCount": int(retry_count) if retry_count is not None else None,
        "lastFailureClass": _enum_value(last_failure_class),
        "resumed": bool(resumed) if resumed is not None else None,
        "host": host,
    })
    return payload


def make_capability_event(*,
                          session_id: str | None,
                          resume_enabled: bool,
                          adaptive_concurrency_enabled: bool,
                          validated_hosts: Iterable[str] | None = None,
                          retry_matrix_version: int = 1,
                          state_schema_version: int = 1,
                          cohort: str | None = None,
                          feature_flags: Mapping[str, Any] | None = None,
                          central_ux_enabled: bool | None = None,
                          telemetry_enabled: bool | None = None,
                          retry_policy_enabled: bool | None = None,
                          timestamp: str | None = None) -> dict[str, Any]:
    payload = make_envelope(DownloadEventType.CAPABILITY,
                            session_id=session_id, timestamp=timestamp)
    safe_hosts: list[str] = []
    if validated_hosts:
        for raw in validated_hosts:
            host = str(raw or "").strip().lower()
            if not host or "/" in host or "?" in host or "#" in host:
                # Defense-in-depth: only accept bare host strings.
                continue
            safe_hosts.append(host)
    # Phase 6 P6-001/P6-003: include cohort and the canonical flag map so
    # Central + telemetry can compare control/treatment without parsing
    # text. Cohort normalization happens at the call site
    # (downloadCohort.resolve_cohort_from_config) so this builder only
    # has to forward the label. Unknown labels are still allowed through
    # for forward compatibility, but Central normalizes again on the
    # consumer side.
    try:
        from .downloadCohort import normalize_cohort  # local import: avoid cycle
    except ImportError:  # tests import without the pyinstl package context
        from downloadCohort import normalize_cohort  # type: ignore[no-redef]
    safe_flags: dict[str, bool] = {}
    if feature_flags:
        for key, value in feature_flags.items():
            if not isinstance(key, str) or not key:
                continue
            safe_flags[key] = bool(value)
    payload.update({
        "resumeEnabled": bool(resume_enabled),
        "adaptiveConcurrencyEnabled": bool(adaptive_concurrency_enabled),
        "validatedHosts": sorted(set(safe_hosts)),
        "retryMatrixVersion": int(retry_matrix_version),
        "stateSchemaVersion": int(state_schema_version),
        "eventSchemaVersion": DOWNLOAD_EVENT_SCHEMA_VERSION,
        "cohort": normalize_cohort(cohort),
        "featureFlags": safe_flags,
        "centralUxEnabled": bool(central_ux_enabled) if central_ux_enabled is not None else False,
        "telemetryEnabled": bool(telemetry_enabled) if telemetry_enabled is not None else True,
        "retryPolicyEnabled": bool(retry_policy_enabled) if retry_policy_enabled is not None else True,
    })
    return payload


def make_session_summary_event(*,
                               session_id: str | None,
                               summary: Mapping[str, Any],
                               timestamp: str | None = None) -> dict[str, Any]:
    """Wrap the ``session-summary.json`` payload in the event envelope.

    The summary is produced by ``downloadObservability`` and is already
    redacted (host-only, no URLs/paths). The wrapper simply lifts it
    onto the structured event channel so Central can consume the same
    data without reading the local sidecar.
    """
    payload = make_envelope(DownloadEventType.SESSION_SUMMARY,
                            session_id=session_id, timestamp=timestamp)
    payload["summary"] = _drop_disallowed(summary)
    return payload


def make_retry_decision_event(decision,
                              *,
                              session_id: str | None,
                              file_id: str | None = None,
                              repo_path: str | None = None,
                              received_bytes: int | None = None,
                              concurrency: int | None = None,
                              timestamp: str | None = None) -> dict[str, Any]:
    """Build the unified-envelope form of the retry decision event.

    Mirrors ``downloadRetry.RetryDecision.to_event`` field names so a
    Central consumer can use the same parser whether it sees the legacy
    ``DOWNLOAD_RETRY_DECISION`` line or this ``DOWNLOAD_EVENT`` line.
    """
    payload = make_envelope(DownloadEventType.RETRY_DECISION,
                            session_id=session_id, timestamp=timestamp)
    failure_class = getattr(decision, "failure_class", None)
    action = getattr(decision, "action", None)
    payload.update({
        "fileId": file_id,
        "repoPath": repo_path,
        "failureClass": _enum_value(failure_class),
        "attempt": int(getattr(decision, "attempt", 0) or 0),
        "decision": _enum_value(action),
        "delayMs": int(round(float(getattr(decision, "delay_seconds", 0.0) or 0.0) * 1000)),
        "restartRequired": bool(getattr(decision, "restart_required", False)),
        "reason": getattr(decision, "reason", ""),
        "receivedBytes": int(received_bytes) if received_bytes is not None else None,
        "concurrency": int(concurrency) if concurrency is not None else None,
        "retryAfterSeconds": getattr(decision, "retry_after_seconds", None),
        "httpStatus": getattr(decision, "http_status", None),
        "curlExitCode": getattr(decision, "curl_exit_code", None),
    })
    return payload


# -- Convenience emitters ---------------------------------------------------


def emit_session_state(**kwargs) -> str | None:
    return emit_event(make_session_state_event(**kwargs))


def emit_file_state(**kwargs) -> str | None:
    return emit_event(make_file_state_event(**kwargs))


def emit_capability(**kwargs) -> str | None:
    return emit_event(make_capability_event(**kwargs))


def emit_session_summary(**kwargs) -> str | None:
    return emit_event(make_session_summary_event(**kwargs))


def emit_retry_decision(decision, **kwargs) -> str | None:
    return emit_event(make_retry_decision_event(decision, **kwargs))


__all__ = [
    "DOWNLOAD_EVENT_LOG_PREFIX",
    "DOWNLOAD_EVENT_SCHEMA_VERSION",
    "DownloadEventType",
    "emit_capability",
    "emit_event",
    "emit_file_state",
    "emit_retry_decision",
    "emit_session_state",
    "emit_session_summary",
    "format_event_line",
    "make_capability_event",
    "make_envelope",
    "make_file_state_event",
    "make_retry_decision_event",
    "make_session_state_event",
    "make_session_summary_event",
]
