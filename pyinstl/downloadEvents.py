#!/usr/bin/env python3.12

"""Structured event contract from instl to Central.

Single source of truth for the JSON-line event channel that Central consumes
instead of parsing free-text progress. It does not replace the legacy
progress text; it runs alongside it so older Central builds and the new
structured consumer both keep working during rollout.

Transport
---------

Every event is emitted as one log line of the form::

    DOWNLOAD_EVENT {compact-json-with-sorted-keys}

The literal prefix :data:`DOWNLOAD_EVENT_LOG_PREFIX` lets Central identify
structured events without parsing every output line. The line is written via
Python ``logging`` at INFO so the existing instl log handlers (which Central
captures from stdout) carry it without any additional plumbing.

``downloadRetry.format_retry_decision_log_line`` emits the same payload under
the legacy ``DOWNLOAD_RETRY_DECISION`` prefix, which stays as-is for backward
compatibility; ``format_retry_decision_event`` wraps that payload in the
``DOWNLOAD_EVENT`` envelope so consumers can ingest either channel.

Privacy
-------

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

    In-flight ``downloading`` ticks additionally carry ``bytesReceived`` and
    ``filesCompleted`` (cumulative, monotonic) plus
    ``observedThroughputBytesPerSecond`` (EMA-smoothed), so Central can
    compute an ETA without waiting for the end-of-session summary, which
    only arrives once the download is already over. Lifecycle transitions
    omit them. Post-download phases (e.g. ``verifying_downloads``) may
    instead carry ``phaseBytesDone`` / ``phaseBytesPlanned`` to drive a
    determinate bar through the install tail. All of these are additive and
    optional, so ``schemaVersion`` is unchanged.

``download.file_state``
    Per-file transitions. Fields: ``fileId``, ``repoPath``, ``state``
    (one of :class:`DownloadFileState`), ``previousState`` (optional),
    ``expectedSize``, ``receivedBytes``, ``retryCount``,
    ``lastFailureClass`` (optional, :class:`DownloadFailureClass`
    value), ``resumed`` (bool), ``host`` (optional, bare host).

``download.retry_decision``
    Wrapped form of the legacy
    ``downloadRetry.format_retry_decision_log_line`` payload. Fields:
    ``failureClass``, ``attempt``, ``decision``, ``delayMs``,
    ``restartRequired``, ``reason``, ``receivedBytes``, ``concurrency``,
    ``retryAfterSeconds``, ``httpStatus``, ``curlExitCode``, ``repoPath``,
    ``fileId``.

``download.capability``
    One-shot snapshot of the backend feature flags Central uses for UX
    gating. Fields: ``resumeEnabled``, ``validatedHosts`` (list, bare hosts
    only), ``retryMatrixVersion`` (int), ``stateSchemaVersion`` (int),
    ``eventSchemaVersion`` (int), ``featureFlags`` (map), ``centralUxEnabled``,
    ``telemetryEnabled``, ``retryPolicyEnabled``.

``download.session_summary``
    The aggregated session totals ``downloadObservability`` writes as
    ``session-summary.json``, so Central need not read the sidecar to
    render end-of-session UI.

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

from configVar import config_vars, config_var_str

DOWNLOAD_EVENT_LOG_PREFIX = "DOWNLOAD_EVENT"
DOWNLOAD_EVENT_SCHEMA_VERSION = 1

_log = logging.getLogger(__name__)


class DownloadEventType(str, Enum):
    """Canonical event identifiers. Consumers must accept unknown values
    and treat them as forward-compatible no-ops."""

    SESSION_STATE = "download.session_state"
    FILE_STATE = "download.file_state"
    RETRY_DECISION = "download.retry_decision"
    CAPABILITY = "download.capability"
    SESSION_SUMMARY = "download.session_summary"


# The kill switches reported on the capability event, so a failed install's log
# says which recovery layers were active. Defaults match defaults/InstlClient.yaml
# and only apply when the key is undefined (an older client yaml); once loaded,
# the yaml wins.
_REPORTED_FLAGS: tuple[tuple[str, bool], ...] = (
    ("DOWNLOAD_TELEMETRY_ENABLED", True),
    ("DOWNLOAD_RESUME_ENABLED", True),
    ("DOWNLOAD_RETRY_POLICY_ENABLED", True),
    ("DOWNLOAD_CENTRAL_UX_ENABLED", True),
    ("DOWNLOAD_RECONCILE_MISSING_OUTPUTS", True),
    ("DOWNLOAD_OFFLINE_HOLD_ENABLED", True),
    ("DOWNLOAD_CURL_STALL_DETECTION", True),
    ("DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES", True),
    # set to true only by a NEW Central, which treats backend-hold evidence as
    # informational and never auto-pauses on it; default FALSE so an old
    # Central sees only the legacy event stream while the engine still recovers
    ("DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD", False),
)


def active_flags_from_config(config_vars: Any) -> dict[str, bool]:
    """Read :data:`_REPORTED_FLAGS` for the capability event's ``featureFlags``."""
    return {name: _read_flag(config_vars, name, default) for name, default in _REPORTED_FLAGS}


