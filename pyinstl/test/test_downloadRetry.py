#!/usr/bin/env python3.12

"""Tests for Phase 3 retry matrix, backoff, and decision log helper.

Covers ``P3-004`` (matrix + backoff) and ``P3-005`` (structured retry
decision log). Integration with the bulk download code path itself is
exercised through the existing ``test_downloadPromotion.py`` happy path;
this file focuses on deterministic per-class behavior so failures are
easy to diagnose.
"""

import json
import os
import sys
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadFailures import (
    DownloadFailureClass,
    DownloadFailureInfo,
    classify_curl_exit_code,
    classify_http_status,
    is_retryable_failure_class,
)
from downloadRetry import (
    DEFAULT_RETRY_MATRIX,
    DOWNLOAD_RETRY_DECISION_LOG_PREFIX,
    RetryAction,
    RetryDecision,
    RetryPolicy,
    compute_backoff_seconds,
    decide_retry,
    format_retry_decision_log_line,
    policy_for,
)


def _info(failure_class, **kwargs):
    return DownloadFailureInfo(
        failure_class=failure_class,
        retryable=is_retryable_failure_class(failure_class),
        source=kwargs.pop("source", "test"),
        reason=kwargs.pop("reason", ""),
        curl_exit_code=kwargs.pop("curl_exit_code", None),
        http_status=kwargs.pop("http_status", None),
        retry_after_seconds=kwargs.pop("retry_after_seconds", None),
    )


class TestRetryMatrix(unittest.TestCase):
    def test_every_failure_class_has_a_policy(self):
        for failure_class in DownloadFailureClass:
            with self.subTest(failure_class=failure_class):
                self.assertIsInstance(policy_for(failure_class), RetryPolicy)

    def test_retryable_classes_have_max_attempts(self):
        for failure_class in DownloadFailureClass:
            policy = policy_for(failure_class)
            retryable = is_retryable_failure_class(failure_class)
            with self.subTest(failure_class=failure_class):
                if policy.max_attempts > 0:
                    self.assertTrue(
                        retryable,
                        f"{failure_class} has retry budget but is not in RETRYABLE_FAILURE_CLASSES",
                    )

    def test_terminal_classes_have_zero_budget(self):
        for failure_class in (
                DownloadFailureClass.TLS,
                DownloadFailureClass.HTTP_AUTH_POLICY,
                DownloadFailureClass.HTTP_4XX,
                DownloadFailureClass.DISK_WRITE,
                DownloadFailureClass.DISK_SPACE,
                DownloadFailureClass.PERMISSION_DENIED,
                DownloadFailureClass.CANCELLED,
                DownloadFailureClass.MALFORMED_URL,
                DownloadFailureClass.UNKNOWN_DOWNLOAD_ERROR,
        ):
            with self.subTest(failure_class=failure_class):
                self.assertEqual(policy_for(failure_class).max_attempts, 0)

    def test_classes_that_require_restart_have_flag(self):
        for failure_class in (
                DownloadFailureClass.CHECKSUM_MISMATCH,
                DownloadFailureClass.MISSING_AFTER_TRANSFER,
        ):
            with self.subTest(failure_class=failure_class):
                self.assertTrue(policy_for(failure_class).restart_required)

    def test_unknown_value_returns_default_policy(self):
        self.assertEqual(policy_for("not_a_class"), RetryPolicy())


