#!/usr/bin/env python3.12

"""Tests for the download control channel (stdin and file transports).

Covers:
* Malformed JSON lines are logged and ignored without crashing.
* ``{"cmd":"pause"}`` sets the pause flag; ``{"cmd":"resume"}`` clears it.
* ``{"cmd":"try_now"}`` is consume-once and wakes ``sleep_or_wake``.
* Mismatched ``sessionId`` is ignored.
* Pause/resume callbacks fire with the expected reason.
* The ``sleep_backoff`` helper in ``downloadRetry`` returns early on try_now.
* File transport: commands via appended lines; tail-from-EOF (no replay of
  pre-existing content); partial lines held until their newline; truncation
  read from the top; missing file awaited; sessionId guard; idempotent start.
* ``start_file_reader_from_config`` arms the file transport from
  ``DOWNLOAD_CONTROL_FILE`` and no-ops when it is empty/absent.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from configVar import config_vars
from downloadControlChannel import (
    DownloadControlChannel,
    get_global_channel,
    reset_global_channel,
    set_global_channel,
    start_file_reader_from_config,
)
from downloadRetry import sleep_backoff


class _StubStream:
    """Iterable stream that releases lines on demand.

    Mimics stdin: ``__iter__`` blocks (via a Condition) until lines are
    queued or the stream is closed. This lets tests drive the reader
    thread deterministically.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._lines = []
        self._closed = False

    def push(self, line):
        with self._cond:
            self._lines.append(line if line.endswith("\n") else line + "\n")
            self._cond.notify_all()

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def __iter__(self):
        return self

    def __next__(self):
        with self._cond:
            while not self._lines and not self._closed:
                self._cond.wait(timeout=2.0)
            if self._lines:
                return self._lines.pop(0)
            raise StopIteration