def _read_flag(config_vars: Any, name: str, default: bool) -> bool:
    try:
        if config_vars is None:
            return default
        # `config_vars` is the instl ConfigVarStack: `__getitem__` returns a
        # variable with `.bool()`. Mapping-style access is for tests.
        if hasattr(config_vars, "__contains__") and name not in config_vars:
            return default
        var = config_vars[name]
        if hasattr(var, "bool"):
            return bool(var.bool())
        if isinstance(var, bool):
            return var
        if isinstance(var, (int, float)):
            return bool(var)
        return str(var).strip().lower() in ("yes", "true", "1", "on")
    except Exception:
        return default


# Dropped by the formatter rather than emit auth/header/local-path material.
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
    """Flatten enums for JSON serialization; anything else passes through."""
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

    :data:`DOWNLOAD_EVENT_LOG_PREFIX`, a space, then compact JSON with sorted
    keys. Denylisted keys are dropped here too, so a caller that forgets the
    redaction contract still cannot leak auth material.
    """
    safe = _drop_disallowed(event)
    return f"{DOWNLOAD_EVENT_LOG_PREFIX} {json.dumps(safe, sort_keys=True)}"


def emit_event(event: Mapping[str, Any]) -> str | None:
    """Format and emit ``event`` via the module logger. Returns the line.

    Returns ``None`` and writes nothing when :func:`set_telemetry_enabled`
    has turned the channel off.
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


# -- Telemetry kill switch --------------------------------------------------
#
# Default ON in shipped builds; process-global, so rollout/support can disable
# the channel out-of-band if a downstream parser regresses.

_telemetry_enabled: bool = True


def set_telemetry_enabled(enabled: bool) -> None:
    """Toggle the structured-event kill switch.

    Called from ``do_check_checksum`` based on ``DOWNLOAD_TELEMETRY_ENABLED``.
    The legacy ``DOWNLOAD_RETRY_DECISION`` text line comes from
    ``downloadRetry`` and is NOT affected by this switch.
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
                             bytes_received: int | None = None,
                             files_completed: int | None = None,
                             observed_throughput_bytes_per_second: int | None = None,
                             phase_bytes_done: int | None = None,
                             phase_bytes_planned: int | None = None,
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
    # live-progress fields, included only when supplied so lifecycle-transition
    # events keep their existing shape
    if bytes_received is not None:
        payload["bytesReceived"] = int(bytes_received)
    if files_completed is not None:
        payload["filesCompleted"] = int(files_completed)
    if observed_throughput_bytes_per_second is not None:
        payload["observedThroughputBytesPerSecond"] = int(observed_throughput_bytes_per_second)
    # per-phase byte progress for post-download phases (e.g. verify); distinct
    # from the download-phase bytesReceived/bytesPlanned above
    if phase_bytes_done is not None:
        payload["phaseBytesDone"] = int(phase_bytes_done)
    if phase_bytes_planned is not None:
        payload["phaseBytesPlanned"] = int(phase_bytes_planned)
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
                          validated_hosts: Iterable[str] | None = None,
                          retry_matrix_version: int = 1,
                          state_schema_version: int = 1,
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
                continue  # only bare host strings
            safe_hosts.append(host)
    safe_flags: dict[str, bool] = {}
    if feature_flags:
        for key, value in feature_flags.items():
            if not isinstance(key, str) or not key:
                continue
            safe_flags[key] = bool(value)
    payload.update({
        "resumeEnabled": bool(resume_enabled),
        "validatedHosts": sorted(set(safe_hosts)),
        "retryMatrixVersion": int(retry_matrix_version),
        "stateSchemaVersion": int(state_schema_version),
        "eventSchemaVersion": DOWNLOAD_EVENT_SCHEMA_VERSION,
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

    ``downloadObservability`` already produced it redacted (host-only, no
    URLs/paths).
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

    Field names mirror ``downloadRetry.RetryDecision.to_event`` so Central can
    use one parser for both the legacy ``DOWNLOAD_RETRY_DECISION`` line and
    this ``DOWNLOAD_EVENT`` line.
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


# -- config-aware session_state emission --------------------------


def download_event_context():
    """Session id + rollout flags for a download event, applying the telemetry kill
    switch. Each instl invocation is its own process, so a later `copy` must re-read the
    flag that the `sync` before it honored."""
    rollout_flags = active_flags_from_config(config_vars)
    telemetry_enabled = bool(rollout_flags.get("DOWNLOAD_TELEMETRY_ENABLED", True))
    set_telemetry_enabled(telemetry_enabled)
    return config_var_str("__INVOCATION_RANDOM_ID__", "unknown"), rollout_flags, telemetry_enabled


def emit_download_state(state, reason=None, files_planned=None, bytes_planned=None):
    """Emit a session_state transition for a phase that is not the transfer itself -
    preparing before anything runs, verify and copy/unwtar after curl is done, failed on
    the way out. Lives here rather than next to the phase that calls it: every caller is
    a different subsystem and none of them should have to import another to say where
    the install has got to."""
    try:
        session_id, _rollout_flags, _telemetry_enabled = download_event_context()
        emit_session_state(
            session_id=session_id,
            state=state,
            files_planned=files_planned,
            bytes_planned=bytes_planned,
            reason=reason,
        )
    except Exception as ex:  # pragma: no cover - instrumentation must never break sync
        _log.debug(f"could not emit download state {state!r}: {ex}")


__all__ = [
    "DOWNLOAD_EVENT_LOG_PREFIX",
    "DOWNLOAD_EVENT_SCHEMA_VERSION",
    "DownloadEventType",
    "active_flags_from_config",
    "download_event_context",
    "emit_capability",
    "emit_download_state",
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
