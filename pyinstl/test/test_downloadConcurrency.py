#!/usr/bin/env python3.12

"""Tests for Phase 4 adaptive concurrency controller.

Covers:

* ``P4-002`` bounds — min/max clamping, step caps, fresh-start fallback.
* ``P4-003`` increase/decrease logic — healthy growth and slow/lossy
  backoff signals.
* ``P4-004`` manual override — user override and feature-flag kill
  switch both bypass the matrix.
* ``P4-005`` slow/lossy/high-latency validation — synthetic summaries
  that simulate timeout bursts, packet loss, and HTTP 5xx clusters.
"""

import os
import sys
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadConcurrency import (
    AdaptiveAction,
    ConcurrencyBounds,
    DEFAULT_DECREASE_STEP,
    DEFAULT_ERROR_RATE_BACKOFF_THRESHOLD,
    DEFAULT_INCREASE_STEP,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MIN_CONCURRENCY,
    DEFAULT_START_CONCURRENCY,
    decide_next_concurrency,
    resolve_concurrency_from_config,
)


def _summary(*,
             concurrency=8,
             attempts=20,
             successes=20,
             failures_retryable=0,
             failures_terminal=0,
             restarts=0,
             total_bytes=10 * 1024 * 1024,
             wall_ms=4000,
             error_rate=None,
             retryable_error_rate=None):
    if error_rate is None:
        error_rate = round((attempts - successes) / attempts, 4) if attempts else 0.0
    if retryable_error_rate is None:
        retryable_error_rate = round(failures_retryable / attempts, 4) if attempts else 0.0
    return {
        "schemaVersion": 1,
        "sessionId": "prev",
        "concurrencyPlanned": concurrency,
        "totals": {
            "attempts": attempts,
            "successes": successes,
            "failuresRetryable": failures_retryable,
            "failuresTerminal": failures_terminal,
            "restarts": restarts,
            "bytesReceived": total_bytes,
        },
        "errorRate": error_rate,
        "retryableErrorRate": retryable_error_rate,
        "wallMs": wall_ms,
        "observedThroughputBytesPerSecond": int(total_bytes / max(1, wall_ms / 1000)),
    }


class TestBounds(unittest.TestCase):
    def test_defaults_are_sane(self):
        bounds = ConcurrencyBounds()
        self.assertEqual(bounds.min_concurrency, DEFAULT_MIN_CONCURRENCY)
        self.assertEqual(bounds.max_concurrency, DEFAULT_MAX_CONCURRENCY)
        self.assertEqual(bounds.start_concurrency, DEFAULT_START_CONCURRENCY)
        self.assertGreaterEqual(bounds.start_concurrency, bounds.min_concurrency)
        self.assertLessEqual(bounds.start_concurrency, bounds.max_concurrency)

    def test_invalid_values_are_normalized(self):
        # min < 1 is bumped to 1; max < min is bumped to min; start is clamped.
        bounds = ConcurrencyBounds(min_concurrency=0, max_concurrency=-5, start_concurrency=999)
        self.assertEqual(bounds.min_concurrency, 1)
        self.assertEqual(bounds.max_concurrency, 1)
        self.assertEqual(bounds.start_concurrency, 1)

    def test_clamp_respects_min_and_max(self):
        bounds = ConcurrencyBounds(min_concurrency=4, max_concurrency=12, start_concurrency=8)
        self.assertEqual(bounds.clamp(1), 4)
        self.assertEqual(bounds.clamp(7), 7)
        self.assertEqual(bounds.clamp(100), 12)


class TestFreshStart(unittest.TestCase):
    def test_no_prior_summary_uses_start_value(self):
        decision = decide_next_concurrency(None, adaptive_enabled=True)
        self.assertEqual(decision.action, AdaptiveAction.FRESH_START)
        self.assertEqual(decision.recommended, DEFAULT_START_CONCURRENCY)
        self.assertIsNone(decision.previous)

    def test_summary_without_concurrency_is_treated_as_fresh(self):
        decision = decide_next_concurrency({"totals": {"attempts": 0}}, adaptive_enabled=True)
        self.assertEqual(decision.action, AdaptiveAction.FRESH_START)


