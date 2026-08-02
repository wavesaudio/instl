#!/usr/bin/env python3.12

"""Tests for the batched resume-sidecar journal in ``DownloadStateStore``.

One JSON file per download item cost a write + flush + fsync + atomic replace each,
and ``PrepareDownloadTempFiles`` writes one per item before a single byte is
transferred. The journal takes one fsync for that whole pass.

The contract this pins is durability, not speed: nothing writes a sidecar during the
curl transfer, so the pre-download pass is what makes resume-after-interrupt work at
all. It may be batched, never skipped. Covered here: a clean pass, resume after a
mid-transfer kill, resume from a fresh process, a torn journal, a schema-version
mismatch, journal-without-part, part-without-journal, and the per-file layout an
older instl left behind.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

from pyinstl.downloadState import (  # noqa: E402
    DOWNLOAD_STATE_SCHEMA_VERSION,
    DownloadFileState,
    DownloadStateSchemaError,
    DownloadStateStore,
    build_resume_sidecar_record_for_download_item,
    file_id_for_download_item,
    reset_store_cache,
    resume_decision_for_download_item,
    save_resume_sidecar_for_download_item,
    save_resume_sidecar_records,
    store_for_bookkeeping_dir,
    temp_path_for_download_item,
    write_json_atomic,
)
from pyinstl.test.test_downloadState import FakeDownloadItem  # noqa: E402


SOURCE_URL = "https://cdn.example.com/V16/Products/Foo{index}.pkg"


class TestResumeJournal(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bookkeeping_dir = Path(self.temp_dir.name, "bookkeeping")
        # the store keeps the journal in memory per process; every case here stands for
        # its own instl run
        reset_store_cache()
        self.addCleanup(reset_store_cache)

    # --- helpers ----------------------------------------------------------

    def make_item(self, index=0, size=100):
        return FakeDownloadItem(
            path=f"Products/Foo{index}.pkg",
            revision=7,
            checksum=f"checksum{index}",
            size=size,
            download_path=os.path.join(self.temp_dir.name, "Products", f"Foo{index}.pkg"),
        )

    def write_partial(self, item, num_bytes):
        temp_path = temp_path_for_download_item(item)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(b"x" * num_bytes)
        return temp_path

    def prepare_pass(self, items, transfer_state=DownloadFileState.QUEUED):
        """What PrepareDownloadTempFiles does: build a record per item, write once."""
        records = [
            build_resume_sidecar_record_for_download_item(
                item,
                SOURCE_URL.format(index=index),
                bookkeeping_dir=self.bookkeeping_dir,
                session_id="session-1",
                transfer_state=transfer_state,
                source_metadata={"etag": f'"etag-{index}"'},
            )
            for index, item in enumerate(items)
        ]
        save_resume_sidecar_records(records, self.bookkeeping_dir, replace=True)
        return records

    def decision_for(self, item, index=0):
        return resume_decision_for_download_item(
            item,
            SOURCE_URL.format(index=index),
            self.bookkeeping_dir,
            resume_enabled=True,
            validated_hosts=["cdn.example.com"],
            validated_path_prefixes=["/V16/"],
        )

    def journal_path(self):
        return DownloadStateStore.from_bookkeeping_dir(self.bookkeeping_dir).journal_path()

    # --- a clean pass -----------------------------------------------------

    def test_whole_pass_lands_in_one_journal(self):
        items = [self.make_item(i) for i in range(20)]
        self.prepare_pass(items)

        lines = self.journal_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(20, len(lines))
        self.assertFalse(
            DownloadStateStore.from_bookkeeping_dir(self.bookkeeping_dir).files_dir.exists(),
            "the batched pass must not fall back to one file per item")

        store = store_for_bookkeeping_dir(self.bookkeeping_dir)
        for item in items:
            self.assertIsNotNone(store.load_file(file_id_for_download_item(item)))

    def test_a_later_pass_compacts_away_the_previous_session(self):
        stale = [self.make_item(i) for i in range(5)]
        self.prepare_pass(stale)
        fresh = [self.make_item(i + 100) for i in range(2)]
        self.prepare_pass(fresh)

        lines = self.journal_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(2, len(lines))
        reset_store_cache()
        store = store_for_bookkeeping_dir(self.bookkeeping_dir)
        self.assertIsNone(store.load_file(file_id_for_download_item(stale[0])))
        self.assertIsNotNone(store.load_file(file_id_for_download_item(fresh[0])))

    def test_single_saves_append_without_losing_the_pass(self):
        items = [self.make_item(i) for i in range(3)]
        self.prepare_pass(items)
        save_resume_sidecar_for_download_item(
            items[1], SOURCE_URL.format(index=1), self.bookkeeping_dir,
            session_id="session-1", transfer_state=DownloadFileState.FAILED_RETRYABLE,
            retry_count=2)

        reset_store_cache()
        store = store_for_bookkeeping_dir(self.bookkeeping_dir)
        updated = store.load_file(file_id_for_download_item(items[1]))
        self.assertEqual(DownloadFileState.FAILED_RETRYABLE, updated.transfer.state)
        self.assertEqual(2, updated.transfer.retry_count)
        # the other two are untouched
        self.assertEqual(DownloadFileState.QUEUED,
                         store.load_file(file_id_for_download_item(items[0])).transfer.state)

    # --- resume after an interruption -------------------------------------

    def test_resume_after_mid_transfer_kill(self):
        item = self.make_item()
        self.prepare_pass([item])
        self.write_partial(item, 42)  # curl got this far before the kill

        decision = self.decision_for(item)

        self.assertTrue(decision.can_resume)
        self.assertEqual(42, decision.resume_from_byte)
        self.assertEqual(('If-Match: "etag-0"',), decision.conditional_headers)

    def test_resume_after_a_full_process_kill(self):
        item = self.make_item()
        self.prepare_pass([item])
        self.write_partial(item, 64)
        reset_store_cache()  # nothing survives in memory across processes

        decision = self.decision_for(item)

        self.assertTrue(decision.can_resume)
        self.assertEqual(64, decision.resume_from_byte)

    def test_journal_without_a_partial_does_not_resume(self):
        item = self.make_item()
        self.prepare_pass([item])

        decision = self.decision_for(item)

        self.assertFalse(decision.can_resume)
        self.assertEqual("missing_partial_temp", decision.reason)

    def test_partial_without_a_journal_does_not_resume(self):
        item = self.make_item()
        self.write_partial(item, 42)

        decision = self.decision_for(item)

        self.assertFalse(decision.can_resume)
        self.assertEqual("sidecar_missing", decision.reason)

    # --- damaged journals -------------------------------------------------

    def test_a_torn_last_append_costs_only_that_record(self):
        items = [self.make_item(i) for i in range(3)]
        self.prepare_pass(items)
        with open(self.journal_path(), "r+", encoding="utf-8") as fd:
            text = fd.read()
            fd.seek(0)
            fd.truncate()
            # keep the first two lines whole, cut the third mid-object
            head, _, tail = text.rstrip("\n").rpartition("\n")
            fd.write(head + "\n" + tail[:len(tail) // 2])

        reset_store_cache()
        store = store_for_bookkeeping_dir(self.bookkeeping_dir)
        self.assertIsNotNone(store.load_file(file_id_for_download_item(items[0])))
        self.assertIsNotNone(store.load_file(file_id_for_download_item(items[1])))
        self.assertIsNone(store.load_file(file_id_for_download_item(items[2])))

    def test_a_garbage_journal_reads_as_no_resume_state(self):
        item = self.make_item()
        self.prepare_pass([item])
        self.write_partial(item, 42)
        self.journal_path().write_text("this is not json at all\n", encoding="utf-8")

        reset_store_cache()
        decision = self.decision_for(item)

        self.assertFalse(decision.can_resume)
        self.assertEqual("sidecar_missing", decision.reason)

    def test_a_schema_version_mismatch_is_reported_not_guessed(self):
        item = self.make_item()
        records = self.prepare_pass([item])
        record_data = records[0].to_dict()
        record_data["schemaVersion"] = DOWNLOAD_STATE_SCHEMA_VERSION + 1
        self.journal_path().write_text(json.dumps(record_data, sort_keys=True) + "\n",
                                       encoding="utf-8")

        reset_store_cache()
        store = store_for_bookkeeping_dir(self.bookkeeping_dir)
        with self.assertRaises(DownloadStateSchemaError):
            store.load_file(file_id_for_download_item(item))

        # the decision path swallows it into a plain "do not resume"
        self.write_partial(item, 42)
        reset_store_cache()
        decision = self.decision_for(item)
        self.assertFalse(decision.can_resume)
        self.assertEqual("sidecar_unusable", decision.reason)

    # --- promotion survives a transient sharing violation ------------------

    def test_promote_retries_a_file_held_by_another_process(self):
        # Windows answers os.replace on a held file with a sharing violation instead
        # of waiting; a scanner touching a just-hashed .part must not fail the install
        from pyinstl import downloadState

        item = self.make_item()
        temp_path = self.write_partial(item, 10)
        attempts = []
        real_replace = os.replace

        def flaky_replace(src, dst):
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError(32, "The process cannot access the file")
            return real_replace(src, dst)

        with mock.patch.object(downloadState.os, "replace", side_effect=flaky_replace), \
                mock.patch.object(downloadState.time, "sleep"):
            downloadState.promote_temp_file(temp_path, item.download_path)

        self.assertEqual(3, len(attempts))
        self.assertTrue(Path(item.download_path).is_file())
        self.assertFalse(temp_path.exists())

    def test_promote_gives_up_and_reports_a_file_held_for_good(self):
        from pyinstl import downloadState

        item = self.make_item()
        temp_path = self.write_partial(item, 10)
        with mock.patch.object(downloadState.os, "replace",
                               side_effect=PermissionError(32, "held")), \
                mock.patch.object(downloadState.time, "sleep"):
            with self.assertRaises(PermissionError):
                downloadState.promote_temp_file(temp_path, item.download_path)

    # --- the layout an older instl left behind ----------------------------

    def test_a_pre_journal_bookkeeping_dir_is_still_resumable(self):
        item = self.make_item()
        record = build_resume_sidecar_record_for_download_item(
            item, SOURCE_URL.format(index=0),
            bookkeeping_dir=self.bookkeeping_dir,
            session_id="session-0",
            transfer_state=DownloadFileState.INTERRUPTED,
            source_metadata={"etag": '"etag-0"'},
        )
        store = DownloadStateStore.from_bookkeeping_dir(self.bookkeeping_dir)
        write_json_atomic(store.file_path(record.file_id), record.to_dict())
        self.write_partial(item, 42)

        reset_store_cache()
        decision = self.decision_for(item)

        self.assertTrue(decision.can_resume)
        self.assertEqual(42, decision.resume_from_byte)


if __name__ == "__main__":
    unittest.main(verbosity=3)
