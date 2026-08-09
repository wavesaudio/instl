#!/usr/bin/env python3.12

import errno
import email.utils
import os
import socket
import ssl
import subprocess
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover - requests is optional for admin-only environments
    requests = None


class DownloadFailureClass(str, Enum):
    DNS_RESOLUTION = "dns_resolution"
    TCP_CONNECT = "tcp_connect"
    TLS = "tls"
    TIMEOUT_BEFORE_FIRST_BYTE = "timeout_before_first_byte"
    TIMEOUT_DURING_TRANSFER = "timeout_during_transfer"
    HTTP_429 = "http_429"
    HTTP_5XX = "http_5xx"
    HTTP_AUTH_POLICY = "http_auth_policy"
    HTTP_4XX = "http_4xx"
    HTTP_ERROR = "http_error"
    DISK_WRITE = "disk_write"
    DISK_SPACE = "disk_space"
    PERMISSION_DENIED = "permission_denied"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    PARTIAL_TRANSFER = "partial_transfer"
    PROCESS_TERMINATED = "process_terminated"
    CANCELLED = "cancelled"
    MISSING_AFTER_TRANSFER = "missing_after_transfer"
    MALFORMED_URL = "malformed_url"
    NETWORK_SEND_ERROR = "network_send_error"
    NETWORK_RECEIVE_ERROR = "network_receive_error"
    UNKNOWN_DOWNLOAD_ERROR = "unknown_download_error"


RETRYABLE_FAILURE_CLASSES = frozenset({
    DownloadFailureClass.DNS_RESOLUTION,
    DownloadFailureClass.TCP_CONNECT,
    DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE,
    DownloadFailureClass.TIMEOUT_DURING_TRANSFER,
    DownloadFailureClass.HTTP_429,
    DownloadFailureClass.HTTP_5XX,
    DownloadFailureClass.HTTP_ERROR,
    DownloadFailureClass.CHECKSUM_MISMATCH,
    DownloadFailureClass.PARTIAL_TRANSFER,
    DownloadFailureClass.PROCESS_TERMINATED,
    DownloadFailureClass.MISSING_AFTER_TRANSFER,
    DownloadFailureClass.NETWORK_SEND_ERROR,
    DownloadFailureClass.NETWORK_RECEIVE_ERROR,
})


CURL_ERROR_DESCRIPTIONS = {
    3: "URL malformed",
    5: "Couldnt resolve proxy",
    6: "Couldn't resolve host",
    7: "Failed to connect to host",
    18: "Partial file. Only a part of the file was transferred",
    21: "Quote error. A quote command returned an error from the server",
    22: "HTTP page not retrieved. The requested url was not found or returned another error",
    23: "Write error. Curl could not write data to a local filesystem",
    28: "Operation timeout. The specified time-out period was reached according to the conditions",
    33: "HTTP range request failed. The server did not return a usable partial response",
    35: "TLS/SSL connect error",
    51: "The peer's SSL certificate or SSH MD5 fingerprint was not OK",
    52: "Nothing was returned from the server",
    55: "Failure while sending network data",
    56: "Failure while receiving network data",
    60: "Peer certificate cannot be authenticated with known CA certificates",
    77: "Problem with the SSL CA cert",
}


@dataclass(frozen=True)
class DownloadFailureInfo:
    failure_class: DownloadFailureClass
    retryable: bool
    source: str
    reason: str = ""
    curl_exit_code: int | None = None
    http_status: int | None = None
    retry_after_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "failureClass": self.failure_class.value,
            "retryable": self.retryable,
            "source": self.source,
            "reason": self.reason,
            "curlExitCode": self.curl_exit_code,
            "httpStatus": self.http_status,
            "retryAfterSeconds": self.retry_after_seconds,
        }


def is_retryable_failure_class(failure_class: DownloadFailureClass | str) -> bool:
    if not isinstance(failure_class, DownloadFailureClass):
        try:
            failure_class = DownloadFailureClass(failure_class)
        except ValueError:
            return False
    return failure_class in RETRYABLE_FAILURE_CLASSES


def _failure_info(
        failure_class: DownloadFailureClass,
        source: str,
        reason: str = "",
        curl_exit_code: int | None = None,
        http_status: int | None = None,
        retry_after_seconds: int | None = None) -> DownloadFailureInfo:
    return DownloadFailureInfo(
        failure_class=failure_class,
        retryable=is_retryable_failure_class(failure_class),
        source=source,
        reason=reason,
        curl_exit_code=curl_exit_code,
        http_status=http_status,
        retry_after_seconds=retry_after_seconds,
    )


def retry_after_seconds(header_value: Any, now: datetime | None = None) -> int | None:
    if header_value is None:
        return None
    value = str(header_value).strip()
    if not value:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, int((parsed.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()))


def _header_value(headers: Any, header_name: str) -> Any:
    if not headers:
        return None
    if hasattr(headers, "get"):
        return headers.get(header_name)
    return None


