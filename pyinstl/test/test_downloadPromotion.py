#!/usr/bin/env python3.12

import hashlib
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

FULL_STACK_IMPORT_ERROR = None
try:
    from configVar import config_vars
    from pyinstl.curlHelper import CUrlHelper
    from downloadState import (
        DownloadFileState,
        DownloadStateStore,
        file_id_for_download_item,
        save_resume_sidecar_for_download_item,
        temp_path_for_download_item,
    )
    from pybatch.info_mapBatchCommands import CheckDownloadFolderChecksum, PrepareDownloadTempFiles
    from pybatch.reportingBatchCommands import AnonymousAccum
    from pybatch.subprocessBatchCommands import ParallelRun
except ImportError as ex:
    FULL_STACK_IMPORT_ERROR = ex


@dataclass
class FakeDownloadItem:
    path: str
    revision: int
    checksum: str
    size: int
    download_path: str


class FakeInfoMapTable:
    def __init__(self, download_items):
        self.download_items = download_items

    def get_download_items(self, what="file"):
        self.last_what = what
        return self.download_items

    def get_sync_url_for_file_item(self, file_item):
        return f"https://cdn.example.com/{file_item.path}"


class _RecordingControlChannel:
    """Minimal control channel stub for retry-loop tests.

    Never pauses (``wait_if_paused`` is a no-op) and its backoff sleep
    returns instantly so tests don't incur real wall-clock waits. Records
    the requested sleep durations so tests can assert backoff happened.
    """
    def __init__(self, woke=False):
        self.wait_if_paused_calls = 0
        self.sleep_calls = []
        self._woke = woke

    def wait_if_paused(self, poll_seconds=0.5):
        self.wait_if_paused_calls += 1

    def sleep_or_wake(self, seconds):
        self.sleep_calls.append(seconds)
        return self._woke

    def try_now_requested(self):
        return False


if FULL_STACK_IMPORT_ERROR is None:
    class FakeCheckDownloadFolderChecksum(CheckDownloadFolderChecksum):
        info_map_table = None


    class FakePrepareDownloadTempFiles(PrepareDownloadTempFiles):
        info_map_table = None


