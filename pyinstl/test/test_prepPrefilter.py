#!/usr/bin/env python3.12

"""Tests for the pre-download checksum-pass speedups in utils.misc_utils:

1) SIZE pre-filter in need_to_download_file: a size mismatch must short-circuit to
   "download required" WITHOUT hashing the file contents.
2) CHUNKED read in check_file_checksum / get_file_checksum: same SHA1 digest as a
   whole-file read, even for files larger than the 1 MB chunk.

These are hermetic: they only touch temp files created by the test.
"""

import hashlib
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))

import utils
from utils.misc_utils import (
    check_file_checksum,
    get_file_checksum,
    need_to_download_file,
)


def sha1_of(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(data)
    return h.hexdigest()


class TestSizePrefilter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="prep_prefilter_")

    def tearDown(self):
        for name in os.listdir(self.tmpdir):
            try:
                os.remove(os.path.join(self.tmpdir, name))
            except OSError:
                pass
        os.rmdir(self.tmpdir)

    def _write(self, name, data: bytes) -> str:
        p = os.path.join(self.tmpdir, name)
        with open(p, "wb") as wfd:
            wfd.write(data)
        return p

    def test_missing_file_needs_download(self):
        missing = os.path.join(self.tmpdir, "does_not_exist.bin")
        self.assertTrue(need_to_download_file(missing, sha1_of(b"whatever"), 7))
        # also missing with unknown size (no size arg) -> still download
        self.assertTrue(need_to_download_file(missing, sha1_of(b"whatever")))

    def test_size_mismatch_short_circuits_without_reading_contents(self):
        data = b"hello world contents"
        p = self._write("a.bin", data)
        on_disk_size = os.path.getsize(p)
        wrong_size = on_disk_size + 1

        # Sentinel: if the function reads/hashes the file, this is opened. We patch the
        # builtin open in misc_utils' namespace to detect any read of the file.
        import utils.misc_utils as mu
        opened = {"count": 0}
        real_open = mu.open if hasattr(mu, "open") else open

        def spy_open(*args, **kwargs):
            opened["count"] += 1
            return real_open(*args, **kwargs)

        mu.open = spy_open
        try:
            # checksum deliberately matches the file content, so the ONLY way to return
            # True is via the size short-circuit (not via checksum mismatch).
            result = need_to_download_file(p, sha1_of(data), wrong_size)
        finally:
            del mu.open
        self.assertTrue(result, "size mismatch must require download")
        self.assertEqual(opened["count"], 0, "file contents must NOT be read on size mismatch")

    def test_size_match_and_checksum_match_no_download(self):
        data = b"identical bytes here"
        p = self._write("b.bin", data)
        size = os.path.getsize(p)
        self.assertFalse(need_to_download_file(p, sha1_of(data), size))

    def test_size_match_but_checksum_mismatch_needs_download(self):
        data = b"x" * 100
        p = self._write("c.bin", data)
        size = os.path.getsize(p)
        # same size, wrong checksum -> falls through to checksum compare -> download
        self.assertTrue(need_to_download_file(p, sha1_of(b"y" * 100), size))

    def test_unknown_size_falls_through_to_checksum(self):
        data = b"some payload"
        p = self._write("d.bin", data)
        # size None -> no short-circuit, checksum matches -> no download
        self.assertFalse(need_to_download_file(p, sha1_of(data), None))
        # size -1 (unknown in info-map) -> no short-circuit, checksum matches -> no download
        self.assertFalse(need_to_download_file(p, sha1_of(data), -1))
        # size None, checksum mismatch -> download
        self.assertTrue(need_to_download_file(p, sha1_of(b"other"), None))


class TestChunkedChecksum(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="prep_chunked_")

    def tearDown(self):
        for name in os.listdir(self.tmpdir):
            try:
                os.remove(os.path.join(self.tmpdir, name))
            except OSError:
                pass
        os.rmdir(self.tmpdir)

    def _write(self, name, data: bytes) -> str:
        p = os.path.join(self.tmpdir, name)
        with open(p, "wb") as wfd:
            wfd.write(data)
        return p

    def test_get_file_checksum_multi_chunk_matches_whole_file_digest(self):
        # > 1 MB chunk size so the chunked loop runs multiple iterations
        data = (b"abcdefghij" * 300000)  # ~2.86 MB
        p = self._write("big.bin", data)
        expected = sha1_of(data)
        self.assertEqual(get_file_checksum(p), expected)

    def test_check_file_checksum_multi_chunk_matches(self):
        data = bytes(bytearray((i % 256) for i in range(0, 2_500_000)))  # ~2.5 MB
        p = self._write("big2.bin", data)
        expected = sha1_of(data)
        self.assertTrue(check_file_checksum(p, expected))
        self.assertFalse(check_file_checksum(p, sha1_of(data + b"!")))

    def test_get_file_checksum_empty_file(self):
        p = self._write("empty.bin", b"")
        self.assertEqual(get_file_checksum(p), sha1_of(b""))

    def test_check_file_checksum_none_args_returns_false(self):
        p = self._write("x.bin", b"data")
        self.assertFalse(check_file_checksum(p, None))
        self.assertFalse(check_file_checksum(None, sha1_of(b"data")))


if __name__ == "__main__":
    unittest.main()
