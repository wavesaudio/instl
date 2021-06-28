#!/usr/bin/env python3.9


import unittest
import logging
log = logging.getLogger(__name__)

from pybatch import *


from .test_PythonBatchBase import *


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
        file_that_should_not_exist_if_true = self.pbt.path_inside_test_folder("should_not_exist_if_true")

        file_that_should_exist_if_false = self.pbt.path_inside_test_folder("should_exist_if_false")
        file_that_should_not_exist_if_false = self.pbt.path_inside_test_folder("should_not_exist_if_false")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += If(IsEq(1234, 1234), if_true=Touch(file_that_should_exist_if_true), if_false=Touch(file_that_should_not_exist_if_true))
        self.pbt.batch_accum += If(IsEq("yoyo", "ma"), if_true=Touch(file_that_should_not_exist_if_false), if_false=Touch(file_that_should_exist_if_false))
        self.pbt.exec_and_capture_output()
        self.assertTrue(file_that_should_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_true} should have been created")
        self.assertFalse(file_that_should_not_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_true} should have not been created")
        self.assertTrue(file_that_should_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_false} should have been created")
        self.assertFalse(file_that_should_not_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_false} should have not been created")

    def test_If_NotEq(self):
        file_that_should_exist_if_true = self.pbt.path_inside_test_folder("should_exist_if_true")
        file_that_should_not_exist_if_true = self.pbt.path_inside_test_folder("should_not_exist_if_true")

        file_that_should_exist_if_false = self.pbt.path_inside_test_folder("should_exist_if_false")
        file_that_should_not_exist_if_false = self.pbt.path_inside_test_folder("should_not_exist_if_false")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += If(IsNotEq(1234, 1234), if_true=Touch(file_that_should_not_exist_if_true), if_false=Touch(file_that_should_exist_if_true))
        self.pbt.batch_accum += If(IsNotEq("yoyo", "ma"), if_true=Touch(file_that_should_exist_if_false), if_false=Touch(file_that_should_not_exist_if_false))
        self.pbt.exec_and_capture_output()
        self.assertTrue(file_that_should_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_true} should have been created")
        self.assertFalse(file_that_should_not_exist_if_true.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_true} should have not been created")
        self.assertTrue(file_that_should_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_exist_if_false} should have been created")
        self.assertFalse(file_that_should_not_exist_if_false.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_if_false} should have not been created")

    def test_IfFileExist(self):
        file_that_should_exist = self.pbt.path_inside_test_folder("should_exist")
        file_that_should_not_exist = self.pbt.path_inside_test_folder("should_not_exist")
        file_touched_if_exist = self.pbt.path_inside_test_folder("touched_if_exist")
        file_touched_if_not_exist = self.pbt.path_inside_test_folder("touched_if_not_exist")

        self.pbt.batch_accum.clear(section_name="doit")
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
        file_touched_if_exist = self.pbt.path_inside_test_folder("touched_if_exist")
        file_touched_if_not_exist = self.pbt.path_inside_test_folder("touched_if_not_exist")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += If("2 == 1+1", if_true=Touch(file_touched_if_exist), if_false=Touch(file_that_should_not_exist))
        self.pbt.batch_accum += If("2 == 1+3", if_true=Touch(file_that_should_not_exist), if_false=Touch(file_touched_if_not_exist))

        self.pbt.exec_and_capture_output()
        self.assertTrue(file_touched_if_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_exist} should have been created")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not have been created")
        self.assertTrue(file_touched_if_not_exist.exists(), f"{self.pbt.which_test}: {file_touched_if_not_exist} should have been created")

    def test_If_from_index(self):

        self.pbt.batch_accum.clear(section_name="doit")
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

    def test_IsConfigVarEq_repr(self):
        list_of_objs = list()
        list_of_remarks = list()
        for var in ['WZLIB_EXTENSION','NON_EXISTING_VAR']:
            for expected in ['.wzip','Momo']:
                for default in ["ben 1", "ben 2", None]:
                    list_of_objs.append(IsConfigVarEq(var, expected, default))
                    list_of_remarks.append(", ".join(("IsConfigVarEq", var, expected, str(default))))
                    list_of_objs.append(IsConfigVarNotEq(var, expected, default))
                    list_of_remarks.append(", ".join(("IsConfigVarNotEq", var, expected, str(default))))
        self.pbt.reprs_test_runner(*list_of_objs, remark_list=list_of_remarks)

    def test_IsConfigVarEq(self):
        file_that_should_not_exist = self.pbt.path_inside_test_folder("should_not_exist")
        file_touched_if_var_eq = self.pbt.path_inside_test_folder("touched_if_var_eq")
        file_touched_if_not_var_eq = self.pbt.path_inside_test_folder("touched_if_not_var_eq")

        file_that_should_not_exist_w_default = self.pbt.path_inside_test_folder("should_not_exist_w_default")
        file_touched_if_var_eq_w_default = self.pbt.path_inside_test_folder("touched_if_var_eq_w_default")
        file_touched_if_not_var_eq_w_default = self.pbt.path_inside_test_folder("touched_if_not_var_eq_w_default")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += ConfigVarAssign("BOO", "MOO")
        self.pbt.batch_accum += If(IsConfigVarEq("BOO", "MOO"), if_true=Touch(file_touched_if_var_eq), if_false=Touch(file_that_should_not_exist))
        self.pbt.batch_accum += If(IsConfigVarEq("BOO", "YOOOO"), if_true=Touch(file_that_should_not_exist), if_false=Touch(file_touched_if_not_var_eq))

        self.pbt.batch_accum += If(IsConfigVarEq("POO", "MOO", "MOO"), if_true=Touch(file_touched_if_var_eq_w_default), if_false=Touch(file_that_should_not_exist_w_default))
        self.pbt.batch_accum += If(IsConfigVarEq("POO", "MOO", "YOOOO"), if_true=Touch(file_that_should_not_exist_w_default), if_false=Touch(file_touched_if_not_var_eq_w_default))

        self.pbt.exec_and_capture_output()
        self.assertTrue(file_touched_if_var_eq.exists(), f"{self.pbt.which_test}: {file_touched_if_var_eq} should have been created")
        self.assertFalse(file_that_should_not_exist.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist} should not have been created")
        self.assertTrue(file_touched_if_not_var_eq.exists(), f"{self.pbt.which_test}: {file_touched_if_not_var_eq} should have been created")

        self.assertTrue(file_touched_if_var_eq_w_default.exists(), f"{self.pbt.which_test}: {file_touched_if_var_eq_w_default} should have been created")
        self.assertFalse(file_that_should_not_exist_w_default.exists(), f"{self.pbt.which_test}: {file_that_should_not_exist_w_default} should not have been created")
        self.assertTrue(file_touched_if_not_var_eq_w_default.exists(), f"{self.pbt.which_test}: {file_touched_if_not_var_eq_w_default} should have been created")

    def test_IsConfigVarDefined_repr(self):
        self.pbt.reprs_test_runner(IsConfigVarDefined("MAMA_MIA"))

    def test_IsConfigVarDefined(self):
        """ define a configVar "MAMA_MIA" and create a file if "MAMA_MIA" is defined and different file if not
            DO NOT define a configVar "PILPEL" and create a file if "PILPEL" is defined and different file if not
            Check that the correct files exist
        """
        MAMA_MIA_is_defined_file = self.pbt.path_inside_test_folder("MAMA_MIA_is_defined")
        MAMA_MIA_is_not_defined_file = self.pbt.path_inside_test_folder("MAMA_MIA_is_not_defined")
        PILPEL_is_defined_file = self.pbt.path_inside_test_folder("PILPEL_is_defined")
        PILPEL_is_not_defined_file = self.pbt.path_inside_test_folder("PILPEL_is_not_defined")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += ConfigVarAssign("MAMA_MIA", "ABBA")
        self.pbt.batch_accum += If(IsConfigVarDefined("MAMA_MIA"),
                                   if_true=Touch(MAMA_MIA_is_defined_file),
                                   if_false=Touch(MAMA_MIA_is_not_defined_file))
        self.pbt.batch_accum += If(IsConfigVarDefined("PILPEL"),
                                   if_true=Touch(PILPEL_is_defined_file),
                                   if_false=Touch(PILPEL_is_not_defined_file))
        self.pbt.exec_and_capture_output()
        self.assertTrue(MAMA_MIA_is_defined_file.exists(), f"{self.pbt.which_test}: {MAMA_MIA_is_defined_file} should have been created")
        self.assertFalse(MAMA_MIA_is_not_defined_file.exists(), f"{self.pbt.which_test}: {MAMA_MIA_is_not_defined_file} should have not been created")
        self.assertFalse(PILPEL_is_defined_file.exists(), f"{self.pbt.which_test}: {PILPEL_is_defined_file} should have not been created")
        self.assertTrue(PILPEL_is_not_defined_file.exists(), f"{self.pbt.which_test}: {PILPEL_is_not_defined_file} should have been created")
