#!/usr/bin/env python3.12

"""Tests for Phase 4 throughput/error sampler (``P4-001``).

These tests run without ``instl`` runtime dependencies. They exercise
the per-session in-memory aggregator, the privacy rules around URL
ingestion, the JSON snapshot shape consumed by the controller, and
atomic summary persistence.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadFailures import DownloadFailureClass
from downloadObservability import (
    DOWNLOAD_OBSERVABILITY_SCHEMA_VERSION,
    DownloadObservability,
    DownloadOutcome,
    end_session,
    host_from_url,
    record_outcome,
    set_plan,
    start_session,
)


def _read_summary(bookkeeping_dir):
    """Read back the persisted session-summary.json to assert on its content."""
    target = Path(bookkeeping_dir).joinpath("download-state", "session-summary.json")
    with open(target, "r", encoding="utf-8") as rfd:
        return json.load(rfd)


class _FrozenClock:
    """Monotonic clock that advances only when test code asks it to."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += float(seconds)


class TestHostFromUrl(unittest.TestCase):
    def test_extracts_host_and_drops_query(self):
        self.assertEqual(host_from_url("https://cdn.example.com/V16/foo?Signature=abc"), "cdn.example.com")

    def test_normalizes_case(self):
        self.assertEqual(host_from_url("https://CDN.Example.Com/path"), "cdn.example.com")

    def test_strips_userinfo_and_port(self):
        self.assertEqual(host_from_url("https://user:pass@cdn.example.com:8443/path"), "cdn.example.com")

    def test_returns_none_for_missing_or_invalid(self):
        self.assertIsNone(host_from_url(None))
        self.assertIsNone(host_from_url(""))
        self.assertIsNone(host_from_url("not-a-url-just-a-string"))


class TestObservabilityRecording(unittest.TestCase):
    def test_record_success_aggregates_per_host_and_totals(self):
        clock = _FrozenClock()
        sampler = DownloadObservability(session_id="s1", concurrency_planned=8, wall_clock=clock)
        sampler.record_outcome(
            outcome=DownloadOutcome.SUCCESS,
            url="https://cdn.example.com/V16/a.bundle",
            bytes_received=1024,
            transfer_time_seconds=1.0,
        )
        sampler.record_outcome(
            outcome=DownloadOutcome.SUCCESS,
            host="cdn.example.com",
            bytes_received=2048,
            transfer_time_seconds=2.0,
        )
        sampler.record_outcome(
            outcome=DownloadOutcome.FAILED_RETRYABLE,
            url="https://other.host.example.net/x",
            failure_class=DownloadFailureClass.HTTP_5XX,
            bytes_received=0,
        )

        clock.advance(4.0)
        sampler.mark_finished()
        snapshot = sampler.snapshot()

        self.assertEqual(snapshot["schemaVersion"], DOWNLOAD_OBSERVABILITY_SCHEMA_VERSION)
        self.assertEqual(snapshot["sessionId"], "s1")
        self.assertEqual(snapshot["concurrencyPlanned"], 8)
        self.assertEqual(snapshot["totals"]["attempts"], 3)
        self.assertEqual(snapshot["totals"]["successes"], 2)
        self.assertEqual(snapshot["totals"]["failuresRetryable"], 1)
        self.assertEqual(snapshot["totals"]["bytesReceived"], 3072)
        self.assertEqual(snapshot["totals"]["failureClasses"], {"http_5xx": 1})
        self.assertEqual(snapshot["errorRate"], 0.3333)
        self.assertEqual(snapshot["retryableErrorRate"], 0.3333)
        # wallMs = 4000 -> 3072 B / 4 s = 768 B/s
        self.assertEqual(snapshot["wallMs"], 4000)
        self.assertEqual(snapshot["observedThroughputBytesPerSecond"], 768)
        self.assertIn("cdn.example.com", snapshot["hosts"])
        self.assertIn("other.host.example.net", snapshot["hosts"])
        self.assertEqual(snapshot["hosts"]["cdn.example.com"]["attempts"], 2)
        self.assertEqual(snapshot["hosts"]["cdn.example.com"]["bytesReceived"], 3072)
        self.assertEqual(snapshot["hosts"]["other.host.example.net"]["failuresRetryable"], 1)

    def test_invalid_outcome_is_dropped(self):
        sampler = DownloadObservability(wall_clock=_FrozenClock())
        sampler.record_outcome(outcome="not_a_real_outcome", url="https://cdn.example.com/a")
        self.assertEqual(sampler.snapshot()["totals"]["attempts"], 0)

    def test_failure_class_string_normalizes_to_enum_value(self):
        sampler = DownloadObservability(wall_clock=_FrozenClock())
        sampler.record_outcome(
            outcome=DownloadOutcome.FAILED_RETRYABLE,
            url="https://cdn.example.com/a",
            failure_class="timeout_during_transfer",
            bytes_received=0,
        )
        snapshot = sampler.snapshot()
        self.assertEqual(snapshot["totals"]["failureClasses"], {"timeout_during_transfer": 1})

    def test_unknown_host_for_missing_url(self):
        sampler = DownloadObservability(wall_clock=_FrozenClock())
        sampler.record_outcome(outcome=DownloadOutcome.SUCCESS, bytes_received=10, transfer_time_seconds=0.5)
        snapshot = sampler.snapshot()
        self.assertEqual(list(snapshot["hosts"].keys()), ["unknown"])