class TestUserOverride(unittest.TestCase):
    def test_override_always_wins(self):
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8)
        decision = decide_next_concurrency(
            _summary(concurrency=16, failures_terminal=10),
            bounds=bounds,
            user_override=4,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.OVERRIDE)
        self.assertEqual(decision.recommended, 4)
        self.assertEqual(decision.reason, "user_override")

    def test_override_is_clamped_to_bounds(self):
        bounds = ConcurrencyBounds(min_concurrency=4, max_concurrency=16, start_concurrency=8)
        too_high = decide_next_concurrency(None, bounds=bounds, user_override=100)
        too_low = decide_next_concurrency(None, bounds=bounds, user_override=1)
        self.assertEqual(too_high.recommended, 16)
        self.assertEqual(too_low.recommended, 4)


class TestDisabledFlag(unittest.TestCase):
    def test_disabled_uses_configured_default(self):
        decision = decide_next_concurrency(
            _summary(concurrency=20, failures_terminal=5),
            adaptive_enabled=False,
            configured_default=12,
        )
        self.assertEqual(decision.action, AdaptiveAction.DISABLED)
        self.assertEqual(decision.recommended, 12)

    def test_disabled_falls_back_to_start_when_no_default(self):
        decision = decide_next_concurrency(None, adaptive_enabled=False)
        self.assertEqual(decision.action, AdaptiveAction.DISABLED)
        self.assertEqual(decision.recommended, DEFAULT_START_CONCURRENCY)


class TestHealthyGrowth(unittest.TestCase):
    def test_healthy_session_increases_by_step(self):
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8, increase_step=2)
        decision = decide_next_concurrency(
            _summary(concurrency=8, attempts=50, successes=50),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.INCREASE)
        self.assertEqual(decision.recommended, 10)
        self.assertEqual(decision.previous, 8)

    def test_growth_capped_at_max(self):
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=10, start_concurrency=8, increase_step=4)
        decision = decide_next_concurrency(
            _summary(concurrency=8, attempts=50, successes=50),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.recommended, 10)

    def test_at_max_holds_steady(self):
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=10, start_concurrency=8, increase_step=4)
        decision = decide_next_concurrency(
            _summary(concurrency=10, attempts=50, successes=50),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.KEEP)
        self.assertEqual(decision.recommended, 10)


class TestSlowLossyBackoff(unittest.TestCase):
    def test_timeout_burst_decreases_by_step(self):
        # Simulates P4-005 slow/high-latency signal: 8/20 retryable errors -> 40% error rate.
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8, decrease_step=4)
        decision = decide_next_concurrency(
            _summary(concurrency=16, attempts=20, successes=12, failures_retryable=8),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.DECREASE)
        self.assertEqual(decision.recommended, 12)

    def test_packet_loss_5xx_burst_decreases(self):
        # Simulates P4-005 lossy network: 5/10 retryable errors -> 50% retryable error rate.
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8, decrease_step=3)
        decision = decide_next_concurrency(
            _summary(concurrency=12, attempts=10, successes=5, failures_retryable=5),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.DECREASE)
        self.assertEqual(decision.recommended, 9)

    def test_backoff_clamped_at_min(self):
        bounds = ConcurrencyBounds(min_concurrency=4, max_concurrency=32, start_concurrency=8, decrease_step=20)
        decision = decide_next_concurrency(
            _summary(concurrency=8, attempts=10, successes=2, failures_retryable=8),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.DECREASE)
        self.assertEqual(decision.recommended, 4)

    def test_terminal_failure_forces_decrease(self):
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8, decrease_step=4)
        decision = decide_next_concurrency(
            _summary(concurrency=12, attempts=10, successes=8, failures_terminal=2),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.DECREASE)
        self.assertEqual(decision.reason, "terminal_or_restart_cluster")
        self.assertEqual(decision.recommended, 8)

    def test_restart_cluster_forces_decrease(self):
        # 5 restarts on 10 attempts is way above the attempts//5 threshold.
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8, decrease_step=4)
        decision = decide_next_concurrency(
            _summary(concurrency=12, attempts=10, successes=5, restarts=5),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.DECREASE)
        self.assertEqual(decision.reason, "terminal_or_restart_cluster")

    def test_high_latency_below_threshold_holds_steady(self):
        # Slightly elevated errors (1/20 = 5%) — below the 15% backoff threshold and above the 2% growth threshold.
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8)
        decision = decide_next_concurrency(
            _summary(concurrency=8, attempts=20, successes=19, failures_retryable=1),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.KEEP)
        self.assertEqual(decision.recommended, 8)


