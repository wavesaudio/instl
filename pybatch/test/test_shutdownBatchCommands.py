#!/usr/bin/env python3.9
import unittest

from pybatch import Shutdown
from .test_PythonBatchBase import *


class TestShutdwonProc(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_ShutDown_repr(self):
        self.pbt.reprs_test_runner(Shutdown())

    def test_ShutDown_action(self):
        if sys.platform == 'Darwin':
            config_vars['WAVES_PROGRAMDATA_DIR'] = '/Library/Application Support/Waves'
        else:
            config_vars['WAVES_PROGRAMDATA_DIR'] = str(os.getenv('ProgramData')) + "\Waves Audio"

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += Shutdown()
        self.pbt.exec_and_capture_output("test_ShutDown")
