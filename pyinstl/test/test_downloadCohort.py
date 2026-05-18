#!/usr/bin/env python3.12

"""Tests for the Phase 6 rollout cohort module (``P6-001``/``P6-003``)."""

import os
import sys
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadCohort import (
    ADAPTIVE_COHORT,
    ATOMICITY_COHORT,
    COHORTS,
    CONTROL_COHORT,
    RESUME_COHORT,
    RETRY_COHORT,
    UX_COHORT,
    active_flags_from_config,
    downgrade_cohort_to_active_flags,
    normalize_cohort,
    required_flags_for,
    resolve_cohort_from_config,
    tracked_flag_names,
)


class _FakeVar:
    def __init__(self, value):
        self._value = value

    def str(self):
        return str(self._value)

    def bool(self):
        if isinstance(self._value, bool):
            return self._value
        text = str(self._value).strip().lower()
        return text in ("yes", "true", "1", "on")


class _FakeConfig:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def __contains__(self, key):
        return key in self._values

    def __getitem__(self, key):
        return _FakeVar(self._values[key])


class TestCohortLabels(unittest.TestCase):
    def test_cohorts_match_rollout_plan_order(self):
        self.assertEqual(
            COHORTS,
            (
                CONTROL_COHORT,
                ATOMICITY_COHORT,
                RESUME_COHORT,
                RETRY_COHORT,
                ADAPTIVE_COHORT,
                UX_COHORT,
            ),
        )

    def test_normalize_cohort_canonicalizes_case_and_unknowns(self):
        self.assertEqual(normalize_cohort("Resume"), RESUME_COHORT)
        self.assertEqual(normalize_cohort("  ux  "), UX_COHORT)
        self.assertEqual(normalize_cohort("unknown"), CONTROL_COHORT)
        self.assertEqual(normalize_cohort(""), CONTROL_COHORT)
        self.assertEqual(normalize_cohort(None), CONTROL_COHORT)

    def test_required_flags_grow_monotonically(self):
        # Each cohort must require at least the flags its predecessor needs,
        # so the downgrade walk in resolve_cohort_from_config is consistent.
        previous = ()
        for cohort in (RESUME_COHORT, RETRY_COHORT, ADAPTIVE_COHORT, UX_COHORT):
            required = required_flags_for(cohort)
            self.assertTrue(set(previous).issubset(set(required)),
                            f"{cohort} required flags shrank: {previous!r} -> {required!r}")
            previous = required


class TestDowngradeToActiveFlags(unittest.TestCase):
    def test_full_flag_set_keeps_requested_cohort(self):
        flags = {
            "DOWNLOAD_RESUME_ENABLED": True,
            "DOWNLOAD_RETRY_POLICY_ENABLED": True,
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": True,
            "DOWNLOAD_CENTRAL_UX_ENABLED": True,
        }
        self.assertEqual(downgrade_cohort_to_active_flags(UX_COHORT, flags), UX_COHORT)

    def test_missing_ux_flag_downgrades_to_adaptive(self):
        flags = {
            "DOWNLOAD_RESUME_ENABLED": True,
            "DOWNLOAD_RETRY_POLICY_ENABLED": True,
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": True,
            "DOWNLOAD_CENTRAL_UX_ENABLED": False,
        }
        self.assertEqual(downgrade_cohort_to_active_flags(UX_COHORT, flags), ADAPTIVE_COHORT)

    def test_missing_resume_flag_walks_all_the_way_down_to_atomicity(self):
        flags = {
            "DOWNLOAD_RESUME_ENABLED": False,
            "DOWNLOAD_RETRY_POLICY_ENABLED": True,
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": True,
            "DOWNLOAD_CENTRAL_UX_ENABLED": True,
        }
        # Requested ux -> needs resume+retry+adaptive+ux, but resume off,
        # so it walks down through adaptive (needs resume), retry (needs
        # resume), resume (needs resume) and lands at atomicity (no flags).
        self.assertEqual(downgrade_cohort_to_active_flags(UX_COHORT, flags), ATOMICITY_COHORT)

    def test_unknown_cohort_starts_at_control(self):
        self.assertEqual(
            downgrade_cohort_to_active_flags("nonsense", {}),
            CONTROL_COHORT,
        )