def sha1_bytes(in_bytes: bytes) -> str:
    return hashlib.sha1(in_bytes).hexdigest()


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None, f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestDownloadPromotion(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        config_vars["LOCAL_SYNC_DIR"] = self.temp_dir.name
        config_vars["LOCAL_REPO_BOOKKEEPING_DIR"] = os.path.join(self.temp_dir.name, "bookkeeping")
        config_vars["__INVOCATION_RANDOM_ID__"] = "test-session"
        config_vars["SYNC_BASE_URL_MAIN_ITEM"] = "V16"
        config_vars["REPO_REV"] = "123"
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "no"
        config_vars["DOWNLOAD_RESUME_REQUIRE_CONDITIONAL"] = "yes"
        config_vars["DOWNLOAD_RESUME_VALIDATED_HOSTS"] = ""
        config_vars["DOWNLOAD_RESUME_VALIDATED_PATH_PREFIXES"] = ""

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_item(self, relative_path: str, payload: bytes) -> FakeDownloadItem:
        final_path = Path(self.temp_dir.name, relative_path)
        return FakeDownloadItem(
            path=relative_path,
            revision=123,
            checksum=sha1_bytes(payload),
            size=len(payload),
            download_path=os.fspath(final_path),
        )

    def test_curl_config_writes_temp_artifact_not_final_path(self):
        config_vars["PARALLEL_DOWNLOAD_METHOD"] = "external"
        config_vars["CURL_CONFIG_FILE_NAME"] = "dl"
        config_vars["PARALLEL_SYNC"] = "1"
        config_vars["COOKIE_FOR_SYNC_URLS"] = "test=1"

        final_path = Path(self.temp_dir.name, "Products", "Foo.pkg")
        temp_path = Path(f"{final_path}.instl-test.part")
        helper = CUrlHelper()
        helper.add_download_url(
            "https://cdn.example.com/Products/Foo.pkg",
            final_path,
            verbatim=True,
            size=10,
            output_path=temp_path,
        )

        config_files = helper.create_config_files(Path(self.temp_dir.name), 1)

        config_text = config_files[0].path.read_text(encoding="utf-8")
        self.assertIn(f'output = "{temp_path}"', config_text)
        self.assertNotIn(f'output = "{final_path}"', config_text)

    def test_curl_resume_config_requests_range_and_does_not_leak_to_next_url(self):
        curl_path = shutil.which("curl")
        if not curl_path:
            self.skipTest("curl executable unavailable")

        config_vars["PARALLEL_DOWNLOAD_METHOD"] = "external"
        config_vars["CURL_CONFIG_FILE_NAME"] = "dl"
        config_vars["PARALLEL_SYNC"] = "1"
        config_vars["COOKIE_FOR_SYNC_URLS"] = "test=1"

        payload = b"0123456789abcdef" * 256
        item = self.make_item("Products/Foo.pkg", payload)
        final_path = Path(item.download_path)
        temp_path = temp_path_for_download_item(item)
        resume_from_byte = 128
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(payload[:resume_from_byte])

        fresh_final_path = Path(self.temp_dir.name, "Products", "Bar.pkg")
        fresh_temp_path = Path(f"{fresh_final_path}.part")
        request_ranges = []
        request_if_match = []

        class RangeHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                request_ranges.append((self.path, self.headers.get("Range")))
                request_if_match.append((self.path, self.headers.get("If-Match")))
                if (
                    self.path == "/resume"
                    and self.headers.get("Range") == f"bytes={resume_from_byte}-"
                    and self.headers.get("If-Match") == '"etag-1"'
                ):
                    body = payload[resume_from_byte:]
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {resume_from_byte}-{len(payload)-1}/{len(payload)}")
                else:
                    body = payload
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            helper = CUrlHelper()
            helper.add_download_url(
                f"http://127.0.0.1:{server.server_port}/resume",
                final_path,
                verbatim=True,
                size=len(payload),
                output_path=temp_path,
                resume_from_byte=resume_from_byte,
                conditional_headers=('If-Match: "etag-1"',),
            )
            helper.add_download_url(
                f"http://127.0.0.1:{server.server_port}/fresh",
                fresh_final_path,
                verbatim=True,
                size=len(payload),
                output_path=fresh_temp_path,
            )
            config_files = helper.create_config_files(Path(self.temp_dir.name), 1)
            config_text = config_files[0].path.read_text(encoding="utf-8")
            self.assertIn(f"continue-at = {resume_from_byte}", config_text)
            self.assertIn(r'header = "If-Match: \"etag-1\""', config_text)
            self.assertIn("next\n", config_text)

            proc_env = os.environ.copy()
            proc_env["NO_PROXY"] = "127.0.0.1,localhost,*"
            proc = subprocess.run(
                [curl_path, "--noproxy", "*", "--config", os.fspath(config_files[0].path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
                timeout=10,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr.decode(errors="replace"))
            self.assertEqual(request_ranges, [("/resume", f"bytes={resume_from_byte}-"), ("/fresh", None)])
            self.assertEqual(request_if_match, [("/resume", '"etag-1"'), ("/fresh", None)])
            self.assertEqual(temp_path.read_bytes(), payload)
            self.assertEqual(fresh_temp_path.read_bytes(), payload)
            self.assertFalse(final_path.exists())
            self.assertFalse(fresh_final_path.exists())
        finally:
            server.shutdown()
            server.server_close()

    def run_resume_fallback_case(self, response_mode):
        curl_path = shutil.which("curl")
        if not curl_path:
            self.skipTest("curl executable unavailable")

        config_vars["PARALLEL_DOWNLOAD_METHOD"] = "external"
        config_vars["CURL_CONFIG_FILE_NAME"] = "dl"
        config_vars["PARALLEL_SYNC"] = "1"
        config_vars["COOKIE_FOR_SYNC_URLS"] = "test=1"
        config_vars["DOWNLOAD_TOOL_PATH"] = curl_path
        config_vars["__MAIN_OUT_FILE__"] = os.path.join(self.temp_dir.name, f"{response_mode}.out")

        payload = b"0123456789abcdef" * 256
        item = self.make_item("Products/Foo.pkg", payload)
        final_path = Path(item.download_path)
        temp_path = temp_path_for_download_item(item)
        resume_from_byte = 128
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(payload[:resume_from_byte])
        request_ranges = []
        request_if_match = []

        class FallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                request_ranges.append(self.headers.get("Range"))
                request_if_match.append(self.headers.get("If-Match"))
                if self.headers.get("Range"):
                    if response_mode == "unexpected_200":
                        body = payload
                        self.send_response(200)
                    elif response_mode == "invalid_content_range":
                        body = payload[resume_from_byte:]
                        self.send_response(206)
                        self.send_header("Content-Range", f"bytes 0-{len(body)-1}/{len(payload)}")
                    elif response_mode == "conditional_failure":
                        body = b"precondition failed"
                        self.send_response(412)
                    else:
                        raise AssertionError(f"unsupported response_mode {response_mode}")
                else:
                    body = payload
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FallbackHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            helper = CUrlHelper()
            helper.add_download_url(
                f"http://127.0.0.1:{server.server_port}/Foo.pkg",
                final_path,
                verbatim=True,
                size=len(payload),
                output_path=temp_path,
                resume_from_byte=resume_from_byte,
                conditional_headers=('If-Match: "etag-1"',),
            )
            config_vars["CURL_CONFIG_FILE_NAME"] = f"{response_mode}-dl"
            config_vars["__NUM_FILES_TO_DOWNLOAD__"] = "1"
            config_vars["__NUM_BYTES_TO_DOWNLOAD__"] = str(len(payload))
            dl_commands = AnonymousAccum()
            helper.create_download_instructions(dl_commands)
            parallel_commands = [
                command
                for command in dl_commands.child_batch_commands
                if isinstance(command, ParallelRun)
            ]
            self.assertEqual(len(parallel_commands), 1)
            command = parallel_commands[0]
            self.assertIsNotNone(command.fallback_config_file)
            command.own_progress_count = 0
            command()

            self.assertEqual(request_ranges, [f"bytes={resume_from_byte}-", None])
            self.assertEqual(request_if_match, ['"etag-1"', None])
            self.assertEqual(temp_path.read_bytes(), payload)
            self.assertFalse(final_path.exists())
        finally:
            server.shutdown()
            server.server_close()

    def test_resume_fallback_restarts_from_zero_on_unexpected_200(self):
        self.run_resume_fallback_case("unexpected_200")

    def test_resume_fallback_restarts_from_zero_on_invalid_content_range(self):
        self.run_resume_fallback_case("invalid_content_range")

    def test_resume_fallback_restarts_from_zero_on_conditional_failure(self):
        self.run_resume_fallback_case("conditional_failure")

    def test_checksum_command_promotes_only_verified_temp_file(self):
        # Resume sidecars are only written when resume bookkeeping is enabled.
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "yes"
        payload = b"verified payload"
        item = self.make_item("Products/Foo.pkg", payload)
        final_path = Path(item.download_path)
        temp_path = temp_path_for_download_item(item)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"old invalid payload")
        temp_path.write_bytes(payload)

        command = FakeCheckDownloadFolderChecksum(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command()

        self.assertEqual(final_path.read_bytes(), payload)
        self.assertFalse(temp_path.exists())
        sidecar = DownloadStateStore.from_bookkeeping_dir(config_vars["LOCAL_REPO_BOOKKEEPING_DIR"].Path()).load_file(file_id_for_download_item(item))
        self.assertEqual(sidecar.transfer.state, DownloadFileState.VERIFIED)
        self.assertEqual(sidecar.transfer.received_bytes, len(payload))
        self.assertEqual(sidecar.expected.checksum, item.checksum)

    def test_checksum_command_rejects_bad_temp_without_replacing_final(self):
        # Resume sidecars are only written when resume bookkeeping is enabled.
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "yes"
        payload = b"verified payload"
        item = self.make_item("Products/Foo.pkg", payload)
        final_path = Path(item.download_path)
        temp_path = temp_path_for_download_item(item)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"old invalid payload")
        temp_path.write_bytes(b"wrong payload")

        command = FakeCheckDownloadFolderChecksum(max_bad_files_to_redownload=0, report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])

        with self.assertRaises(ValueError):
            command()

        self.assertEqual(final_path.read_bytes(), b"old invalid payload")
        self.assertEqual(temp_path.read_bytes(), b"wrong payload")
        sidecar = DownloadStateStore.from_bookkeeping_dir(config_vars["LOCAL_REPO_BOOKKEEPING_DIR"].Path()).load_file(file_id_for_download_item(item))
        self.assertEqual(sidecar.transfer.state, DownloadFileState.FAILED_RETRYABLE)
        self.assertEqual(sidecar.transfer.received_bytes, len(b"wrong payload"))
        self.assertEqual(sidecar.transfer.last_failure_class, "checksum_mismatch")

    def test_prepare_download_temp_files_removes_stale_partial(self):
        payload = b"verified payload"
        item = self.make_item("Products/Foo.pkg", payload)
        temp_path = temp_path_for_download_item(item)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(b"stale partial")

        command = FakePrepareDownloadTempFiles(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command()

        self.assertFalse(temp_path.exists())

    def test_prepare_download_temp_files_writes_resume_sidecar_before_cleanup(self):
        # Sidecar bookkeeping is a resume feature; only written when enabled.
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "yes"
        payload = b"verified payload"
        item = self.make_item("Products/Foo.pkg", payload)
        temp_path = temp_path_for_download_item(item)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(b"stale partial")

        command = FakePrepareDownloadTempFiles(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command()

        sidecar = DownloadStateStore.from_bookkeeping_dir(config_vars["LOCAL_REPO_BOOKKEEPING_DIR"].Path()).load_file(file_id_for_download_item(item))
        self.assertIsNotNone(sidecar)
        self.assertEqual(sidecar.session_id, "test-session")
        self.assertEqual(sidecar.repository_major_version, "V16")
        self.assertEqual(sidecar.repository_revision, item.revision)
        self.assertEqual(sidecar.source.url_redacted, "https://cdn.example.com/Products/Foo.pkg")
        self.assertEqual(sidecar.transfer.state, DownloadFileState.INTERRUPTED)
        self.assertEqual(sidecar.transfer.received_bytes, len(b"stale partial"))
        self.assertFalse(temp_path.exists())

    def test_prepare_download_temp_files_skips_sidecar_when_resume_disabled(self):
        # Regression guard: with resume disabled (the default) the prep stage
        # must NOT write a per-file fsync'd sidecar — that O(N) disk-flush
        # work was the cause of the multi-minute pre-download slowdown. It
        # must still purge stale partial artifacts.
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "no"
        payload = b"verified payload"
        item = self.make_item("Products/Foo.pkg", payload)
        temp_path = temp_path_for_download_item(item)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(b"stale partial")

        command = FakePrepareDownloadTempFiles(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command()

        self.assertFalse(temp_path.exists())
        sidecar = DownloadStateStore.from_bookkeeping_dir(config_vars["LOCAL_REPO_BOOKKEEPING_DIR"].Path()).load_file(file_id_for_download_item(item))
        self.assertIsNone(sidecar)

    def test_prepare_download_temp_files_preserves_resume_eligible_partial(self):
        config_vars["DOWNLOAD_RESUME_ENABLED"] = "yes"
        config_vars["DOWNLOAD_RESUME_VALIDATED_HOSTS"] = "cdn.example.com"
        config_vars["DOWNLOAD_RESUME_VALIDATED_PATH_PREFIXES"] = "/Products/"

        payload = b"verified payload"
        item = self.make_item("Products/Foo.pkg", payload)
        partial_payload = payload[:8]
        temp_path = temp_path_for_download_item(item)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(partial_payload)
        save_resume_sidecar_for_download_item(
            item,
            "https://cdn.example.com/Products/Foo.pkg?Signature=old",
            config_vars["LOCAL_REPO_BOOKKEEPING_DIR"].Path(),
            session_id="test-session",
            transfer_state=DownloadFileState.INTERRUPTED,
            source_metadata={"etag": '"etag-1"', "contentLength": len(payload)},
        )

        command = FakePrepareDownloadTempFiles(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command()

        self.assertEqual(temp_path.read_bytes(), partial_payload)
        sidecar = DownloadStateStore.from_bookkeeping_dir(config_vars["LOCAL_REPO_BOOKKEEPING_DIR"].Path()).load_file(file_id_for_download_item(item))
        self.assertEqual(sidecar.transfer.state, DownloadFileState.QUEUED)
        self.assertEqual(sidecar.transfer.received_bytes, len(partial_payload))
        self.assertEqual(sidecar.source.etag, '"etag-1"')

    def test_re_download_retries_transient_failure_then_succeeds(self):
        # A transient network failure is retried with backoff and recovers.
        config_vars["DOWNLOAD_RETRY_POLICY_ENABLED"] = "yes"
        payload = b"recovered payload"
        item = self.make_item("Products/Foo.pkg", payload)
        Path(item.download_path).parent.mkdir(parents=True, exist_ok=True)

        command = FakeCheckDownloadFolderChecksum(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command.num_bad_files = 1

        attempts = {"n": 0}

        def fake_dler(path, url, checksum, temp_path):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise urllib.error.URLError("connection refused")
            Path(path).write_bytes(payload)

        channel = _RecordingControlChannel()
        command._redownload_one_file(fake_dler, item, channel, retry_enabled=True)

        self.assertEqual(attempts["n"], 3)              # 2 failed attempts + 1 success
        self.assertEqual(command.num_bad_files, 0)      # decremented only on success
        self.assertEqual(Path(item.download_path).read_bytes(), payload)
        self.assertEqual(len(channel.sleep_calls), 2)   # backoff before each retry
        # Pause is checked at the top of every attempt (offline auto-pause hook).
        self.assertEqual(channel.wait_if_paused_calls, 3)

    def test_re_download_gives_up_after_retries_exhausted(self):
        # A persistent failure exhausts the matrix and is left terminal.
        config_vars["DOWNLOAD_RETRY_POLICY_ENABLED"] = "yes"
        payload = b"never arrives"
        item = self.make_item("Products/Foo.pkg", payload)

        command = FakeCheckDownloadFolderChecksum(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command.num_bad_files = 1

        def always_fail(path, url, checksum, temp_path):
            raise urllib.error.URLError("connection refused")

        channel = _RecordingControlChannel()
        with self.assertRaises(Exception):
            command._redownload_one_file(always_fail, item, channel, retry_enabled=True)

        self.assertEqual(command.num_bad_files, 1)          # never recovered
        self.assertGreaterEqual(len(channel.sleep_calls), 1)  # backed off before giving up

    def test_re_download_no_retry_when_policy_disabled(self):
        # With the retry policy kill switch off, the first failure is terminal.
        config_vars["DOWNLOAD_RETRY_POLICY_ENABLED"] = "no"
        payload = b"x"
        item = self.make_item("Products/Foo.pkg", payload)

        command = FakeCheckDownloadFolderChecksum(report_own_progress=False)
        command.info_map_table = FakeInfoMapTable([item])
        command.num_bad_files = 1

        calls = {"n": 0}

        def fail_once(path, url, checksum, temp_path):
            calls["n"] += 1
            raise urllib.error.URLError("connection refused")

        channel = _RecordingControlChannel()
        with self.assertRaises(Exception):
            command._redownload_one_file(fail_once, item, channel, retry_enabled=False)

        self.assertEqual(calls["n"], 1)                 # no retry attempted
        self.assertEqual(len(channel.sleep_calls), 0)   # no backoff
        self.assertEqual(command.num_bad_files, 1)

    def test_killed_curl_leaves_only_recoverable_temp_artifact(self):
        curl_path = shutil.which("curl")
        if not curl_path:
            self.skipTest("curl executable unavailable")

        config_vars["PARALLEL_DOWNLOAD_METHOD"] = "external"
        config_vars["CURL_CONFIG_FILE_NAME"] = "dl"
        config_vars["PARALLEL_SYNC"] = "1"
        config_vars["COOKIE_FOR_SYNC_URLS"] = "test=1"

        payload = b"x" * (1024 * 1024 * 8)
        item = self.make_item("Products/Foo.pkg", payload)
        final_path = Path(item.download_path)
        temp_path = temp_path_for_download_item(item)

        class SlowHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                chunk = b"x" * 65536
                try:
                    for _ in range(len(payload) // len(chunk)):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        time.sleep(0.01)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        proc = None
        try:
            helper = CUrlHelper()
            helper.add_download_url(
                f"http://127.0.0.1:{server.server_port}/Foo.pkg",
                final_path,
                verbatim=True,
                size=len(payload),
                output_path=temp_path,
            )
            config_files = helper.create_config_files(Path(self.temp_dir.name), 1)

            proc_env = os.environ.copy()
            proc_env["NO_PROXY"] = "127.0.0.1,localhost,*"
            proc = subprocess.Popen(
                [curl_path, "--noproxy", "*", "--config", os.fspath(config_files[0].path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=proc_env,
            )
            deadline = time.time() + 5
            while time.time() < deadline:
                if temp_path.exists() and 0 < temp_path.stat().st_size < len(payload):
                    break
                time.sleep(0.02)
            if not temp_path.exists():
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
                self.fail(
                    f"curl did not create temp artifact; stdout={stdout.decode(errors='replace')!r}; "
                    f"stderr={stderr.decode(errors='replace')!r}"
                )
            self.assertTrue(temp_path.exists())
            self.assertGreater(temp_path.stat().st_size, 0)
            self.assertLess(temp_path.stat().st_size, len(payload))

            proc.kill()
            proc.communicate(timeout=5)

            self.assertFalse(final_path.exists())
            self.assertTrue(temp_path.exists())

            command = FakePrepareDownloadTempFiles(report_own_progress=False)
            command.info_map_table = FakeInfoMapTable([item])
            command()

            self.assertFalse(temp_path.exists())
            self.assertFalse(final_path.exists())
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=5)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=3)
