#!/usr/bin/env python3.12

"""Tests for Phase 4 throughput/error sampler (``P4-001``).

These tests run without ``instl`` runtime dependencies. They exercise
the per-session in-memory aggregator, the privacy rules around URL
ingestion, the JSON snapshot shape consumed by the controller, and
``load_session_summary`` round-trip.
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
    load_session_summary,
    record_outcome,
    record_retry_decision,
    set_plan,
    start_session,
)
from downloadRetry import RetryAction, RetryDecision


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

    def test_record_retry_decision_maps_action_to_outcome(self):
        sampler = DownloadObservability(wall_clock=_FrozenClock())
        terminal = RetryDecision(
            action=RetryAction.FAIL_TERMINAL,
            failure_class=DownloadFailureClass.HTTP_AUTH_POLICY,
            attempt=1,
            delay_seconds=0.0,
            reason="terminal_failure_class",
        )
        restart = RetryDecision(
            action=RetryAction.RESTART,
            failure_class=DownloadFailureClass.CHECKSUM_MISMATCH,
            attempt=2,
            delay_seconds=0.0,
            reason="restart_required_by_class",
            restart_required=True,
        )
        resume = RetryDecision(
            action=RetryAction.RESUME,
            failure_class=DownloadFailureClass.TIMEOUT_DURING_TRANSFER,
            attempt=3,
            delay_seconds=1.5,
            reason="resume_eligible_partial",
        )
        for d in (terminal, restart, resume):
            sampler.record_retry_decision(d, url="https://cdn.example.com/a", bytes_received=10)
        snapshot = sampler.snapshot()
        totals = snapshot["totals"]
        self.assertEqual(totals["attempts"], 3)
        self.assertEqual(totals["failuresTerminal"], 1)
        self.assertEqual(totals["restarts"], 1)
        self.assertEqual(totals["failuresRetryable"], 1)
        # The retryable bucket carries the failure class even when the
        # action is RESUME — the controller wants to see class counts.
        self.assertEqual(set(totals["failureClasses"].keys()),
                         {"http_auth_policy", "checksum_mismatch", "timeout_during_transfer"})

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

            loaded = load_session_summary(bookkeeping)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["sessionId"], "round-trip")
            self.assertEqual(loaded["filesPlanned"], 42)
            self.assertEqual(loaded["bytesPlanned"], 1024 * 1024)
            self.assertEqual(loaded["totals"]["successes"], 1)
            self.assertEqual(loaded["hosts"]["cdn.example.com"]["bytesReceived"], 1024)

    def test_load_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(load_session_summary(Path(tmpdir).joinpath("bookkeeping")))

    def test_load_rejects_unknown_schema_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bookkeeping = Path(tmpdir).joinpath("bookkeeping")
            state_dir = bookkeeping.joinpath("download-state")
            state_dir.mkdir(parents=True)
            with open(state_dir.joinpath("session-summary.json"), "w", encoding="utf-8") as wfd:
                json.dump({"schemaVersion": 9999, "sessionId": "future"}, wfd)
            self.assertIsNone(load_session_summary(bookkeeping))


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
            record_retry_decision(
                RetryDecision(
                    action=RetryAction.RESTART,
                    failure_class=DownloadFailureClass.CHECKSUM_MISMATCH,
                    attempt=1,
                    delay_seconds=0.0,
                    reason="restart_required_by_class",
                    restart_required=True,
                ),
                url="https://cdn.example.com/V16/b",
                bytes_received=50,
            )
            target = end_session(bookkeeping)
            self.assertIsNotNone(target)
            loaded = load_session_summary(bookkeeping)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["sessionId"], "mod")
            self.assertEqual(loaded["concurrencyPlanned"], 4)
            self.assertEqual(loaded["totals"]["attempts"], 2)
            self.assertEqual(loaded["totals"]["successes"], 1)
            self.assertEqual(loaded["totals"]["restarts"], 1)

    def test_record_without_active_session_is_no_op(self):
        # Should not raise, should not crash.
        record_outcome(outcome=DownloadOutcome.SUCCESS, url="https://cdn.example.com/a", bytes_received=1)
        record_retry_decision(
            RetryDecision(
                action=RetryAction.FAIL_TERMINAL,
                failure_class=DownloadFailureClass.HTTP_4XX,
                attempt=1,
                delay_seconds=0.0,
                reason="terminal_failure_class",
            ),
            url="https://cdn.example.com/a",
        )
        set_plan(1, 1)
        self.assertIsNone(end_session(None))


if __name__ == "__main__":
    unittest.main()
