#!/usr/bin/env python3.6


import unittest
import logging
log = logging.getLogger()

from pybatch import *


from test_PythonBatchBase import *


class TestPythonBatchConditional(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_If_repr(self):
        list_of_objs = list()
        the_condition = True
        list_of_objs.append(If(the_condition, if_true=Touch("hootenanny"), if_false=Touch("hootebunny")))
        list_of_objs.append(If(Path("/mama/mia/here/i/go/again").exists(), if_true=Touch("hootenanny"), if_false=Touch("hootebunny")))
        list_of_objs.append(If("2 == 1+1", if_true=Touch("hootenanny"), if_false=Touch("hootebunny")))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_If_Eq(self):
        file_that_should_exist_if_true = self.pbt.path_inside_test_folder("should_exist_if_true")
        self.assertFalse(file_that_should_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_true} should not exist before test")
        file_that_should_not_exist_if_true = self.pbt.path_inside_test_folder("should_not_exist_if_true")
        self.assertFalse(file_that_should_not_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_true} should not exist before test")

        file_that_should_exist_if_false = self.pbt.path_inside_test_folder("should_exist_if_false")
        self.assertFalse(file_that_should_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_false} should not exist before test")
        file_that_should_not_exist_if_false = self.pbt.path_inside_test_folder("should_not_exist_if_false")
        self.assertFalse(file_that_should_not_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_false} should not exist before test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += If(IsEq(1234, 1234), if_true=Touch(file_that_should_exist_if_true), if_false=Touch(file_that_should_not_exist_if_true))
        self.pbt.batch_accum += If(IsEq("yoyo", "ma"), if_true=Touch(file_that_should_not_exist_if_false), if_false=Touch(file_that_should_exist_if_false))
        self.pbt.exec_and_capture_output()
        self.assertTrue(file_that_should_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_true} should have been created")
        self.assertFalse(file_that_should_not_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_true} should have not been created")
        self.assertTrue(file_that_should_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_false} should have been created")
        self.assertFalse(file_that_should_not_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_false} should have not been created")

    def test_If_NotEq(self):
        file_that_should_exist_if_true = self.pbt.path_inside_test_folder("should_exist_if_true")
        self.assertFalse(file_that_should_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_true} should not exist before test")
        file_that_should_not_exist_if_true = self.pbt.path_inside_test_folder("should_not_exist_if_true")
        self.assertFalse(file_that_should_not_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_true} should not exist before test")

        file_that_should_exist_if_false = self.pbt.path_inside_test_folder("should_exist_if_false")
        self.assertFalse(file_that_should_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_false} should not exist before test")
        file_that_should_not_exist_if_false = self.pbt.path_inside_test_folder("should_not_exist_if_false")
        self.assertFalse(file_that_should_not_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_false} should not exist before test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += If(IsNotEq(1234, 1234), if_true=Touch(file_that_should_not_exist_if_true), if_false=Touch(file_that_should_exist_if_true))
        self.pbt.batch_accum += If(IsNotEq("yoyo", "ma"), if_true=Touch(file_that_should_exist_if_false), if_false=Touch(file_that_should_not_exist_if_false))
        self.pbt.exec_and_capture_output()
        self.assertTrue(file_that_should_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_true} should have been created")
        self.assertFalse(file_that_should_not_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_true} should have not been created")
        self.assertTrue(file_that_should_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_false} should have been created")
        self.assertFalse(file_that_should_not_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_false} should have not been created")

    def test_IfFileExist(self):
        file_that_should_exist = self.pbt.path_inside_test_folder("should_exist")
        self.assertFalse(file_that_should_exist.exists(), f"{self.pbt.which_test}: {file_that_should_exist} should not exist before test")
        file_that_should_not_exist = self.pbt.path_inside_test_folder("should_not_exist")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not exist before test")
        file_touched_if_exist = self.pbt.path_inside_test_folder("touched_if_exist")
        self.assertFalse(file_touched_if_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_exist} should not exist before test")
        file_touched_if_not_exist = self.pbt.path_inside_test_folder("touched_if_not_exist")
        self.assertFalse(file_touched_if_not_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_not_exist} should not exist before test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += Touch(file_that_should_exist)
        self.pbt.batch_accum += If(IsFile(file_that_should_exist), if_true=Touch(file_touched_if_exist), if_false=Touch(file_that_should_not_exist))
        self.pbt.batch_accum += If(IsFile(file_that_should_not_exist), if_true=Touch(file_that_should_not_exist), if_false=Touch(file_touched_if_not_exist))

        self.pbt.exec_and_capture_output()
        self.assertTrue(file_that_should_exist.exists(), f"{self.pbt.which_test}: {file_that_should_exist} should have been created")
        self.assertTrue(file_touched_if_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_exist} should have been created")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not have been created")
        self.assertTrue(file_touched_if_not_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_not_exist} should have been created")

    def test_If_2_is_1_plus_1(self):
        file_that_should_not_exist = self.pbt.path_inside_test_folder("should_not_exist")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not exist before test")
        file_touched_if_exist = self.pbt.path_inside_test_folder("touched_if_exist")
        self.assertFalse(file_touched_if_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_exist} should not exist before test")
        file_touched_if_not_exist = self.pbt.path_inside_test_folder("touched_if_not_exist")
        self.assertFalse(file_touched_if_not_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_not_exist} should not exist before test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += If("2 == 1+1", if_true=Touch(file_touched_if_exist), if_false=Touch(file_that_should_not_exist))
        self.pbt.batch_accum += If("2 == 1+3", if_true=Touch(file_that_should_not_exist), if_false=Touch(file_touched_if_not_exist))

        self.pbt.exec_and_capture_output()
        self.assertTrue(file_touched_if_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_exist} should have been created")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not have been created")
        self.assertTrue(file_touched_if_not_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_not_exist} should have been created")

    def test_If_from_index(self):

        self.pbt.batch_accum.clear()
        self.pbt.reprs_test_runner(If(r"$(JEX_HOST_TYPE)" != "venue", if_true=ShellCommand(r'"$(WAVES_SOUNDGRID_UTILITIES_DIR)\WavesSoundGridDriverSetup.exe" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES', message="Installing SoundGrid Driver", ignore_specific_exit_codes=(8,))))

        obj_recreated = eval(r"""If(r"$(JEX_HOST_TYPE)" != "venue", if_true=ShellCommand(r'"$(WAVES_SOUNDGRID_UTILITIES_DIR)\WavesSoundGridDriverSetup.exe" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES', message="Installing SoundGrid Driver", ignore_specific_exit_codes=(8,)))""")
        print(repr(obj_recreated))

    def test_IsFile_repr(self):
        pass

    def test_IsFile(self):
        pass

    def test_IsDir_repr(self):
        pass

    def test_IsDir(self):
        pass

    def test_IsSymlink_repr(self):
        pass

    def test_IsSymlink(self):
        pass
