#!/usr/bin/env python3.12

"""Tests for the recovery-cliff removal in ``CheckDownloadFolderChecksum``
(gated by DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES, bounded by
DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES / DOWNLOAD_REDOWNLOAD_MAX_SECONDS).

The contract: the verify loop counts ALL bad/missing files (no early break),
the pause-aware redownload pass ALWAYS runs when enabled — cap+1 bad files
must recover instead of failing the install with zero recovery attempts —
and budgets, not a count cliff, bound the pass; files beyond an exhausted
budget stay bad and surface through the existing
'Bad checksum for N files\\nMissing M files' ValueError that Central parses.
max_bad_files_to_redownload stays accepted for old generated batch scripts:
None/0 keep meaning "verify only", a positive value is a warn threshold (or
the legacy hard cap when the kill switch is off).

Reuses the hermetic FakeInfoMapTable + FakeCheckDownloadFolderChecksum +
temp-file helpers from test_downloadPromotion.
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from pyinstl.test.test_downloadPromotion import (  # noqa: E402
    FULL_STACK_IMPORT_ERROR,
    FakeInfoMapTable,
    sha1_bytes,
)

if FULL_STACK_IMPORT_ERROR is None:
    from configVar import config_vars
    from pyinstl.test.test_downloadPromotion import (
        FakeCheckDownloadFolderChecksum,
        FakeDownloadItem,
    )
    import pybatch.info_mapBatchCommands as imbc


class _FakeDler:
    """Stands in for the DownloadManager's callable: 'downloads' a file by
    writing its expected payload straight to the final path (matching the
    contract _redownload_one_file relies on: on return the download_path
    exists with the verified bytes). Records every call so tests can assert
    exactly which files got a recovery attempt."""

    def __init__(self, payload_by_download_path):
        self.payload_by_download_path = payload_by_download_path
        self.calls = []

    def __call__(self, path, url, checksum, temp_path):
        self.calls.append(os.fspath(path))
        final_path = Path(path)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(self.payload_by_download_path[os.fspath(path)])


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestRedownloadBudget(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config_vars["LOCAL_SYNC_DIR"] = self.temp_dir.name
        config_vars["LOCAL_REPO_BOOKKEEPING_DIR"] = os.path.join(self.temp_dir.name, "bookkeeping")
        config_vars["__INVOCATION_RANDOM_ID__"] = "test-session"
        config_vars["SYNC_BASE_URL_MAIN_ITEM"] = "V16"
        config_vars["REPO_REV"] = "123"
        config_vars["COOKIE_JAR"] = ""
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "no"
        config_vars["DOWNLOAD_RESUME_REQUIRE_CONDITIONAL"] = "yes"
        config_vars["DOWNLOAD_RESUME_VALIDATED_HOSTS"] = ""
        config_vars["DOWNLOAD_RESUME_VALIDATED_PATH_PREFIXES"] = ""
        config_vars["DOWNLOAD_RETRY_POLICY_ENABLED"] = "yes"
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "no"
        # Explicit defaults so cross-test config_vars leakage can't flip the
        # behavior under test: cliff removal on, both budgets unlimited.
        config_vars["DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES"] = "yes"
        config_vars["DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES"] = "0"
        config_vars["DOWNLOAD_REDOWNLOAD_MAX_SECONDS"] = "0"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_missing_items(self, count, payload_bytes=b"never-arrived-payload"):
        """Items whose final AND temp files are absent — the exact shape of the
        Windows offline smoke-test failure (no .part written at all)."""
        items = []
        payloads = {}
        for i in range(count):
            payload = payload_bytes + f"-{i}".encode()
            final_path = Path(self.temp_dir.name, "Products", f"Missing{i}.pkg")
            item = FakeDownloadItem(
                path=f"Products/Missing{i}.pkg",
                revision=123,
                checksum=sha1_bytes(payload),
                size=len(payload),
                download_path=os.fspath(final_path),
            )
            final_path.parent.mkdir(parents=True, exist_ok=True)
            items.append(item)
            payloads[item.download_path] = payload
        return items, payloads

    def _patch_download_manager(self, dler):
        fake_cm = mock.MagicMock()
        fake_cm.__enter__.return_value = dler
        fake_cm.__exit__.return_value = False
        return mock.patch.object(imbc, "DownloadManager", return_value=fake_cm)

    def _make_command(self, items, **kwargs):
        command = FakeCheckDownloadFolderChecksum(report_own_progress=False, **kwargs)
        command.info_map_table = FakeInfoMapTable(items)
        return command

    # --- the recovery cliff is gone ----------------------------------------

    def test_cap_plus_one_bad_files_now_recovers(self):
        # The regression scenario: more bad files than the cap (33 vs 32 in the
        # field, 3 vs 2 here). Previously the redownload pass was skipped
        # entirely and the install failed; now every file is recovered.
        items, payloads = self._make_missing_items(3)
        dler = _FakeDler(payloads)
        command = self._make_command(items, max_bad_files_to_redownload=2)
        with self._patch_download_manager(dler):
            command()  # must NOT raise: recovery ran and fixed everything

        self.assertEqual(len(dler.calls), 3)
        self.assertEqual(command.num_bad_files, 0)
        for item in items:
            self.assertEqual(Path(item.download_path).read_bytes(),
                             payloads[item.download_path])

    def test_verify_loop_counts_all_bad_files_past_threshold(self):
        # No early break: with 5 bad files and a threshold of 2, all 5 are
        # counted and queued for recovery (the old code stopped at 3).
        items, payloads = self._make_missing_items(5)
        dler = _FakeDler(payloads)
        command = self._make_command(items, max_bad_files_to_redownload=2)
        with self._patch_download_manager(dler):
            command()

        self.assertEqual(len(command.lists_of_files["to redownload"]), 5)
        self.assertEqual(len(command.lists_of_files["missing_files"]), 5)
        self.assertEqual(len(dler.calls), 5)

    # --- budgets bound the pass instead of a count cliff --------------------

    def test_bytes_budget_exhaustion_leaves_clear_error(self):
        # Budget covers exactly the first file: the remaining two are left
        # unrecovered and the existing error format (Central regexes on
        # /Bad checksum/i) reports them AFTER recovery had its chance.
        items, payloads = self._make_missing_items(3)
        config_vars["DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES"] = str(items[0].size)
        dler = _FakeDler(payloads)
        command = self._make_command(items, max_bad_files_to_redownload=2)
        with self._patch_download_manager(dler):
            with self.assertRaisesRegex(ValueError, r"Bad checksum for \d+ files\nMissing \d+ files"):
                command()

        self.assertEqual(len(dler.calls), 1)        # only within-budget file attempted
        self.assertEqual(command.num_bad_files, 2)  # the rest stay bad
        self.assertTrue(Path(items[0].download_path).is_file())
        self.assertFalse(Path(items[1].download_path).exists())
        self.assertFalse(Path(items[2].download_path).exists())

    def test_zero_budgets_mean_unlimited(self):
        budget = imbc._RedownloadBudget(max_total_bytes=0, max_seconds=0)
        budget.spend_bytes(10 ** 12)
        budget.started_at -= 10 ** 6
        self.assertIsNone(budget.exhausted_reason())

    def test_seconds_budget_excludes_pause_time(self):
        # An offline hold / user pause must never burn the recovery budget —
        # that would recreate the very failure the budget replaces.
        budget = imbc._RedownloadBudget(max_total_bytes=0, max_seconds=10)
        budget.started_at -= 15  # pretend 15s wall time elapsed
        self.assertIsNotNone(budget.exhausted_reason())
        self.assertIsNone(budget.exhausted_reason(paused_seconds=10))

    def test_pause_tracking_channel_measures_and_delegates(self):
        class _SleepyChannel:
            def __init__(self):
                self.wait_calls = 0

            def wait_if_paused(self, poll_seconds=0.5):
                self.wait_calls += 1
                time.sleep(0.02)

            def try_now_requested(self):
                return True

        inner = _SleepyChannel()
        wrapper = imbc._PauseTrackingChannel(inner)
        wrapper.wait_if_paused()
        self.assertEqual(inner.wait_calls, 1)
        self.assertGreater(wrapper.paused_seconds, 0.0)
        # non-wait calls pass through untouched
        self.assertTrue(wrapper.try_now_requested())

    # --- back-compat: the old param & the kill switch ------------------------

    def test_kill_switch_off_restores_legacy_count_cliff(self):
        # DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES=no must reproduce the old
        # (macOS-validated) behavior exactly: the verify loop breaks one past
        # the cap and the redownload pass never runs.
        config_vars["DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES"] = "no"
        items, payloads = self._make_missing_items(3)
        dler = _FakeDler(payloads)
        command = self._make_command(items, max_bad_files_to_redownload=1)
        with self._patch_download_manager(dler):
            with self.assertRaisesRegex(ValueError, r"Bad checksum"):
                command()

        self.assertEqual(command.num_bad_files, 2)  # counted up to cap+1, then broke
        self.assertEqual(len(dler.calls), 0)        # recovery skipped (the cliff)

    def test_param_none_keeps_verify_only_semantics(self):
        # Old scripts / the in-process check-checksum command construct the
        # class without max_bad_files_to_redownload: still verify-only.
        items, payloads = self._make_missing_items(2)
        dler = _FakeDler(payloads)
        command = self._make_command(items, raise_on_bad_checksum=False)
        with self._patch_download_manager(dler):
            command()

        self.assertEqual(len(dler.calls), 0)
        self.assertEqual(command.num_bad_files, 2)

    def test_param_zero_keeps_redownload_disabled(self):
        # Legacy 0 effectively meant "never redownload" (any bad count exceeds
        # 0); the reinterpretation preserves that.
        items, payloads = self._make_missing_items(1)
        dler = _FakeDler(payloads)
        command = self._make_command(items, max_bad_files_to_redownload=0)
        with self._patch_download_manager(dler):
            with self.assertRaisesRegex(ValueError, r"Bad checksum"):
                command()

        self.assertEqual(len(dler.calls), 0)

    def test_back_compat_param_repr_round_trips(self):
        # Old generated batch scripts pass max_bad_files_to_redownload; the
        # dual-identity contract must keep accepting and re-emitting it.
        from pybatch.info_mapBatchCommands import CheckDownloadFolderChecksum
        obj = CheckDownloadFolderChecksum(max_bad_files_to_redownload=32,
                                          own_progress_count=0, report_own_progress=False)
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, obj.explain_diff(obj_recreated))
        self.assertEqual(obj_recreated.max_bad_files_to_redownload, 32)


if __name__ == "__main__":
    unittest.main(verbosity=3)