class TestResolveCohortFromConfig(unittest.TestCase):
    def test_default_when_config_is_empty(self):
        self.assertEqual(resolve_cohort_from_config(_FakeConfig()), CONTROL_COHORT)

    def test_resume_label_with_flag_on(self):
        cfg = _FakeConfig({
            "DOWNLOAD_COHORT": "resume",
            "DOWNLOAD_RESUME_ENABLED": "yes",
        })
        self.assertEqual(resolve_cohort_from_config(cfg), RESUME_COHORT)

    def test_resume_label_with_flag_off_downgrades(self):
        cfg = _FakeConfig({
            "DOWNLOAD_COHORT": "resume",
            "DOWNLOAD_RESUME_ENABLED": "no",
        })
        # Resume needs DOWNLOAD_RESUME_ENABLED; atomicity needs nothing;
        # so the walk lands at atomicity, not control.
        self.assertEqual(resolve_cohort_from_config(cfg), ATOMICITY_COHORT)

    def test_ux_label_falls_back_when_central_ux_off(self):
        cfg = _FakeConfig({
            "DOWNLOAD_COHORT": "ux",
            "DOWNLOAD_RESUME_ENABLED": "yes",
            "DOWNLOAD_RETRY_POLICY_ENABLED": "yes",
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": "yes",
            "DOWNLOAD_CENTRAL_UX_ENABLED": "no",
        })
        self.assertEqual(resolve_cohort_from_config(cfg), ADAPTIVE_COHORT)


class TestActiveFlagsFromConfig(unittest.TestCase):
    def test_tracked_flag_names_cover_all_phase6_flags(self):
        names = set(tracked_flag_names())
        self.assertEqual(names, {
            "DOWNLOAD_TELEMETRY_ENABLED",
            "DOWNLOAD_RESUME_ENABLED",
            "DOWNLOAD_RETRY_POLICY_ENABLED",
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED",
            "DOWNLOAD_CENTRAL_UX_ENABLED",
        })

    def test_active_flags_defaults_match_shipping_defaults(self):
        # Untouched config -> tracked flags fall back to their declared
        # defaults. Two flags default on (telemetry, retry policy) so
        # that Phase 5 capabilities keep working after Phase 6 lands.
        flags = active_flags_from_config(_FakeConfig())
        self.assertEqual(flags["DOWNLOAD_TELEMETRY_ENABLED"], True)
        self.assertEqual(flags["DOWNLOAD_RETRY_POLICY_ENABLED"], True)
        self.assertEqual(flags["DOWNLOAD_RESUME_ENABLED"], False)
        self.assertEqual(flags["DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED"], False)
        self.assertEqual(flags["DOWNLOAD_CENTRAL_UX_ENABLED"], False)

    def test_active_flags_read_from_config(self):
        cfg = _FakeConfig({
            "DOWNLOAD_TELEMETRY_ENABLED": "no",
            "DOWNLOAD_RESUME_ENABLED": "yes",
            "DOWNLOAD_RETRY_POLICY_ENABLED": "no",
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": "yes",
            "DOWNLOAD_CENTRAL_UX_ENABLED": "yes",
        })
        flags = active_flags_from_config(cfg)
        self.assertFalse(flags["DOWNLOAD_TELEMETRY_ENABLED"])
        self.assertTrue(flags["DOWNLOAD_RESUME_ENABLED"])
        self.assertFalse(flags["DOWNLOAD_RETRY_POLICY_ENABLED"])
        self.assertTrue(flags["DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED"])
        self.assertTrue(flags["DOWNLOAD_CENTRAL_UX_ENABLED"])


