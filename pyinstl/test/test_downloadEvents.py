#!/usr/bin/env python3.12

"""Tests for the structured DOWNLOAD_EVENT channel.

These tests exercise ``downloadEvents`` without any ``instl`` runtime
dependency. They cover the JSON-line envelope, redaction denylist,
event type builders, host validation in ``make_capability_event``, and
the unified retry decision event shape.
"""

import json
import logging
import os
import sys
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadEvents import (
    DOWNLOAD_EVENT_LOG_PREFIX,
    DOWNLOAD_EVENT_SCHEMA_VERSION,
    DownloadEventType,
    active_flags_from_config,
    emit_event,
    format_event_line,
    make_capability_event,
    make_envelope,
    make_file_state_event,
    make_retry_decision_event,
    make_session_state_event,
    make_session_summary_event,
)
from downloadFailures import DownloadFailureClass
from downloadRetry import RetryAction, RetryDecision


def _parse_line(line):
    self_test = line.split(" ", 1)
    assert self_test[0] == DOWNLOAD_EVENT_LOG_PREFIX, line
    return json.loads(self_test[1])


class TestEnvelope(unittest.TestCase):
    def test_envelope_has_required_fields(self):
        env = make_envelope(DownloadEventType.SESSION_STATE,
                            session_id="abc",
                            timestamp="2026-05-17T10:00:00Z")
        self.assertEqual(env["event"], "download.session_state")
        self.assertEqual(env["schemaVersion"], DOWNLOAD_EVENT_SCHEMA_VERSION)
        self.assertEqual(env["sessionId"], "abc")
        self.assertEqual(env["timestamp"], "2026-05-17T10:00:00Z")

    def test_envelope_defaults_session_id_when_missing(self):
        env = make_envelope(DownloadEventType.CAPABILITY,
                            session_id=None, timestamp="2026-05-17T10:00:00Z")
        self.assertEqual(env["sessionId"], "unknown")

    def test_format_event_line_uses_sorted_compact_json(self):
        env = make_envelope(DownloadEventType.CAPABILITY,
                            session_id="s1", timestamp="2026-05-17T10:00:00Z")
        env["b"] = 1
        env["a"] = 2
        line = format_event_line(env)
        prefix, payload = line.split(" ", 1)
        self.assertEqual(prefix, DOWNLOAD_EVENT_LOG_PREFIX)
        # sorted keys -> "a" comes before "b" in the serialization
        self.assertLess(payload.index('"a"'), payload.index('"b"'))


