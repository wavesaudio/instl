#!/usr/bin/env python3.12

"""Tests for the parallelized post-download checksum-verify pass in
``CheckDownloadFolderChecksum`` (gated by DOWNLOAD_PARALLEL_VERIFY /
DOWNLOAD_PARALLEL_WORKERS).

The contract: parallel hashing must produce byte-for-byte identical
promotion / sidecar / bad-file outcomes to the serial path, the verify-
progress ticks must still fire, and the flag-off / single-worker path must
fall back to the original serial loop.

Reuses the hermetic FakeInfoMapTable + FakeCheckDownloadFolderChecksum +
temp-file helpers from test_downloadPromotion.
"""

import os
import sys
import tempfile
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
    from pyinstl.downloadState import (
        DownloadFileState,
        DownloadStateStore,
        file_id_for_download_item,
        temp_path_for_download_item,
    )
    import pyinstl.downloadVerify as downloadVerify


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestParallelVerify(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config_vars["LOCAL_SYNC_DIR"] = self.temp_dir.name
        config_vars["LOCAL_REPO_BOOKKEEPING_DIR"] = os.path.join(self.temp_dir.name, "bookkeeping")
        config_vars["__INVOCATION_RANDOM_ID__"] = "test-session"
        config_vars["SYNC_BASE_URL_MAIN_ITEM"] = "V16"
        config_vars["REPO_REV"] = "123"
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "yes"
        config_vars["DOWNLOAD_RESUME_REQUIRE_CONDITIONAL"] = "yes"
        config_vars["DOWNLOAD_RESUME_VALIDATED_HOSTS"] = ""
        config_vars["DOWNLOAD_RESUME_VALIDATED_PATH_PREFIXES"] = ""

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_item(self, relative_path: str, payload: bytes) -> "FakeDownloadItem":
        final_path = Path(self.temp_dir.name, relative_path)
        return FakeDownloadItem(
            path=relative_path,
            revision=123,
            checksum=sha1_bytes(payload),
            size=len(payload),
            download_path=os.fspath(final_path),
        )

    # --- scenario construction -------------------------------------------

    def _build_mixed_scenario(self):
        """A mix of: already-valid (final ok), valid-temp-to-promote,
        bad-checksum-temp, and missing-temp files."""
        items = []

        # 1) already valid: final exists and matches, no temp needed.
        valid_payload = b"already-valid-payload-0"
        valid_item = self.make_item("Products/AlreadyValid.pkg", valid_payload)
        fp = Path(valid_item.download_path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(valid_payload)
        items.append(valid_item)

        # 2) good temp to promote: final missing/stale, temp matches.
        promote_payload = b"good-temp-to-promote-1" * 4
        promote_item = self.make_item("Products/Promote.pkg", promote_payload)
        Path(promote_item.download_path).parent.mkdir(parents=True, exist_ok=True)
        tp = temp_path_for_download_item(promote_item)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_bytes(promote_payload)
        items.append(promote_item)

        # 3) bad temp: temp exists but wrong bytes.
        bad_item = self.make_item("Products/Bad.pkg", b"expected-bad-payload-2")
        Path(bad_item.download_path).parent.mkdir(parents=True, exist_ok=True)
        btp = temp_path_for_download_item(bad_item)
        btp.parent.mkdir(parents=True, exist_ok=True)
        btp.write_bytes(b"WRONG BYTES")
        items.append(bad_item)

        # 4) missing temp: neither final nor temp present.
        missing_item = self.make_item("Products/Missing.pkg", b"never-arrived-payload-3")
        Path(missing_item.download_path).parent.mkdir(parents=True, exist_ok=True)
        items.append(missing_item)

        return items

    def _snapshot_outcome(self, items):
        """Capture the observable post-verify state for comparison."""
        store = DownloadStateStore.from_bookkeeping_dir(
            config_vars["LOCAL_REPO_BOOKKEEPING_DIR"].Path())
        snap = {}
        for it in items:
            final_path = Path(it.download_path)
            temp_path = temp_path_for_download_item(it)
            sidecar = store.load_file(file_id_for_download_item(it))
            snap[it.path] = {
                "final_exists": final_path.is_file(),
                "final_bytes": final_path.read_bytes() if final_path.is_file() else None,
                "temp_exists": temp_path.is_file(),
                "sidecar_state": sidecar.transfer.state if sidecar else None,
            }
        return snap

    def _run_verify(self, items, *, parallel, workers=0):
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "yes" if parallel else "no"
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = str(workers)
        command = FakeCheckDownloadFolderChecksum(
            raise_on_bad_checksum=False, report_own_progress=False)
        command.info_map_table = FakeInfoMapTable(items)
        # max_bad_files_to_redownload stays None: with it None the re_download
        # pass is never triggered (so no real network) AND the early-stop break
        # never fires, so every file is processed by the verify loop.
        command()
        return command

    # --- tests ------------------------------------------------------------

    def test_parallel_matches_serial_for_mixed_files(self):
        # Run the serial path in one temp dir...
        serial_items = self._build_mixed_scenario()
        serial_cmd = self._run_verify(serial_items, parallel=False)
        serial_snap = self._snapshot_outcome(serial_items)
        serial_lists = {k: list(v) for k, v in serial_cmd.lists_of_files.items()}
        serial_bad = serial_cmd.num_bad_files

        # ...then reset the temp dir and run the parallel path on identical inputs.
        self.tearDown()
        self.setUp()
        parallel_items = self._build_mixed_scenario()
        parallel_cmd = self._run_verify(parallel_items, parallel=True, workers=4)
        parallel_snap = self._snapshot_outcome(parallel_items)
        parallel_lists = {k: list(v) for k, v in parallel_cmd.lists_of_files.items()}
        parallel_bad = parallel_cmd.num_bad_files

        self.assertEqual(parallel_snap, serial_snap)
        self.assertEqual(parallel_bad, serial_bad)
        self.assertEqual(parallel_bad, 2)  # bad temp + missing temp
        # bad_checksum / missing_files / to-redownload lists must match exactly,
        # including order (the main thread iterates dl_file_items in order).
        self.assertEqual(
            sorted(parallel_lists.keys()), sorted(serial_lists.keys()))
        # The bad_checksum / missing_files entries embed absolute temp paths
        # that differ between the two runs' temp dirs, so compare counts (the
        # ordering / membership is asserted precisely via the redownload list,
        # whose entries carry the stable relative item path).
        self.assertEqual(len(parallel_lists["bad_checksum"]),
                         len(serial_lists["bad_checksum"]))
        self.assertEqual(len(parallel_lists["missing_files"]),
                         len(serial_lists["missing_files"]))
        redl_serial = [i.path for i in serial_lists["to redownload"]]
        redl_parallel = [i.path for i in parallel_lists["to redownload"]]
        self.assertEqual(redl_parallel, redl_serial)
        self.assertEqual(redl_parallel, ["Products/Bad.pkg", "Products/Missing.pkg"])

    def test_parallel_promotes_and_marks_bad_files(self):
        items = self._build_mixed_scenario()
        self._run_verify(items, parallel=True, workers=4)
        snap = self._snapshot_outcome(items)

        # The verify loop intentionally writes NO resume sidecar for files that
        # verify successfully: resume bookkeeping is a download-phase concern and
        # resume_decision never reads the verify-time transfer_state, so the
        # per-file write was pure I/O with no consumer (it dominated the verify
        # pass). A cache-hit / promoted file therefore has no verify sidecar.
        self.assertIsNone(snap["Products/AlreadyValid.pkg"]["sidecar_state"])
        # Promoted file: final now exists with the temp bytes, temp gone.
        self.assertIsNone(snap["Products/Promote.pkg"]["sidecar_state"])
        self.assertTrue(snap["Products/Promote.pkg"]["final_exists"])
        self.assertFalse(snap["Products/Promote.pkg"]["temp_exists"])
        # Bad temp: not promoted, temp retained, marked retryable. The retry path
        # (not the verify loop) still writes a sidecar so a later session can act
        # on the failure — bad/missing files are rare, so this is not hot.
        self.assertFalse(snap["Products/Bad.pkg"]["final_exists"])
        self.assertTrue(snap["Products/Bad.pkg"]["temp_exists"])
        self.assertEqual(snap["Products/Bad.pkg"]["sidecar_state"],
                         DownloadFileState.FAILED_RETRYABLE)

    def test_parallel_emits_verify_progress_ticks(self):
        items = self._build_mixed_scenario()
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "yes"
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = "4"
        command = FakeCheckDownloadFolderChecksum(
            raise_on_bad_checksum=False, report_own_progress=False)
        command.info_map_table = FakeInfoMapTable(items)
        with mock.patch.object(downloadVerify, "_events_emit_session_state") as emit:
            command()
        verify_calls = [c.kwargs for c in emit.call_args_list
                        if c.kwargs.get("state") == "verifying_downloads"]
        self.assertTrue(verify_calls, "expected verifying_downloads ticks under parallel verify")
        planned = sum(i.size for i in items)
        # The forced final tick reaches full planned bytes.
        self.assertEqual(verify_calls[-1]["phase_bytes_planned"], planned)
        self.assertEqual(verify_calls[-1]["phase_bytes_done"], planned)

    def test_flag_off_uses_serial_path(self):
        # With the flag off, the pool is never constructed; map() is the
        # serial comprehension. Assert no ThreadPoolExecutor is created and the
        # outcome is still correct.
        items = self._build_mixed_scenario()
        with mock.patch.object(downloadVerify, "ThreadPoolExecutor") as pool_ctor:
            self._run_verify(items, parallel=False)
        pool_ctor.assert_not_called()
        snap = self._snapshot_outcome(items)
        # Promote happened (final exists, temp gone); verify writes no sidecar.
        self.assertTrue(snap["Products/Promote.pkg"]["final_exists"])
        self.assertFalse(snap["Products/Promote.pkg"]["temp_exists"])
        self.assertIsNone(snap["Products/Promote.pkg"]["sidecar_state"])

    def test_single_item_falls_back_to_serial(self):
        # A single download item must not spin up a worker pool even when the
        # flag is on (workers capped to num_items, then <=1 -> serial).
        payload = b"single-item-payload"
        item = self.make_item("Products/Single.pkg", payload)
        Path(item.download_path).parent.mkdir(parents=True, exist_ok=True)
        tp = temp_path_for_download_item(item)
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_bytes(payload)
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "yes"
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = "8"
        command = FakeCheckDownloadFolderChecksum(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        with mock.patch.object(downloadVerify, "ThreadPoolExecutor") as pool_ctor:
            command()
        pool_ctor.assert_not_called()
        self.assertEqual(Path(item.download_path).read_bytes(), payload)

    def test_pool_failure_falls_back_to_serial(self):
        # If the pool blows up, the serial fallback still completes the verify.
        items = self._build_mixed_scenario()
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "yes"
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = "4"
        command = FakeCheckDownloadFolderChecksum(
            raise_on_bad_checksum=False, report_own_progress=False)
        command.info_map_table = FakeInfoMapTable(items)
        with mock.patch.object(downloadVerify, "ThreadPoolExecutor",
                               side_effect=RuntimeError("no threads for you")):
            command()  # must not raise; falls back to serial
        snap = self._snapshot_outcome(items)
        # Promote happened via the serial fallback; verify writes no sidecar.
        self.assertTrue(snap["Products/Promote.pkg"]["final_exists"])
        self.assertFalse(snap["Products/Promote.pkg"]["temp_exists"])
        self.assertIsNone(snap["Products/Promote.pkg"]["sidecar_state"])
        self.assertEqual(command.num_bad_files, 2)

    def test_progress_log_throttled_but_counts_every_file(self):
        # The per-file progress LOG is throttled (it was the dominant cost of the
        # verify pass: a line per file across tens of thousands of files), but the
        # progress COUNTER must still advance exactly once per file so Central's
        # running total stays accurate.
        from pybatch.baseClasses import PythonBatchCommandBase
        cmd = FakeCheckDownloadFolderChecksum(report_own_progress=True)
        PythonBatchCommandBase.running_progress = 0
        PythonBatchCommandBase.total_progress = 100000
        PythonBatchCommandBase.ignore_progress = False
        n = 200
        with mock.patch.object(downloadVerify.log, "info") as log_info:
            for i in range(n):
                downloadVerify.verify_progress_log(cmd, f"check checksum for file {i}", 1, i, n)
        # Counter advanced exactly once per file.
        self.assertEqual(PythonBatchCommandBase.running_progress, n)
        # Logging was throttled to far fewer than one line per file (the loop runs
        # well within the 0.25s window, so essentially just the first + last).
        self.assertLess(log_info.call_count, n)
        self.assertGreaterEqual(log_info.call_count, 1)

    def test_resolve_workers_respects_flags(self):
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "no"
        self.assertEqual(downloadVerify.resolve_verify_workers(10), 1)
        config_vars["DOWNLOAD_PARALLEL_VERIFY"] = "yes"
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = "3"
        self.assertEqual(downloadVerify.resolve_verify_workers(10), 3)
        # capped to number of items
        self.assertEqual(downloadVerify.resolve_verify_workers(2), 2)
        # single item -> serial
        self.assertEqual(downloadVerify.resolve_verify_workers(1), 1)
        # auto (0) -> cpu_count, still >= 1
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = "0"
        self.assertGreaterEqual(downloadVerify.resolve_verify_workers(100), 1)


if __name__ == "__main__":
    unittest.main(verbosity=3)
