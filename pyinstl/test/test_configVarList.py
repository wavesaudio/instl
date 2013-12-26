#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import os
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
import configVarList

class TestConfigVarList(unittest.TestCase):

    def setUp(self):
        self.cvl = configVarList.ConfigVarList()
    def tearDown(self):
        del self.cvl

    def test_construction_empty(self):
        """ Construct ConfigVarList without values. """
        self.cvl = configVarList.ConfigVarList()
        self.assertEqual(len(self.cvl), 0)
        with self.assertRaises(KeyError):
            self.cvl["no man's land"].get_str()
        self.assertFalse("no man's land" in self.cvl)
        self.assertEqual(self.cvl.get_list("no man's land"), ())
        self.assertEqual(self.cvl.get_str("no man's land"), "")
        self.assertEqual(self.cvl.keys(), [])

    def test_set_variable_new(self):
        """ Set one variable. """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.set_variable("banana", "phone")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(self.cvl.get_configVar_obj("banana").description(), "phone")
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.assertEqual(self.cvl.get_list("banana"), ("get", "down", "tonight"))
        self.assertEqual(self.cvl.get_str("banana"), "get down tonight")
        self.assertEqual(self.cvl.keys(), ["banana"])

    def test_set_variable_reset(self):
        """ Set one variable, reset it. """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.set_variable("banana", "phone")
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.cvl.set_variable("banana", "kirk")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(self.cvl.get_configVar_obj("banana").description(), "kirk")
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("set", "up", "tomorrow"))
        self.assertEqual(self.cvl.get_list("banana"), ("set", "up", "tomorrow"))
        self.assertEqual(self.cvl.get_str("banana"), "set up tomorrow")
        self.assertEqual(self.cvl.keys(), ["banana"])

    def test_get_configVar_obj(self):
        """ Set one variable, by getting it. """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("banana")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.assertEqual(self.cvl.get_list("banana"), ("get", "down", "tonight"))
        self.assertEqual(self.cvl.get_str("banana"), "get down tonight")
        self.assertEqual(self.cvl.keys(), ["banana"])

    def test_del(self):
        """ Set one variable, and delete it. """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("banana")
        self.assertEqual(len(self.cvl), 1)
        del self.cvl["banana"]
        self.assertFalse("banana" in self.cvl)
        self.assertEqual(len(self.cvl), 0)

    def test_duplicate_variable_good(self):
        """ Create variable, duplicate it """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("banana")
        self.cvl.get_configVar_obj("banana").extend(("grease", "is", "the", "world"))
        self.assertEqual(len(self.cvl), 1)
        self.cvl.duplicate_variable("banana", "oranges")
        self.assertEqual(len(self.cvl), 2)
        self.assertEqual(self.cvl.get_list("banana"), self.cvl.get_list("oranges"))
        self.assertEqual(self.cvl.get_str("banana"), self.cvl.get_str("oranges"))
        self.assertEqual(sorted(self.cvl.keys()), ["banana", "oranges"])

    def test_duplicate_variable_bad(self):
        """ Dont's create variable, duplicate it anyway"""
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("banana")
        self.cvl.get_configVar_obj("banana").extend(("grease", "is", "the", "world"))
        self.assertEqual(len(self.cvl), 1)
        with self.assertRaises(KeyError):
            self.cvl.duplicate_variable("peaches", "oranges")
        self.assertEqual(len(self.cvl), 1)
        self.assertEqual(self.cvl.get_list("oranges"), ())
        self.assertEqual(self.cvl.get_str("oranges"), "")
        self.assertEqual(sorted(self.cvl.keys()), ["banana"])

    def test_resolve_string_from_nothing(self):
        """ resolve values from variables where list is empty """
        self.cvl = configVarList.ConfigVarList()
        resolved = self.cvl.resolve_string("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve_string("$(Kupperbush)")
        self.assertEqual(resolved, "$(Kupperbush)")
        resolved = self.cvl.resolve_string("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper$(bush)")
        resolved = self.cvl.resolve_string("$(Kupper$(bush))")
        self.assertEqual(resolved, "$(Kupper$(bush))")

    def test_resolve_string_from_empty(self):
        """ resolve values from variables where list has empty variables """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("Kupperbush")
        self.cvl.get_configVar_obj("bush")
        resolved = self.cvl.resolve_string("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve_string("$(Kupperbush)")
        self.assertEqual(resolved, "")
        resolved = self.cvl.resolve_string("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper")
        resolved = self.cvl.resolve_string("$(Kupper$(bush))")
        self.assertEqual(resolved, "$(Kupper)")

    def test_resolve_string_from_partial(self):
        """ resolve values from variables where list has partial variables """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("Kupperbush").append("kid creole")
        self.cvl.get_configVar_obj("bush").append("bush")
        resolved = self.cvl.resolve_string("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve_string("$(Kupperbush)")
        self.assertEqual(resolved, "kid creole")
        resolved = self.cvl.resolve_string("Kupper$(bush)")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve_string("$(Kupper$(bush))")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_1(self):
        """ resolve values from variables with single value with non-default separator """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("Kupperbush").append("kid creole")
        self.cvl.get_configVar_obj("bush").append("bush")
        resolved = self.cvl.resolve_string("Kupperbush", sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve_string("$(Kupperbush)", sep="-")
        self.assertEqual(resolved, "kid creole")
        resolved = self.cvl.resolve_string("Kupper$(bush)", sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve_string("$(Kupper$(bush))", sep="-")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_2(self):
        """ resolve values from variables with multi value with non-default separator """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("name").extend(("kid","creole"))
        self.cvl.get_configVar_obj("beer").extend(("Anheuser", "Busch"))
        resolved = self.cvl.resolve_string("$(name) drinks $(beer)", sep="-")
        self.assertEqual(resolved, "kid creole drinks Anheuser Busch")
        resolved = self.cvl.resolve_string("$(name)", sep="-")
        self.assertEqual(resolved, "kid-creole")
        resolved = self.cvl.resolve_string("$(beer)", sep="-")
        self.assertEqual(resolved, "Anheuser-Busch")