def classify_http_status(status_code: int | str | None, headers: Any = None) -> DownloadFailureInfo:
    try:
        status = int(status_code)
    except (TypeError, ValueError):
        return _failure_info(DownloadFailureClass.HTTP_ERROR, "http_status", "missing_or_invalid_http_status")

    retry_after = retry_after_seconds(_header_value(headers, "Retry-After"))
    if status == 429:
        return _failure_info(
            DownloadFailureClass.HTTP_429,
            "http_status",
            "too_many_requests",
            http_status=status,
            retry_after_seconds=retry_after,
        )
    if status == 408:
        return _failure_info(
            DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE,
            "http_status",
            "request_timeout",
            http_status=status,
            retry_after_seconds=retry_after,
        )
    if 500 <= status <= 599:
        return _failure_info(
            DownloadFailureClass.HTTP_5XX,
            "http_status",
            "server_error",
            http_status=status,
            retry_after_seconds=retry_after,
        )
    if status in (401, 403, 407):
        return _failure_info(
            DownloadFailureClass.HTTP_AUTH_POLICY,
            "http_status",
            "auth_or_policy_failure",
            http_status=status,
            retry_after_seconds=retry_after,
        )
    if 400 <= status <= 499:
        return _failure_info(
            DownloadFailureClass.HTTP_4XX,
            "http_status",
            "client_error",
            http_status=status,
            retry_after_seconds=retry_after,
        )
    return _failure_info(
        DownloadFailureClass.HTTP_ERROR,
        "http_status",
        "unexpected_http_status",
        http_status=status,
        retry_after_seconds=retry_after,
    )


def classify_curl_exit_code(
        exit_code: int | str | None,
        http_status: int | str | None = None,
        headers: Any = None,
        received_bytes: int | None = None) -> DownloadFailureInfo:
    try:
        curl_exit_code = int(exit_code)
    except (TypeError, ValueError):
        return _failure_info(DownloadFailureClass.UNKNOWN_DOWNLOAD_ERROR, "curl", "missing_or_invalid_curl_exit_code")

    if curl_exit_code == 22:
        info = classify_http_status(http_status, headers) if http_status is not None else _failure_info(
            DownloadFailureClass.HTTP_ERROR,
            "curl",
            "http_error_without_status",
        )
        return DownloadFailureInfo(
            failure_class=info.failure_class,
            retryable=info.retryable,
            source="curl",
            reason=info.reason,
            curl_exit_code=curl_exit_code,
            http_status=info.http_status,
            retry_after_seconds=info.retry_after_seconds,
        )
    if curl_exit_code in (5, 6):
        failure_class = DownloadFailureClass.DNS_RESOLUTION
    elif curl_exit_code == 7:
        failure_class = DownloadFailureClass.TCP_CONNECT
    elif curl_exit_code in (35, 51, 60, 77):
        failure_class = DownloadFailureClass.TLS
    elif curl_exit_code == 28:
        failure_class = (
            DownloadFailureClass.TIMEOUT_DURING_TRANSFER
            if received_bytes and received_bytes > 0
            else DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE
        )
    elif curl_exit_code in (18, 33):
        failure_class = DownloadFailureClass.PARTIAL_TRANSFER
    elif curl_exit_code == 23:
        failure_class = DownloadFailureClass.DISK_WRITE
    elif curl_exit_code == 55:
        failure_class = DownloadFailureClass.NETWORK_SEND_ERROR
    elif curl_exit_code in (52, 56):
        failure_class = DownloadFailureClass.NETWORK_RECEIVE_ERROR
    elif curl_exit_code == 3:
        failure_class = DownloadFailureClass.MALFORMED_URL
    else:
        failure_class = DownloadFailureClass.UNKNOWN_DOWNLOAD_ERROR

    return _failure_info(
        failure_class,
        "curl",
        CURL_ERROR_DESCRIPTIONS.get(curl_exit_code, "unmapped_curl_exit_code"),
        curl_exit_code=curl_exit_code,
    )


def curl_error_description(exit_code: int | str | None) -> str | None:
    try:
        return CURL_ERROR_DESCRIPTIONS.get(int(exit_code))
    except (TypeError, ValueError):
        return None


def _iter_exception_chain(exc: BaseException):
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _contains_exception(exc: BaseException, exception_type) -> bool:
    return any(isinstance(chained, exception_type) for chained in _iter_exception_chain(exc))


def _message_contains(exc: BaseException, *needles: str) -> bool:
    message = " ".join(str(chained) for chained in _iter_exception_chain(exc)).lower()
    return any(needle.lower() in message for needle in needles)