class TestCapabilityEmissionSmoke(unittest.TestCase):
    """Phase 6 P6-004 smoke-test: exercise the rollout flag + cohort resolver
    end-to-end against the capability event builder so a misconfigured
    rollout surfaces here, not in production telemetry.

    The cohort label on the wire MUST match the active flag set: a build
    tagged ``ux`` but missing ``DOWNLOAD_CENTRAL_UX_ENABLED`` cannot ship,
    because metrics would compare cohorts that are not actually different.
    """

    def _build(self, cohort_label, flags):
        from downloadEvents import format_event_line, make_capability_event
        config = _FakeConfig({
            "DOWNLOAD_COHORT": cohort_label,
            **{name: ("yes" if value else "no") for name, value in flags.items()},
        })
        cohort = resolve_cohort_from_config(config)
        active = active_flags_from_config(config)
        event = make_capability_event(
            session_id="smoke",
            resume_enabled=active["DOWNLOAD_RESUME_ENABLED"],
            adaptive_concurrency_enabled=active["DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED"],
            validated_hosts=["cdn.example.com"],
            cohort=cohort,
            feature_flags=active,
            central_ux_enabled=active["DOWNLOAD_CENTRAL_UX_ENABLED"],
            telemetry_enabled=active["DOWNLOAD_TELEMETRY_ENABLED"],
            retry_policy_enabled=active["DOWNLOAD_RETRY_POLICY_ENABLED"],
            timestamp="2026-05-17T10:00:00Z",
        )
        return cohort, active, event, format_event_line(event)

    def test_control_cohort_emits_with_all_runtime_flags_off(self):
        cohort, flags, event, line = self._build(CONTROL_COHORT, {})
        self.assertEqual(cohort, CONTROL_COHORT)
        self.assertEqual(event["cohort"], CONTROL_COHORT)
        self.assertFalse(event["resumeEnabled"])
        self.assertFalse(event["adaptiveConcurrencyEnabled"])
        self.assertFalse(event["centralUxEnabled"])
        # Telemetry/retry policy default ON per D-018 so Phase 5 keeps working.
        self.assertTrue(event["telemetryEnabled"])
        self.assertTrue(event["retryPolicyEnabled"])
        self.assertTrue(line.startswith("DOWNLOAD_EVENT "))

    def test_full_ux_cohort_emits_with_every_flag_on(self):
        cohort, flags, event, _line = self._build(UX_COHORT, {
            "DOWNLOAD_RESUME_ENABLED": True,
            "DOWNLOAD_RETRY_POLICY_ENABLED": True,
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": True,
            "DOWNLOAD_CENTRAL_UX_ENABLED": True,
            "DOWNLOAD_TELEMETRY_ENABLED": True,
        })
        self.assertEqual(cohort, UX_COHORT)
        self.assertEqual(event["cohort"], UX_COHORT)
        self.assertTrue(event["resumeEnabled"])
        self.assertTrue(event["adaptiveConcurrencyEnabled"])
        self.assertTrue(event["centralUxEnabled"])
        self.assertEqual(event["featureFlags"], {
            "DOWNLOAD_TELEMETRY_ENABLED": True,
            "DOWNLOAD_RESUME_ENABLED": True,
            "DOWNLOAD_RETRY_POLICY_ENABLED": True,
            "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": True,
            "DOWNLOAD_CENTRAL_UX_ENABLED": True,
        })

    def test_misconfigured_resume_cohort_downgrades_to_atomicity(self):
        # If the rollout tool tags an install ``resume`` but the resume
        # flag is off, the event must record the actual layer (atomicity)
        # rather than the wishful label.
        cohort, flags, event, _line = self._build(RESUME_COHORT, {
            "DOWNLOAD_RESUME_ENABLED": False,
            "DOWNLOAD_RETRY_POLICY_ENABLED": True,
        })
        self.assertEqual(cohort, ATOMICITY_COHORT)
        self.assertEqual(event["cohort"], ATOMICITY_COHORT)
        self.assertFalse(event["resumeEnabled"])

    def test_each_documented_cohort_round_trips_through_emission(self):
        # P6-004 entry criterion: every documented cohort label produces
        # a parseable, structured event line. This guards against typos
        # in COHORTS or downgrade logic accidentally collapsing labels.
        import json
        from downloadEvents import DOWNLOAD_EVENT_LOG_PREFIX
        for label in (CONTROL_COHORT, ATOMICITY_COHORT, RESUME_COHORT, RETRY_COHORT, ADAPTIVE_COHORT, UX_COHORT):
            cohort, _flags, _event, line = self._build(label, {
                "DOWNLOAD_RESUME_ENABLED": True,
                "DOWNLOAD_RETRY_POLICY_ENABLED": True,
                "DOWNLOAD_ADAPTIVE_CONCURRENCY_ENABLED": True,
                "DOWNLOAD_CENTRAL_UX_ENABLED": True,
            })
            prefix, payload = line.split(" ", 1)
            self.assertEqual(prefix, DOWNLOAD_EVENT_LOG_PREFIX)
            decoded = json.loads(payload)
            self.assertEqual(decoded["event"], "download.capability")
            self.assertEqual(decoded["cohort"], label)
            self.assertIn("featureFlags", decoded)


if __name__ == "__main__":
    unittest.main()
