#!/usr/bin/env python3.12

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


DOWNLOAD_STATE_SCHEMA_VERSION = 1
TEMP_ARTIFACT_FILE_ID_LENGTH = 16


class DownloadStateSchemaError(ValueError):
    pass


class DownloadSessionState(str, Enum):
    PREPARING = "preparing"
    VERIFYING_EXISTING_FILES = "verifying_existing_files"
    DOWNLOADING = "downloading"
    RETRYING = "retrying"
    PAUSED = "paused"
    VERIFYING_DOWNLOADS = "verifying_downloads"
    READY_TO_COPY = "ready_to_copy"
    COPYING = "copying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadFileState(str, Enum):
    PLANNED = "planned"
    ALREADY_VALID = "already_valid"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    DOWNLOADED_UNVERIFIED = "downloaded_unverified"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def redact_url_for_state(in_url: str | None) -> str | None:
    """Keep object identity path but remove query/fragment auth material."""
    if not in_url:
        return None
    split_url = urlsplit(in_url)
    if not split_url.scheme and not split_url.netloc:
        return in_url.split("?", 1)[0].split("#", 1)[0]
    return urlunsplit((split_url.scheme, split_url.netloc, split_url.path, "", ""))


def object_key_from_url(in_url: str | None) -> str | None:
    if not in_url:
        return None
    split_url = urlsplit(in_url)
    object_key = split_url.path.lstrip("/")
    return object_key or None


