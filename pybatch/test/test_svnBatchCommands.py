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

        svn_url = "https://svn.apache.org/repos/asf/subversion/trunk"
        svn_info_out_file = self.pbt.path_inside_test_folder("svn_info.txt")
        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Stage(svn_url)) as sub_bc:
            sub_bc += SVNClient("info", url=svn_url, depth='immediates', out_file=svn_info_out_file)

        self.pbt.exec_and_capture_output()
        self.assertTrue(svn_info_out_file.is_file(), f"{svn_info_out_file} does not exist after running curl")
        with open(svn_info_out_file, 'r') as stream:
            downloaded_data = stream.read()
        self.assertIn(svn_url, downloaded_data)

    def test_SVNLastRepoRev_repr(self):

        if sys.platform != 'darwin':
            return
        self.pbt.reprs_test_runner(SVNLastRepoRev(url="http://svn.apache.org/repos/asf/spamassassin/trunk", reply_config_var="__LAST_REPO_REV__"))

    def test_SVNLastRepoRev(self):

        if sys.platform != 'darwin':
            return

        self.pbt.batch_accum.clear()
        #config_vars["SVN_REPO_URL"] = "http://lachouffe/svn/V10_test"
        config_vars["SVN_REPO_URL"] = "http://svn.apache.org/repos/asf/spamassassin/trunk"
        config_vars["__LAST_REPO_REV__"] = -12345
        self.pbt.batch_accum += SVNLastRepoRev(url=str(config_vars["SVN_REPO_URL"]), reply_config_var="__LAST_REPO_REV__")
        self.pbt.batch_accum += ConfigVarPrint("__LAST_REPO_REV__")
        self.pbt.exec_and_capture_output()
        self.assertGreater(int(config_vars["__LAST_REPO_REV__"]), 1845907, f"configVar __LAST_REPO_REV__ ({int(config_vars['__LAST_REPO_REV__'])}) was not set to proper value")

    def test_SVNCheckout_repr(self):

        if sys.platform != 'darwin':
            return
        self.pbt.reprs_test_runner(SVNCheckout(url="http://svn.apache.org/repos/asf/spamassassin/trunk", where="somewhere"))

    def test_SVNCheckout(self):

        if sys.platform != 'darwin':
            return

        out_file_1 = self.pbt.path_inside_test_folder("out-file-1")
        checkout_folder_1 = self.pbt.path_inside_test_folder("checkout-folder-1")
        some_folder_that_should_be_there_after_checkout_1 = checkout_folder_1.joinpath("powered_by").resolve()

        checkout_folder_2 = self.pbt.path_inside_test_folder("checkout-folder-2")
        some_file_that_should_be_there_after_checkout_2 = checkout_folder_2.joinpath("apache-header.txt").resolve()

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDirs(checkout_folder_1)
        self.pbt.batch_accum += SVNCheckout(where=os.fspath(checkout_folder_1), url="http://svn.apache.org/repos/asf/spamassassin/trunk", depth="immediates", out_file=os.fspath(out_file_1))
        self.pbt.batch_accum += MakeDirs(checkout_folder_2)
        self.pbt.batch_accum += SVNCheckout(where=os.fspath(checkout_folder_2), url="http://svn.apache.org/repos/asf/camel/trunk/etc", depth="files")
        self.pbt.exec_and_capture_output()

        self.assertTrue(some_folder_that_should_be_there_after_checkout_1.exists(), f"{self.pbt.which_test}: {some_folder_that_should_be_there_after_checkout_1} should exist after test")
        self.assertTrue(some_file_that_should_be_there_after_checkout_2.is_file(), f"{self.pbt.which_test}: {some_file_that_should_be_there_after_checkout_2} should exist after test")

    def test_SVNInfo_repr(self):

        if sys.platform != 'darwin':
            return
        self.pbt.reprs_test_runner(SVNInfo(url="http://svn.apache.org/repos/asf/spamassassin/trunk", out_file="somewhere"))

    def test_SVNInfo(self):

        if sys.platform != 'darwin':
            return

        info_file = self.pbt.path_inside_test_folder("info-file")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += SVNInfo(out_file=os.fspath(info_file), url="http://svn.apache.org/repos/asf/spamassassin/trunk", depth="immediates")
        self.pbt.exec_and_capture_output()
        self.assertTrue(info_file.is_file(), f"{self.pbt.which_test}: {info_file} should exist after test")

    def test_SVNPropList(self):

        if sys.platform != 'darwin':
            return

        proplist_file = self.pbt.path_inside_test_folder("proplist-file")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += SVNClient(command="proplist", out_file=os.fspath(proplist_file), url="https://svn.apache.org/repos/asf/subversion/trunk", depth='immediates')
        self.pbt.exec_and_capture_output()
        self.assertTrue(proplist_file.is_file(), f"{self.pbt.which_test}: {proplist_file} should exist after test")

    def test_SVNCheckout_repr(self):

        if sys.platform != 'darwin':
            return
        self.pbt.reprs_test_runner(SVNCheckout(where="here", url="http://svn.apache.org/repos/asf/spamassassin/trunk", out_file="somewhere"))
