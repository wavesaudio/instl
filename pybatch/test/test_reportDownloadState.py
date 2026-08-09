#!/usr/bin/env python3.12

""" Tests for the ReportDownloadState pybatch command and the copy-phase byte
    funnel it arms.

    ReportDownloadState is a pybatch command, so the first thing that has to hold
    is the dual-identity contract: its __repr__ must eval back to an equal object.
    A mismatch there silently corrupts the generated batch script rather than
    failing loudly.

    The rest is instrumentation, which must move the state machine and report
    bytes without ever being able to break a copy.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pybatch import *
from pybatch import ReportDownloadState, CopyFileToFile
import pybatch.copyPhaseProgress as cpp
import pyinstl.downloadEvents as downloadEvents

current_os_names = utils.get_current_os_names()
config_vars["__CURRENT_OS_NAMES__"] = current_os_names


class TestReportDownloadStateRepr(unittest.TestCase):
    def test_repr_round_trips(self):
        obj = ReportDownloadState("verifying_downloads", reason="checksum_verify",
                                  own_progress_count=0, report_own_progress=False)
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, obj.explain_diff(obj_recreated))

    def test_repr_round_trips_with_phase_bytes(self):
        obj = ReportDownloadState("copying", reason="copy_started", phase_bytes_planned=5000,
                                  own_progress_count=0, report_own_progress=False)
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, obj.explain_diff(obj_recreated))


class TestReportDownloadStateEmits(unittest.TestCase):
    def test_emits_the_requested_transition(self):
        with mock.patch.object(downloadEvents, "emit_session_state") as emit:
            ReportDownloadState("copying", reason="copy_started",
                                own_progress_count=0, report_own_progress=False)()
        emit.assert_called_once()
        self.assertEqual(emit.call_args.kwargs["state"], "copying")
        self.assertEqual(emit.call_args.kwargs["reason"], "copy_started")

    def test_never_raises(self):
        # instrumentation must not be able to break a sync or copy run
        with mock.patch.object(downloadEvents, "emit_session_state",
                               side_effect=RuntimeError("emit failed")):
            ReportDownloadState("completed", own_progress_count=0,
                                report_own_progress=False)()  # must not raise

    def test_copying_arms_the_copy_phase(self):
        with mock.patch.object(downloadEvents, "emit_session_state"), \
                mock.patch.object(cpp, "begin_copy_phase") as begin:
            ReportDownloadState("copying", reason="copy_started", phase_bytes_planned=5000,
                                own_progress_count=0, report_own_progress=False)()
        begin.assert_called_once()
        self.assertEqual(begin.call_args.args[0], 5000)


class TestCopyPhaseByteFunnel(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(cpp.begin_copy_phase, 0)  # disarm whatever a test armed

    def test_copy_file_to_file_reports_bytes_when_armed(self):
        src = Path(self.temp_dir.name, "src.bin")
        dst = Path(self.temp_dir.name, "dst.bin")
        src.write_bytes(b"x" * 1234)
        cpp.begin_copy_phase(10000, session_id="s")
        with mock.patch.object(downloadEvents, "emit_session_state") as emit:
            CopyFileToFile(src, dst, report_own_progress=False)()
        self.assertTrue(dst.exists())
        copy_calls = [c.kwargs for c in emit.call_args_list if c.kwargs.get("state") == "copying"]
        self.assertTrue(copy_calls, "expected a copying tick from the copy funnel")
        self.assertEqual(copy_calls[-1]["phase_bytes_done"], 1234)

    def test_no_ticks_when_the_phase_was_never_armed(self):
        src = Path(self.temp_dir.name, "src2.bin")
        dst = Path(self.temp_dir.name, "dst2.bin")
        src.write_bytes(b"y" * 10)
        cpp.begin_copy_phase(0)
        with mock.patch.object(downloadEvents, "emit_session_state") as emit:
            CopyFileToFile(src, dst, report_own_progress=False)()
        self.assertTrue(dst.exists())
        self.assertEqual([c for c in emit.call_args_list
                          if c.kwargs.get("state") == "copying"], [])


if __name__ == "__main__":
    unittest.main(verbosity=3)
