#!/usr/bin/env python3.12

"""CHARACTERIZATION (golden/snapshot) tests for the pybatch serialization backbone.

These tests LOCK the current ``repr()`` -> ``eval()`` model that underpins how
``instl`` serializes a batch of ``PythonBatchCommand`` objects to an executable
``.py`` file and re-materializes them. They are intentionally:

  * OFFLINE / hermetic - no network, no svn repo, no filesystem side effects.
  * Deterministic - the golden strings below are exact snapshots of the
    current canonical ``repr()`` form. Any change to the serialization contract
    will flip a snapshot and force an explicit, reviewed decision.

Style/fixtures follow the existing pybatch test suite: we reuse the
``reprs_test_runner`` helper from ``pybatch/test/test_PythonBatchBase.py`` for
the repr -> eval round-trip (the same mechanism the real accumulator uses when
it writes and then ``exec()``s a batch file), and we add explicit golden
snapshots on top to pin the exact serialized text.

Download commands are deliberately EXCLUDED: their repr() carries live transfer
counters, so pinning it here would lock numbers that legitimately vary.
"""

import sys
import os
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))

import utils  # noqa: F401  do not remove, prevents cyclic import problems
from pybatch import *
from pybatch import PythonBatchCommandAccum
from pybatch.copyBatchCommands import RsyncClone
from configVar import config_vars

# Match the fixture used by the rest of the pybatch suite.
from pybatch.test.test_PythonBatchBase import TestPythonBatch

# Some commands resolve $(__CURRENT_OS_NAMES__) inside their repr (e.g. Chmod
# maps symbolic modes per-OS). The rest of the pybatch suite sets this at module
# import time; we mirror that so repr is well-defined and stable here too.
config_vars["__CURRENT_OS_NAMES__"] = utils.get_current_os_names()


# Commands whose repr is NOT a round-trippable constructor call: their repr is
# a bare statement (print(...), a comment, or a config_vars assignment) that
# evals to None rather than back to an equal object. These are pinned by exact
# snapshot only (matching how the existing reporting tests assert them).
NON_ROUND_TRIPPING = {"Echo", "Remark", "ConfigVarAssign_scalar", "ConfigVarAssign_list"}


def native_abs(*parts):
    """ An absolute path written the way the current platform writes it.
        Some commands (RmDir, the copy commands, RsyncClone) normalize their paths
        when building repr(), so a "/a/b" literal comes back as r"C:\\a\\b" on Windows:
        the snapshot could not match on both platforms, and repr()->eval() would not
        round-trip either (the object keeps the un-normalized path it was given).
    """
    return os.path.normpath(os.path.join("C:\\" if sys.platform == 'win32' else "/", *parts))


# Exact snapshots of the current canonical repr form for a representative
# set of (non-download) PythonBatchCommand objects. (name, factory, golden_repr)
# The factory is a 0-arg callable so each test/run constructs a fresh object.
GOLDEN_REPRS = [
    # --- remove commands ---
    ("RmFile", lambda: RmFile(r"/just/remove/me"),
     'RmFile(r"/just/remove/me")'),
    ("RmDir", lambda: RmDir(native_abs("just", "remove", "me")),
     f'RmDir(r"{native_abs("just", "remove", "me")}")'),
    ("RmGlob", lambda: RmGlob("/a/b", "*.tmp"),
     'RmGlob(r"/a/b", r"*.tmp")'),
    ("RemoveEmptyFolders", lambda: RemoveEmptyFolders("/a/b", files_to_ignore=[".DS_Store"]),
     'RemoveEmptyFolders(r"/a/b", files_to_ignore=[r".DS_Store"])'),
    # --- filesystem commands ---
    ("MakeDir", lambda: MakeDir("rumba"),
     'MakeDir(r"rumba")'),
    ("Touch", lambda: Touch("/f/g/h"),
     'Touch(r"/f/g/h")'),
    ("Cd", lambda: Cd("a/b/c"),
     'Cd(r"a/b/c")'),
    ("Chmod", lambda: Chmod("/a/b", "a+rw"),
     'Chmod(path=r"/a/b", mode="a+rw")'),
    # --- copy commands ---
    ("CopyFileToFile", lambda: CopyFileToFile(native_abs("from", "here"), native_abs("to", "there"), hard_links=False, copy_owner=True),
     f'CopyFileToFile(r"{native_abs("from", "here")}", r"{native_abs("to", "there")}", hard_links=False, copy_owner=True)'),
    ("CopyDirToDir", lambda: CopyDirToDir(native_abs("from"), native_abs("to"), hard_links=False),
     f'CopyDirToDir(r"{native_abs("from")}", r"{native_abs("to")}", hard_links=False)'),
    ("RsyncClone", lambda: RsyncClone(native_abs("from"), native_abs("to")),
     f'RsyncClone(r"{native_abs("from")}", r"{native_abs("to")}")'),
    # --- conditional commands ---
    # NB: use IsConfigVarEq (pure, no filesystem) as the If condition so repr
    # stays hermetic - IsFile/IsDir would stat the path during evaluation.
    ("If_IsConfigVarEq", lambda: If(IsConfigVarEq("FOO", "bar"), if_true=Touch("/c/d")),
     'If(IsConfigVarEq(r"FOO", r"bar"), if_true=Touch(r"/c/d"))'),
    ("IsConfigVarEq", lambda: IsConfigVarEq("FOO", "bar"),
     'IsConfigVarEq(r"FOO", r"bar")'),
    # --- reporting commands ---
    ("Stage", lambda: Stage("Tuti", "Fruti"),
     'Stage(r"Tuti", r"Fruti")'),
    ("Progress", lambda: Progress("Tuti", own_progress_count=17),
     'Progress(r"Tuti", own_progress_count=17)'),
    ("Echo", lambda: Echo("hi"),
     'print("hi")'),
    ("Remark", lambda: Remark("note"),
     '# note'),
    ("ConfigVarAssign_scalar", lambda: ConfigVarAssign("luli", "lu"),
     '''config_vars['luli'] = r"lu"'''),
    ("ConfigVarAssign_list", lambda: ConfigVarAssign("Algemene", "Bank", "Nederland"),
     '''config_vars['Algemene'] = (r"Bank", r"Nederland")'''),
    # --- wtar/wzip commands ---
    ("Wzip", lambda: Wzip("/a/b/c"),
     'Wzip(r"/a/b/c")'),
    # --- subprocess commands ---
    ("ShellCommand", lambda: ShellCommand("ls -l", message="listing"),
     'ShellCommand(r"ls -l", message=r"listing")'),
    ("Subprocess", lambda: Subprocess("/rik/ya/vik", message="sababa"),
     'Subprocess(r"/rik/ya/vik", message=r"sababa")'),
]


