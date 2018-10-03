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


class TestPythonBatchSVN(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_SVNClient_repr(self):

        if sys.platform != 'darwin':
            return

        obj = SVNClient("checkout", "--depth", "infinity")
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"SVNClient.repr did not recreate SVNClient object correctly: {diff_explanation}")

    def test_SVNClient(self):

        if sys.platform != 'darwin':
            return

        svn_checkout_dir = Path("/Volumes/BonaFide/installers/testinstl/V9/svn")

        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(svn_checkout_dir)) as sub_bc:
            sub_bc += SVNClient("info")

        self.pbt.exec_and_capture_output()
