#!/usr/bin/env python3.12

"""Tests for the installation-lifecycle state machine: its missing entry and its
missing failure exit.

The contract: a run reaches a terminal state whether it succeeds or fails, and no
state is declared that nothing ever emits. A declared-but-dead member is what made
the machine impossible to audit.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))

try:
    import pybatch.reportingBatchCommands as rbc
    FULL_STACK_IMPORT_ERROR = None
except Exception as ex:  # pragma: no cover - reported as a skip below
    FULL_STACK_IMPORT_ERROR = ex


@unittest.skipIf(FULL_STACK_IMPORT_ERROR is not None,
                 f"full instl dependencies unavailable: {FULL_STACK_IMPORT_ERROR}")
class TestStateMachineHasEntryAndExit(unittest.TestCase):
    def test_failed_is_emitted_for_a_failing_run(self):
        with mock.patch("pyinstl.downloadEvents.emit_download_state") as emit:
            rbc.PythonBatchRuntime.emit_failed_session_state(ValueError)
        emit.assert_called_once_with("failed", reason="ValueError")

    def test_failed_emit_never_breaks_the_error_path(self):
        with mock.patch("pyinstl.downloadEvents.emit_download_state",
                        side_effect=RuntimeError("no events")):
            rbc.PythonBatchRuntime.emit_failed_session_state(ValueError)  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=3)
