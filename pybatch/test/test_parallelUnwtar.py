#!/usr/bin/env python3.12

""" Tests for parallel UNWTAR (pybatch.wtarBatchCommands.Unwtar).

    These tests are hermetic: they build real wtar archives on disk with the
    Wtar command (so the archives carry valid pax_headers/total_checksum), then
    run Unwtar with DOWNLOAD_PARALLEL_UNWTAR on and off and assert the extracted
    output is identical, that a single archive still works (serial fallback),
    and that an extraction error propagates.

    All new tests for this feature live here; the shared test_wtarBatchCommands
    file is intentionally left untouched.
"""

import filecmp
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pytest

from pybatch import *
from pybatch.wtarBatchCommands import Unwtar, _unwtar_one_archive

current_os_names = utils.get_current_os_names()
config_vars["__CURRENT_OS_NAMES__"] = current_os_names


def _is_identical_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(os.fspath(a), os.fspath(b), ignore=['.DS_Store'])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    for sub in cmp.subdirs.values():
        if sub.left_only or sub.right_only or sub.diff_files or sub.funny_files:
            return False
    return True


class TestParallelUnwtar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="parallel_unwtar_"))
        # ensure a clean, predictable flag state for each test
        config_vars["DOWNLOAD_PARALLEL_UNWTAR"] = "yes"
        config_vars["DOWNLOAD_PARALLEL_WORKERS"] = "0"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers -------------------------------------------------------

    def _make_source_tree(self, root: Path, num_archives: int) -> Path:
        """ Build <root>/src with num_archives independent sibling subfolders,
            each holding a few files, then wtar each subfolder in place so the
            tree contains num_archives independent .wtar.aa first-parts whose
            destinations do not overlap.  Returns the src path. """
        src = root.joinpath("src")
        for i in range(num_archives):
            sub = src.joinpath(f"item_{i}")
            sub.mkdir(parents=True, exist_ok=True)
            for j in range(3):
                with open(sub.joinpath(f"file_{j}.txt"), "w") as wfd:
                    wfd.write(f"content of archive {i} file {j}\n" * (10 + i + j))
            with Wtar(sub, report_own_progress=False) as w:
                w()
            # remove the original folder so only the .wtar.aa remains to unwtar
            shutil.rmtree(sub)
        return src

    def _run_unwtar(self, src: Path, dest: Path, parallel: bool, no_artifacts=False, copy_owner=True):
        config_vars["DOWNLOAD_PARALLEL_UNWTAR"] = "yes" if parallel else "no"
        with Unwtar(src, dest, no_artifacts=no_artifacts, copy_owner=copy_owner, report_own_progress=False) as u:
            u()

    # ---- tests ---------------------------------------------------------

    def test_repr_roundtrip(self):
        """ dual-identity: eval(repr(obj)) == obj for Unwtar (unchanged args). """
        for obj in (Unwtar("/a/b/c"),
                    Unwtar("/a/b/c", None),
                    Unwtar("/a/b/c", "/dest", no_artifacts=True)):
            the_repr = repr(obj)
            evaled = eval(the_repr)
            self.assertEqual(obj, evaled, f"repr round-trip failed for {the_repr}")

    def test_parallel_matches_serial_multi_archive(self):
        """ Same input, flag on vs flag off, must produce identical output. """
        root = self.tmp.joinpath("multi")
        src = self._make_source_tree(root, num_archives=4)

        dest_serial = root.joinpath("out_serial")
        dest_parallel = root.joinpath("out_parallel")

        # Unwtar mutates what_to_unwtar in place; use a fresh command per run and
        # a fresh copy of the source so no_artifacts/state cannot leak between runs.
        src_serial = root.joinpath("src_serial")
        src_parallel = root.joinpath("src_parallel")
        shutil.copytree(src, src_serial)
        shutil.copytree(src, src_parallel)

        self._run_unwtar(src_serial, dest_serial, parallel=False)
        self._run_unwtar(src_parallel, dest_parallel, parallel=True)

        # Unwtar(dir) extracts into dest/<src_basename>/...
        out_serial = dest_serial.joinpath(src_serial.name)
        out_parallel = dest_parallel.joinpath(src_parallel.name)
        self.assertTrue(out_serial.is_dir(), f"serial output missing: {out_serial}")
        self.assertTrue(out_parallel.is_dir(), f"parallel output missing: {out_parallel}")
        self.assertTrue(_is_identical_tree(out_serial, out_parallel),
                        "parallel and serial extracted trees differ")
        # every archive's content extracted
        for i in range(4):
            self.assertTrue(out_parallel.joinpath(f"item_{i}", "file_0.txt").is_file(),
                            f"missing extracted file for archive {i}")

    def test_single_archive_serial_fallback(self):
        """ A single archive must take the serial fallback and still extract. """
        root = self.tmp.joinpath("single")
        src = self._make_source_tree(root, num_archives=1)
        dest = root.joinpath("out")
        # flag on, but only one archive -> serial fallback path
        self._run_unwtar(src, dest, parallel=True)
        out = dest.joinpath(src.name)
        self.assertTrue(out.joinpath("item_0", "file_0.txt").is_file(),
                        "single-archive (serial fallback) did not extract")

    def test_no_artifacts_removed_parallel(self):
        """ no_artifacts must remove the wtar files even on the parallel path. """
        root = self.tmp.joinpath("noartifacts")
        src = self._make_source_tree(root, num_archives=3)
        dest = root.joinpath("out")
        self._run_unwtar(src, dest, parallel=True, no_artifacts=True)
        leftover = list(src.rglob("*.wtar*"))
        self.assertEqual(leftover, [], f"no_artifacts left wtar files behind: {leftover}")
        out = dest.joinpath(src.name)
        for i in range(3):
            self.assertTrue(out.joinpath(f"item_{i}", "file_0.txt").is_file(),
                            f"missing extracted file for archive {i}")

    def test_extraction_error_propagates(self):
        """ A corrupt archive must make the command raise (failed extract fails
            the command), on the parallel path. """
        root = self.tmp.joinpath("err")
        src = self._make_source_tree(root, num_archives=3)
        # corrupt one of the first-parts so tarfile cannot read it
        first_parts = sorted(src.rglob("*.wtar.aa"))
        self.assertTrue(first_parts, "test setup produced no wtar first-parts")
        with open(first_parts[0], "wb") as wfd:
            wfd.write(b"this is not a valid bzip2 tar stream" * 50)
        dest = root.joinpath("out")
        with self.assertRaises(Exception):
            self._run_unwtar(src, dest, parallel=True)

    def test_worker_function_is_picklable_plain_data(self):
        """ The worker entry point accepts only plain picklable data and runs
            correctly when called directly (as a process pool would). """
        root = self.tmp.joinpath("worker")
        src = self._make_source_tree(root, num_archives=1)
        first_part = sorted(src.rglob("*.wtar.aa"))[0]
        dest = root.joinpath("dest")
        dest.mkdir(parents=True, exist_ok=True)
        done = _unwtar_one_archive(os.fspath(first_part), os.fspath(dest),
                                   False, (), False)
        self.assertTrue(all(isinstance(p, str) for p in done),
                        "worker must return plain string paths")
        self.assertTrue(dest.joinpath("item_0", "file_0.txt").is_file(),
                        "worker did not extract content")

    def test_partition_independent_isolates_overlap(self):
        """ Overlapping/nested destinations must NOT be partitioned as parallel;
            clearly-independent destinations must be. """
        a = self.tmp.joinpath("dst_a")
        nested = a.joinpath("inner")
        b = self.tmp.joinpath("dst_b")
        jobs = [
            (self.tmp.joinpath("x.wtar.aa"), a),
            (self.tmp.joinpath("y.wtar.aa"), nested),   # nested under a -> not parallel
            (self.tmp.joinpath("z.wtar.aa"), b),        # independent
        ]
        parallel_jobs, serial_jobs = Unwtar._partition_independent(jobs)
        parallel_dests = {os.fspath(d) for _, d in parallel_jobs}
        serial_dests = {os.fspath(d) for _, d in serial_jobs}
        self.assertIn(os.fspath(b), parallel_dests)
        self.assertIn(os.fspath(a), serial_dests)
        self.assertIn(os.fspath(nested), serial_dests)


if __name__ == "__main__":
    unittest.main()