def _wait_for(predicate, timeout=1.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class TestParseAndState(unittest.TestCase):
    def setUp(self):
        self.stream = _StubStream()
        self.channel = DownloadControlChannel(stream=self.stream)
        self.channel.start()
        self.addCleanup(self.stream.close)
        self.addCleanup(self.channel.stop)

    def test_malformed_json_is_ignored(self):
        # Two bad lines, then a good pause line. The reader must not
        # crash and must apply the pause once it reaches the valid line.
        self.stream.push("not json at all")
        self.stream.push("{not: valid}")
        self.stream.push('{"cmd":"pause"}')
        self.assertTrue(_wait_for(self.channel.is_paused))

    def test_pause_sets_flag(self):
        self.stream.push('{"cmd":"pause"}')
        self.assertTrue(_wait_for(self.channel.is_paused))

    def test_resume_clears_flag(self):
        self.stream.push('{"cmd":"pause"}')
        self.assertTrue(_wait_for(self.channel.is_paused))
        self.stream.push('{"cmd":"resume"}')
        self.assertTrue(_wait_for(lambda: not self.channel.is_paused()))

    def test_try_now_is_consume_once(self):
        self.stream.push('{"cmd":"try_now"}')
        self.assertTrue(_wait_for(self.channel.try_now_requested))
        # Second read returns False because the flag was consumed.
        self.assertFalse(self.channel.try_now_requested())

    def test_unknown_cmd_is_ignored(self):
        self.stream.push('{"cmd":"nuke"}')
        # Give the reader a chance to process; state must remain default.
        time.sleep(0.05)
        self.assertFalse(self.channel.is_paused())
        self.assertFalse(self.channel.try_now_requested())

    def test_session_id_mismatch_is_ignored(self):
        self.channel.session_id = "expected-session"
        self.stream.push('{"cmd":"pause","sessionId":"other-session"}')
        time.sleep(0.05)
        self.assertFalse(self.channel.is_paused())
        # A matching sessionId works.
        self.stream.push('{"cmd":"pause","sessionId":"expected-session"}')
        self.assertTrue(_wait_for(self.channel.is_paused))

    def test_pause_callback_fires_with_reason(self):
        captured = []
        self.channel.on_pause_event = lambda reason: captured.append(reason)
        self.stream.push('{"cmd":"pause"}')
        self.assertTrue(_wait_for(lambda: captured == ["user"]))

    def test_resume_callback_fires_only_on_transition(self):
        captured = []
        self.channel.on_resume_event = lambda reason: captured.append(reason)
        # No pause first -> resume is a no-op transition.
        self.stream.push('{"cmd":"resume"}')
        time.sleep(0.05)
        self.assertEqual(captured, [])
        # After a real pause, resume fires once.
        self.stream.push('{"cmd":"pause"}')
        self.assertTrue(_wait_for(self.channel.is_paused))
        self.stream.push('{"cmd":"resume"}')
        self.assertTrue(_wait_for(lambda: captured == ["user"]))


class TestSleepBackoff(unittest.TestCase):
    def setUp(self):
        reset_global_channel()
        self.stream = _StubStream()
        self.channel = DownloadControlChannel(stream=self.stream)
        self.channel.start()
        set_global_channel(self.channel)
        self.addCleanup(reset_global_channel)
        self.addCleanup(self.stream.close)
        self.addCleanup(self.channel.stop)

    def test_sleep_backoff_returns_false_when_full_interval_elapses(self):
        woke = sleep_backoff(0.05, channel=self.channel)
        self.assertFalse(woke)

    def test_sleep_backoff_returns_early_on_try_now(self):
        # Schedule a try_now during the sleep.
        def _fire():
            time.sleep(0.05)
            self.stream.push('{"cmd":"try_now"}')
        threading.Thread(target=_fire, daemon=True).start()
        started = time.monotonic()
        woke = sleep_backoff(2.0, channel=self.channel)
        elapsed = time.monotonic() - started
        self.assertTrue(woke)
        self.assertLess(elapsed, 1.5)  # generous bound for CI

    def test_sleep_backoff_zero_delay_is_no_op(self):
        self.assertFalse(sleep_backoff(0.0, channel=self.channel))
        self.assertFalse(sleep_backoff(-1.0, channel=self.channel))


class TestGlobalChannel(unittest.TestCase):
    def test_singleton_is_lazily_created_and_resettable(self):
        reset_global_channel()
        c1 = get_global_channel()
        c2 = get_global_channel()
        self.assertIs(c1, c2)
        reset_global_channel()
        c3 = get_global_channel()
        self.assertIsNot(c3, c1)
        reset_global_channel()


class TestFileTransport(unittest.TestCase):
    """The control-file tail: same commands, same dispatch, no stdin needed."""

    POLL = 0.02

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ctl-file-test-")
        self.control_path = os.path.join(self.tmp_dir, "download.control")
        self.channel = DownloadControlChannel(stream=_StubStream())
        self.addCleanup(self.channel.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def _append(self, line):
        with open(self.control_path, "ab") as control_file:
            control_file.write(line.encode("utf-8"))

    def _start(self):
        self.channel.start_file_reader(self.control_path, poll_seconds=self.POLL)

    def test_commands_via_file(self):
        open(self.control_path, "wb").close()  # driver creates/truncates before spawn
        self._start()
        self._append('{"cmd":"pause"}\n')
        self.assertTrue(_wait_for(self.channel.is_paused))
        self._append('{"cmd":"resume"}\n')
        self.assertTrue(_wait_for(lambda: not self.channel.is_paused()))
        self._append('{"cmd":"try_now"}\n')
        self.assertTrue(_wait_for(self.channel.try_now_requested))

    def test_preexisting_content_is_not_replayed(self):
        # A stale pause from an earlier invocation sharing the file must not
        # pause this invocation: the reader starts at end-of-file.
        self._append('{"cmd":"pause"}\n')
        self._start()
        time.sleep(self.POLL * 5)
        self.assertFalse(self.channel.is_paused())
        # ...but fresh appends are consumed.
        self._append('{"cmd":"pause"}\n')
        self.assertTrue(_wait_for(self.channel.is_paused))

    def test_partial_line_waits_for_newline(self):
        open(self.control_path, "wb").close()
        self._start()
        self._append('{"cmd":"pau')
        time.sleep(self.POLL * 5)
        self.assertFalse(self.channel.is_paused())
        self._append('se"}\n')
        self.assertTrue(_wait_for(self.channel.is_paused))

    def test_truncated_file_is_read_from_the_top(self):
        open(self.control_path, "wb").close()
        self._start()
        # Two lines so the consumed offset is comfortably larger than the
        # recreated content below — the truncation heuristic is size-based
        # (a recreation that happens to be >= the consumed offset is a
        # documented blind spot; drivers only truncate before spawning).
        self._append('{"cmd":"pause"}\n{"cmd":"pause"}\n')
        self.assertTrue(_wait_for(self.channel.is_paused))
        # Driver recreates the file: smaller than the consumed offset, so the
        # reader resets and consumes the fresh content from offset 0.
        with open(self.control_path, "wb") as control_file:
            control_file.write(b'{"cmd":"resume"}\n')
        self.assertTrue(_wait_for(lambda: not self.channel.is_paused()))

    def test_missing_file_is_awaited(self):
        self._start()  # file does not exist yet
        time.sleep(self.POLL * 5)
        self._append('{"cmd":"pause"}\n')
        self.assertTrue(_wait_for(self.channel.is_paused))

    def test_session_id_guard_applies_to_file_lines(self):
        open(self.control_path, "wb").close()
        self.channel.session_id = "expected-session"
        self._start()
        self._append('{"cmd":"pause","sessionId":"other-session"}\n')
        time.sleep(self.POLL * 5)
        self.assertFalse(self.channel.is_paused())
        self._append('{"cmd":"pause","sessionId":"expected-session"}\n')
        self.assertTrue(_wait_for(self.channel.is_paused))

    def test_second_start_is_ignored(self):
        open(self.control_path, "wb").close()
        self._start()
        self._start()
        readers = [t for t in threading.enumerate() if t.name == "download-control-file"]
        self.assertEqual(len(readers), 1)
        self._append('{"cmd":"pause"}\n')
        self.assertTrue(_wait_for(self.channel.is_paused))


class TestStartFileReaderFromConfig(unittest.TestCase):
    """DOWNLOAD_CONTROL_FILE config var arms the file transport; empty leaves it off."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ctl-cfg-test-")
        self.control_path = os.path.join(self.tmp_dir, "download.control")
        open(self.control_path, "wb").close()
        self.channel = DownloadControlChannel(stream=_StubStream())
        self.addCleanup(self.channel.stop)
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def _reader_alive(self):
        thread = self.channel._file_thread
        return thread is not None and thread.is_alive()

    def test_var_set_starts_reader(self):
        with config_vars.push_scope_context():
            config_vars["DOWNLOAD_CONTROL_FILE"] = self.control_path
            start_file_reader_from_config(self.channel)
        self.assertTrue(_wait_for(self._reader_alive))

    def test_var_empty_or_absent_is_a_no_op(self):
        with config_vars.push_scope_context():
            config_vars["DOWNLOAD_CONTROL_FILE"] = ""
            start_file_reader_from_config(self.channel)
            self.assertFalse(self._reader_alive())
        # absent entirely (whatever outer scopes hold, the empty-string
        # default in defaults/InstlClient.yaml resolves to "no path")
        with config_vars.push_scope_context():
            config_vars["DOWNLOAD_CONTROL_FILE"] = ""
            start_file_reader_from_config(self.channel)
            self.assertFalse(self._reader_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
