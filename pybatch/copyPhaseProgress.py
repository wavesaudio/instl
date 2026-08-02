#!/usr/bin/env python3.12

"""Process-global copy/install-phase byte-progress accumulator.

The copy phase is a sequence of many discrete pybatch commands (CopyFileToDir,
CopyDirToDir, Unwtar, ...), so unlike download or verify there is no single loop
to tick from. The copy/unwtar commands report the bytes they handle here, and
this module emits throttled ``copying`` ``session_state`` ticks carrying
``phaseBytesDone`` / ``phaseBytesPlanned``, which Central needs for a
determinate bar through the install tail.

The counters below are module state, so reporting MUST happen on the main
process - bytes reported from a worker process accumulate in that process and
are lost.

``report_copy_bytes`` is a no-op until ``begin_copy_phase`` has set a positive
planned total, and ``begin_copy_phase`` is called only from the client copy
flow (via the ``copying`` ``ReportDownloadState``), so the copy commands stay
silent in every other context: admin, tests, ad-hoc copies.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

_planned: int = 0
_done: int = 0
_session_id: str = "unknown"
_last_emit: float | None = None

# same cadence as the download/verify ticks
_EMIT_MIN_INTERVAL_SEC = 1.0


def begin_copy_phase(planned_bytes, session_id: str = "unknown") -> None:
    global _planned, _done, _session_id, _last_emit
    try:
        _planned = max(0, int(planned_bytes or 0))
    except (TypeError, ValueError):
        _planned = 0
    _done = 0
    _session_id = session_id or "unknown"
    _last_emit = None


def end_copy_phase() -> None:
    """Final tick at the full planned total, past the throttle. The phase is over
    whatever the accounting reached, and without this the bar stops wherever the last
    throttled tick happened to land."""
    global _done
    if _planned <= 0:
        return
    _done = _planned
    report_copy_bytes(0, force=True)


def report_copy_bytes(num_bytes, force: bool = False) -> None:
    """ throttled to one emit per _EMIT_MIN_INTERVAL_SEC, force bypasses the
        throttle - for the final tick of a phase
    """
    global _done, _last_emit
    if _planned <= 0:
        return
    try:
        _done += max(0, int(num_bytes or 0))
    except (TypeError, ValueError):
        return
    try:
        now = time.monotonic()
        if not force and _last_emit is not None and (now - _last_emit) < _EMIT_MIN_INTERVAL_SEC:
            return
        _last_emit = now
        # Lazy import to avoid a pybatch -> pyinstl import cycle at load time.
        from pyinstl.downloadEvents import emit_session_state
        emit_session_state(
            session_id=_session_id,
            state="copying",
            phase_bytes_done=min(_done, _planned),
            phase_bytes_planned=_planned,
            reason="copy_progress",
        )
    except Exception as ex:  # pragma: no cover - instrumentation must never break a copy
        log.debug(f"could not emit copy progress tick: {ex}")
