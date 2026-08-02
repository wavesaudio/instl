#!/usr/bin/env python3.12

"""Tests for the installation-lifecycle reporting: the phases that used to run
silently, and the state machine's missing entry and failure exit.

The contract: every phase that takes real time reports while it is working, not
after; a phase bar is never driven to full before the phase's work is over; and a
run reaches a terminal state whether it succeeds or fails.

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
    from pyinstl.test.test_redownloadBudget import _FakeDler
    from pyinstl.downloadState import DownloadSessionState
    import pybatch.info_mapBatchCommands as imbc
    import pybatch.reportingBatchCommands as rbc
    import pyinstl.downloadVerify as downloadVerify


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestVerifyHashingReportsWhileItWorks(unittest.TestCase):
    """The verify phase did every SHA-1 over every downloaded byte before its first
    report, so it announced itself and then went silent for minutes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config_vars["LOCAL_SYNC_DIR"] = self.temp_dir.name
        config_vars["LOCAL_REPO_BOOKKEEPING_DIR"] = os.path.join(self.temp_dir.name, "bookkeeping")
        config_vars["__INVOCATION_RANDOM_ID__"] = "test-session"
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "yes"
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = "4"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _items(self, count):
        items = []
        for i in range(count):
            payload = f"lifecycle-payload-{i}".encode()
            items.append(FakeDownloadItem(
                path=f"Products/Item{i}.pkg",
                revision=123,
                checksum=sha1_bytes(payload),
                size=len(payload),
                download_path=os.fspath(Path(self.temp_dir.name, "Products", f"Item{i}.pkg")),
            ))
        return items

    def test_results_keep_input_order_when_hashes_finish_out_of_order(self):
        # the bookkeeping loop indexes precomputed[file_index], so as_completed
        # ordering must not reach it
        items = self._items(6)
        slowest = items[0]

        def fake_hash(file_item):
            if file_item is slowest:
                time.sleep(0.15)  # guarantees it completes last
            return (file_item.path, False, None)

        with mock.patch.object(downloadVerify, "precompute_verify_hashes", side_effect=fake_hash):
            results = downloadVerify.precompute_all_verify_hashes(items)

        self.assertEqual([r[0] for r in results], [i.path for i in items])

    def test_every_item_is_reported_exactly_once(self):
        items = self._items(6)
        reported = []
        with mock.patch.object(downloadVerify, "precompute_verify_hashes",
                               side_effect=lambda fi: (fi.path, False, None)):
            downloadVerify.precompute_all_verify_hashes(items, on_item_hashed=reported.append)
        self.assertEqual(sorted(i.path for i in reported), sorted(i.path for i in items))

    def test_first_report_does_not_wait_for_the_slowest_hash(self):
        items = self._items(6)
        slowest = items[-1]

        def fake_hash(file_item):
            if file_item is slowest:
                time.sleep(0.3)
            return (file_item.path, False, None)

        report_times = []
        started = time.monotonic()
        with mock.patch.object(downloadVerify, "precompute_verify_hashes", side_effect=fake_hash):
            downloadVerify.precompute_all_verify_hashes(
                items, on_item_hashed=lambda fi: report_times.append(time.monotonic() - started))

        self.assertTrue(report_times)
        self.assertLess(report_times[0], 0.3,
                        "the phase reported nothing until the whole pass had finished")

    def test_serial_path_reports_too(self):
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "no"
        items = self._items(3)
        reported = []
        with mock.patch.object(downloadVerify, "precompute_verify_hashes",
                               side_effect=lambda fi: (fi.path, False, None)):
            results = downloadVerify.precompute_all_verify_hashes(items, on_item_hashed=reported.append)
        self.assertEqual([r[0] for r in results], [i.path for i in items])
        self.assertEqual([i.path for i in reported], [i.path for i in items])


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestRecoveryPassIsItsOwnPhase(unittest.TestCase):
    """The redownload pass ran after the verify bar had been forced to full, so
    Central showed verifying_downloads at 100% for a pass that is unbounded by
    default."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config_vars["LOCAL_SYNC_DIR"] = self.temp_dir.name
        config_vars["LOCAL_REPO_BOOKKEEPING_DIR"] = os.path.join(self.temp_dir.name, "bookkeeping")
        config_vars["__INVOCATION_RANDOM_ID__"] = "test-session"
        config_vars["COOKIE_JAR"] = ""
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "no"
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "no"
        config_vars["DOWNLOAD_RETRY_POLICY_ENABLED"] = "yes"
        config_vars["DOWNLOAD_REDOWNLOAD_ALL_BAD_FILES"] = "yes"
        config_vars["DOWNLOAD_REDOWNLOAD_MAX_TOTAL_BYTES"] = "0"
        config_vars["DOWNLOAD_REDOWNLOAD_MAX_SECONDS"] = "0"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _missing_items(self, count):
        items, payloads = [], {}
        for i in range(count):
            payload = f"never-arrived-{i}".encode()
            final_path = Path(self.temp_dir.name, "Products", f"Missing{i}.pkg")
            final_path.parent.mkdir(parents=True, exist_ok=True)
            item = FakeDownloadItem(
                path=f"Products/Missing{i}.pkg",
                revision=123,
                checksum=sha1_bytes(payload),
                size=len(payload),
                download_path=os.fspath(final_path),
            )
            items.append(item)
            payloads[item.download_path] = payload
        return items, payloads

    def _run_with_recovery(self, items, payloads):
        dler = _FakeDler(payloads)
        fake_cm = mock.MagicMock()
        fake_cm.__enter__.return_value = dler
        fake_cm.__exit__.return_value = False
        command = FakeCheckDownloadFolderChecksum(
            report_own_progress=False, raise_on_bad_checksum=False,
            max_bad_files_to_redownload=16)
        command.info_map_table = FakeInfoMapTable(items)
        with mock.patch.object(imbc, "DownloadManager", return_value=fake_cm):
            with mock.patch.object(downloadVerify, "_events_emit_session_state") as emit:
                command()
        return [c.kwargs for c in emit.call_args_list]

    def test_recovery_reports_a_retrying_phase_of_its_own(self):
        items, payloads = self._missing_items(3)
        calls = self._run_with_recovery(items, payloads)

        retrying = [c for c in calls if c.get("state") == "retrying"]
        self.assertTrue(retrying, "the redownload pass reported no phase of its own")
        self.assertEqual(retrying[0]["phase_bytes_planned"], sum(i.size for i in items))
        self.assertEqual(retrying[0]["phase_bytes_done"], 0)

    def test_verify_bar_reaches_full_only_after_recovery(self):
        items, payloads = self._missing_items(3)
        calls = self._run_with_recovery(items, payloads)

        states = [c.get("state") for c in calls]
        planned = sum(i.size for i in items)
        self.assertEqual(states[-1], "verifying_downloads")
        self.assertEqual(calls[-1]["phase_bytes_done"], planned)
        self.assertEqual(calls[-1]["phase_bytes_planned"], planned)
        # nothing claimed the verify phase was complete while recovery was still running
        full_verify_before_retry = [
            i for i, c in enumerate(calls)
            if c.get("state") == "verifying_downloads" and c.get("phase_bytes_done") == planned
        ]
        self.assertEqual(full_verify_before_retry, [len(calls) - 1])


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestStateMachineHasEntryAndExit(unittest.TestCase):
    def test_failed_is_emitted_for_a_failing_run(self):
        with mock.patch("pyinstl.downloadEvents.emit_download_state") as emit:
            rbc.PythonBatchRuntime.emit_failed_session_state(ValueError)
        emit.assert_called_once_with("failed", reason="ValueError")

    def test_failed_emit_never_breaks_the_error_path(self):
        with mock.patch("pyinstl.downloadEvents.emit_download_state",
                        side_effect=RuntimeError("no events")):
            rbc.PythonBatchRuntime.emit_failed_session_state(ValueError)  # must not raise

    def test_no_state_is_declared_without_an_emitter(self):
        # every declared state now has a site that emits it; a declared-but-dead
        # member is what made the machine impossible to audit
        self.assertNotIn("cancelled", [state.value for state in DownloadSessionState])


if __name__ == "__main__":
    unittest.main(verbosity=3)
