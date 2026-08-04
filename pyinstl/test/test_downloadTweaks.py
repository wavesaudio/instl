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
        # A silently stalled transfer must exit (28) instead of
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


class TestCurlParallelMeterRegex(unittest.TestCase):
    """The `curl --parallel` progress-meter parser in CurlTransfer._run_curl_once.

    Lines below are captured verbatim from real runs: curl 8.7.1 (macOS) and
    curl 8.21.0 (the system curl Waves Central invokes on Windows). Up to 8.19 an
    unknown time column printed "--:--:--"; 8.20+ leaves it blank, which used to
    make every Windows meter line fail to parse.
    """

    # curl 8.7.1 -- placeholder time columns
    METER_LINES_8_7 = [
        ("--  --      0     0     6     6  --:--:-- --:--:-- --:--:--     0      ", "0", "6", "6", "0"),
        ("--  --  26847     0     6     6  --:--:--  0:00:01 --:--:-- 23447      ", "26847", "6", "6", "23447"),
        ("--  --   403k     0     6     6  --:--:--  0:00:01 --:--:--  244k      ", "403k", "6", "6", "244k"),
        ("100 --   600k     0     6     0   0:00:01  0:00:01 --:--:--  333k      ", "600k", "6", "0", "333k"),
    ]

    # curl 8.21.0 -- blank time columns
    METER_LINES_8_21 = [
        ("--  --      0     0     6     1                                 0      ", "0", "6", "1", "0"),
        ("--  --   100k     0     6     5           00:00:01          52111      ", "100k", "6", "5", "52111"),
        ("--  --   482k     0     6     2           00:00:03           156k      ", "482k", "6", "2", "156k"),
        (" 90 --   540k     0     6     1  00:00:04 00:00:03           146k      ", "540k", "6", "1", "146k"),
        ("100 --   600k     0     6     0  00:00:03 00:00:03           150k     ", "600k", "6", "0", "150k"),
    ]

    @staticmethod
    def _meter_regex():
        """The regex as it appears in CurlTransfer._run_curl_once."""
        return re.compile(r"""^\s*
           (?P<DL_percent>[\d.-]+)\s+
           (?P<UL_percent>[\d.-]+)\s+
           (?P<Dled>[\d.a-z]+)\s+
           (?P<Uled>[\d.a-z]+)\s+
           (?P<Xfers>[\d]+)\s+
           (?P<Live>[\d]+)\s+
           (?P<Queue>[\d]+)?\s*?
           (?P<Total>[\d:-]+)?\s+
           (?P<Current>[\d:-]+)?\s+
           (?P<Left>[\d:-]+)?\s+
           (?P<Speed>[\d.a-z]+)
           (?P<the_rest>.*)?$""", re.IGNORECASE | re.VERBOSE)

    def _assert_parses(self, lines, label):
        reg = self._meter_regex()
        for line, dled, xfers, live, speed in lines:
            with self.subTest(curl=label, line=line.strip()):
                match = reg.match(line)
                self.assertIsNotNone(match, f"{label} meter line did not parse: {line!r}")
                self.assertEqual(match.group("Dled"), dled)
                self.assertEqual(match.group("Xfers"), xfers)
                self.assertEqual(match.group("Live"), live)
                self.assertEqual(match.group("Speed"), speed)

    def test_parses_curl_8_7_placeholder_time_columns(self):
        self._assert_parses(self.METER_LINES_8_7, "curl 8.7.1")

    def test_parses_curl_8_21_blank_time_columns(self):
        # This is the regression: requiring Total/Current/Left matched none of these.
        self._assert_parses(self.METER_LINES_8_21, "curl 8.21.0")

    def test_source_regex_keeps_the_time_columns_optional(self):
        # Guard the actual source, not just the copy above, so tightening the
        # regex back up fails here instead of silently in the field.
        source = Path(__file__).parent.parent.joinpath("downloadTransfer.py").read_text(encoding="utf-8")
        for group in ("Total", "Current", "Left"):
            self.assertIn(f"(?P<{group}>[\\d:-]+)?", source,
                          f"{group} must stay optional: curl 8.20+ leaves it blank")

    def test_ignores_non_meter_output(self):
        reg = self._meter_regex()
        for line in ("DL% UL%  Dled  Uled  Xfers  Live Total     Current  Left    Speed",
                     "curl: (28) Operation timed out",
                     ""):
            self.assertIsNone(reg.match(line), f"should not parse as a meter line: {line!r}")


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestMeterFilesHoldFreeze(unittest.TestCase):
    """CurlTransfer._note_meter_files: the files-done high-water freezes while the
    offline hold is active. With the network down curl burns the queue with instant
    connection failures and counts them in Xfers, so an unfrozen count climbs
    through the outage with zero bytes moving — and that count drives Central's
    progress bar."""

    def _make_transfer(self, total_files=100):
        from pyinstl.downloadTransfer import CurlTransfer
        return CurlTransfer(curl_path="curl", config_file_path="dl-00",
                            total_files_to_download=total_files,
                            previously_downloaded_files=0,
                            total_bytes_to_download=1000)

    def test_climbs_while_online(self):
        transfer = self._make_transfer()
        self.assertEqual(transfer._note_meter_files(10), 10)
        self.assertEqual(transfer._note_meter_files(25), 25)
        # monotonic: a lower sample (curl re-run restarting Xfers) never regresses
        self.assertEqual(transfer._note_meter_files(5), 25)

    def test_frozen_during_offline_hold(self):
        transfer = self._make_transfer()
        transfer._note_meter_files(10)
        transfer._offline_hold_active = True
        # the queue burns with failures during the outage; the reported count holds
        self.assertEqual(transfer._note_meter_files(40), 10)
        self.assertEqual(transfer._note_meter_files(90), 10)

    def test_catches_up_after_hold_release(self):
        transfer = self._make_transfer()
        transfer._note_meter_files(10)
        transfer._offline_hold_active = True
        transfer._note_meter_files(60)
        transfer._offline_hold_active = False
        # next sample folds curl's cumulative meter back in
        self.assertEqual(transfer._note_meter_files(65), 65)

    def test_clamped_to_total(self):
        transfer = self._make_transfer(total_files=50)
        self.assertEqual(transfer._note_meter_files(80), 50)


if __name__ == "__main__":
    unittest.main(verbosity=3)