class TestBackoff(unittest.TestCase):
    def test_exponential_growth_capped_by_max(self):
        policy = RetryPolicy(max_attempts=10, base_delay_seconds=1.0, max_delay_seconds=8.0)
        delays = [compute_backoff_seconds(attempt, policy) for attempt in range(1, 7)]
        # 1, 2, 4, 8, 8, 8 — no jitter so the sequence is deterministic
        self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 8.0, 8.0])

    def test_jitter_uses_injected_rng_and_does_not_underflow(self):
        policy = RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=10.0, jitter_fraction=0.5)
        # With RNG returning exactly 1.0 we get the maximum jitter: 2 * (1 + 0.5*1) = 3.0
        self.assertEqual(compute_backoff_seconds(1, policy, random_unit_fn=lambda: 1.0), 3.0)
        # With RNG returning 0.0 we get the base.
        self.assertEqual(compute_backoff_seconds(1, policy, random_unit_fn=lambda: 0.0), 2.0)

    def test_zero_budget_policy_returns_zero_delay(self):
        self.assertEqual(compute_backoff_seconds(1, RetryPolicy()), 0.0)

    def test_retry_after_overrides_when_policy_allows_and_value_is_larger(self):
        policy = policy_for(DownloadFailureClass.HTTP_429)
        # Policy base for 429 is 5 with cap 60. Retry-After of 17 wins on attempt 1 (base=5).
        self.assertEqual(
            compute_backoff_seconds(1, policy, retry_after_seconds=17, random_unit_fn=lambda: 0.0),
            17.0,
        )

    def test_retry_after_ignored_when_policy_does_not_respect_it(self):
        policy = policy_for(DownloadFailureClass.DNS_RESOLUTION)
        self.assertFalse(policy.respect_retry_after)
        # 1.0 base attempt 1, no jitter via RNG=0.
        self.assertEqual(
            compute_backoff_seconds(1, policy, retry_after_seconds=999, random_unit_fn=lambda: 0.0),
            1.0,
        )


class TestDecideRetry(unittest.TestCase):
    def _zero_jitter(self):
        return lambda: 0.0

    def test_terminal_class_yields_fail_terminal(self):
        decision = decide_retry(_info(DownloadFailureClass.HTTP_AUTH_POLICY, http_status=403), 0)
        self.assertEqual(decision.action, RetryAction.FAIL_TERMINAL)
        self.assertEqual(decision.attempt, 1)
        self.assertEqual(decision.delay_seconds, 0.0)
        self.assertEqual(decision.http_status, 403)
        self.assertEqual(decision.reason, "terminal_failure_class")

    def test_exhausted_budget_yields_fail_terminal(self):
        policy = policy_for(DownloadFailureClass.DNS_RESOLUTION)
        decision = decide_retry(_info(DownloadFailureClass.DNS_RESOLUTION), previous_retry_count=policy.max_attempts)
        self.assertEqual(decision.action, RetryAction.FAIL_TERMINAL)
        self.assertEqual(decision.reason, "max_attempts_exhausted")

    def test_retryable_class_without_resume_yields_restart(self):
        decision = decide_retry(
            _info(DownloadFailureClass.TIMEOUT_DURING_TRANSFER),
            previous_retry_count=0,
            resume_eligible=False,
            random_unit_fn=self._zero_jitter(),
        )
        self.assertEqual(decision.action, RetryAction.RESTART)
        self.assertEqual(decision.reason, "resume_not_eligible")
        self.assertFalse(decision.restart_required)
        self.assertTrue(decision.will_retry)

    def test_retryable_class_with_resume_yields_resume(self):
        decision = decide_retry(
            _info(DownloadFailureClass.TIMEOUT_DURING_TRANSFER),
            previous_retry_count=0,
            resume_eligible=True,
            random_unit_fn=self._zero_jitter(),
        )
        self.assertEqual(decision.action, RetryAction.RESUME)
        self.assertEqual(decision.reason, "resume_eligible_partial")

    def test_checksum_mismatch_forces_restart_even_when_resume_eligible(self):
        decision = decide_retry(
            _info(DownloadFailureClass.CHECKSUM_MISMATCH),
            previous_retry_count=0,
            resume_eligible=True,
        )
        self.assertEqual(decision.action, RetryAction.RESTART)
        self.assertTrue(decision.restart_required)
        self.assertEqual(decision.reason, "restart_required_by_class")

    def test_missing_after_transfer_forces_restart(self):
        decision = decide_retry(
            _info(DownloadFailureClass.MISSING_AFTER_TRANSFER),
            previous_retry_count=0,
            resume_eligible=True,
        )
        self.assertEqual(decision.action, RetryAction.RESTART)
        self.assertTrue(decision.restart_required)

    def test_429_honors_retry_after_when_larger_than_backoff(self):
        info = classify_http_status(429, headers={"Retry-After": "30"})
        self.assertEqual(info.retry_after_seconds, 30)
        decision = decide_retry(info, previous_retry_count=0, random_unit_fn=self._zero_jitter())
        # Policy base for 429 is 5; Retry-After=30 must dominate.
        self.assertEqual(decision.delay_seconds, 30.0)
        self.assertEqual(decision.action, RetryAction.RESTART)  # no resume eligible by default

    def test_curl_exit_28_received_bytes_zero_classifies_as_first_byte_timeout(self):
        info = classify_curl_exit_code(28, received_bytes=0)
        decision = decide_retry(info, previous_retry_count=0)
        self.assertEqual(info.failure_class, DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE)
        self.assertTrue(decision.will_retry)
        self.assertEqual(decision.curl_exit_code, 28)


