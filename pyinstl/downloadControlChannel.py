#!/usr/bin/env python3.12

"""One-way stdin control channel for the bulk download engine.

Central writes one-line JSON commands (``{"cmd":"pause"}``,
``{"cmd":"resume"}``, ``{"cmd":"try_now"}``, each optionally tagged with
``"sessionId":"..."``) to ``instl``'s standard input. A daemon thread reads
stdin line by line and updates in-process shared state; the URL-sync
scheduling loop and the retry backoff sleeper check that state between
batches/sleeps.

Pause is **cooperative**: callers must invoke :meth:`wait_if_paused`
between batches/files. In-flight ``curl`` invocations are never
interrupted, so the ``.part`` artifacts and resume sidecars described in
``downloadState.py`` remain safe.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any, Callable, Optional, TextIO

_log = logging.getLogger(__name__)


_CMD_PAUSE = "pause"
_CMD_RESUME = "resume"
_CMD_TRY_NOW = "try_now"
_KNOWN_CMDS = frozenset({_CMD_PAUSE, _CMD_RESUME, _CMD_TRY_NOW})


class DownloadControlChannel:
    """Daemon-thread stdin reader and shared pause/try_now state.

    ``on_pause_event`` / ``on_resume_event`` fire *from the reader thread* on
    every paused/not-paused transition, so the sync engine can persist
    ``state="paused"`` and emit ``download.session_state``. A callback that
    raises is swallowed and logged at debug, so the reader keeps running.
    """

    def __init__(self,
                 stream: Optional[TextIO] = None,
                 session_id: Optional[str] = None) -> None:
        # Inverted relative to the natural reading of "paused": the event is
        # *set* when the engine is RUNNING, so ``_run_event.wait(timeout)``
        # blocks while paused and returns immediately when resumed.
        self._run_event = threading.Event()
        self._run_event.set()  # default: not paused
        # Wakeable primitive for the retry-backoff sleeper. Distinct from
        # ``_run_event`` so a ``try_now`` wake does not look like a resume.
        self._try_now_event = threading.Event()
        self._lock = threading.Lock()
        self._try_now_pending = False
        self._session_id: Optional[str] = session_id
        self._stream: TextIO = stream if stream is not None else sys.stdin
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()
        self.on_pause_event: Optional[Callable[[str], None]] = None
        self.on_resume_event: Optional[Callable[[str], None]] = None

    # -- public state -------------------------------------------------------

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @session_id.setter
    def session_id(self, value: Optional[str]) -> None:
        with self._lock:
            self._session_id = value or None

    def is_paused(self) -> bool:
        return not self._run_event.is_set()

    def try_now_requested(self) -> bool:
        """Consume-once read: ``True`` at most once per ``try_now``, so the
        backoff sleeper can tell a real wake from a spurious one."""
        with self._lock:
            pending = self._try_now_pending
            self._try_now_pending = False
            return pending

    # -- waiters ------------------------------------------------------------

    def wait_if_paused(self, poll_seconds: float = 0.5) -> None:
        """Block while the channel is paused, return immediately otherwise."""
        while not self._run_event.is_set():
            # bounded wait, so the caller stays responsive to KeyboardInterrupt
            self._run_event.wait(poll_seconds)

    def sleep_or_wake(self, seconds: float) -> bool:
        """``True`` when a ``try_now`` interrupted the sleep, ``False`` when the
        full duration elapsed. The caller must then clear the consume-once flag
        via :meth:`try_now_requested`."""
        if seconds <= 0:
            return self.try_now_requested()
        woke = self._try_now_event.wait(seconds)
        if woke:
            self._try_now_event.clear()  # reset for the next caller
        return woke

    # -- thread lifecycle ---------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="download-control-channel",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the reader to exit on its next iteration. Does not
        ``close()`` stdin — the parent process owns that fd."""
        self._stopped.set()

    # -- internals ----------------------------------------------------------

    def _reader_loop(self) -> None:
        # iterating the stream blocks on stdin until the parent writes; EOF
        # ends the loop cleanly
        try:
            for raw_line in self._stream:
                if self._stopped.is_set():
                    break
                self._handle_line(raw_line)
        except (ValueError, OSError) as ex:
            # ValueError fires when the stream is closed mid-read;
            # OSError covers Windows pipe teardown.
            _log.debug(f"control channel reader exiting: {ex}")
        except Exception as ex:  # pragma: no cover - defensive
            _log.warning(f"control channel reader unexpected error: {ex}")

    def _handle_line(self, raw_line: str) -> None:
        line = (raw_line or "").strip()
        if not line:
            return
        try:
            payload = json.loads(line)
        except (ValueError, TypeError) as ex:
            _log.warning(f"control channel: malformed JSON line, ignoring: {ex}")
            return
        if not isinstance(payload, dict):
            _log.warning("control channel: payload not an object, ignoring")
            return

        cmd = payload.get("cmd")
        if not isinstance(cmd, str) or cmd not in _KNOWN_CMDS:
            _log.warning(f"control channel: unknown cmd {cmd!r}, ignoring")
            return

        msg_session_id = payload.get("sessionId")
        if msg_session_id is not None:
            with self._lock:
                expected = self._session_id
            if expected is not None and msg_session_id != expected:
                _log.warning(
                    f"control channel: sessionId mismatch "
                    f"(got {msg_session_id!r}, expected {expected!r}); ignoring"
                )
                return

        if cmd == _CMD_PAUSE:
            self._apply_pause()
        elif cmd == _CMD_RESUME:
            self._apply_resume()
        elif cmd == _CMD_TRY_NOW:
            self._apply_try_now()

    def _apply_pause(self) -> None:
        was_running = self._run_event.is_set()
        self._run_event.clear()
        if was_running:
            _log.info("control channel: pause requested")
            self._fire_callback(self.on_pause_event, "user")

    def _apply_resume(self) -> None:
        was_paused = not self._run_event.is_set()
        self._run_event.set()
        if was_paused:
            _log.info("control channel: resume requested")
            self._fire_callback(self.on_resume_event, "user")

    def _apply_try_now(self) -> None:
        with self._lock:
            self._try_now_pending = True
        self._try_now_event.set()  # wake any retry-backoff sleeper
        _log.info("control channel: try_now requested")

    @staticmethod
    def _fire_callback(callback: Optional[Callable[[str], None]], reason: str) -> None:
        if callback is None:
            return
        try:
            callback(reason)
        except Exception as ex:  # pragma: no cover - defensive
            _log.debug(f"control channel callback raised, ignoring: {ex}")


# -- Module-level singleton ------------------------------------------------
# process-global, so the sync engine and the retry sleeper reach the same
# channel; tests should call reset_global_channel() between cases

_GLOBAL_CHANNEL: Optional[DownloadControlChannel] = None
_GLOBAL_CHANNEL_LOCK = threading.Lock()


def get_global_channel() -> DownloadControlChannel:
    """Return the process-wide control channel, creating it on first use."""
    global _GLOBAL_CHANNEL
    with _GLOBAL_CHANNEL_LOCK:
        if _GLOBAL_CHANNEL is None:
            _GLOBAL_CHANNEL = DownloadControlChannel()
        return _GLOBAL_CHANNEL


def set_global_channel(channel: Optional[DownloadControlChannel]) -> None:
    """Replace the singleton. Used by tests and by the boot path."""
    global _GLOBAL_CHANNEL
    with _GLOBAL_CHANNEL_LOCK:
        _GLOBAL_CHANNEL = channel


def reset_global_channel() -> None:
    """Clear the singleton (test helper)."""
    set_global_channel(None)


__all__ = [
    "DownloadControlChannel",
    "get_global_channel",
    "reset_global_channel",
    "set_global_channel",
]