class TestRedaction(unittest.TestCase):
    def test_denylisted_keys_are_dropped_from_envelope(self):
        env = make_envelope(DownloadEventType.SESSION_STATE,
                            session_id="s1", timestamp="2026-05-17T10:00:00Z")
        env["url"] = "https://example.com/secret"
        env["cookies"] = "CloudFront-Policy=abc"
        env["finalPath"] = "/Users/foo/bar"
        env["tempPath"] = "/Users/foo/bar.part"
        env["state"] = "downloading"
        line = format_event_line(env)
        payload = _parse_line(line)
        self.assertNotIn("url", payload)
        self.assertNotIn("cookies", payload)
        self.assertNotIn("finalPath", payload)
        self.assertNotIn("tempPath", payload)
        self.assertEqual(payload["state"], "downloading")

    def test_capability_event_rejects_non_host_strings(self):
        event = make_capability_event(
            session_id="s1",
            resume_enabled=True,
            validated_hosts=[
                "cdn.example.com",
                "evil.example.com/path",   # rejected: path
                "?query=bad",              # rejected: query
                "http://withscheme.com",   # rejected: contains "/"
                " ",                       # rejected: blank
                "CDN.Example.Com",         # normalized to lowercase, dedup'd
            ],
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertEqual(event["validatedHosts"], ["cdn.example.com"])

    def test_session_summary_redacts_disallowed_keys(self):
        bad_summary = {
            "sessionId": "s1",
            "url": "https://cdn.example.com/V16/secret",
            "finalPath": "/Users/foo/bar",
            "totals": {"attempts": 3, "successes": 2},
        }
        event = make_session_summary_event(
            session_id="s1",
            summary=bad_summary,
            timestamp="2026-05-17T10:00:00Z",
        )
        line = format_event_line(event)
        payload = _parse_line(line)
        # Top-level summary still includes legit fields but not the
        # denylisted ones (note: nested denial is the caller's
        # responsibility; downloadObservability never produces them).
        self.assertNotIn("url", payload["summary"])
        self.assertNotIn("finalPath", payload["summary"])
        self.assertIn("totals", payload["summary"])


class TestSessionStateEvent(unittest.TestCase):
    def test_full_payload(self):
        event = make_session_state_event(
            session_id="s1",
            state="downloading",
            previous_state="preparing",
            files_planned=10,
            bytes_planned=5000,
            concurrency_planned=8,
            action_id="install",
            repository_major_version=16,
            repository_revision=123456,
            reason="curl_started",
            timestamp="2026-05-17T10:00:00Z",
        )
        line = format_event_line(event)
        payload = _parse_line(line)
        self.assertEqual(payload["event"], "download.session_state")
        self.assertEqual(payload["state"], "downloading")
        self.assertEqual(payload["previousState"], "preparing")
        self.assertEqual(payload["filesPlanned"], 10)
        self.assertEqual(payload["bytesPlanned"], 5000)
        self.assertEqual(payload["concurrencyPlanned"], 8)
        self.assertEqual(payload["actionId"], "install")
        self.assertEqual(payload["repositoryMajorVersion"], 16)
        self.assertEqual(payload["repositoryRevision"], 123456)
        self.assertEqual(payload["reason"], "curl_started")

    def test_state_accepts_enum_values(self):
        from downloadState import DownloadSessionState
        event = make_session_state_event(
            session_id="s1",
            state=DownloadSessionState.DOWNLOADING,
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertEqual(event["state"], "downloading")

    def test_live_progress_fields_present_when_supplied(self):
        # In-flight download ticks carry cumulative bytes/files
        # and a smoothed throughput so Central can compute a live ETA.
        event = make_session_state_event(
            session_id="s1",
            state="downloading",
            bytes_planned=5000,
            bytes_received=1234,
            files_completed=3,
            observed_throughput_bytes_per_second=456,
            reason="download_progress",
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertEqual(event["bytesReceived"], 1234)
        self.assertEqual(event["filesCompleted"], 3)
        self.assertEqual(event["observedThroughputBytesPerSecond"], 456)

    def test_phase_progress_fields_present_when_supplied(self):
        # Post-download phases (e.g. verify) carry
        # per-phase byte progress so Central can drive a determinate install bar.
        event = make_session_state_event(
            session_id="s1",
            state="verifying_downloads",
            phase_bytes_done=4096,
            phase_bytes_planned=8192,
            reason="verify_progress",
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertEqual(event["phaseBytesDone"], 4096)
        self.assertEqual(event["phaseBytesPlanned"], 8192)

    def test_live_progress_fields_absent_on_lifecycle_transitions(self):
        # Lifecycle-transition events (no live fields supplied) must keep their
        # original shape so existing consumers/fixtures are unaffected.
        event = make_session_state_event(
            session_id="s1",
            state="downloading",
            files_planned=10,
            bytes_planned=5000,
            reason="download_started",
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertNotIn("bytesReceived", event)
        self.assertNotIn("filesCompleted", event)
        self.assertNotIn("observedThroughputBytesPerSecond", event)


class TestFileStateEvent(unittest.TestCase):
    def test_file_state_event_shape(self):
        event = make_file_state_event(
            session_id="s1",
            file_id="deadbeef",
            repo_path="foo/bar.bundle",
            state="failed_retryable",
            previous_state="downloading",
            expected_size=12345,
            received_bytes=678,
            retry_count=2,
            last_failure_class=DownloadFailureClass.TIMEOUT_DURING_TRANSFER,
            resumed=False,
            host="cdn.example.com",
            timestamp="2026-05-17T10:00:00Z",
        )
        line = format_event_line(event)
        payload = _parse_line(line)
        self.assertEqual(payload["event"], "download.file_state")
        self.assertEqual(payload["fileId"], "deadbeef")
        self.assertEqual(payload["repoPath"], "foo/bar.bundle")
        self.assertEqual(payload["state"], "failed_retryable")
        self.assertEqual(payload["previousState"], "downloading")
        self.assertEqual(payload["expectedSize"], 12345)
        self.assertEqual(payload["receivedBytes"], 678)
        self.assertEqual(payload["retryCount"], 2)
        self.assertEqual(payload["lastFailureClass"], "timeout_during_transfer")
        self.assertFalse(payload["resumed"])
        self.assertEqual(payload["host"], "cdn.example.com")


class TestCapabilityEvent(unittest.TestCase):
    def test_capability_event_includes_versions(self):
        event = make_capability_event(
            session_id="s1",
            resume_enabled=True,
            validated_hosts=["cdn.example.com"],
            retry_matrix_version=1,
            state_schema_version=1,
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertTrue(event["resumeEnabled"])
        self.assertEqual(event["validatedHosts"], ["cdn.example.com"])
        self.assertEqual(event["retryMatrixVersion"], 1)
        self.assertEqual(event["stateSchemaVersion"], 1)
        self.assertEqual(event["eventSchemaVersion"], DOWNLOAD_EVENT_SCHEMA_VERSION)

    def test_capability_event_optional_fields_default_when_omitted(self):
        # when the caller omits the optional fields the builder still emits
        # sensible defaults so Central always sees a complete envelope
        event = make_capability_event(
            session_id="s1",
            resume_enabled=False,
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertEqual(event["featureFlags"], {})
        self.assertFalse(event["centralUxEnabled"])
        self.assertTrue(event["telemetryEnabled"])
        self.assertTrue(event["retryPolicyEnabled"])

    def test_capability_event_redacts_feature_flag_keys(self):
        event = make_capability_event(
            session_id="s1",
            resume_enabled=True,
            feature_flags={
                "DOWNLOAD_RESUME_ENABLED": True,
                "DOWNLOAD_TELEMETRY_ENABLED": "yes",  # coerced bool
                "": True,  # empty key dropped
            },
            central_ux_enabled=True,
            telemetry_enabled=False,
            retry_policy_enabled=False,
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertEqual(event["featureFlags"], {
            "DOWNLOAD_RESUME_ENABLED": True,
            "DOWNLOAD_TELEMETRY_ENABLED": True,
        })
        self.assertTrue(event["centralUxEnabled"])
        self.assertFalse(event["telemetryEnabled"])
        self.assertFalse(event["retryPolicyEnabled"])


class _FakeVar:
    def __init__(self, value):
        self._value = value

    def bool(self):
        if isinstance(self._value, bool):
            return self._value
        return str(self._value).strip().lower() in ("yes", "true", "1", "on")


class _FakeConfig:
    """Stands in for the instl ConfigVarStack: __getitem__ yields a var with .bool()."""

    def __init__(self, values=None):
        self._values = dict(values or {})

    def __contains__(self, name):
        return name in self._values

    def __getitem__(self, name):
        return _FakeVar(self._values[name])


class TestActiveFlagsFromConfig(unittest.TestCase):
    """The featureFlags map reported on the capability event."""

    def test_defaults_match_shipping_yaml_defaults(self):
        # An undefined key falls back to the declared default, which must agree
        # with defaults/InstlClient.yaml -- the two used to disagree.
        flags = active_flags_from_config(_FakeConfig())
        self.assertEqual(flags, {
            "DOWNLOAD_TELEMETRY_ENABLED": True,
            "DOWNLOAD_RESUME_ENABLED": True,
            "DOWNLOAD_RETRY_POLICY_ENABLED": True,
            "DOWNLOAD_CENTRAL_UX_ENABLED": True,
            "DOWNLOAD_RECONCILE_MISSING_OUTPUTS": True,
            "DOWNLOAD_OFFLINE_HOLD_ENABLED": True,
            "DOWNLOAD_CURL_STALL_DETECTION": True,
            "DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES": True,
            # only a NEW Central that handles backend-hold events without
            # auto-pausing declares this one
            "DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD": False,
        })

    def test_reads_yes_no_from_config(self):
        cfg = _FakeConfig({
            "DOWNLOAD_TELEMETRY_ENABLED": "no",
            "DOWNLOAD_RETRY_POLICY_ENABLED": "no",
            "DOWNLOAD_CENTRAL_UX_ENABLED": "yes",
            "DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD": "yes",
        })
        flags = active_flags_from_config(cfg)
        self.assertFalse(flags["DOWNLOAD_TELEMETRY_ENABLED"])
        self.assertFalse(flags["DOWNLOAD_RETRY_POLICY_ENABLED"])
        self.assertTrue(flags["DOWNLOAD_CENTRAL_UX_ENABLED"])
        self.assertTrue(flags["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"])
        # untouched keys still fall back
        self.assertTrue(flags["DOWNLOAD_OFFLINE_HOLD_ENABLED"])

    def test_unreadable_config_falls_back_to_defaults(self):
        class Exploding:
            def __contains__(self, name):
                raise RuntimeError("config unavailable")

        flags = active_flags_from_config(Exploding())
        self.assertTrue(flags["DOWNLOAD_TELEMETRY_ENABLED"])
        self.assertFalse(flags["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"])
        self.assertIsNone(active_flags_from_config(None).get("missing"))

    def test_flags_flow_onto_the_capability_event(self):
        flags = active_flags_from_config(_FakeConfig({"DOWNLOAD_TELEMETRY_ENABLED": "no"}))
        event = make_capability_event(
            session_id="smoke",
            resume_enabled=flags["DOWNLOAD_RESUME_ENABLED"],
            validated_hosts=["cdn.example.com"],
            feature_flags=flags,
            central_ux_enabled=flags["DOWNLOAD_CENTRAL_UX_ENABLED"],
            telemetry_enabled=flags["DOWNLOAD_TELEMETRY_ENABLED"],
            retry_policy_enabled=flags["DOWNLOAD_RETRY_POLICY_ENABLED"],
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertFalse(event["featureFlags"]["DOWNLOAD_TELEMETRY_ENABLED"])
        self.assertFalse(event["telemetryEnabled"])
        self.assertTrue(event["resumeEnabled"])
        self.assertEqual(event["validatedHosts"], ["cdn.example.com"])
        # the line must still serialize after the flag map is attached
        self.assertIn(DOWNLOAD_EVENT_LOG_PREFIX, format_event_line(event))


class TestRetryDecisionEvent(unittest.TestCase):
    def _make_decision(self):
        return RetryDecision(
            action=RetryAction.RESUME,
            failure_class=DownloadFailureClass.TIMEOUT_DURING_TRANSFER,
            attempt=2,
            delay_seconds=1.5,
            reason="resume_eligible_partial",
            restart_required=False,
            retry_after_seconds=None,
            http_status=None,
            curl_exit_code=28,
        )

    def test_retry_decision_event_shape(self):
        decision = self._make_decision()
        event = make_retry_decision_event(
            decision,
            session_id="s1",
            file_id="deadbeef",
            repo_path="foo/bar.bundle",
            received_bytes=1024,
            concurrency=4,
            timestamp="2026-05-17T10:00:00Z",
        )
        self.assertEqual(event["event"], "download.retry_decision")
        self.assertEqual(event["fileId"], "deadbeef")
        self.assertEqual(event["repoPath"], "foo/bar.bundle")
        self.assertEqual(event["failureClass"], "timeout_during_transfer")
        self.assertEqual(event["attempt"], 2)
        self.assertEqual(event["decision"], "resume")
        self.assertEqual(event["delayMs"], 1500)
        self.assertFalse(event["restartRequired"])
        self.assertEqual(event["reason"], "resume_eligible_partial")
        self.assertEqual(event["receivedBytes"], 1024)
        self.assertEqual(event["concurrency"], 4)
        self.assertIsNone(event["retryAfterSeconds"])
        self.assertIsNone(event["httpStatus"])
        self.assertEqual(event["curlExitCode"], 28)

    def test_retry_decision_event_serializes_cleanly(self):
        decision = self._make_decision()
        event = make_retry_decision_event(
            decision, session_id="s1", timestamp="2026-05-17T10:00:00Z")
        line = format_event_line(event)
        payload = _parse_line(line)
        # Ensure no auth or local-path material can have been added.
        for key in ("url", "headers", "cookies", "tempPath", "finalPath"):
            self.assertNotIn(key, payload)


class TestEmitEvent(unittest.TestCase):
    def test_emit_event_logs_at_info_with_prefix(self):
        event = make_session_state_event(
            session_id="s1",
            state="preparing",
            timestamp="2026-05-17T10:00:00Z",
        )
        with self.assertLogs("downloadEvents", level="INFO") as captured:
            line = emit_event(event)
        self.assertIsNotNone(line)
        self.assertTrue(line.startswith(DOWNLOAD_EVENT_LOG_PREFIX + " "))
        # The logger should have captured exactly the same line.
        joined = "\n".join(captured.output)
        self.assertIn(DOWNLOAD_EVENT_LOG_PREFIX, joined)


class TestTelemetryKillSwitch(unittest.TestCase):
    """Phase 6 P6-002: ``set_telemetry_enabled(False)`` mutes the channel."""

    def tearDown(self):
        # Restore the default so subsequent tests in the same suite are
        # not affected by a stuck process-level flag.
        from downloadEvents import set_telemetry_enabled
        set_telemetry_enabled(True)

    def test_emit_event_returns_none_when_disabled(self):
        from downloadEvents import set_telemetry_enabled, is_telemetry_enabled
        event = make_session_state_event(
            session_id="s1",
            state="preparing",
            timestamp="2026-05-17T10:00:00Z",
        )
        set_telemetry_enabled(False)
        self.assertFalse(is_telemetry_enabled())
        # Assert no INFO line is emitted while the flag is off.
        logger = logging.getLogger("downloadEvents")
        records: list = []

        class _Handler(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Handler(level=logging.INFO)
        logger.addHandler(handler)
        try:
            line = emit_event(event)
        finally:
            logger.removeHandler(handler)
        self.assertIsNone(line)
        self.assertEqual(records, [])

    def test_emit_event_resumes_after_re_enabling(self):
        from downloadEvents import set_telemetry_enabled
        set_telemetry_enabled(False)
        set_telemetry_enabled(True)
        event = make_session_state_event(
            session_id="s1",
            state="preparing",
            timestamp="2026-05-17T10:00:00Z",
        )
        with self.assertLogs("downloadEvents", level="INFO") as captured:
            line = emit_event(event)
        self.assertIsNotNone(line)
        self.assertIn(DOWNLOAD_EVENT_LOG_PREFIX, "\n".join(captured.output))


class TestPrivacyIntegration(unittest.TestCase):
    """End-to-end check: a full event line never contains denylisted fields."""

    def test_session_state_line_never_contains_disallowed_keys(self):
        event = make_session_state_event(
            session_id="s1",
            state="downloading",
            timestamp="2026-05-17T10:00:00Z",
        )
        # Attempt to slip secret fields into a mutable copy.
        event["url"] = "https://cdn.example.com/V16/file?Signature=abc"
        event["headers"] = "Authorization: Bearer secret"
        line = format_event_line(event)
        self.assertNotIn("Signature", line)
        self.assertNotIn("Bearer", line)
        self.assertNotIn("Authorization", line)


if __name__ == "__main__":
    unittest.main()
