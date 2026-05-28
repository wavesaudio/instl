#!/usr/bin/env python3.12

"""One-way stdin control channel for the bulk download engine.

Phase 7 / control-channel work item. Central writes one-line JSON
commands (``{"cmd":"pause"}``, ``{"cmd":"resume"}``, ``{"cmd":"try_now"}``,
each optionally tagged with ``"sessionId":"..."``) to ``instl``'s
standard input. A daemon thread inside ``instl`` reads stdin line by
line, parses each JSON object, and updates an in-process shared
state. The URL-sync scheduling loop and the retry backoff sleeper
cooperatively check this state between batches/sleeps; in-flight
``curl`` invocations are never interrupted, so the partial ``.part``
artifacts and resume sidecars described in ``downloadState.py``
remain safe per the Phase 2 atomicity invariants (``D-001``,
``D-009``, ``D-010``).

Why stdin? Cross-platform process signaling is awkward on Windows,
and ``instl`` already emits one-line ``DOWNLOAD_EVENT`` records on
stdout; a symmetric one-line JSON channel on stdin keeps the framing
contract identical and avoids OS-specific IPC.

Why a module-level singleton? The URL sync engine is reached through
multiple paths (``instlClientSync.do_sync`` for fresh sync,
``info_mapBatchCommands.CheckDownloadFolderChecksum.re_download_bad_files``
for in-process redownload, and the retry sleeper inside
``downloadRetry``). Threading a channel reference through every call
site is invasive; a small module-level accessor keeps the wiring
local and testable. ``reset_global_channel()`` makes the singleton
test-friendly.

Pause is **cooperative**: callers must invoke :meth:`wait_if_paused`
between batches/files. The pause flag never kills a worker
mid-chunk.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any, Callable, Optional, TextIO

_log = logging.getLogger(__name__)


# Accepted command verbs. Unknown verbs are logged at warning and ignored.
_CMD_PAUSE = "pause"
_CMD_RESUME = "resume"
_CMD_TRY_NOW = "try_now"
_KNOWN_CMDS = frozenset({_CMD_PAUSE, _CMD_RESUME, _CMD_TRY_NOW})


class DownloadControlChannel:
    """Daemon-thread stdin reader and shared pause/try_now state.

    The class is safe to instantiate multiple times in tests; only
    :meth:`start` spawns the reader thread, and :meth:`stop` is a
    no-op when no thread is running. ``stream`` defaults to
    :data:`sys.stdin` but may be overridden with any iterable text
    stream for tests.

    ``on_pause_event`` / ``on_resume_event`` are optional callbacks
    fired *from the reader thread* whenever the channel transitions
    between paused and not-paused. They are meant for the sync engine
    to persist ``state="paused"`` and emit the
    ``download.session_state`` event with the appropriate ``reason``.
    Callbacks must not raise: exceptions are swallowed and logged at
    debug so the reader keeps running.
    """

    def __init__(self,
                 stream: Optional[TextIO] = None,
                 session_id: Optional[str] = None) -> None:
        # Use threading.Event for the pause flag so any waiter (the
        # sync loop or the retry sleeper) can block on the same primitive.
        # The semantics are inverted relative to the natural reading
        # of "paused": the event is *set* when the engine is RUNNING.
        # That way ``_run_event.wait(timeout)`` blocks while paused and
        # returns immediately when resumed, which is exactly the
        # behavior every consumer wants.
        self._run_event = threading.Event()
        self._run_event.set()  # default: not paused
        # Dedicated wakeable primitive for the retry-backoff sleeper.
        # Setting it releases ``sleep_or_wake``; the sleeper clears it
        # for the next round. Distinct from ``_run_event`` so that a
        # ``try_now`` wake does not look like a resume.
        self._try_now_event = threading.Event()
        self._lock = threading.Lock()
        self._try_now_pending = False
        self._session_id: Optional[str] = session_id
        self._stream: TextIO = stream if stream is not None else sys.stdin
        self._thread: Optional[threading.Thread] = None
        self._stopped = threading.Event()
        # Public callbacks; set by the sync engine boot path.
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
        """Consume-once read: returns ``True`` at most once per ``try_now``.

        Callers (typically the retry backoff sleeper) check this after
        being woken to decide whether the wake was real or spurious.
        """
        with self._lock:
            pending = self._try_now_pending
            self._try_now_pending = False
            return pending

    # -- waiters ------------------------------------------------------------

    def wait_if_paused(self, poll_seconds: float = 0.5) -> None:
        """Block while the channel is paused.

        Uses ``threading.Event.wait`` with a short timeout so that the
        thread remains responsive to interpreter shutdown (KeyboardInterrupt
        propagates through ``wait`` cleanly on all supported platforms).
        Returns immediately when the channel is not paused.
        """
        # Fast path: not paused -> return immediately.
        while not self._run_event.is_set():
            # Bounded wait so callers can periodically log progress
            # without holding a heavy lock. ``wait`` returns True as
            # soon as ``_run_event`` is set (resume) or False after
            # ``poll_seconds`` elapse.
            self._run_event.wait(poll_seconds)

    def sleep_or_wake(self, seconds: float) -> bool:
        """Sleep for ``seconds`` or return early on ``try_now``.

        Returns ``True`` when the sleep was interrupted by a ``try_now``
        command (the consume-once flag is cleared by the caller via
        :meth:`try_now_requested`), ``False`` when the full duration
        elapsed.

        The implementation uses the run-event as a wakeable primitive:
        ``try_now`` clears + re-sets the event, which wakes any waiter
        without changing the paused/running state.
        """
        if seconds <= 0:
            return self.try_now_requested()
        # Use a dedicated event for try_now so we don't perturb the
        # paused/running flag.
        woke = self._try_now_event.wait(seconds)
        if woke:
            # Reset for the next caller. Reading the consume-once flag
            # below also clears it.
            self._try_now_event.clear()
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
        """Signal the reader to exit. Does not close stdin.

        The daemon thread exits on its own when stdin reaches EOF; this
        method only flips ``_stopped`` so the loop's next iteration
        bails out promptly. We deliberately do not ``close()`` stdin —
        the parent process owns that file descriptor.
        """
        self._stopped.set()

    # -- internals ----------------------------------------------------------

    def _reader_loop(self) -> None:
        # ``for line in stream:`` blocks the daemon thread on stdin until
        # the parent writes (or closes). EOF ends the iteration cleanly.
        # Any IOError (e.g. stdin redirected to /dev/null on some CI
        # runners) is logged once and the thread exits without raising.
        try:
            for raw_line in self._stream:
                if self._stopped.is_set():
                    break
                self._handle_line(raw_line)
        except (ValueError, OSError) as ex:
            # ValueError fires when the underlying stream is closed
            # mid-read; OSError covers Windows pipe teardown.
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
        # Wake any retry-backoff sleeper. Setting the event releases
        # ``_try_now_event.wait``; the sleeper resets it.
        self._try_now_event.set()
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
#
# The sync engine and the retry sleeper both need access to the same
# channel instance. Threading a reference through every call site (and
# every test fixture) would be invasive, so we expose a single accessor
# that lazily constructs an instance bound to ``sys.stdin`` and lets
# the boot path attach event callbacks. Tests should call
# :func:`reset_global_channel` between cases.

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
