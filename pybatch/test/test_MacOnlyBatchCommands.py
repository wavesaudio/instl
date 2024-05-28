#!/usr/bin/env python3.9


import unittest


from .test_PythonBatchBase import *


class TestPythonBatchMac(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    @unittest.skipUnless(running_on_Mac, "Mac only test")
    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_MacDoc_repr(self):
        self.pbt.reprs_test_runner(MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True),
                                   MacDock("/Santa/Catalina/Island", "Santa Catalina Island", False),
                                   MacDock("/Santa/Catalina/Island", "Santa Catalina Island", True, remove=True))

    def test_MacDoc_add_to_and_restart_dock(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(app_to_add_to_dock, restart_the_doc=True, username="orenc")
        self.pbt.exec_and_capture_output("test_MacDoc_add_to_and_restart_dock")

    def test_MacDoc_remove_from_and_restart_dock(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(None, label_for_item="Cubase 10.5", remove=True, restart_the_doc=True, username="orenc")
        self.pbt.exec_and_capture_output("test_MacDoc_remove_from_and_restart_dock")

    def test_MacDoc_add_to_and_restart_dock_separately(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(app_to_add_to_dock, username="orenc")
        self.pbt.batch_accum += MacDock(restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_add_to_and_restart_dock_separately")

    def test_MacDoc_remove_from_and_restart_dock_separately(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(None,"Cubase 10", remove=True, restart_the_doc=False, username="orenc")
        self.pbt.batch_accum += MacDock(restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_remove_from_and_restart_dock_separately")

    def test_MacDoc_just_restart_dock(self):
        """ it's hard to define an automatic assert to result of MacDock operations
            so this test should be run manually
        """
        # app_to_add_to_dock = Path("/Applications/Cubase 10.5.app")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MacDock(restart_the_doc=True)
        self.pbt.exec_and_capture_output("test_MacDoc_remove_from_dock")
