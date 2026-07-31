#!/usr/bin/env python3.12

"""Process-global copy/install-phase byte-progress accumulator.

The copy phase of an install is a sequence of many discrete pybatch commands
(CopyFileToDir, CopyDirToDir, Unwtar, ...), so there is no single loop to tick
from like the download or verify phases have. Instead, the copy/unwtar commands
report the bytes they handle into this module, which emits throttled ``copying``
``session_state`` ticks carrying ``phaseBytesDone`` / ``phaseBytesPlanned`` so
Central can drive a determinate bar through the install tail.

Gating: ``report_copy_bytes`` is a no-op until ``begin_copy_phase`` has set a
positive planned total. ``begin_copy_phase`` is called only from the client
copy flow (via the ``copying`` ``ReportDownloadState``), so the copy commands
stay silent in every other context (admin, tests, ad-hoc copies).

Best-effort throughout: instrumentation must never break a copy run.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

_planned: int = 0
_done: int = 0
_session_id: str = "unknown"
_last_emit: float | None = None

# Mirror the cadence of the download/verify ticks.
_EMIT_MIN_INTERVAL_SEC = 1.0


def begin_copy_phase(planned_bytes, session_id: str = "unknown") -> None:
    """Arm the accumulator for a copy phase of ``planned_bytes`` total."""
    global _planned, _done, _session_id, _last_emit
    try:
        _planned = max(0, int(planned_bytes or 0))
    except (TypeError, ValueError):
        _planned = 0
    _done = 0
    _session_id = session_id or "unknown"
    _last_emit = None


def report_copy_bytes(num_bytes, force: bool = False) -> None:
    """Add ``num_bytes`` of copied/unwtarred work and maybe emit a tick.

    No-op unless a copy phase is armed (``begin_copy_phase`` with planned > 0).
    Throttled to one emit per interval; ``force`` bypasses the throttle (used
    for a final tick). Never raises.
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
