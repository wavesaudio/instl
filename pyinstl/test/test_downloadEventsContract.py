#!/usr/bin/env python3.12

"""Contract guard for the structured download-event channel.

`test_downloadEvents.py` checks individual builder behavior; this file pins the
*contract* documented in `docs/download-events.md`: the set of keys each event
type carries, the schema version, the additive-field invariants, and the privacy
denylist. The Central consumer (`downloadEventContract.test.tsx`) pins the same
contract from the other side.

The intent is that any change which would silently break Central — removing or
renaming a documented field, bumping the schema version, leaking a denylisted key
— fails here first. Additive fields are explicitly allowed (subset checks, not
equality), matching the evolution rule in the doc.
"""

import json
import os
import sys
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadEvents import (
    DOWNLOAD_EVENT_SCHEMA_VERSION,
    _DISALLOWED_EVENT_FIELDS,
    format_event_line,
    make_capability_event,
    make_file_state_event,
    make_retry_decision_event,
    make_session_state_event,
    make_session_summary_event,
)
from downloadFailures import DownloadFailureClass
from downloadRetry import RetryAction, RetryDecision

# The documented envelope keys (docs/download-events.md §2).
ENVELOPE_KEYS = {"event", "schemaVersion", "sessionId", "timestamp"}

# Required (always-present) keys per event type (docs §3). Subset checks: adding
# a NEW optional field is allowed and must not break this; removing/renaming a
# documented field is a breaking change and must fail here.
REQUIRED_KEYS = {
    "download.session_state": ENVELOPE_KEYS | {
        "state", "previousState", "filesPlanned", "bytesPlanned",
        "concurrencyPlanned", "actionId", "repositoryMajorVersion",
        "repositoryRevision", "reason",
    },
    "download.file_state": ENVELOPE_KEYS | {
        "fileId", "repoPath", "state", "previousState", "expectedSize",
        "receivedBytes", "retryCount", "lastFailureClass", "resumed", "host",
    },
    "download.retry_decision": ENVELOPE_KEYS | {
        "fileId", "repoPath", "failureClass", "attempt", "decision", "delayMs",
        "restartRequired", "reason", "receivedBytes", "concurrency",
        "retryAfterSeconds", "httpStatus", "curlExitCode",
    },
    "download.capability": ENVELOPE_KEYS | {
        "resumeEnabled", "validatedHosts",
        "retryMatrixVersion", "stateSchemaVersion", "eventSchemaVersion",
        "featureFlags", "centralUxEnabled", "telemetryEnabled",
        "retryPolicyEnabled",
    },
    "download.session_summary": ENVELOPE_KEYS | {"summary"},
}

# The live-progress fields are additive and only on in-flight download ticks.
SESSION_STATE_LIVE_FIELDS = {
    "bytesReceived", "filesCompleted", "observedThroughputBytesPerSecond",
}


class TestEventContract(unittest.TestCase):
    def _all_events(self):
        retry = RetryDecision(
            action=RetryAction.RESUME,
            failure_class=DownloadFailureClass.TIMEOUT_DURING_TRANSFER,
            attempt=1,
            delay_seconds=2.0,
            reason="transient",
        )
        return {
            "download.session_state": make_session_state_event(
                session_id="s1", state="downloading"),
            "download.file_state": make_file_state_event(
                session_id="s1", file_id="f1", repo_path="a/b.bundle",
                state="downloading"),
            "download.retry_decision": make_retry_decision_event(
                retry, session_id="s1"),
            "download.capability": make_capability_event(
                session_id="s1", resume_enabled=True),
            "download.session_summary": make_session_summary_event(
                session_id="s1", summary={"wallMs": 10, "totals": {}}),
        }

    def test_required_keys_present_for_each_event(self):
        for event_name, event in self._all_events().items():
            missing = REQUIRED_KEYS[event_name] - set(event.keys())
            self.assertEqual(missing, set(),
                             f"{event_name} dropped documented key(s): {missing}")
            self.assertEqual(event["event"], event_name)

    def test_schema_version_is_one(self):
        # Bumping this is a deliberate BREAKING change (renames/removals/retyping).
        # Additive fields must NOT bump it. See docs/download-events.md §5.
        self.assertEqual(DOWNLOAD_EVENT_SCHEMA_VERSION, 1)
        for event in self._all_events().values():
            self.assertEqual(event["schemaVersion"], 1)

    def test_session_state_live_fields_are_additive(self):
        # Absent on lifecycle transitions (keeps the base shape stable)...
        base = make_session_state_event(session_id="s1", state="downloading")
        self.assertEqual(SESSION_STATE_LIVE_FIELDS & set(base.keys()), set())
        # ...present on in-flight download ticks, without disturbing required keys.
        tick = make_session_state_event(
            session_id="s1", state="downloading",
            bytes_received=10, files_completed=1,
            observed_throughput_bytes_per_second=5)
        self.assertTrue(SESSION_STATE_LIVE_FIELDS <= set(tick.keys()))
        self.assertTrue(REQUIRED_KEYS["download.session_state"] <= set(tick.keys()))

    def test_denylisted_keys_never_serialized(self):
        # Even if a caller smuggles a denylisted key in, the formatter drops it.
        leaky = make_session_state_event(session_id="s1", state="downloading")
        leaky["url"] = "https://secret/signed?token=abc"
        leaky["finalPath"] = "/Users/someone/secret"
        payload = json.loads(format_event_line(leaky).split(" ", 1)[1])
        for banned in _DISALLOWED_EVENT_FIELDS:
            self.assertNotIn(banned, payload)

    def test_emitted_line_prefixed_and_sorted(self):
        line = format_event_line(
            make_session_state_event(session_id="s1", state="downloading"))
        prefix, body = line.split(" ", 1)
        self.assertEqual(prefix, "DOWNLOAD_EVENT")
        # Keys are emitted sorted so consumers/fixtures are stable.
        parsed = json.loads(body)
        self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))


if __name__ == "__main__":
    unittest.main()
