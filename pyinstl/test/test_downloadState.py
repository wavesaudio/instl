#!/usr/bin/env python3.12

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from downloadState import (
    DOWNLOAD_STATE_SCHEMA_VERSION,
    DownloadExpectedState,
    DownloadFileRecord,
    DownloadFileState,
    DownloadSessionRecord,
    DownloadSessionState,
    DownloadSourceState,
    DownloadStateSchemaError,
    DownloadStateStore,
    DownloadTargetState,
    DownloadTransferState,
    build_resume_sidecar_record_for_download_item,
    checksum_matches,
    file_id_for_download_item,
    make_file_id,
    promote_verified_temp_file,
    redact_url_for_state,
    remove_stale_temp_for_download_item,
    resume_decision_for_download_item,
    save_resume_sidecar_for_download_item,
    temp_path_for_final_path,
    temp_path_for_download_item,
)


class FakeDownloadItem:
    def __init__(self, path, revision, checksum, size, download_path):
        self.path = path
        self.revision = revision
        self.checksum = checksum
        self.size = size
        self.download_path = download_path


class TestDownloadState(unittest.TestCase):
    def test_redact_url_for_state_removes_signed_query_and_fragment(self):
        signed_url = "https://cdn.example.com/path/pkg.zip?Policy=secret&Signature=sig#token"

        self.assertEqual(
            redact_url_for_state(signed_url),
            "https://cdn.example.com/path/pkg.zip",
        )

    def test_make_file_id_is_stable_and_ignores_source_url_auth(self):
        first_id = make_file_id("Products/Foo.pkg", "sha1:abc", 1234, repository_revision=4321)
        second_id = make_file_id("Products/Foo.pkg", "sha1:abc", 1234, repository_revision=4321)
        different_revision_id = make_file_id("Products/Foo.pkg", "sha1:abc", 1234, repository_revision=4322)

        self.assertEqual(first_id, second_id)
        self.assertNotEqual(first_id, different_revision_id)
        self.assertEqual(len(first_id), 64)

    def test_temp_path_for_final_path_includes_stable_file_id_prefix(self):
        file_id = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

        self.assertEqual(
            temp_path_for_final_path("/cache/Products/Foo.pkg", file_id).as_posix(),
            "/cache/Products/Foo.pkg.instl-1234567890abcdef.part",
        )

    def test_download_target_can_be_created_from_final_path(self):
        file_id = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

        target = DownloadTargetState.from_final_path("/cache/Foo.pkg", file_id)

        self.assertEqual(target.final_path, "/cache/Foo.pkg")
        self.assertEqual(target.temp_path, "/cache/Foo.pkg.instl-abcdef1234567890.part")

    def test_download_item_temp_path_uses_manifest_identity(self):
        item = FakeDownloadItem(
            path="Products/Foo.pkg",
            revision=7,
            checksum="abc123",
            size=100,
            download_path="/cache/Products/Foo.pkg",
        )
        expected_file_id = make_file_id("Products/Foo.pkg", "abc123", 100, repository_revision=7)

        self.assertEqual(file_id_for_download_item(item), expected_file_id)
        self.assertEqual(
            temp_path_for_download_item(item).as_posix(),
            f"/cache/Products/Foo.pkg.instl-{expected_file_id[:16]}.part",
        )

    def test_promote_verified_temp_file_checks_checksum_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = Path(temp_dir, "cache", "Foo.pkg")
            temp_path = Path(f"{final_path}.instl-1234567890abcdef.part")
            payload = b"verified payload"
            checksum = "b7c500ca2bd3ab91ce5ee2a8553dd70a144dd7a3"
            final_path.parent.mkdir(parents=True, exist_ok=True)
            final_path.write_bytes(b"old payload")
            temp_path.write_bytes(payload)

            promoted_checksum = promote_verified_temp_file(temp_path, final_path, checksum)

            self.assertEqual(promoted_checksum, checksum)
            self.assertEqual(final_path.read_bytes(), payload)
            self.assertFalse(temp_path.exists())
            self.assertTrue(checksum_matches(final_path, checksum))

    def test_promote_verified_temp_file_rejects_bad_checksum_without_replacing_final(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            final_path = Path(temp_dir, "cache", "Foo.pkg")
            temp_path = Path(f"{final_path}.instl-1234567890abcdef.part")
            final_path.parent.mkdir(parents=True, exist_ok=True)
            final_path.write_bytes(b"old payload")
            temp_path.write_bytes(b"wrong payload")

            with self.assertRaises(ValueError):
                promote_verified_temp_file(temp_path, final_path, "b7c500ca2bd3ab91ce5ee2a8553dd70a144dd7a3")

            self.assertEqual(final_path.read_bytes(), b"old payload")
            self.assertTrue(temp_path.exists())

    def test_remove_stale_temp_for_download_item(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            temp_path = temp_path_for_download_item(item)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"stale partial")

            self.assertTrue(remove_stale_temp_for_download_item(item))
            self.assertFalse(temp_path.exists())
            self.assertFalse(remove_stale_temp_for_download_item(item))

    def test_resume_sidecar_record_captures_partial_identity_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            temp_path = temp_path_for_download_item(item)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"partial payload")
            bookkeeping_dir = Path(temp_dir, "bookkeeping")

            record = build_resume_sidecar_record_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg?Signature=secret",
                bookkeeping_dir=bookkeeping_dir,
                session_id="session-1",
                repository_major_version=16,
                transfer_state=DownloadFileState.INTERRUPTED,
                source_metadata={
                    "etag": '"etag-1"',
                    "lastModified": "Wed, 06 May 2026 10:00:00 GMT",
                    "contentLength": 100,
                    "versionId": "version-1",
                },
            )

            self.assertEqual(record.session_id, "session-1")
            self.assertEqual(record.repo_path, "Products/Foo.pkg")
            self.assertEqual(record.repository_revision, 7)
            self.assertEqual(record.source.url_redacted, "https://cdn.example.com/V16/Products/Foo.pkg")
            self.assertEqual(record.source.object_key, "V16/Products/Foo.pkg")
            self.assertEqual(record.source.etag, '"etag-1"')
            self.assertEqual(record.source.last_modified, "Wed, 06 May 2026 10:00:00 GMT")
            self.assertEqual(record.source.content_length, 100)
            self.assertEqual(record.source.version_id, "version-1")
            self.assertEqual(record.target.final_path, item.download_path)
            self.assertEqual(record.target.temp_path, os.fspath(temp_path))
            self.assertEqual(record.target.sidecar_path, os.fspath(DownloadStateStore.from_bookkeeping_dir(bookkeeping_dir).file_path(record.file_id)))
            self.assertEqual(record.expected.size, 100)
            self.assertEqual(record.expected.checksum, "abc123")
            self.assertEqual(record.transfer.state, DownloadFileState.INTERRUPTED)
            self.assertEqual(record.transfer.received_bytes, len(b"partial payload"))

    def test_resume_sidecar_is_saved_atomically_in_download_state_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            bookkeeping_dir = Path(temp_dir, "bookkeeping")

            record = save_resume_sidecar_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg?Policy=secret",
                bookkeeping_dir,
                session_id="session-1",
            )
            loaded = DownloadStateStore.from_bookkeeping_dir(bookkeeping_dir).load_file(record.file_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.file_id, record.file_id)
            self.assertEqual(loaded.source.url_redacted, "https://cdn.example.com/V16/Products/Foo.pkg")
            self.assertEqual(loaded.transfer.state, DownloadFileState.QUEUED)
            self.assertEqual(loaded.transfer.received_bytes, 0)

    def test_resume_decision_requires_validated_endpoint_and_conditional_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            temp_path = temp_path_for_download_item(item)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"x" * 42)
            bookkeeping_dir = Path(temp_dir, "bookkeeping")
            save_resume_sidecar_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg?Signature=secret",
                bookkeeping_dir,
                session_id="session-1",
                transfer_state=DownloadFileState.INTERRUPTED,
                source_metadata={"etag": '"etag-1"', "contentLength": 100},
            )

            decision = resume_decision_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg?Signature=fresh",
                bookkeeping_dir,
                resume_enabled=True,
                validated_hosts=["cdn.example.com"],
                validated_path_prefixes=["/V16/"],
            )

            self.assertTrue(decision.can_resume)
            self.assertEqual(decision.resume_from_byte, 42)
            self.assertEqual(decision.conditional_headers, ('If-Match: "etag-1"',))

    def test_resume_decision_rejects_unknown_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            temp_path = temp_path_for_download_item(item)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"x" * 42)
            bookkeeping_dir = Path(temp_dir, "bookkeeping")
            save_resume_sidecar_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg",
                bookkeeping_dir,
                source_metadata={"etag": '"etag-1"'},
            )

            decision = resume_decision_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg",
                bookkeeping_dir,
                resume_enabled=True,
                validated_hosts=["other.example.com"],
                validated_path_prefixes=["/V16/"],
            )

            self.assertFalse(decision.can_resume)
            self.assertEqual(decision.reason, "endpoint_not_resume_validated")

    def test_resume_decision_rejects_source_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            temp_path = temp_path_for_download_item(item)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"x" * 42)
            bookkeeping_dir = Path(temp_dir, "bookkeeping")
            save_resume_sidecar_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg",
                bookkeeping_dir,
                source_metadata={"etag": '"etag-1"'},
            )

            decision = resume_decision_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Changed.pkg",
                bookkeeping_dir,
                resume_enabled=True,
                validated_hosts=["cdn.example.com"],
                validated_path_prefixes=["/V16/"],
            )

            self.assertFalse(decision.can_resume)
            self.assertEqual(decision.reason, "source_identity_mismatch")

    def test_resume_decision_rejects_expired_signed_url_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            temp_path = temp_path_for_download_item(item)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"x" * 42)
            bookkeeping_dir = Path(temp_dir, "bookkeeping")
            expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            save_resume_sidecar_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg",
                bookkeeping_dir,
                source_metadata={
                    "etag": '"etag-1"',
                    "signedUrlExpiresAt": expired_at.isoformat().replace("+00:00", "Z"),
                },
            )

            decision = resume_decision_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg",
                bookkeeping_dir,
                resume_enabled=True,
                validated_hosts=["cdn.example.com"],
                validated_path_prefixes=["/V16/"],
            )

            self.assertFalse(decision.can_resume)
            self.assertEqual(decision.reason, "signed_url_expired_or_expiring")

    def test_resume_decision_allows_unexpired_signed_url_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            item = FakeDownloadItem(
                path="Products/Foo.pkg",
                revision=7,
                checksum="abc123",
                size=100,
                download_path=os.path.join(temp_dir, "Products", "Foo.pkg"),
            )
            temp_path = temp_path_for_download_item(item)
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(b"x" * 42)
            bookkeeping_dir = Path(temp_dir, "bookkeeping")
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
            save_resume_sidecar_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg",
                bookkeeping_dir,
                source_metadata={
                    "etag": '"etag-1"',
                    "signedUrlExpiresAt": expires_at.isoformat().replace("+00:00", "Z"),
                },
            )

            decision = resume_decision_for_download_item(
                item,
                "https://cdn.example.com/V16/Products/Foo.pkg",
                bookkeeping_dir,
                resume_enabled=True,
                validated_hosts=["cdn.example.com"],
                validated_path_prefixes=["/V16/"],
                signed_url_min_ttl_seconds=300,
            )

            self.assertTrue(decision.can_resume)
            self.assertEqual(decision.resume_from_byte, 42)

    def test_session_record_round_trip(self):
        session_record = DownloadSessionRecord.new(
            session_id="session-1",
            state=DownloadSessionState.DOWNLOADING,
            action_id="install",
            repository_major_version=16,
            repository_revision=12345,
            sync_base_url_redacted="https://cdn.example.com/V16",
            local_repo_sync_dir="/cache",
            bookkeeping_dir="/cache/bookkeeping",
            planned_files=3,
            files_to_download=2,
            bytes_to_download=42,
        )

        round_tripped = DownloadSessionRecord.from_dict(session_record.to_dict())

        self.assertEqual(round_tripped.session_id, "session-1")
        self.assertEqual(round_tripped.state, DownloadSessionState.DOWNLOADING)
        self.assertEqual(round_tripped.repository_revision, 12345)
        self.assertEqual(round_tripped.bytes_to_download, 42)

    def test_file_record_round_trip(self):
        file_id = make_file_id("Products/Foo.pkg", "abc123", 100, repository_revision=7)
        file_record = DownloadFileRecord(
            session_id="session-1",
            file_id=file_id,
            repo_path="Products/Foo.pkg",
            repository_major_version=16,
            repository_revision=7,
            source=DownloadSourceState.from_url(
                "https://cdn.example.com/V16/Products/Foo.pkg?Signature=secret",
                etag='"etag-1"',
                last_modified="Wed, 06 May 2026 10:00:00 GMT",
                content_length=100,
            ),
            target=DownloadTargetState.from_final_path(
                final_path="/cache/Products/Foo.pkg",
                file_id=file_id,
                sidecar_path="/cache/bookkeeping/download-state/files/file.json",
            ),
            expected=DownloadExpectedState(size=100, checksum="abc123"),
            transfer=DownloadTransferState(
                state=DownloadFileState.INTERRUPTED,
                received_bytes=50,
                retry_count=1,
                last_failure_class="timeout_during_transfer",
                last_updated_at="2026-05-06T10:00:00Z",
            ),
        )

        round_tripped = DownloadFileRecord.from_dict(file_record.to_dict())

        self.assertEqual(round_tripped.file_id, file_id)
        self.assertEqual(round_tripped.source.url_redacted, "https://cdn.example.com/V16/Products/Foo.pkg")
        self.assertEqual(round_tripped.source.object_key, "V16/Products/Foo.pkg")
        self.assertEqual(round_tripped.expected.checksum_algorithm, "sha1")
        self.assertEqual(round_tripped.transfer.state, DownloadFileState.INTERRUPTED)

    def test_rejects_unknown_schema_version(self):
        with self.assertRaises(DownloadStateSchemaError):
            DownloadSessionRecord.from_dict(
                {
                    "schemaVersion": DOWNLOAD_STATE_SCHEMA_VERSION + 1,
                    "sessionId": "session-1",
                    "state": "preparing",
                    "createdAt": "2026-05-06T10:00:00Z",
                    "updatedAt": "2026-05-06T10:00:00Z",
                }
            )

    def test_rejects_unknown_file_state(self):
        with self.assertRaises(DownloadStateSchemaError):
            DownloadTransferState.from_dict({"state": "almost_done"})

    def test_store_saves_and_loads_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DownloadStateStore.from_bookkeeping_dir(Path(temp_dir, "bookkeeping"))
            session_record = DownloadSessionRecord.new(session_id="session-1")
            file_id = make_file_id("Products/Foo.pkg", "abc123", 100, repository_revision=7)
            file_record = DownloadFileRecord(
                session_id="session-1",
                file_id=file_id,
                repo_path="Products/Foo.pkg",
                repository_revision=7,
                source=DownloadSourceState.from_url("https://cdn.example.com/Products/Foo.pkg"),
                target=DownloadTargetState.from_final_path(os.path.join(temp_dir, "Foo.pkg"), file_id),
                expected=DownloadExpectedState(size=100, checksum="abc123"),
                transfer=DownloadTransferState(state=DownloadFileState.QUEUED),
            )

            store.save_session(session_record)
            store.save_file(file_record)

            self.assertEqual(store.load_session().session_id, "session-1")
            self.assertEqual(store.load_file(file_record.file_id).repo_path, "Products/Foo.pkg")

            with open(store.file_path(file_record.file_id), encoding="utf-8") as rfd:
                raw_json = json.load(rfd)
            self.assertEqual(raw_json["source"]["urlRedacted"], "https://cdn.example.com/Products/Foo.pkg")

    def test_missing_records_return_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DownloadStateStore(temp_dir)

            self.assertIsNone(store.load_session())
            self.assertIsNone(store.load_file("missing"))


if __name__ == "__main__":
    unittest.main(verbosity=3)
