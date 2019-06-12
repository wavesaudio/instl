#!/usr/bin/env python3.6


import unittest
import logging
log = logging.getLogger(__name__)

from pybatch import *


from test_PythonBatchBase import *


class TestPythonBatchInfoMap(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_InfoMapBase_repr(self):
        pass

    def test_InfoMapBase(self):
        pass

    def test_CheckDownloadFolderChecksum_repr(self):
        pass

    def test_CheckDownloadFolderChecksum(self):
        pass

    def test_SetExecPermissionsInSyncFolder_repr(self):
        pass

    def test_SetExecPermissionsInSyncFolder(self):
        pass

    def test_CreateSyncFolders_repr(self):
        pass

    def test_CreateSyncFolders(self):
        pass