class TestObservabilityPrivacy(unittest.TestCase):
    def test_snapshot_keys_do_not_leak_query_or_path(self):
        sampler = DownloadObservability(wall_clock=_FrozenClock())
        sampler.record_outcome(
            outcome=DownloadOutcome.SUCCESS,
            url="https://cdn.example.com/V16/path/to/secret?Signature=PRIVATE&Policy=PRIVATE",
            bytes_received=10,
            transfer_time_seconds=0.1,
        )
        snapshot = sampler.snapshot()
        encoded = json.dumps(snapshot)
        self.assertNotIn("Signature", encoded)
        self.assertNotIn("Policy", encoded)
        self.assertNotIn("PRIVATE", encoded)
        self.assertNotIn("/V16/", encoded)
        self.assertEqual(list(snapshot["hosts"].keys()), ["cdn.example.com"])


class TestObservabilityPersistence(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bookkeeping = Path(tmpdir).joinpath("bookkeeping")
            sampler = DownloadObservability(session_id="round-trip", wall_clock=_FrozenClock())
            sampler.set_plan(files_planned=42, bytes_planned=1024 * 1024)
            sampler.record_outcome(
                outcome=DownloadOutcome.SUCCESS,
                url="https://cdn.example.com/V16/a",
                bytes_received=1024,
                transfer_time_seconds=0.5,
            )
            target = sampler.save(bookkeeping)
            self.assertIsNotNone(target)
            self.assertTrue(target.exists())
            # Snapshot file lives under download-state/session-summary.json
            expected = bookkeeping.joinpath("download-state", "session-summary.json")
            self.assertEqual(target, expected)

            loaded = _read_summary(bookkeeping)
            self.assertEqual(loaded["sessionId"], "round-trip")
            self.assertEqual(loaded["filesPlanned"], 42)
            self.assertEqual(loaded["bytesPlanned"], 1024 * 1024)
            self.assertEqual(loaded["totals"]["successes"], 1)
            self.assertEqual(loaded["hosts"]["cdn.example.com"]["bytesReceived"], 1024)


class TestModuleSingleton(unittest.TestCase):
    def setUp(self):
        # Ensure no leftover singleton from a previous test.
        end_session(None)

    def tearDown(self):
        end_session(None)

    def test_module_level_record_uses_active_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bookkeeping = Path(tmpdir).joinpath("bookkeeping")
            start_session(session_id="mod", concurrency_planned=4)
            set_plan(files_planned=2, bytes_planned=200)
            record_outcome(
                outcome=DownloadOutcome.SUCCESS,
                url="https://cdn.example.com/V16/a",
                bytes_received=100,
                transfer_time_seconds=0.2,
            )
            target = end_session(bookkeeping)
            self.assertIsNotNone(target)
            loaded = _read_summary(bookkeeping)
            self.assertEqual(loaded["sessionId"], "mod")
            self.assertEqual(loaded["concurrencyPlanned"], 4)
            self.assertEqual(loaded["totals"]["attempts"], 1)
            self.assertEqual(loaded["totals"]["successes"], 1)

    def test_record_without_active_session_is_no_op(self):
        # Should not raise, should not crash.
        record_outcome(outcome=DownloadOutcome.SUCCESS, url="https://cdn.example.com/a", bytes_received=1)
        set_plan(1, 1)
        self.assertIsNone(end_session(None))


if __name__ == "__main__":
    unittest.main()
