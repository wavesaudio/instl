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


from test_PythonBatchBase import *


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
        obj = RaiseException(the_exception, the_message)
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, "RaiseException.repr (1) did not recreate RsyncClone object correctly")

    def test_RaiseException(self):
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += RaiseException(ValueError, "la la la")
        self.pbt.exec_and_capture_output(expected_exception=ValueError)

    def test_Stage_repr(self):
        """ test that Stage.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        obj = Stage("Tuti")
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, "Stage.repr did not recreate Stage object correctly")

        obj = Stage("Tuti", "Fruti")
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, "Stage.repr did not recreate Stage object correctly")

    def test_Stage(self):
        pass

    def test_Progress_repr(self):
        """ test that Progress.__repr__ is implemented correctly to fully
            reconstruct the object
        """
        obj = Progress("Tuti")
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, "Progress.repr did not recreate Progress object correctly")

        obj = Progress("Tuti", own_progress_count=17)
        obj_recreated = eval(repr(obj))
        self.assertEqual(obj, obj_recreated, "Progress.repr did not recreate Progress object correctly")

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

    def test_PythonBatchRuntime_repr(self):
        pass

    def test_PythonBatchRuntime(self):
        pass
