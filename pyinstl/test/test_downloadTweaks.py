#!/usr/bin/env python3.12

"""Curl throughput tweaks: HTTP/2 opt-in and largest-first external ordering.

Hermetic — no network, no real curl. We only inspect the generated curl
config text (the same surface ParallelRun later hands to curl).
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

FULL_STACK_IMPORT_ERROR = None
try:
    from configVar import config_vars
    from pyinstl.curlHelper import CUrlHelper
except ImportError as ex:
    FULL_STACK_IMPORT_ERROR = ex


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestCurlDownloadTweaks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        # Force the EXTERNAL parallel path (the production default) so we exercise
        # external_parallel_header_text and the descending url_sorter.
        config_vars["PARALLEL_DOWNLOAD_METHOD"] = "external"
        config_vars["CURL_CONFIG_FILE_NAME"] = "dl"
        config_vars["PARALLEL_SYNC"] = "1"
        config_vars["COOKIE_FOR_SYNC_URLS"] = "test=1"
        # Pin the curl HTTP/2 capability probe (hermetic - no real curl); the
        # flag tests below exercise the DOWNLOAD_CURL_HTTP2 gate on top of it.
        CUrlHelper.cached_http2_supported = True

    def tearDown(self):
        self.temp_dir.cleanup()
        CUrlHelper.cached_http2_supported = None  # un-pin the capability probe

    def _build_config_text(self, *url_size_pairs):
        helper = CUrlHelper()
        for url, size in url_size_pairs:
            final_path = Path(self.temp_dir.name, os.path.basename(url))
            helper.add_download_url(url, final_path, verbatim=True, size=size,
                                    output_path=Path(f"{final_path}.part"))
        config_files = helper.create_config_files(Path(self.temp_dir.name), 1)
        return "\n".join(cf.path.read_text(encoding="utf-8")
                         for cf in config_files if cf is not None)

    def test_http2_line_present_when_flag_on(self):
        config_vars["DOWNLOAD_CURL_HTTP2"] = "yes"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        # the http2 directive must appear on its own line in the curl config
        self.assertTrue(any(line.strip() == "http2" for line in text.splitlines()),
                        f"expected an http2 line; got:\n{text}")

    def test_http2_line_absent_when_flag_off(self):
        config_vars["DOWNLOAD_CURL_HTTP2"] = "no"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertNotIn("http2", text, f"http2 must be omitted when flag off; got:\n{text}")

    def test_http2_line_absent_when_curl_lacks_support(self):
        # The stock Windows System32 curl is built without HTTP/2; for such a
        # binary the `http2` option is a hard error (exit 2, zero files
        # downloaded), so the flag must be overridden by the capability probe.
        config_vars["DOWNLOAD_CURL_HTTP2"] = "yes"
        CUrlHelper.cached_http2_supported = False
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertNotIn("http2", text,
                         f"http2 must be omitted when curl does not support it; got:\n{text}")

    def test_http2_flag_off_still_produces_valid_config(self):
        # Turning the tweak off must not corrupt the rest of the config format:
        # the cookie line (which directly follows the http2 placeholder) must
        # still be present and well-formed.
        config_vars["DOWNLOAD_CURL_HTTP2"] = "no"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertIn("cookie = test=1", text)
        self.assertIn('url = "https://cdn.example.com/Foo.pkg"', text)

    def test_stall_detection_lines_present_by_default(self):
        # Workstream C: a silently stalled transfer must exit (28) instead of
        # hanging forever; speed-limit/speed-time are emitted by default.
        config_vars["DOWNLOAD_CURL_STALL_DETECTION"] = "yes"
        config_vars["DOWNLOAD_CURL_SPEED_LIMIT"] = "1"
        config_vars["DOWNLOAD_CURL_SPEED_TIME"] = "120"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertIn("speed-limit = 1", text)
        self.assertIn("speed-time = 120", text)

    def test_stall_detection_lines_absent_when_flag_off(self):
        # Kill switch: turning the flag off must restore the previous
        # (macOS-validated) config format exactly.
        config_vars["DOWNLOAD_CURL_STALL_DETECTION"] = "no"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertNotIn("speed-limit", text)
        self.assertNotIn("speed-time", text)
        # the rest of the retry block is unaffected
        self.assertIn("retry-connrefused", text)
        self.assertIn("retry-max-time", text)

    def test_stall_detection_values_come_from_config(self):
        config_vars["DOWNLOAD_CURL_STALL_DETECTION"] = "yes"
        config_vars["DOWNLOAD_CURL_SPEED_LIMIT"] = "512"
        config_vars["DOWNLOAD_CURL_SPEED_TIME"] = "60"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertIn("speed-limit = 512", text)
        self.assertIn("speed-time = 60", text)

    def test_stall_detection_bumps_retry_max_time_above_speed_time(self):
        # curl's --retry-max-time window starts at the transfer's first
        # attempt while a speed-limit abort fires only AFTER speed-time
        # seconds of stall — with retry-max-time (90) < speed-time (120) the
        # promised in-place retry of a stall abort could never happen. The
        # emitted retry-max-time must comfortably exceed speed-time (3x).
        config_vars["DOWNLOAD_CURL_STALL_DETECTION"] = "yes"
        config_vars["DOWNLOAD_CURL_SPEED_LIMIT"] = "1"
        config_vars["DOWNLOAD_CURL_SPEED_TIME"] = "120"
        config_vars["CURL_RETRY_MAX_TIME"] = "90"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertIn("retry-max-time = 360", text)
        self.assertNotIn("retry-max-time = 90", text)

    def test_stall_detection_keeps_larger_explicit_retry_max_time(self):
        # An explicitly configured retry window larger than 3x speed-time is
        # never lowered.
        config_vars["DOWNLOAD_CURL_STALL_DETECTION"] = "yes"
        config_vars["DOWNLOAD_CURL_SPEED_TIME"] = "60"
        config_vars["CURL_RETRY_MAX_TIME"] = "600"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertIn("retry-max-time = 600", text)

    def test_stall_detection_off_keeps_legacy_retry_max_time(self):
        # With the kill switch off the legacy (macOS-validated) retry window
        # is emitted untouched.
        config_vars["DOWNLOAD_CURL_STALL_DETECTION"] = "no"
        config_vars["CURL_RETRY_MAX_TIME"] = "90"
        text = self._build_config_text(("https://cdn.example.com/Foo.pkg", 10))
        self.assertIn("retry-max-time = 90", text)

    def test_external_ordering_is_largest_first(self):
        config_vars["DOWNLOAD_CURL_HTTP2"] = "no"
        # Intentionally add in non-sorted order; expect output ordered by
        # descending size (largest first / longest-processing-time first).
        text = self._build_config_text(
            ("https://cdn.example.com/small.pkg", 5),
            ("https://cdn.example.com/huge.wtar", 9000),
            ("https://cdn.example.com/medium.pkg", 300),
        )
        url_order = re.findall(r'url = "([^"]+)"', text)
        self.assertEqual(
            url_order,
            [
                "https://cdn.example.com/huge.wtar",
                "https://cdn.example.com/medium.pkg",
                "https://cdn.example.com/small.pkg",
            ],
            f"external path must emit largest-first; got {url_order}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=3)
