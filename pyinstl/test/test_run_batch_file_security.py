#!/usr/bin/env python3.12

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))
sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))

import utils
from configVar import config_vars
from pybatch import PythonBatchCommandAccum
from pyinstl.instlInstanceBase import InstlInstanceBase


class TestRunBatchFileSecurity(unittest.TestCase):

    @staticmethod
    def _expected_site_packages(venv_dir: Path) -> Path:
        if sys.platform == "win32":
            return venv_dir / "Lib" / "site-packages"
        py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        return venv_dir / "lib" / py_ver / "site-packages"

    def _make_instance(self, script_path: Path, expected_bytes: bytes) -> InstlInstanceBase:
        """Create a minimal InstlInstanceBase with valid script AND snapshot integrity metadata.

        All tests that reach the subprocess execution path require both the script and
        its sidecar snapshot to pass validation.  Tests that fail earlier (symlink check,
        script tamper check) are not affected because those checks precede the snapshot.
        """
        inst = object.__new__(InstlInstanceBase)
        inst.out_file_realpath = os.fspath(script_path)
        inst._batch_script_checksum = utils.get_buffer_checksum(expected_bytes)
        inst._batch_script_size = len(expected_bytes)

        # Create a minimal valid snapshot alongside the script so run_batch_file() can
        # validate it before launching the subprocess.
        snapshot_path = Path(os.fspath(script_path)).with_suffix('.snapshot.json')
        snapshot_bytes = b'{}'
        snapshot_path.write_bytes(snapshot_bytes)
        inst._snapshot_checksum = utils.get_buffer_checksum(snapshot_bytes)
        inst._snapshot_size = len(snapshot_bytes)

        return inst

    def test_tampering_is_detected_before_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            original = b"print('safe')\n"
            script_path.write_bytes(original)
            inst = self._make_instance(script_path, original)

            # Simulate a modification between write and run.
            script_path.write_bytes(b"print('tampered')\n")

            with mock.patch("subprocess.run") as mocked_run:
                with self.assertRaisesRegex(RuntimeError, "unexpectedly modified before execution"):
                    inst.run_batch_file()
                mocked_run.assert_not_called()

    def test_runs_in_isolated_python_subprocess(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)
            inst = self._make_instance(script_path, script_bytes)

            with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as mocked_run:
                inst.run_batch_file()

            mocked_run.assert_called_once()
            run_args, run_kwargs = mocked_run.call_args
            self.assertEqual(run_args[0][0], os.fspath(Path(sys.executable).resolve()))
            self.assertIn("-I", run_args[0])
            self.assertIn("-B", run_args[0])
            self.assertIn("-s", run_args[0])
            self.assertEqual(run_args[0][-1], os.fspath(script_path))
            self.assertFalse(run_kwargs["shell"])
            self.assertFalse(run_kwargs["check"])
            self.assertEqual(run_kwargs["env"]["PYTHONNOUSERSITE"], "1")
            self.assertEqual(run_kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(run_kwargs["env"]["PYTHONSAFEPATH"], "1")

    def test_non_zero_exit_is_raised(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)
            inst = self._make_instance(script_path, script_bytes)

            with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=7)):
                with self.assertRaisesRegex(SystemExit, "returned exit code 7"):
                    inst.run_batch_file()

    @unittest.skipIf(sys.platform == "win32", "symlink test requires unix symlink semantics")
    def test_symlink_script_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            link_path = Path(temp_dir, "generated-link.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)
            link_path.symlink_to(script_path)
            inst = self._make_instance(link_path, script_bytes)

            with self.assertRaisesRegex(RuntimeError, "Refusing to execute symlink batch script"):
                inst.run_batch_file()

    def test_no_in_process_exec_with_globals(self):
        source_path = Path(__file__).resolve().parents[1] / "instlInstanceBase.py"
        source = source_path.read_text(encoding="utf-8")
        self.assertNotIn("exec(py_compiled, globals())", source)

    def test_bootstrap_vars_are_forced_into_batch_assignments(self):
        class DummyBatchAccum:
            def __init__(self):
                self.commands = []

            def set_current_section(self, _section_name):
                pass

            def __iadd__(self, cmd):
                self.commands.append(cmd)
                return self

        original_stack_size = config_vars.stack_size()
        try:
            config_vars.push_scope()
            config_vars["DONT_WRITE_CONFIG_VARS"] = ("__INSTL_DATA_FOLDER__", "__INSTL_DEFAULTS_FOLDER__")
            config_vars["WRITE_CONFIG_VARS_READ_FROM_ENVIRON_TO_BATCH_FILE"] = "no"
            config_vars["__INSTL_DATA_FOLDER__"] = "/tmp/instl-data"
            config_vars["__INSTL_DEFAULTS_FOLDER__"] = "/tmp/instl-data/defaults"

            inst = object.__new__(InstlInstanceBase)
            dummy_accum = DummyBatchAccum()
            inst.create_variables_assignment(dummy_accum)

            assigned_var_names = [cmd.var_name for cmd in dummy_accum.commands if hasattr(cmd, "var_name")]
            self.assertIn("__INSTL_DATA_FOLDER__", assigned_var_names)
            self.assertIn("__INSTL_DEFAULTS_FOLDER__", assigned_var_names)
            self.assertEqual(assigned_var_names.count("__INSTL_DATA_FOLDER__"), 1)
            self.assertEqual(assigned_var_names.count("__INSTL_DEFAULTS_FOLDER__"), 1)
        finally:
            config_vars.resize_stack(original_stack_size)

    # ------------------------------------------------------------------
    # Snapshot-specific tests
    # ------------------------------------------------------------------

    def test_snapshot_tampering_is_detected_before_execution(self):
        """A modified snapshot must be rejected before the subprocess is launched."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)
            inst = self._make_instance(script_path, script_bytes)

            # Tamper the snapshot after _make_instance recorded its integrity metadata.
            snapshot_path = script_path.with_suffix('.snapshot.json')
            snapshot_path.write_bytes(b'{"INJECTED": ["evil"]}')

            with mock.patch("subprocess.run") as mocked_run:
                with self.assertRaisesRegex(RuntimeError, "unexpectedly modified before execution"):
                    inst.run_batch_file()
                mocked_run.assert_not_called()

    def test_missing_snapshot_prevents_execution(self):
        """A missing snapshot must prevent the subprocess from being launched."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)
            inst = self._make_instance(script_path, script_bytes)

            # Delete the snapshot that _make_instance created.
            script_path.with_suffix('.snapshot.json').unlink()

            with mock.patch("subprocess.run") as mocked_run:
                with self.assertRaises((FileNotFoundError, RuntimeError)):
                    inst.run_batch_file()
                mocked_run.assert_not_called()

    @unittest.skipIf(sys.platform == "win32", "symlink test requires unix symlink semantics")
    def test_symlink_snapshot_is_rejected(self):
        """A symlinked snapshot must be rejected before the subprocess is launched."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)

            # Build instance with a real snapshot first so we have valid checksums.
            inst = self._make_instance(script_path, script_bytes)
            snapshot_path = script_path.with_suffix('.snapshot.json')
            snapshot_bytes = snapshot_path.read_bytes()

            # Replace the regular snapshot file with a symlink to itself.
            real_target = Path(temp_dir, "real.snapshot.json")
            real_target.write_bytes(snapshot_bytes)
            snapshot_path.unlink()
            snapshot_path.symlink_to(real_target)

            with mock.patch("subprocess.run") as mocked_run:
                with self.assertRaisesRegex(RuntimeError, "Refusing to load symlink config snapshot"):
                    inst.run_batch_file()
                mocked_run.assert_not_called()

    def test_snapshot_includes_env_key_excluded_vars(self):
        """_write_config_snapshot must include vars whose names match env-var keys.

        create_variables_assignment skips such vars when
        WRITE_CONFIG_VARS_READ_FROM_ENVIRON_TO_BATCH_FILE=no (the default).  Those
        missing vars are the root cause of the runtime_progress_num drift because
        DB-backed commands rely on them to open the correct SQLite file.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir, "test.snapshot.json")

            original_stack_size = config_vars.stack_size()
            try:
                config_vars.push_scope()
                config_vars["DONT_WRITE_CONFIG_VARS"] = []

                # Pick a name that is almost certainly in os.environ (HOME on Unix,
                # USERNAME on Windows) so it would be excluded by the env-key filter.
                env_key = "HOME" if sys.platform != "win32" else "USERNAME"
                config_vars[env_key] = "snapshot_test_value"

                inst = object.__new__(InstlInstanceBase)
                inst._snapshot_checksum = None
                inst._snapshot_size = None
                inst._write_config_snapshot(snapshot_path)

                with open(snapshot_path, encoding="utf-8") as f:
                    snap = json.load(f)

                self.assertIn(env_key, snap,
                              f"env-key var '{env_key}' must appear in snapshot even though "
                              f"create_variables_assignment would exclude it")
                self.assertEqual(snap[env_key], ["snapshot_test_value"])
            finally:
                config_vars.resize_stack(original_stack_size)

    def test_snapshot_excludes_secret_vars(self):
        """_write_config_snapshot must honour the DONT_WRITE_CONFIG_VARS denylist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir, "test.snapshot.json")

            original_stack_size = config_vars.stack_size()
            try:
                config_vars.push_scope()
                config_vars["DONT_WRITE_CONFIG_VARS"] = ["SECRET_TOKEN"]
                config_vars["SECRET_TOKEN"] = "s3cr3t"
                config_vars["SAFE_VAR"] = "visible"

                inst = object.__new__(InstlInstanceBase)
                inst._snapshot_checksum = None
                inst._snapshot_size = None
                inst._write_config_snapshot(snapshot_path)

                with open(snapshot_path, encoding="utf-8") as f:
                    snap = json.load(f)

                self.assertNotIn("SECRET_TOKEN", snap)
                self.assertIn("SAFE_VAR", snap)
            finally:
                config_vars.resize_stack(original_stack_size)

    def test_snapshot_integrity_metadata_is_stored(self):
        """_write_config_snapshot must populate _snapshot_checksum and _snapshot_size."""
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir, "test.snapshot.json")

            original_stack_size = config_vars.stack_size()
            try:
                config_vars.push_scope()
                config_vars["DONT_WRITE_CONFIG_VARS"] = []
                config_vars["SOME_VAR"] = "hello"

                inst = object.__new__(InstlInstanceBase)
                inst._snapshot_checksum = None
                inst._snapshot_size = None
                inst._write_config_snapshot(snapshot_path)

                self.assertIsNotNone(inst._snapshot_checksum)
                self.assertIsNotNone(inst._snapshot_size)

                actual_bytes = snapshot_path.read_bytes()
                self.assertEqual(inst._snapshot_size, len(actual_bytes))
                self.assertEqual(inst._snapshot_checksum, utils.get_buffer_checksum(actual_bytes))
            finally:
                config_vars.resize_stack(original_stack_size)


    def test_venv_python_is_preferred_when_valid(self):
        """run_batch_file() must use INSTL_VIRTUAL_ENVIRONMENT_PYTHON when it points to a real file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)
            inst = self._make_instance(script_path, script_bytes)

            # Create a fake venv python file so the path check passes.
            fake_venv_python = Path(temp_dir, "fake_python")
            fake_venv_python.write_bytes(b"")

            original_stack_size = config_vars.stack_size()
            try:
                config_vars.push_scope()
                config_vars["INSTL_VIRTUAL_ENVIRONMENT_PYTHON"] = os.fspath(fake_venv_python)

                with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as mocked_run:
                    inst.run_batch_file()

                mocked_run.assert_called_once()
                run_args, _run_kwargs = mocked_run.call_args
                self.assertEqual(run_args[0][0], os.fspath(fake_venv_python.resolve()))
            finally:
                config_vars.resize_stack(original_stack_size)

    def test_falls_back_to_sys_executable_when_venv_python_missing(self):
        """run_batch_file() must fall back to sys.executable when INSTL_VIRTUAL_ENVIRONMENT_PYTHON is not a file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir, "generated.py")
            script_bytes = b"print('safe')\n"
            script_path.write_bytes(script_bytes)
            inst = self._make_instance(script_path, script_bytes)

            original_stack_size = config_vars.stack_size()
            try:
                config_vars.push_scope()
                config_vars["INSTL_VIRTUAL_ENVIRONMENT_PYTHON"] = os.path.join(temp_dir, "nonexistent_python")

                with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0)) as mocked_run:
                    inst.run_batch_file()

                mocked_run.assert_called_once()
                run_args, _run_kwargs = mocked_run.call_args
                self.assertEqual(run_args[0][0], os.fspath(Path(sys.executable).resolve()))
            finally:
                config_vars.resize_stack(original_stack_size)

    def test_opening_code_includes_venv_site_packages_when_configured(self):
        """Generated batches must expose venv site-packages before importing project modules."""
        with tempfile.TemporaryDirectory() as temp_dir:
            venv_dir = Path(temp_dir, "venv")
            expected_site_packages = self._expected_site_packages(venv_dir)
            expected_line = f"sys.path.insert(0, {utils.quoteme_raw_by_type(expected_site_packages)})"

            original_stack_size = config_vars.stack_size()
            try:
                config_vars.push_scope()
                config_vars["INSTL_VIRTUAL_ENVIRONMENT_DIR"] = os.fspath(venv_dir)

                opening_lines = PythonBatchCommandAccum()._python_opening_code().splitlines()

                self.assertIn(expected_line, opening_lines)
                self.assertLess(
                    opening_lines.index(expected_line),
                    opening_lines.index("import utils"),
                )
            finally:
                config_vars.resize_stack(original_stack_size)

    def test_opening_code_omits_venv_site_packages_when_not_configured(self):
        """Non-build generated batches should not get an empty site-packages path."""
        original_stack_size = config_vars.stack_size()
        try:
            config_vars.push_scope()
            config_vars["INSTL_VIRTUAL_ENVIRONMENT_DIR"] = ""

            opening_code = PythonBatchCommandAccum()._python_opening_code()

            self.assertNotIn("sys.path.insert(0,", opening_code)
        finally:
            config_vars.resize_stack(original_stack_size)


if __name__ == "__main__":
    unittest.main()
