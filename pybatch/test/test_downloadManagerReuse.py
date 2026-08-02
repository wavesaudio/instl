#!/usr/bin/env python3.12

"""Tests DownloadManager's per-file overhead — the connection reuse its own class
comment has always promised.

The contract: the connection pool survives between calls (``with self.session``
would close it, since ``Session.__exit__`` calls ``close()``), the session is closed
once when the batch ends, and MakeDir is driven once per directory rather than once
per file — its "already exists, just fix permissions" branch spawns two child
processes on Windows, and a download calls it for both parents of every file.

Hermetic — a local HTTP server on a loopback port, counting accepted sockets.
"""

import hashlib
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))

FULL_STACK_IMPORT_ERROR = None
try:
    from configVar import config_vars
    from pybatch.downloadBatchCommands import DownloadManager
except ImportError as ex:
    FULL_STACK_IMPORT_ERROR = ex

PAYLOAD = b"waves" * 200
CHECKSUM = hashlib.sha1(PAYLOAD).hexdigest()


class _CountingServer(ThreadingHTTPServer):
    daemon_threads = True
    accepted = 0

    def get_request(self):
        request = super().get_request()
        type(self).accepted += 1
        return request


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, so reuse is observable

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, *args):
        pass


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestDownloadManagerReuse(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)

        _CountingServer.accepted = 0
        self.server = _CountingServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

        config_vars["COOKIE_JAR"] = ""
        config_vars["CURL_MAX_TIME"] = "60"

    def _download_many(self, count, dirs=1):
        with DownloadManager(cookie="", report_own_progress=False) as dler:
            for i in range(count):
                sub = self.root / f"d{i % dirs}"
                dler(path=str(sub / f"f{i:04}.bin"),
                     url=f"http://127.0.0.1:{self.port}/f{i:04}.bin",
                     checksum=CHECKSUM,
                     temp_path=str(sub / f"f{i:04}.bin.part"))
            return dler

    def test_one_connection_serves_many_files(self):
        """The regression: the pool must survive between calls."""
        self._download_many(25)

        self.assertEqual(25, len(list(self.root.rglob("*.bin"))))
        self.assertLess(_CountingServer.accepted, 5,
                        f"expected connection reuse, server accepted "
                        f"{_CountingServer.accepted} connections for 25 files")

    def test_makedir_runs_once_per_directory_not_once_per_file(self):
        dler = self._download_many(20, dirs=2)

        # both the final path's parent and the temp path's parent resolve to the
        # same two folders, so exactly two directories should ever be ensured
        self.assertEqual(2, len(dler._ensured_dirs),
                         f"MakeDir was driven for {len(dler._ensured_dirs)} distinct "
                         f"paths across 20 files in 2 directories")

    def test_each_new_directory_still_goes_through_makedir(self):
        """Memoizing must not skip a directory that has never been prepared."""
        dler = self._download_many(6, dirs=6)

        self.assertEqual(6, len(dler._ensured_dirs))
        for i in range(6):
            self.assertTrue((self.root / f"d{i}").is_dir())

    def test_session_is_closed_once_at_the_end_not_once_per_file(self):
        closes = []
        with DownloadManager(cookie="", report_own_progress=False) as dler:
            real_close = dler.session.close
            dler.session.close = lambda: (closes.append(1), real_close())[1]
            for i in range(3):
                dler(path=str(self.root / f"a{i}.bin"),
                     url=f"http://127.0.0.1:{self.port}/a{i}.bin",
                     checksum=CHECKSUM,
                     temp_path=str(self.root / f"a{i}.bin.part"))
            self.assertEqual([], closes, "session was closed mid-batch, killing the pool")

        self.assertEqual(1, len(closes), "session was not closed when the batch ended")


if __name__ == "__main__":
    unittest.main()