class TestEmptyOrTinySessions(unittest.TestCase):
    def test_no_attempts_holds_steady(self):
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8)
        decision = decide_next_concurrency(
            _summary(concurrency=12, attempts=0, successes=0),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.KEEP)
        self.assertEqual(decision.recommended, 12)

    def test_two_attempts_does_not_grow(self):
        # successes=2 < max(4, 2//2=1) -> max(4, 1) = 4, so no growth signal.
        bounds = ConcurrencyBounds(min_concurrency=2, max_concurrency=32, start_concurrency=8)
        decision = decide_next_concurrency(
            _summary(concurrency=8, attempts=2, successes=2),
            bounds=bounds,
            adaptive_enabled=True,
        )
        self.assertEqual(decision.action, AdaptiveAction.KEEP)


class TestConfigBridge(unittest.TestCase):
    """Exercise resolve_concurrency_from_config with a fake config_vars."""

    class _FakeVar:
        def __init__(self, value):
            self._value = value

        def str(self):
            return str(self._value)

        def bool(self):
            return str(self._value).strip().lower() in ("1", "true", "yes", "on")

        def list(self):
            return [self._value]

    class _FakeConfigVars(dict):
        def __contains__(self, key):
            return super().__contains__(key)

        def __getitem__(self, key):
            return TestConfigBridge._FakeVar(super().__getitem__(key))

        def get(self, key, default=None):
            if super().__contains__(key):
                return TestConfigBridge._FakeVar(super().__getitem__(key))
            return TestConfigBridge._FakeVar(default) if default is not None else None

    def test_user_override_wins_over_adaptive(self):
        config = self._FakeConfigVars({
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": "yes",
            "PARALLEL_SYNC_USER_OVERRIDE": "6",
            "PARALLEL_SYNC": "50",
            "LOCAL_REPO_BOOKKEEPING_DIR": "/tmp/bookkeeping",
        })
        loader_calls = []

        def loader(path):
            loader_calls.append(path)
            return _summary(concurrency=16, attempts=20, successes=20)

        decision = resolve_concurrency_from_config(config, summary_loader=loader)
        self.assertEqual(decision.action, AdaptiveAction.OVERRIDE)
        self.assertEqual(decision.recommended, 6)

    def test_adaptive_disabled_falls_back_to_configured(self):
        config = self._FakeConfigVars({
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": "no",
            "PARALLEL_SYNC": "24",
        })
        decision = resolve_concurrency_from_config(config, summary_loader=lambda _: None)
        self.assertEqual(decision.action, AdaptiveAction.DISABLED)
        self.assertEqual(decision.recommended, 24)

    def test_loader_failure_falls_back_to_fresh_start(self):
        config = self._FakeConfigVars({
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": "yes",
            "LOCAL_REPO_BOOKKEEPING_DIR": "/tmp/bookkeeping",
        })

        def broken_loader(path):
            raise IOError("disk gone")

        decision = resolve_concurrency_from_config(config, summary_loader=broken_loader)
        self.assertEqual(decision.action, AdaptiveAction.FRESH_START)
        self.assertEqual(decision.recommended, DEFAULT_START_CONCURRENCY)

    def test_adaptive_reads_summary_via_loader(self):
        config = self._FakeConfigVars({
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": "yes",
            "LOCAL_REPO_BOOKKEEPING_DIR": "/tmp/bookkeeping",
        })
        decision = resolve_concurrency_from_config(
            config,
            summary_loader=lambda _: _summary(
                concurrency=8, attempts=10, successes=4, failures_retryable=6),
        )
        # >50% retryable error rate -> decrease.
        self.assertEqual(decision.action, AdaptiveAction.DECREASE)
        self.assertEqual(decision.recommended, max(DEFAULT_MIN_CONCURRENCY, 8 - DEFAULT_DECREASE_STEP))


if __name__ == "__main__":
    unittest.main()