def _classify_requests_exception(exc: BaseException) -> DownloadFailureInfo | None:
    if requests is None or not isinstance(exc, requests.exceptions.RequestException):
        return None
    if isinstance(exc, requests.exceptions.HTTPError) and getattr(exc, "response", None) is not None:
        return classify_http_status(exc.response.status_code, exc.response.headers)
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return _failure_info(DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE, "requests", "connect_timeout")
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return _failure_info(DownloadFailureClass.TIMEOUT_DURING_TRANSFER, "requests", "read_timeout")
    if isinstance(exc, requests.exceptions.SSLError):
        return _failure_info(DownloadFailureClass.TLS, "requests", "tls_error")
    if isinstance(exc, requests.exceptions.ConnectionError):
        if _contains_exception(exc, socket.gaierror) or _message_contains(exc, "name resolution", "getaddrinfo", "resolve"):
            return _failure_info(DownloadFailureClass.DNS_RESOLUTION, "requests", "dns_resolution")
        return _failure_info(DownloadFailureClass.TCP_CONNECT, "requests", "connection_error")
    if isinstance(exc, requests.exceptions.Timeout):
        return _failure_info(DownloadFailureClass.TIMEOUT_DURING_TRANSFER, "requests", "timeout")
    if getattr(exc, "response", None) is not None:
        return classify_http_status(exc.response.status_code, exc.response.headers)
    return _failure_info(DownloadFailureClass.UNKNOWN_DOWNLOAD_ERROR, "requests", exc.__class__.__name__)


def _classify_urllib_exception(exc: BaseException) -> DownloadFailureInfo | None:
    if isinstance(exc, urllib.error.HTTPError):
        return classify_http_status(exc.code, exc.headers)
    if not isinstance(exc, urllib.error.URLError):
        return None
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.gaierror):
        return _failure_info(DownloadFailureClass.DNS_RESOLUTION, "urllib", "dns_resolution")
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return _failure_info(DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE, "urllib", "timeout")
    if isinstance(reason, ssl.SSLError):
        return _failure_info(DownloadFailureClass.TLS, "urllib", "tls_error")
    if isinstance(reason, ConnectionRefusedError):
        return _failure_info(DownloadFailureClass.TCP_CONNECT, "urllib", "connection_refused")
    if _message_contains(exc, "getaddrinfo", "nodename nor servname", "name or service not known"):
        return _failure_info(DownloadFailureClass.DNS_RESOLUTION, "urllib", "dns_resolution")
    if _message_contains(exc, "timed out"):
        return _failure_info(DownloadFailureClass.TIMEOUT_BEFORE_FIRST_BYTE, "urllib", "timeout")
    if _message_contains(exc, "ssl", "certificate", "tls"):
        return _failure_info(DownloadFailureClass.TLS, "urllib", "tls_error")
    return _failure_info(DownloadFailureClass.TCP_CONNECT, "urllib", "url_error")


def _classify_os_error(exc: BaseException) -> DownloadFailureInfo | None:
    if not isinstance(exc, OSError):
        return None
    if exc.errno == errno.ENOSPC:
        return _failure_info(DownloadFailureClass.DISK_SPACE, "os", "no_space_left")
    if exc.errno in (errno.EACCES, errno.EPERM):
        return _failure_info(DownloadFailureClass.PERMISSION_DENIED, "os", "permission_denied")
    if exc.errno in (errno.EIO, errno.EBADF):
        return _failure_info(DownloadFailureClass.DISK_WRITE, "os", "disk_write")
    return None


def classify_exception(exc: BaseException) -> DownloadFailureInfo:
    requests_info = _classify_requests_exception(exc)
    if requests_info:
        return requests_info
    urllib_info = _classify_urllib_exception(exc)
    if urllib_info:
        return urllib_info
    os_error_info = _classify_os_error(exc)
    if os_error_info:
        return os_error_info
    if isinstance(exc, subprocess.CalledProcessError):
        return _failure_info(DownloadFailureClass.PROCESS_TERMINATED, "process", "called_process_error")
    if exc.__class__.__name__ == "ProcessTerminatedExternally":
        return _failure_info(DownloadFailureClass.PROCESS_TERMINATED, "process", "terminated_externally")
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return _failure_info(DownloadFailureClass.CANCELLED, "process", "cancelled")

    message = str(exc).lower()
    if "bad checksum" in message:
        return _failure_info(DownloadFailureClass.CHECKSUM_MISMATCH, "exception_text", "bad_checksum")
    if "no space left" in message or "enospc" in message:
        return _failure_info(DownloadFailureClass.DISK_SPACE, "exception_text", "no_space_left")
    if "permission denied" in message or "operation not permitted" in message or "access is denied" in message:
        return _failure_info(DownloadFailureClass.PERMISSION_DENIED, "exception_text", "permission_denied")
    if "missing" in message or "was not found" in message:
        return _failure_info(DownloadFailureClass.MISSING_AFTER_TRANSFER, "exception_text", "missing_after_transfer")

    return _failure_info(DownloadFailureClass.UNKNOWN_DOWNLOAD_ERROR, "exception", exc.__class__.__name__)
