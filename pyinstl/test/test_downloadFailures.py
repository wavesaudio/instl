#!/usr/bin/env python3.12

import errno
import os
import sys
import urllib.error
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadFailures import (
    DownloadFailureClass,
    classify_curl_exit_code,
    classify_exception,
    classify_http_status,
    curl_error_description,
    is_retryable_failure_class,
    retry_after_seconds,
)

try:
    import requests
except Exception:
    requests = None


class TestDownloadFailures(unittest.TestCase):
    def assert_failure(self, info, failure_class, retryable=None, source=None):
        self.assertEqual(info.failure_class, failure_class)
        if retryable is not None:
            self.assertEqual(info.retryable, retryable)
        if source is not None:
            self.assertEqual(info.source, source)

    def test_required_failure_classes_are_defined(self):
        required_classes = {
            "dns_resolution",
            "tcp_connect",
            "tls",
            "timeout_before_first_byte",
            "timeout_during_transfer",
            "http_429",
            "http_5xx",
            "http_auth_policy",
            "disk_write",
            "checksum_mismatch",
            "partial_transfer",
            "process_terminated",
            "unknown_download_error",
        }

        self.assertTrue(required_classes.issubset({failure_class.value for failure_class in DownloadFailureClass}))

    def test_retryability_is_defined_by_failure_class(self):
        self.assertTrue(is_retryable_failure_class(DownloadFailureClass.HTTP_5XX))
        self.assertTrue(is_retryable_failure_class("partial_transfer"))
        self.assertFalse(is_retryable_failure_class(DownloadFailureClass.HTTP_AUTH_POLICY))
        self.assertFalse(is_retryable_failure_class("unknown_value"))

    def test_curl_exit_codes_map_to_normalized_classes(self):
        cases = (
            (3, None, DownloadFailureClass.MALFORMED_URL, False),
            (5, None, DownloadFailureClass.DNS_RESOLUTION, True),
            (6, None, DownloadFailureClass.DNS_RESOLUTION, True),
            (7, None, DownloadFailureClass.TCP_CONNECT, True),
            (18, None, DownloadFailureClass.PARTIAL_TRANSFER, True),
            (23, None, DownloadFailureClass.DISK_WRITE, False),
            (28, 0, DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE, True),
            (28, 10, DownloadFailureClass.TIMEOUT_DURING_TRANSFER, True),
            (33, None, DownloadFailureClass.PARTIAL_TRANSFER, True),
            (35, None, DownloadFailureClass.TLS, False),
            (52, None, DownloadFailureClass.NETWORK_RECEIVE_ERROR, True),
            (55, None, DownloadFailureClass.NETWORK_SEND_ERROR, True),
            (56, None, DownloadFailureClass.NETWORK_RECEIVE_ERROR, True),
        )

        for exit_code, received_bytes, expected_class, retryable in cases:
            with self.subTest(exit_code=exit_code, received_bytes=received_bytes):
                self.assert_failure(
                    classify_curl_exit_code(exit_code, received_bytes=received_bytes),
                    expected_class,
                    retryable,
                    "curl",
                )

    def test_curl_http_exit_code_uses_http_status_when_available(self):
        cases = (
            (429, DownloadFailureClass.HTTP_429, True),
            (500, DownloadFailureClass.HTTP_5XX, True),
            (503, DownloadFailureClass.HTTP_5XX, True),
            (401, DownloadFailureClass.HTTP_AUTH_POLICY, False),
            (403, DownloadFailureClass.HTTP_AUTH_POLICY, False),
            (404, DownloadFailureClass.HTTP_4XX, False),
        )

        for status_code, expected_class, retryable in cases:
            with self.subTest(status_code=status_code):
                info = classify_curl_exit_code(22, http_status=status_code)
                self.assert_failure(info, expected_class, retryable, "curl")
                self.assertEqual(info.curl_exit_code, 22)
                self.assertEqual(info.http_status, status_code)

    def test_http_status_retry_after_is_parsed(self):
        info = classify_http_status(429, headers={"Retry-After": "17"})

        self.assert_failure(info, DownloadFailureClass.HTTP_429, True, "http_status")
        self.assertEqual(info.retry_after_seconds, 17)
        self.assertEqual(retry_after_seconds("not a retry after value"), None)

    def test_curl_error_description_keeps_existing_message_text(self):
        self.assertEqual(curl_error_description(28), "Operation timeout. The specified time-out period was reached according to the conditions")
        self.assertEqual(curl_error_description(9999), None)

    @unittest.skipIf(requests is None, "requests unavailable")
    def test_requests_metadata_exceptions_map_to_taxonomy(self):
        response = requests.Response()
        response.status_code = 503
        response.headers["Retry-After"] = "5"

        cases = (
            (requests.exceptions.HTTPError("server error", response=response), DownloadFailureClass.HTTP_5XX, True),
            (requests.exceptions.ConnectTimeout("connect timed out"), DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE, True),
            (requests.exceptions.ReadTimeout("read timed out"), DownloadFailureClass.TIMEOUT_DURING_TRANSFER, True),
            (requests.exceptions.SSLError("certificate verify failed"), DownloadFailureClass.TLS, False),
            (requests.exceptions.ConnectionError("getaddrinfo failed"), DownloadFailureClass.DNS_RESOLUTION, True),
        )

        for exc, expected_class, retryable in cases:
            with self.subTest(exc=exc.__class__.__name__):
                self.assert_failure(classify_exception(exc), expected_class, retryable)

    def test_urllib_metadata_exceptions_map_to_taxonomy(self):
        http_error = urllib.error.HTTPError(
            url="https://cdn.example.com/payload",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=None,
        )
        dns_error = urllib.error.URLError("getaddrinfo failed")

        self.assert_failure(classify_exception(http_error), DownloadFailureClass.HTTP_AUTH_POLICY, False)
        self.assert_failure(classify_exception(dns_error), DownloadFailureClass.DNS_RESOLUTION, True)

    def test_local_helper_exceptions_map_to_taxonomy(self):
        cases = (
            (OSError(errno.ENOSPC, os.strerror(errno.ENOSPC)), DownloadFailureClass.DISK_SPACE, False),
            (OSError(errno.EACCES, os.strerror(errno.EACCES)), DownloadFailureClass.PERMISSION_DENIED, False),
            (OSError(errno.EIO, os.strerror(errno.EIO)), DownloadFailureClass.DISK_WRITE, False),
            (ValueError("bad checksum for temp download"), DownloadFailureClass.CHECKSUM_MISMATCH, True),
            (RuntimeError("missing temp download '/tmp/file'"), DownloadFailureClass.MISSING_AFTER_TRANSFER, True),
        )

        for exc, expected_class, retryable in cases:
            with self.subTest(exc=str(exc)):
                self.assert_failure(classify_exception(exc), expected_class, retryable)


if __name__ == "__main__":
    unittest.main(verbosity=3)
