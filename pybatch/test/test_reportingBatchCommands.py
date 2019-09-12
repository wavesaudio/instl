#!/usr/bin/env python3.6


import sys
import os
from pathlib import Path
import unittest
import subprocess
import stat
import ctypes
import io
import contextlib
import filecmp
import random
import string
from collections import namedtuple

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum
from pybatch.copyBatchCommands import RsyncClone
from configVar import config_vars

current_os_names = utils.get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

config_vars["__CURRENT_OS_NAMES__"] = current_os_names


from .test_PythonBatchBase import *


class TestPythonBatchReporting(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_AnonymousAccum_repr(self):
        """ test that AnonymousAccum.__repr__ is NOT implemented
        """
        obj = AnonymousAccum()
        with self.assertRaises(NotImplementedError):
            obj_recreated = eval(repr(obj))

    def test_AnonymousAccum(self):
        pass

    def test_RaiseException_repr(self):
        the_exception = ValueError
        the_message = "just a dummy exception"
        self.pbt.reprs_test_runner(RaiseException(the_exception, the_message))

    def test_RaiseException(self):
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += RaiseException(ValueError, "la la la")
        self.pbt.exec_and_capture_output(expected_exception=ValueError)

    def test_Stage_repr(self):
        """ test that Stage.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        self.pbt.reprs_test_runner(Stage("Tuti"), Stage("Tuti", "Fruti"))

    def test_Stage(self):
        pass

    def test_Progress_repr(self):
        """ test that Progress.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        self.pbt.reprs_test_runner(Progress("Tuti"), Progress("Tuti", own_progress_count=17))

    def test_Progress(self):
        pass

    def test_Echo_repr(self):
        """ test that Echo.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        obj = Echo("echo echo echo")
        the_repr = repr(obj)
        self.assertEqual(the_repr, 'print("echo echo echo")', "Echo.repr did not recreate Echo object correctly")

    def test_Echo(self):
        pass

    def test_Remark_repr(self):
        """ test that Remark.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        obj = Remark("remark remark remark")
        the_repr = repr(obj)
        self.assertEqual(the_repr, '# remark remark remark', "Remark.repr did not recreate Remark object correctly")

    def test_Remark(self):
        pass

    def test_PythonVarAssign_repr(self):
        """ test that PythonVarAssign.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        obj = PythonVarAssign("luli", "lu")
        the_repr = repr(obj)
        self.assertEqual(the_repr, 'luli = r"lu"', "PythonVarAssign.repr did not recreate PythonVarAssign object correctly")

    def test_PythonVarAssign(self):
        pass

    def test_ConfigVarAssign_repr(self):
        """ test that ConfigVarAssign.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        obj = ConfigVarAssign("luli", "lu")
        the_repr = repr(obj)
        self.assertEqual(the_repr, '''config_vars['luli'] = r"lu"''', "PythonVarAssign.repr did not recreate PythonVarAssign object correctly")

        obj = ConfigVarAssign("Algemene", "Bank", "Nederland")
        the_repr = repr(obj)
        self.assertEqual(the_repr, '''config_vars['Algemene'] = (r"Bank", r"Nederland")''', "PythonVarAssign.repr did not recreate PythonVarAssign object correctly")

    def test_ConfigVarAssign(self):
        pass

    def test_ConfigVarPrint_repr(self):
        """ test that ConfigVarPrint.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        self.pbt.reprs_test_runner(ConfigVarPrint("Avi Balali $(NIKMAT_HATRACTOR)"))

    def test_ConfigVarPrint(self):
        self.pbt.batch_accum.clear()
        #config_vars["SVN_REPO_URL"] = "http://lachouffe/svn/V10_test"
        config_vars["SVN_REPO_URL"] = "http://svn.apache.org/repos/asf/spamassassin/trunk"
        config_vars["SOME_VAR_TO_PRINT"] = -12345
        self.pbt.batch_accum += ConfigVarPrint("SOME_VAR_TO_PRINT")
        self.pbt.exec_and_capture_output()

        with open(self.pbt.output_file_name, "r") as rfd:
            self.assertIn(str(config_vars["SOME_VAR_TO_PRINT"]), rfd.read())

    def test_PythonBatchRuntime_repr(self):
        pass

    def test_PythonBatchRuntime(self):
        pass

    def test_ResolveConfigVarsInFile_repr(self):
        self.pbt.reprs_test_runner(ResolveConfigVarsInFile("source", "target"), ResolveConfigVarsInFile("source", "target", config_file="I'm a config file"))

    def test_ResolveConfigVarsInFile(self):
        if "BANANA" in config_vars:
            del config_vars["BANANA"]
        if "STEVE" in config_vars:
            del config_vars["STEVE"]
        unresolved_file = self.pbt.path_inside_test_folder("unresolved_file")
        resolve_file = self.pbt.path_inside_test_folder("resolve_file")
        config_file = self.pbt.path_inside_test_folder("config_file")

        config_text = """
--- !define
STEVE: Jobs
        """
        with config_file.open("w") as wfd:
            wfd.write(config_text)

        unresolved_text = "li li li, hamizvada lu sheli $(BANANA)!, $(STEVE)!"
        resolved_text = "li li li, hamizvada lu sheli Rama!, Jobs!"
        with unresolved_file.open("w") as wfd:
            wfd.write(unresolved_text)
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += ConfigVarAssign("BANANA", "Rama")
        self.pbt.batch_accum += ResolveConfigVarsInFile(unresolved_file, resolve_file, config_file=config_file)
        self.pbt.exec_and_capture_output()

        with resolve_file.open("r") as rfd:
            resolved_text_from_File = rfd.read()
            self.assertEqual(resolved_text_from_File, resolved_text_from_File)

    def test_EnvironVarAssign_repr(self):
        obj = EnvironVarAssign("hila", "lulu lin")
        the_repr = repr(obj)
        self.assertEqual(the_repr, 'os.environ["hila"]="lulu lin"', "EnvironVarAssign.repr did not recreate Remark object correctly")

    def test_EnvironVarAssign(self):
        var_name = "hila"
        var_value = "lulu lin"
        if var_name in os.environ:  # del value from previous test run
            del os.environ[var_name]

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += EnvironVarAssign(var_name, var_value)
        self.pbt.exec_and_capture_output()

        self.assertTrue(var_name in os.environ, f"EnvironVarAssign.repr did not set environment variable '{var_name}' at all")
        self.assertEqual(os.environ[var_name], var_value, f"EnvironVarAssign.repr did not set environment variable '{var_name}' correctly")