class TestPybatchSerializationGolden(unittest.TestCase):
    """Pins the repr/serialization contract of the pybatch backbone."""

    def __init__(self, which_test="runTest"):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        # Re-assert per-test (the configVar characterization tests clear
        # config_vars in their own setUp/tearDown, which would otherwise wipe
        # the module-level assignment and break repr of OS-aware commands).
        config_vars["__CURRENT_OS_NAMES__"] = utils.get_current_os_names()
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_golden_reprs_exact(self):
        """Snapshot: each command's repr matches its exact recorded golden string.

        This is the load-bearing serialization contract: the .py batch file that
        instl writes is literally a sequence of these repr() strings.
        """
        for name, factory, golden in GOLDEN_REPRS:
            with self.subTest(command=name):
                obj = factory()
                self.assertEqual(
                    repr(obj), golden,
                    f"{name}: repr() drifted from golden snapshot")

    def test_repr_round_trips_via_eval(self):
        """repr -> eval reconstructs an equal object (the accumulator's model).

        Uses the same ``reprs_test_runner`` round-trip helper the rest of the
        pybatch suite relies on, which is exactly what ``exec()``-ing a written
        batch file does at runtime.
        """
        round_tripping = [(name, factory) for name, factory, _golden in GOLDEN_REPRS
                          if name not in NON_ROUND_TRIPPING]
        objs = [factory() for _name, factory in round_tripping]
        remarks = [name for name, _factory in round_tripping]
        # reprs_test_runner asserts obj == eval(repr(obj)) for every object,
        # using each object's own explain_diff where available.
        self.pbt.reprs_test_runner(*objs, remark_list=remarks)

    def test_accum_serializes_to_executable_repr(self):
        """An accumulator of commands serializes to a compilable batch program.

        Locks the accumulator-level contract: ``repr(accum)`` produces source
        that ``compile()`` accepts and that contains each command's repr. This
        is the offline half of the write-then-exec pipeline (no command is
        executed here, so it stays hermetic).
        """
        config_vars["__MAIN_OUT_FILE__"] = os.fspath(
            self.pbt.path_inside_test_folder("accum_golden.py"))
        config_vars["__MAIN_COMMAND__"] = "characterization;"

        accum = PythonBatchCommandAccum()
        accum.set_current_section("doit")
        accum += MakeDir("rumba")
        accum += Touch("/f/g/h")
        accum += RmFile("/just/remove/me")
        accum += Echo("hi")

        accum_repr = repr(accum)
        # Must be valid, compilable Python (this is what instl writes to disk).
        compiled = compile(accum_repr, "<accum_golden>", "exec")
        self.assertIsNotNone(compiled)

        # The accumulator wraps the run in a PythonBatchRuntime and emits each
        # command inside its section, in context-manager form with an injected
        # prog_num kwarg. We pin these stable STRUCTURAL markers. We deliberately
        # do NOT snapshot:
        #   * the leading "Creation time" header (a timestamp), and
        #   * the concrete prog_num integers (they depend on process-global
        #     progress counters and therefore on test ordering),
        # so the test stays deterministic and order-independent.
        self.assertIn('with PythonBatchRuntime(r"characterization;"', accum_repr)
        self.assertIn('with Stage(r"doit"', accum_repr)
        # commands carry a prog_num kwarg and run as `with <cmd ...> as <name>:`
        self.assertIn('MakeDir(r"rumba", prog_num=', accum_repr)
        self.assertIn('Touch(r"/f/g/h", prog_num=', accum_repr)
        self.assertIn('RmFile(r"/just/remove/me", prog_num=', accum_repr)
        # Echo serializes to a bare print, not a context manager.
        self.assertIn('print("hi")', accum_repr)
        # the epilog section is always appended with timings patching.
        self.assertIn('with Stage(r"epilog"', accum_repr)


if __name__ == "__main__":
    unittest.main()
