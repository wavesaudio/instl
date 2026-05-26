#!/usr/bin/env python3.12

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))
sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))

from configVar import config_vars
from pybatch import PythonDoSomething
from pyinstl.instlInstanceBase import InstlInstanceBase
import utils


def _minimal_initial_vars():
    repo_root = Path(__file__).resolve().parents[2]
    current_os_names = utils.get_current_os_names()
    os_family_name = current_os_names[0]
    os_second_name = current_os_names[0]
    if len(current_os_names) > 1:
        os_second_name = current_os_names[1]
    initial_vars = {
        "__INSTL_DATA_FOLDER__": repo_root,
        "__INSTL_DEFAULTS_FOLDER__": repo_root / "defaults",
        "__INSTL_COMPILED__": "False",
        "__CURRENT_OS__": os_family_name,
        "__CURRENT_OS_SECOND_NAME__": os_second_name,
        "__CURRENT_OS_NAMES__": current_os_names,
        "__ARGV__": ["instl"],
        "ACTING_UID": -1,
        "ACTING_GID": -1,
    }
    if os_family_name != "Win":
        initial_vars.update({
            "__USER_ID__": str(os.getuid()),
            "__GROUP_ID__": str(os.getgid()),
        })
    else:
        initial_vars.update({
            "__USER_ID__": -1,
            "__GROUP_ID__": -1,
        })
    return initial_vars


class TestBatchFileExecution(unittest.TestCase):
    def setUp(self):
        config_vars.clear()
        self.instance = InstlInstanceBase(_minimal_initial_vars())
        self.instance.the_command = "test"
        self.instance.fixed_command = "test"
        config_vars["ACTING_UID"] = -1
        config_vars["ACTING_GID"] = -1

    def test_run_batch_file_executes_in_memory_text_not_disk_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_path = Path(tmpdir) / "test-batch.py"
            marker_path = Path(tmpdir) / "marker.txt"
            config_vars["__MAIN_OUT_FILE__"] = os.fspath(batch_path)
            config_vars["__MAIN_COMMAND__"] = "test"

            # create a batch command sequence
            self.instance.batch_accum.set_current_section("begin")
            self.instance.batch_accum += PythonDoSomething(
                f'open({os.fspath(marker_path)!r}, "w").write("from_memory")'
            )

            # write it to disk
            self.instance.write_batch_file(self.instance.batch_accum)
            self.assertTrue(batch_path.is_file())

            # re-write the batch sequence on disk
            batch_path.write_text(
                f'open({os.fspath(marker_path)!r}, "w").write("from_disk")\n',
                encoding="utf-8",
            )

            # run and make sure that the original sequence in memory runs, not the one on disk
            self.instance.run_batch_file()
            self.assertEqual(marker_path.read_text(encoding="utf-8"), "from_memory")

    def test_run_batch_file_requires_in_memory_text(self):
        # make sure write_batch_file() is triggered before run_batch_file(), otherwise an exception is raised
        self.instance.out_file_realpath = "/tmp/test-batch.py"
        self.instance.batch_file_text = None
        with self.assertRaisesRegex(RuntimeError, "before write_batch_file"):
            self.instance.run_batch_file()


if __name__ == "__main__":
    unittest.main(verbosity=2)
