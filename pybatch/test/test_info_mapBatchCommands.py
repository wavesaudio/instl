#!/usr/bin/env python3.9


import unittest
import logging
log = logging.getLogger(__name__)

from pybatch import *


from .test_PythonBatchBase import *


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

    @unittest.skip("too local to be a general test")
    def test_create_short_index(self):
        self.pbt.batch_accum.clear(section_name="doit")
        path_to_index = "/Volumes/BonaFide/installers/commits/test/V11/svn/instl/index.yaml"
        path_to_short_index = "/Volumes/BonaFide/installers/commits/test/V11/svn/instl/short-index.yaml"

        self.pbt.batch_accum += ConfigVarAssign("__INSTL_DATA_FOLDER__", "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl")
        self.pbt.batch_accum += ConfigVarAssign("__INSTL_DEFAULTS_FOLDER__", "/p4client/ProAudio/dev_central/ProAudio/XPlatform/CopyProtect/instl/defaults")
        self.pbt.batch_accum += ConfigVarAssign("DB_FILE_EXT", "sombrero")
        self.pbt.batch_accum += IndexYamlReader(path_to_index)
        self.pbt.batch_accum += ShortIndexYamlCreator(path_to_short_index)
        self.pbt.exec_and_capture_output("test_create_short_index")
