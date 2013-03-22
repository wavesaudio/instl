#!/usr/local/bin/python2.7

from __future__ import print_function

import sys
import os
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
import configVarList

class TestConfigVarList(unittest.TestCase):

    def setUp(self):
        pass
    def tearDown(self):
        pass

    def test_construction_empty(self):
        """ Construct ConfigVarList without values. """
        cvl1 = configVarList.ConfigVarList()
        self.assertEqual(len(cvl1), 0)
        with self.assertRaises(KeyError):
            cvl1["no man's land"]
        self.assertFalse("no man's land" in cvl1)
        self.assertEqual(cvl1.get_list("no man's land"), ())
        self.assertEqual(cvl1.get_str("no man's land"), "")
        self.assertEqual(cvl1.keys(), [])

    def test_set_variable_new(self):
        """ Set one variable. """
        cvl2 = configVarList.ConfigVarList()
        cvl2.set_variable("banana", "phone")
        self.assertEqual(len(cvl2), 1)
        self.assertTrue("banana" in cvl2)
        self.assertIs(cvl2.get_configVar_obj("banana"), cvl2["banana"])
        self.assertEqual(cvl2.get_configVar_obj("banana").description(), "phone")
        self.assertEqual(len(cvl2), 1)
        cvl2.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.assertEqual(cvl2.get_list("banana"), ("get", "down", "tonight"))
        self.assertEqual(cvl2.get_str("banana"), "get down tonight")
        self.assertEqual(cvl2.keys(), ["banana"])

    def test_set_variable_reset(self):
        """ Set one variable, reset it. """
        cvl2 = configVarList.ConfigVarList()
        cvl2.set_variable("banana", "phone")
        cvl2.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        cvl2.set_variable("banana", "kirk")
        self.assertEqual(len(cvl2), 1)
        self.assertTrue("banana" in cvl2)
        self.assertIs(cvl2.get_configVar_obj("banana"), cvl2["banana"])
        self.assertEqual(cvl2.get_configVar_obj("banana").description(), "kirk")
        self.assertEqual(len(cvl2), 1)
        cvl2.get_configVar_obj("banana").extend(("set", "up", "tomorrow"))
        self.assertEqual(cvl2.get_list("banana"), ("set", "up", "tomorrow"))
        self.assertEqual(cvl2.get_str("banana"), "set up tomorrow")
        self.assertEqual(cvl2.keys(), ["banana"])

    def test_get_configVar_obj(self):
        """ Set one variable, by getting it. """
        cvl3 = configVarList.ConfigVarList()
        cvl3.get_configVar_obj("banana")
        self.assertEqual(len(cvl3), 1)
        self.assertTrue("banana" in cvl3)
        self.assertIs(cvl3.get_configVar_obj("banana"), cvl3["banana"])
        self.assertEqual(len(cvl3), 1)
        cvl3.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.assertEqual(cvl3.get_list("banana"), ("get", "down", "tonight"))
        self.assertEqual(cvl3.get_str("banana"), "get down tonight")
        self.assertEqual(cvl3.keys(), ["banana"])

    def test_del(self):
        """ Set one variable, and delete it. """
        cvl4 = configVarList.ConfigVarList()
        cvl4.get_configVar_obj("banana")
        self.assertEqual(len(cvl4), 1)
        del cvl4["banana"]
        self.assertFalse("banana" in cvl4)
        self.assertEqual(len(cvl4), 0)

    def test_duplicate_variable_good(self):
        """ Create variable, duplicate it """
        cvl5 = configVarList.ConfigVarList()
        cvl5.get_configVar_obj("banana")
        cvl5.get_configVar_obj("banana").extend(("grease", "is", "the", "world"))
        self.assertEqual(len(cvl5), 1)
        cvl5.duplicate_variable("banana", "oranges")
        self.assertEqual(len(cvl5), 2)
        self.assertEqual(cvl5.get_list("banana"), cvl5.get_list("oranges"))
        self.assertEqual(cvl5.get_str("banana"), cvl5.get_str("oranges"))
        self.assertEqual(sorted(cvl5.keys()), ["banana", "oranges"])

    def test_duplicate_variable_bad(self):
        """ Dont's create variable, duplicate it anyway"""
        cvl5 = configVarList.ConfigVarList()
        cvl5.get_configVar_obj("banana")
        cvl5.get_configVar_obj("banana").extend(("grease", "is", "the", "world"))
        self.assertEqual(len(cvl5), 1)
        with self.assertRaises(KeyError):
            cvl5.duplicate_variable("peaches", "oranges")
        self.assertEqual(len(cvl5), 1)
        self.assertEqual(cvl5.get_list("oranges"), ())
        self.assertEqual(cvl5.get_str("oranges"), "")
        self.assertEqual(sorted(cvl5.keys()), ["banana"])

    def test_resolve_string_from_nothing(self):
        """ resolve values from variables where list is empty """
        cvl6 = configVarList.ConfigVarList()
        resolved = cvl6.resolve_string("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = cvl6.resolve_string("$(Kupperbush)")
        self.assertEqual(resolved, "")
        resolved = cvl6.resolve_string("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper")
        resolved = cvl6.resolve_string("$(Kupper$(bush))")
        self.assertEqual(resolved, "")

    def test_resolve_string_from_empty(self):
        """ resolve values from variables where list has empty variables """
        cvl7 = configVarList.ConfigVarList()
        cvl7.get_configVar_obj("Kupperbush")
        cvl7.get_configVar_obj("bush")
        resolved = cvl7.resolve_string("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = cvl7.resolve_string("$(Kupperbush)")
        self.assertEqual(resolved, "")
        resolved = cvl7.resolve_string("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper")
        resolved = cvl7.resolve_string("$(Kupper$(bush))")
        self.assertEqual(resolved, "")

    def test_resolve_string_from_partial(self):
        """ resolve values from variables where list has partial variables """
        cvl8 = configVarList.ConfigVarList()
        cvl8.get_configVar_obj("Kupperbush").append("kid creole")
        cvl8.get_configVar_obj("bush").append("bush")
        resolved = cvl8.resolve_string("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = cvl8.resolve_string("$(Kupperbush)")
        self.assertEqual(resolved, "kid creole")
        resolved = cvl8.resolve_string("Kupper$(bush)")
        self.assertEqual(resolved, "Kupperbush")
        resolved = cvl8.resolve_string("$(Kupper$(bush))")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_1(self):
        """ resolve values from variables with single value with non-default separator """
        cvl8 = configVarList.ConfigVarList()
        cvl8.get_configVar_obj("Kupperbush").append("kid creole")
        cvl8.get_configVar_obj("bush").append("bush")
        resolved = cvl8.resolve_string("Kupperbush", sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = cvl8.resolve_string("$(Kupperbush)", sep="-")
        self.assertEqual(resolved, "kid creole")
        resolved = cvl8.resolve_string("Kupper$(bush)", sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = cvl8.resolve_string("$(Kupper$(bush))", sep="-")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_2(self):
        """ resolve values from variables with multi value with non-default separator """
        cvl9 = configVarList.ConfigVarList()
        cvl9.get_configVar_obj("name").extend(("kid","creole"))
        cvl9.get_configVar_obj("beer").extend(("Anheuser", "Busch"))
        resolved = cvl9.resolve_string("$(name) drinks $(beer)", sep="-")
        self.assertEqual(resolved, "kid creole drinks Anheuser Busch")
        resolved = cvl9.resolve_string("$(name)", sep="-")
        self.assertEqual(resolved, "kid-creole")
        resolved = cvl9.resolve_string("$(beer)", sep="-")
        self.assertEqual(resolved, "Anheuser-Busch")

