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
        self.pbt.reprs_test_runner(SVNClient("checkout"))

    def test_SVNClient(self):

        if sys.platform != 'darwin':
            return

        svn_checkout_dir = Path("/Volumes/BonaFide/installers/testinstl/V9/svn")

        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(svn_checkout_dir)) as sub_bc:
            sub_bc += SVNClient("info")

        self.pbt.exec_and_capture_output()

    def test_SVNLastRepoRev_repr(self):

        if sys.platform != 'darwin':
            return
        self.pbt.reprs_test_runner(SVNLastRepoRev("pararam_1", "pararam_2"))

    def test_SVNLastRepoRev(self):

        if sys.platform != 'darwin':
            return

    def test_SVNLastRepoRev(self):
        self.pbt.batch_accum.clear()
        #config_vars["SVN_REPO_URL"] = "http://lachouffe/svn/V10_test"
        config_vars["SVN_REPO_URL"] = "http://svn.apache.org/repos/asf/spamassassin/trunk"

        self.pbt.batch_accum += SVNLastRepoRev("SVN_REPO_URL", "__LAST_REPO__")
        self.pbt.batch_accum += ConfigVarPrint("__LAST_REPO_REV__")
        self.pbt.exec_and_capture_output()