def make_file_id(repo_path: str, checksum: str, size: int | str, repository_revision: int | str | None = None) -> str:
    hasher = hashlib.sha256()
    stable_parts = (
        str(repository_revision or ""),
        repo_path or "",
        checksum or "",
        str(size or 0),
    )
    for part in stable_parts:
        hasher.update(part.encode("utf-8", errors="backslashreplace"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def temp_path_for_final_path(final_path: str | Path, file_id: str) -> Path:
    if not file_id or "/" in file_id or "\\" in file_id:
        raise ValueError(f"invalid download state file id {file_id!r}")
    short_file_id = file_id[:TEMP_ARTIFACT_FILE_ID_LENGTH]
    return Path(f"{os.fspath(final_path)}.instl-{short_file_id}.part")


def file_id_for_download_item(file_item) -> str:
    return make_file_id(
        repo_path=getattr(file_item, "path", ""),
        checksum=getattr(file_item, "checksum", ""),
        size=getattr(file_item, "size", 0),
        repository_revision=getattr(file_item, "revision", None),
    )


def temp_path_for_download_item(file_item) -> Path:
    return temp_path_for_final_path(getattr(file_item, "download_path"), file_id_for_download_item(file_item))


def remove_stale_temp_for_download_item(file_item) -> bool:
    temp_path = temp_path_for_download_item(file_item)
    if temp_path.is_file() or temp_path.is_symlink():
        temp_path.unlink()
        return True
    return False


def get_file_sha1(path: str | Path) -> str:
    hasher = hashlib.sha1()
    with open(Path(path), "rb") as rfd:
        while True:
            chunk = rfd.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def checksum_matches(path: str | Path, expected_checksum: str) -> bool:
    if not path or not expected_checksum or not Path(path).is_file():
        return False
    return get_file_sha1(path).lower() == expected_checksum.lower()


def promote_temp_file(temp_path: str | Path, final_path: str | Path) -> None:
    final_path = Path(final_path)
    temp_path = Path(temp_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temp_path, final_path)


def promote_verified_temp_file(
        temp_path: str | Path,
        final_path: str | Path,
        expected_checksum: str,
        actual_checksum: str | None = None) -> str:
    file_checksum = actual_checksum or get_file_sha1(temp_path)
    if file_checksum.lower() != expected_checksum.lower():
        raise ValueError(f"bad checksum for temp download '{temp_path}'")
    promote_temp_file(temp_path, final_path)
    return file_checksum


def _require_dict(data: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DownloadStateSchemaError(f"{field_name} must be a dictionary")
    return data


def _validate_schema_version(data: dict[str, Any]) -> None:
    schema_version = data.get("schemaVersion")
    if schema_version != DOWNLOAD_STATE_SCHEMA_VERSION:
        raise DownloadStateSchemaError(f"unsupported download state schemaVersion {schema_version!r}")


def _enum_value(enum_class, value: str, field_name: str):
    try:
        return enum_class(value)
    except ValueError:
        raise DownloadStateSchemaError(f"unsupported {field_name} {value!r}")


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    int_value = int(value)
    if int_value < 0:
        raise DownloadStateSchemaError(f"{field_name} must be non-negative")
    return int_value


def _non_negative_int(value: Any, field_name: str) -> int:
    int_value = int(value)
    if int_value < 0:
        raise DownloadStateSchemaError(f"{field_name} must be non-negative")
    return int_value


@dataclass
class DownloadSourceState:
    url_redacted: str | None = None
    object_key: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None
    version_id: str | None = None
    signed_url_expires_at: str | None = None

    @classmethod
    def from_url(cls, in_url: str | None, **kwargs):
        return cls(
            url_redacted=redact_url_for_state(in_url),
            object_key=kwargs.pop("object_key", object_key_from_url(in_url)),
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        data = _require_dict(data, "source")
        return cls(
            url_redacted=data.get("urlRedacted"),
            object_key=data.get("objectKey"),
            etag=data.get("etag"),
            last_modified=data.get("lastModified"),
            content_length=_optional_non_negative_int(data.get("contentLength"), "source.contentLength"),
            version_id=data.get("versionId"),
            signed_url_expires_at=data.get("signedUrlExpiresAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "urlRedacted": self.url_redacted,
            "objectKey": self.object_key,
            "etag": self.etag,
            "lastModified": self.last_modified,
            "contentLength": self.content_length,
            "versionId": self.version_id,
            "signedUrlExpiresAt": self.signed_url_expires_at,
        }


@dataclass
class DownloadTargetState:
    final_path: str
    temp_path: str
    sidecar_path: str | None = None

    @classmethod
    def from_final_path(cls, final_path: str | Path, file_id: str, sidecar_path: str | Path | None = None):
        return cls(
            final_path=os.fspath(final_path),
            temp_path=os.fspath(temp_path_for_final_path(final_path, file_id)),
            sidecar_path=os.fspath(sidecar_path) if sidecar_path is not None else None,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        data = _require_dict(data, "target")
        return cls(
            final_path=data["finalPath"],
            temp_path=data["tempPath"],
            sidecar_path=data.get("sidecarPath"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finalPath": self.final_path,
            "tempPath": self.temp_path,
            "sidecarPath": self.sidecar_path,
        }


@dataclass
class DownloadExpectedState:
    size: int
    checksum: str
    checksum_algorithm: str = "sha1"

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        data = _require_dict(data, "expected")
        return cls(
            size=_non_negative_int(data["size"], "expected.size"),
            checksum=data["checksum"],
            checksum_algorithm=data.get("checksumAlgorithm", "sha1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "checksumAlgorithm": self.checksum_algorithm,
            "checksum": self.checksum,
        }


@dataclass
class DownloadTransferState:
    state: DownloadFileState
    received_bytes: int = 0
    retry_count: int = 0
    last_failure_class: str | None = None
    last_updated_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        data = _require_dict(data, "transfer")
        return cls(
            state=_enum_value(DownloadFileState, data["state"], "transfer.state"),
            received_bytes=_non_negative_int(data.get("receivedBytes", 0), "transfer.receivedBytes"),
            retry_count=_non_negative_int(data.get("retryCount", 0), "transfer.retryCount"),
            last_failure_class=data.get("lastFailureClass"),
            last_updated_at=data.get("lastUpdatedAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "receivedBytes": self.received_bytes,
            "retryCount": self.retry_count,
            "lastFailureClass": self.last_failure_class,
            "lastUpdatedAt": self.last_updated_at,
        }


@dataclass
class DownloadSessionRecord:
    session_id: str
    state: DownloadSessionState
    created_at: str
    updated_at: str
    action_id: str | None = None
    repository_major_version: int | str | None = None
    repository_revision: int | str | None = None
    sync_base_url_redacted: str | None = None
    local_repo_sync_dir: str | None = None
    bookkeeping_dir: str | None = None
    planned_files: int = 0
    files_to_download: int = 0
    bytes_to_download: int = 0

    @classmethod
    def new(cls, session_id: str | None = None, **kwargs):
        now = utc_now_iso()
        return cls(
            session_id=session_id or uuid.uuid4().hex,
            state=kwargs.pop("state", DownloadSessionState.PREPARING),
            created_at=kwargs.pop("created_at", now),
            updated_at=kwargs.pop("updated_at", now),
            **kwargs,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        data = _require_dict(data, "session")
        _validate_schema_version(data)
        return cls(
            session_id=data["sessionId"],
            state=_enum_value(DownloadSessionState, data["state"], "session.state"),
            created_at=data["createdAt"],
            updated_at=data["updatedAt"],
            action_id=data.get("actionId"),
            repository_major_version=data.get("repositoryMajorVersion"),
            repository_revision=data.get("repositoryRevision"),
            sync_base_url_redacted=data.get("syncBaseUrlRedacted"),
            local_repo_sync_dir=data.get("localRepoSyncDir"),
            bookkeeping_dir=data.get("bookkeepingDir"),
            planned_files=_non_negative_int(data.get("plannedFiles", 0), "session.plannedFiles"),
            files_to_download=_non_negative_int(data.get("filesToDownload", 0), "session.filesToDownload"),
            bytes_to_download=_non_negative_int(data.get("bytesToDownload", 0), "session.bytesToDownload"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": DOWNLOAD_STATE_SCHEMA_VERSION,
            "sessionId": self.session_id,
            "state": self.state.value,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "actionId": self.action_id,
            "repositoryMajorVersion": self.repository_major_version,
            "repositoryRevision": self.repository_revision,
            "syncBaseUrlRedacted": self.sync_base_url_redacted,
            "localRepoSyncDir": self.local_repo_sync_dir,
            "bookkeepingDir": self.bookkeeping_dir,
            "plannedFiles": self.planned_files,
            "filesToDownload": self.files_to_download,
            "bytesToDownload": self.bytes_to_download,
        }


@dataclass
class DownloadFileRecord:
    session_id: str
    file_id: str
    repo_path: str
    source: DownloadSourceState
    target: DownloadTargetState
    expected: DownloadExpectedState
    transfer: DownloadTransferState
    repository_major_version: int | str | None = None
    repository_revision: int | str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        data = _require_dict(data, "file")
        _validate_schema_version(data)
        return cls(
            session_id=data["sessionId"],
            file_id=data["fileId"],
            repo_path=data["repoPath"],
            repository_major_version=data.get("repositoryMajorVersion"),
            repository_revision=data.get("repositoryRevision"),
            source=DownloadSourceState.from_dict(data["source"]),
            target=DownloadTargetState.from_dict(data["target"]),
            expected=DownloadExpectedState.from_dict(data["expected"]),
            transfer=DownloadTransferState.from_dict(data["transfer"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": DOWNLOAD_STATE_SCHEMA_VERSION,
            "sessionId": self.session_id,
            "fileId": self.file_id,
            "repoPath": self.repo_path,
            "repositoryMajorVersion": self.repository_major_version,
            "repositoryRevision": self.repository_revision,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "expected": self.expected.to_dict(),
            "transfer": self.transfer.to_dict(),
        }


def write_json_atomic(path: str | Path, data: dict[str, Any]) -> None:
    target_path = Path(path)
    tmp_path = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8", errors="backslashreplace") as wfd:
            json.dump(data, wfd, indent=2, sort_keys=True)
            wfd.write("\n")
            wfd.flush()
            try:
                os.fsync(wfd.fileno())
            except OSError:
                pass
        os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def read_json(path: str | Path) -> dict[str, Any]:
    with open(Path(path), "r", encoding="utf-8", errors="backslashreplace") as rfd:
        return json.load(rfd)


class DownloadStateStore:
    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.files_dir = self.state_dir.joinpath("files")

    @classmethod
    def from_bookkeeping_dir(cls, bookkeeping_dir: str | Path):
        return cls(Path(bookkeeping_dir).joinpath("download-state"))

    def session_path(self) -> Path:
        return self.state_dir.joinpath("session.json")

    def file_path(self, file_id: str) -> Path:
        if "/" in file_id or "\\" in file_id:
            raise ValueError(f"invalid download state file id {file_id!r}")
        return self.files_dir.joinpath(f"{file_id}.json")

    def load_session(self) -> DownloadSessionRecord | None:
        path = self.session_path()
        if not path.is_file():
            return None
        return DownloadSessionRecord.from_dict(read_json(path))

    def save_session(self, record: DownloadSessionRecord) -> None:
        write_json_atomic(self.session_path(), record.to_dict())

    def load_file(self, file_id: str) -> DownloadFileRecord | None:
        path = self.file_path(file_id)
        if not path.is_file():
            return None
        return DownloadFileRecord.from_dict(read_json(path))

    def save_file(self, record: DownloadFileRecord) -> None:
        write_json_atomic(self.file_path(record.file_id), record.to_dict())


@dataclass(frozen=True)
class DownloadResumeDecision:
    can_resume: bool
    reason: str
    resume_from_byte: int = 0
    conditional_headers: tuple[str, ...] = ()
    record: DownloadFileRecord | None = None


def existing_file_size(path: str | Path) -> int:
    try:
        path = Path(path)
        if path.is_file():
            return path.stat().st_size
    except OSError:
        pass
    return 0


def resume_sidecar_path_for_download_item(file_item, bookkeeping_dir: str | Path) -> Path:
    store = DownloadStateStore.from_bookkeeping_dir(bookkeeping_dir)
    return store.file_path(file_id_for_download_item(file_item))


def load_resume_sidecar_for_download_item(file_item, bookkeeping_dir: str | Path) -> DownloadFileRecord | None:
    store = DownloadStateStore.from_bookkeeping_dir(bookkeeping_dir)
    return store.load_file(file_id_for_download_item(file_item))


def _source_metadata_value(source_metadata: dict[str, Any], *keys: str):
    for key in keys:
        if key in source_metadata:
            return source_metadata[key]
    return None


def build_resume_sidecar_record_for_download_item(
        file_item,
        source_url: str | None,
        bookkeeping_dir: str | Path | None = None,
        session_id: str | None = None,
        repository_major_version: int | str | None = None,
        repository_revision: int | str | None = None,
        transfer_state: DownloadFileState | str = DownloadFileState.QUEUED,
        received_bytes: int | None = None,
        retry_count: int = 0,
        last_failure_class: str | None = None,
        last_updated_at: str | None = None,
        source_metadata: dict[str, Any] | None = None) -> DownloadFileRecord:
    source_metadata = source_metadata or {}
    file_id = file_id_for_download_item(file_item)
    temp_path = temp_path_for_download_item(file_item)
    if received_bytes is None:
        received_bytes = existing_file_size(temp_path)
    if not isinstance(transfer_state, DownloadFileState):
        transfer_state = DownloadFileState(transfer_state)
    source_content_length = _source_metadata_value(source_metadata, "content_length", "contentLength", "Content-Length")
    if source_content_length is not None:
        source_content_length = _optional_non_negative_int(source_content_length, "source.contentLength")

    sidecar_path = None
    if bookkeeping_dir is not None:
        sidecar_path = resume_sidecar_path_for_download_item(file_item, bookkeeping_dir)

    file_repository_revision = repository_revision
    if file_repository_revision is None:
        file_repository_revision = getattr(file_item, "revision", None)

    return DownloadFileRecord(
        session_id=session_id or "unknown",
        file_id=file_id,
        repo_path=getattr(file_item, "path", ""),
        repository_major_version=repository_major_version,
        repository_revision=file_repository_revision,
        source=DownloadSourceState.from_url(
            source_url,
            object_key=_source_metadata_value(source_metadata, "object_key", "objectKey") or object_key_from_url(source_url),
            etag=_source_metadata_value(source_metadata, "etag", "ETag"),
            last_modified=_source_metadata_value(source_metadata, "last_modified", "lastModified", "Last-Modified"),
            content_length=source_content_length,
            version_id=_source_metadata_value(source_metadata, "version_id", "versionId"),
            signed_url_expires_at=_source_metadata_value(source_metadata, "signed_url_expires_at", "signedUrlExpiresAt"),
        ),
        target=DownloadTargetState.from_final_path(
            final_path=getattr(file_item, "download_path"),
            file_id=file_id,
            sidecar_path=sidecar_path,
        ),
        expected=DownloadExpectedState(
            size=_non_negative_int(getattr(file_item, "size", 0), "expected.size"),
            checksum=getattr(file_item, "checksum", ""),
        ),
        transfer=DownloadTransferState(
            state=transfer_state,
            received_bytes=_non_negative_int(received_bytes, "transfer.receivedBytes"),
            retry_count=_non_negative_int(retry_count, "transfer.retryCount"),
            last_failure_class=last_failure_class,
            last_updated_at=last_updated_at or utc_now_iso(),
        ),
    )


def save_resume_sidecar_for_download_item(
        file_item,
        source_url: str | None,
        bookkeeping_dir: str | Path,
        **kwargs) -> DownloadFileRecord:
    store = DownloadStateStore.from_bookkeeping_dir(bookkeeping_dir)
    record = build_resume_sidecar_record_for_download_item(
        file_item,
        source_url,
        bookkeeping_dir=bookkeeping_dir,
        **kwargs,
    )
    store.save_file(record)
    return record


def _safe_http_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value or "\r" in value or "\n" in value:
        return None
    return value


def conditional_headers_for_source(source: DownloadSourceState) -> tuple[str, ...]:
    etag = _safe_http_header_value(source.etag)
    if etag and not etag.startswith("W/"):
        return (f"If-Match: {etag}",)
    last_modified = _safe_http_header_value(source.last_modified)
    if last_modified:
        return (f"If-Unmodified-Since: {last_modified}",)
    return ()


def _expected_matches_download_item(record: DownloadFileRecord, file_item) -> bool:
    expected_size = _non_negative_int(getattr(file_item, "size", 0), "expected.size")
    expected_checksum = getattr(file_item, "checksum", "")
    return (
        record.file_id == file_id_for_download_item(file_item)
        and record.expected.size == expected_size
        and record.expected.checksum.lower() == expected_checksum.lower()
    )


def _source_matches_url(record: DownloadFileRecord, source_url: str | None) -> bool:
    return (
        record.source.url_redacted == redact_url_for_state(source_url)
        and record.source.object_key == object_key_from_url(source_url)
    )


def parse_expiration_datetime(expires_at: Any) -> datetime | None:
    if expires_at is None:
        return None
    if isinstance(expires_at, (int, float)):
        try:
            return datetime.fromtimestamp(float(expires_at), timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    expires_at = str(expires_at).strip()
    if not expires_at:
        return None
    try:
        return datetime.fromtimestamp(float(expires_at), timezone.utc)
    except (OSError, OverflowError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(expires_at)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def has_sufficient_signed_url_ttl(
        signed_url_expires_at: Any,
        min_ttl_seconds: int = 300,
        now: datetime | None = None) -> bool:
    expiration = parse_expiration_datetime(signed_url_expires_at)
    if expiration is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    min_ttl_seconds = max(0, int(min_ttl_seconds or 0))
    return expiration > now.astimezone(timezone.utc) + timedelta(seconds=min_ttl_seconds)


def validated_hosts_from_base_url(base_url: str | None) -> list[str]:
    """Return a single-host validated list derived from a base URL.

    Used when ``DOWNLOAD_RESUME_VALIDATED_HOSTS`` is left empty so the
    resume-capability check follows whatever CDN host Central passes in
    via ``BASE_LINKS_URL`` for this install. Returns ``[]`` when the URL
    is empty or unparseable.
    """
    if not base_url:
        return []
    try:
        host = urlsplit(str(base_url).strip()).hostname or ""
    except Exception:
        return []
    host = host.strip().lower()
    return [host] if host else []


def resolve_validated_hosts(
        configured: tuple[str, ...] | list[str],
        base_url_fallback: str | None) -> list[str]:
    """Return ``configured`` if non-empty, else derive from ``base_url_fallback``."""
    explicit = [str(host).strip() for host in (configured or ()) if str(host).strip()]
    if explicit:
        return explicit
    return validated_hosts_from_base_url(base_url_fallback)


def url_matches_resume_capability(
        source_url: str | None,
        validated_hosts: tuple[str, ...] | list[str] = (),
        validated_path_prefixes: tuple[str, ...] | list[str] = ()) -> bool:
    if not source_url or not validated_hosts:
        return False
    split_url = urlsplit(redact_url_for_state(source_url) or "")
    if split_url.scheme not in ("http", "https"):
        return False

    allowed_hosts = {str(host).strip().lower() for host in validated_hosts if str(host).strip()}
    source_host = (split_url.hostname or "").lower()
    source_netloc = split_url.netloc.lower()
    if source_host not in allowed_hosts and source_netloc not in allowed_hosts:
        return False

    prefixes = tuple(str(prefix) for prefix in validated_path_prefixes if str(prefix))
    return not prefixes or any(split_url.path.startswith(prefix) for prefix in prefixes)


def resume_decision_for_download_item(
        file_item,
        source_url: str | None,
        bookkeeping_dir: str | Path | None,
        resume_enabled: bool = False,
        validated_hosts: tuple[str, ...] | list[str] = (),
        validated_path_prefixes: tuple[str, ...] | list[str] = (),
        require_conditional: bool = True,
        signed_url_min_ttl_seconds: int = 300) -> DownloadResumeDecision:
    if not resume_enabled:
        return DownloadResumeDecision(False, "resume_disabled")
    if not bookkeeping_dir:
        return DownloadResumeDecision(False, "missing_bookkeeping_dir")
    if not url_matches_resume_capability(source_url, validated_hosts, validated_path_prefixes):
        return DownloadResumeDecision(False, "endpoint_not_resume_validated")

    temp_path = temp_path_for_download_item(file_item)
    received_bytes = existing_file_size(temp_path)
    if received_bytes <= 0:
        return DownloadResumeDecision(False, "missing_partial_temp")

    expected_size = _non_negative_int(getattr(file_item, "size", 0), "expected.size")
    if received_bytes >= expected_size:
        return DownloadResumeDecision(False, "partial_not_appendable")

    try:
        record = load_resume_sidecar_for_download_item(file_item, bookkeeping_dir)
    except (OSError, json.JSONDecodeError, DownloadStateSchemaError, ValueError):
        return DownloadResumeDecision(False, "sidecar_unusable")
    if record is None:
        return DownloadResumeDecision(False, "sidecar_missing")
    if not _expected_matches_download_item(record, file_item):
        return DownloadResumeDecision(False, "expected_identity_mismatch", record=record)
    if not _source_matches_url(record, source_url):
        return DownloadResumeDecision(False, "source_identity_mismatch", record=record)
    if record.source.signed_url_expires_at and not has_sufficient_signed_url_ttl(
            record.source.signed_url_expires_at,
            min_ttl_seconds=signed_url_min_ttl_seconds):
        return DownloadResumeDecision(False, "signed_url_expired_or_expiring", record=record)

    conditional_headers = conditional_headers_for_source(record.source)
    if require_conditional and not conditional_headers:
        return DownloadResumeDecision(False, "conditional_validator_missing", record=record)

    return DownloadResumeDecision(
        True,
        "resume_eligible",
        resume_from_byte=received_bytes,
        conditional_headers=conditional_headers,
        record=record,
    )