class TestRetryDecisionLog(unittest.TestCase):
    def test_log_line_has_prefix_and_parsable_json(self):
        decision = decide_retry(
            _info(DownloadFailureClass.HTTP_5XX, http_status=503, retry_after_seconds=2),
            previous_retry_count=1,
            resume_eligible=True,
            random_unit_fn=lambda: 0.0,
        )
        line = format_retry_decision_log_line(
            decision,
            session_id="abc",
            file_id="deadbeef",
            repo_path="path/file.bundle",
            received_bytes=12345,
            concurrency=4,
            timestamp="2026-05-12T00:00:00Z",
        )

        self.assertTrue(line.startswith(DOWNLOAD_RETRY_DECISION_LOG_PREFIX + " "))
        payload = json.loads(line[len(DOWNLOAD_RETRY_DECISION_LOG_PREFIX) + 1:])
        self.assertEqual(payload["event"], "download.retry_decision")
        self.assertEqual(payload["sessionId"], "abc")
        self.assertEqual(payload["fileId"], "deadbeef")
        self.assertEqual(payload["repoPath"], "path/file.bundle")
        self.assertEqual(payload["failureClass"], DownloadFailureClass.HTTP_5XX.value)
        self.assertEqual(payload["decision"], RetryAction.RESUME.value)
        self.assertEqual(payload["attempt"], 2)
        self.assertEqual(payload["httpStatus"], 503)
        self.assertEqual(payload["retryAfterSeconds"], 2)
        self.assertEqual(payload["receivedBytes"], 12345)
        self.assertEqual(payload["concurrency"], 4)
        self.assertEqual(payload["timestamp"], "2026-05-12T00:00:00Z")
        self.assertGreater(payload["delayMs"], 0)
        self.assertFalse(payload["restartRequired"])

    def test_terminal_decision_log_carries_terminal_action(self):
        decision = decide_retry(
            _info(DownloadFailureClass.MALFORMED_URL),
            previous_retry_count=0,
        )
        line = format_retry_decision_log_line(decision, repo_path="x")
        payload = json.loads(line[len(DOWNLOAD_RETRY_DECISION_LOG_PREFIX) + 1:])
        self.assertEqual(payload["decision"], RetryAction.FAIL_TERMINAL.value)
        self.assertEqual(payload["delayMs"], 0)
        self.assertEqual(payload["reason"], "terminal_failure_class")

    def test_log_drops_disallowed_fields_from_extra(self):
        decision = decide_retry(
            _info(DownloadFailureClass.TIMEOUT_DURING_TRANSFER),
            previous_retry_count=0,
            random_unit_fn=lambda: 0.0,
        )
        line = format_retry_decision_log_line(
            decision,
            repo_path="ok",
            extra={
                "url": "https://signed.example.com/?Signature=secret",
                "headers": {"Authorization": "Bearer secret"},
                "cookies": "session=...",
                "policy": "<signed policy>",
                "tempPath": "/Users/me/private",
                "finalPath": "/Users/me/private/final",
                # Allowed: non-sensitive structural extras pass through.
                "hostClass": "cdn",
            },
            timestamp="2026-05-12T00:00:00Z",
        )

        payload = json.loads(line[len(DOWNLOAD_RETRY_DECISION_LOG_PREFIX) + 1:])
        for forbidden in ("url", "headers", "cookies", "policy", "tempPath", "finalPath"):
            self.assertNotIn(forbidden, payload, f"sensitive key {forbidden!r} leaked into log payload")
        self.assertEqual(payload["hostClass"], "cdn")


if __name__ == "__main__":
    unittest.main(verbosity=3)
