#!/usr/bin/env python3.12

"""Tests that a bulk download chunk which dies mid-transfer is never reported as
complete.

The contract: reconciliation runs after every curl exit code, not only 0 — a
non-zero exit means more outputs are missing, not fewer; a non-network exit is
logged instead of returned silently; a config that parses to no entries warns
instead of passing; and a chunk's progress base is what the earlier chunks put on
disk, not the planned url count curlHelper serialized for them.

The trigger this defends against: Central auto-pauses on a navigator offline edge
and resumes under a second later, the pause check fires in between and SIGTERMs
curl, and the re-run exits 23 with the chunk's tail unfetched.

Hermetic — a stub stands in for curl, so no network and no real transfers.
"""

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

FULL_STACK_IMPORT_ERROR = None
try:
    from configVar import config_vars
    import pyinstl.downloadTransfer as downloadTransfer
    from pyinstl.downloadTransfer import CurlTransfer
except ImportError as ex:
    FULL_STACK_IMPORT_ERROR = ex


CONFIG_HEADER = "parallel\nprogress-bar\nfail\ncreate-dirs\nparallel-max = 50\n\n\n"


class _StubCurl:
    """Stands in for one `curl --config` pass: creates the first ``writes`` outputs
    named in the config, then reports ``exit_code``. Models the documented
    --parallel behaviour of dropping transfers while still exiting."""

    def __init__(self, exit_codes, writes_per_pass):
        self.exit_codes = list(exit_codes)
        self.writes_per_pass = list(writes_per_pass)
        self.passes = 0
        self.configs_seen = []

    def __call__(self, config_path_fixed, pause_check):
        idx = min(self.passes, len(self.exit_codes) - 1)
        writes = self.writes_per_pass[min(self.passes, len(self.writes_per_pass) - 1)]
        self.passes += 1
        self.configs_seen.append(config_path_fixed)
        outputs = []
        with open(config_path_fixed, "r", encoding="utf-8") as fd:
            for line in fd:
                s = line.strip()
                if s.startswith("output"):
                    outputs.append(s.partition("=")[2].strip().strip('"'))
        for path in outputs[:writes]:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"data")
        return self.exit_codes[idx], False


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestChunkAbandonment(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.out = self.root / "out"
        self.out.mkdir()
        config_vars["DOWNLOAD_RECONCILE_MISSING_OUTPUTS"] = "yes"
        config_vars["DOWNLOAD_RECONCILE_MAX_ROUNDS"] = "3"
        config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "no"
        config_vars["DOWNLOAD_OFFLINE_HOLD_ENABLED"] = "no"
        CurlTransfer.files_delivered_so_far = None
        CurlTransfer.bytes_delivered_so_far = None
        self.addCleanup(setattr, CurlTransfer, "files_delivered_so_far", None)
        self.addCleanup(setattr, CurlTransfer, "bytes_delivered_so_far", None)
        self.addCleanup(self.temp_dir.cleanup)

    def _write_config(self, name, count, start=0):
        path = self.root / name
        with open(path, "w", encoding="utf-8") as fd:
            fd.write(CONFIG_HEADER)
            for i in range(start, start + count):
                fd.write("no-fail\ncontinue-at = -\n")
                fd.write(f'url = "https://example.invalid/f{i:05}"\n')
                fd.write(f'output = "{(self.out / f"f{i:05}.part").as_posix()}"\n\n')
        return path

    def _transfer(self, config_path, stub, total_files=100, previously=0):
        transfer = CurlTransfer(
            curl_path="curl-not-run",
            config_file_path=config_path,
            total_files_to_download=total_files,
            previously_downloaded_files=previously,
            total_bytes_to_download=total_files * 4,
            label="test/chunk",
        )
        transfer._run_curl_once = stub
        return transfer

    def _outputs_on_disk(self):
        return len(list(self.out.glob("*.part")))

    # -- reconciliation must not be gated on a zero exit --------------------

    def test_non_zero_curl_exit_still_reconciles_missing_outputs(self):
        """A non-network non-zero exit used to skip reconciliation entirely, which
        is exactly when the most outputs are missing."""
        config = self._write_config("dl-00", 40)
        stub = _StubCurl(exit_codes=[23, 0, 0, 0], writes_per_pass=[10, 40, 40, 40])
        transfer = self._transfer(config, stub, total_files=40)

        transfer.run()

        self.assertGreater(stub.passes, 1,
                           "reconciliation never re-ran curl after the non-zero exit")
        self.assertEqual(40, self._outputs_on_disk(),
                         "reconciliation did not recover the abandoned chunk")

    def test_reconciliation_clears_the_exit_code_once_outputs_are_complete(self):
        config = self._write_config("dl-00", 20)
        stub = _StubCurl(exit_codes=[23, 0], writes_per_pass=[5, 20])
        transfer = self._transfer(config, stub, total_files=20)

        self.assertEqual(0, transfer.run(),
                         "a fully recovered chunk should not keep curl's failure code")

    def test_zero_exit_with_dropped_transfers_still_reconciles(self):
        """The behaviour that already worked, pinned so the fix does not lose it."""
        config = self._write_config("dl-00", 30)
        stub = _StubCurl(exit_codes=[0, 0], writes_per_pass=[8, 30])
        transfer = self._transfer(config, stub, total_files=30)

        transfer.run()

        self.assertEqual(30, self._outputs_on_disk())

    def test_still_missing_after_all_rounds_keeps_the_failure_code(self):
        config = self._write_config("dl-00", 50)
        stub = _StubCurl(exit_codes=[23, 23, 23, 23], writes_per_pass=[5, 5, 5, 5])
        transfer = self._transfer(config, stub, total_files=50)

        self.assertNotEqual(0, transfer.run(),
                            "a chunk with outputs still missing must not report success")

    # -- a non-network failure must leave a trace ---------------------------

    def test_non_network_curl_exit_is_logged(self):
        """A chunk must not lose its remaining transfers without saying so."""
        config = self._write_config("dl-00", 10)
        stub = _StubCurl(exit_codes=[23], writes_per_pass=[10])
        transfer = self._transfer(config, stub, total_files=10)

        with self.assertLogs(downloadTransfer.log, level=logging.WARNING) as captured:
            transfer.run()

        self.assertTrue(any("curl exited 23" in line for line in captured.output),
                        f"non-network exit was not logged: {captured.output}")

    def test_unparsable_config_warns_instead_of_silently_passing(self):
        empty = self.root / "dl-empty"
        empty.write_text(CONFIG_HEADER, encoding="utf-8")
        stub = _StubCurl(exit_codes=[0], writes_per_pass=[0])
        transfer = self._transfer(empty, stub, total_files=10)

        with self.assertLogs(downloadTransfer.log, level=logging.WARNING) as captured:
            transfer.run()

        self.assertTrue(any("no download entries parsed" in line for line in captured.output),
                        f"a config that yields no entries must say so: {captured.output}")

    # -- the progress base must be measured, not planned --------------------

    def test_next_chunk_base_is_what_the_previous_chunk_delivered(self):
        """curlHelper seeds each chunk with the cumulative PLANNED url count of the
        chunks before it, which is a fiction once a chunk dies early."""
        config_00 = self._write_config("dl-00", 90)
        # dies having delivered 20 of its 90, and reconciliation cannot help
        stub_00 = _StubCurl(exit_codes=[23, 23, 23, 23], writes_per_pass=[20, 0, 0, 0])
        self._transfer(config_00, stub_00, total_files=100, previously=0).run()

        delivered = self._outputs_on_disk()
        self.assertEqual(20, delivered)

        config_01 = self._write_config("dl-01", 10, start=90)
        stub_01 = _StubCurl(exit_codes=[0], writes_per_pass=[10])
        # curlHelper would hand this chunk previously_downloaded_files=90
        transfer_01 = self._transfer(config_01, stub_01, total_files=100, previously=90)
        transfer_01.run()

        self.assertEqual(20, transfer_01.previously_downloaded_files,
                         "the second chunk kept the dead chunk's planned count as its base")
        self.assertEqual(30, self._outputs_on_disk())

    def test_base_falls_back_to_the_planned_count_when_nothing_measurable(self):
        """No measurement available must mean 'keep the old behaviour', never
        'report zero'."""
        CurlTransfer.files_delivered_so_far = None
        unreadable = self.root / "dl-unreadable"
        unreadable.write_text(CONFIG_HEADER, encoding="utf-8")
        stub = _StubCurl(exit_codes=[0], writes_per_pass=[0])
        transfer = self._transfer(unreadable, stub, total_files=100, previously=77)
        transfer.run()

        self.assertEqual(77, transfer.previously_downloaded_files)
        self.assertIsNone(CurlTransfer.files_delivered_so_far,
                          "an unmeasurable chunk must not publish a running total")

    # -- bytes must not restart at every chunk boundary ---------------------

    def test_byte_progress_carries_across_chunks(self):
        """Both channels report against the GLOBAL planned bytes, so a per-chunk byte
        count made the bar collapse to ~0% at every boundary - including the
        download_last chunk that ends every install."""
        config_00 = self._write_config("dl-00", 20)
        self._transfer(config_00, _StubCurl([0], [20]), total_files=30).run()
        first_chunk_bytes = CurlTransfer.bytes_delivered_so_far
        self.assertEqual(20 * len(b"data"), first_chunk_bytes)

        config_01 = self._write_config("dl-01", 10, start=20)
        transfer_01 = self._transfer(config_01, _StubCurl([0], [10]), total_files=30)
        self.assertEqual(first_chunk_bytes, CurlTransfer.bytes_delivered_so_far)
        transfer_01.run()

        self.assertEqual(first_chunk_bytes, transfer_01.previously_downloaded_bytes)
        self.assertEqual(30 * len(b"data"), CurlTransfer.bytes_delivered_so_far)
        self.assertEqual(30 * len(b"data"), transfer_01._sum_downloaded_part_bytes()[0])

    def test_unmeasurable_chunk_does_not_publish_zero_bytes(self):
        CurlTransfer.bytes_delivered_so_far = 4096
        unreadable = self.root / "dl-unreadable"
        unreadable.write_text(CONFIG_HEADER, encoding="utf-8")
        self._transfer(unreadable, _StubCurl([0], [0]), total_files=100).run()
        self.assertEqual(4096, CurlTransfer.bytes_delivered_so_far)

    def test_files_actually_downloaded_counts_outputs_on_disk(self):
        config = self._write_config("dl-00", 12)
        transfer = self._transfer(config, _StubCurl([0], [0]), total_files=12)
        self.assertEqual(0, transfer.files_actually_downloaded())

        for i in range(5):
            (self.out / f"f{i:05}.part").write_bytes(b"data")
        transfer._part_output_paths_cache = None
        self.assertEqual(5, transfer.files_actually_downloaded())


if __name__ == "__main__":
    unittest.main()
