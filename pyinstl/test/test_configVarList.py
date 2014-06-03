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

    def test_resolve_to_list(self):
        self.cvl.set_var("A").extend( ("a", "b", "c") )
        resolved_list = self.cvl.resolve_to_list("$(A)", list_sep="&")
        self.assertEqual(resolved_list, ["a", "b", "c"])

        resolved_list = self.cvl.resolve_to_list("_$(A)_", list_sep="&")
        self.assertEqual(resolved_list, ["_a&b&c_"])

        self.cvl.set_var("B").extend( ("$(A)", "nunchaku", "$(A)") )
        resolved_list = self.cvl.resolve_to_list("$(B)", list_sep="&")
        self.assertEqual(resolved_list, ["a", "b", "c", "nunchaku", "a", "b", "c"])

        self.cvl.set_var("C").extend( ("$(A)", "nunchaku", "-$(A)") )
        resolved_list = self.cvl.resolve_to_list("$(C)", list_sep="&")
        self.assertEqual(resolved_list, ["a", "b", "c", "nunchaku", "-a&b&c"])

    def test_resolve(self):
        self.cvl.set_var("A").extend( ("a", "a", "a") )
        self.cvl.set_var("B").append("$(Bee)")
        self.cvl.set_var("Bee").append("bbb")
        self.cvl.set_var("C").extend( ("$(B)",))
        self.cvl.set_var("LastName").append("$(LastName_for_$(FirstName))")
        self.cvl.set_var("LastName_for_Shai").append("Shasag")
        self.cvl.set_var("LastName_for_Chilik").append("Maymoni")

        self.cvl.set_var("FirstName").append("Shai")
        resolved = self.cvl.resolve("$(A)$(D)$(B)$(C) - $(LastName)", list_sep=".")
        self.assertEqual(resolved, "a.a.a$(D)bbbbbb - Shasag")

        self.cvl.set_var("FirstName").append("Chilik")
        resolved = self.cvl.resolve("$(A)$(D)$(B)$(C) - $(LastName)", list_sep=".")
        self.assertEqual(resolved, "a.a.a$(D)bbbbbb - Maymoni")

        self.cvl.set_var("FirstName").append("$(LastName)")
        with self.assertRaises(Exception):
            resolved = self.cvl.resolve("$(A)$(D)$(B)$(C) - $(LastName)", list_sep=".")

    def test_construction_empty(self):
        """ Construct ConfigVarList without values. """
        self.assertEqual(len(self.cvl), 0)
        self.assertFalse("no man's land" in self.cvl)
        with self.assertRaises(KeyError):
            self.cvl["no man's land"]
        self.assertEqual(self.cvl.resolve("no man's land"), "no man's land")
        self.assertEqual(self.cvl.resolve("$(no man's land)"), "$(no man's land)")
        self.assertEqual(self.cvl.keys(), [])

    def test_set_variable_new(self):
        """ Set one variable. """
        self.cvl.set_var("banana", "phone")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(self.cvl.get_configVar_obj("banana").description(), "phone")
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.assertEqual(self.cvl.resolve_to_list("$(banana)"), ["get", "down", "tonight"])
        self.assertEqual(self.cvl.resolve("$(banana)"), "get down tonight")
        self.assertEqual(self.cvl.keys(), ["banana"])

    def test_set_variable_reset(self):
        """ Set one variable, reset it. """
        self.cvl.set_var("banana", "phone")
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.cvl.set_var("banana", "kirk")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(self.cvl.get_configVar_obj("banana").description(), "kirk")
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("set", "up", "tomorrow"))
        self.assertEqual(self.cvl.resolve_to_list("$(banana)"), ["set", "up", "tomorrow"])
        self.assertEqual(self.cvl.resolve("$(banana)"), "set up tomorrow")
        self.assertEqual(self.cvl.keys(), ["banana"])

    def test_get_configVar_obj(self):
        """ Set one variable, by getting it. """
        self.cvl.get_configVar_obj("banana")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        resolved_list = [self.cvl.resolve(val) for val in self.cvl["banana"]]
        self.assertSequenceEqual(resolved_list, ("get", "down", "tonight"))
        self.assertEqual(self.cvl.resolve("$(banana)"), "get down tonight")
        self.assertEqual(self.cvl.keys(), ["banana"])

    def test_del(self):
        """ Set one variable, and delete it. """
        self.cvl.get_configVar_obj("banana")
        self.assertEqual(len(self.cvl), 1)
        del self.cvl["banana"]
        self.assertFalse("banana" in self.cvl)
        self.assertEqual(len(self.cvl), 0)

    def test_duplicate_variable_good(self):
        """ Create variable, duplicate it """
        self.cvl.get_configVar_obj("banana")
        self.cvl.get_configVar_obj("banana").extend(("grease", "is", "the", "world"))
        self.assertEqual(len(self.cvl), 1)
        self.cvl.duplicate_variable("banana", "oranges")
        self.assertEqual(len(self.cvl), 2)
        self.assertEqual(self.cvl.resolve_to_list("$(banana)"), self.cvl.resolve_to_list("$(oranges)"))
        self.assertEqual(self.cvl.resolve("$(banana)"), self.cvl.resolve("$(oranges)"))
        self.assertEqual(sorted(self.cvl.keys()), ["banana", "oranges"])

    def test_duplicate_variable_bad(self):
        """ Dont's create variable, duplicate it anyway"""
        self.cvl.get_configVar_obj("banana")
        self.cvl.get_configVar_obj("banana").extend(("grease", "is", "the", "world"))
        self.assertEqual(len(self.cvl), 1)
        with self.assertRaises(KeyError):
            self.cvl.duplicate_variable("peaches", "oranges")
        self.assertEqual(len(self.cvl), 1)
        self.assertEqual(self.cvl.resolve_to_list("$(oranges)"), ["$(oranges)"])
        self.assertEqual(self.cvl.resolve("$(oranges)"), "$(oranges)")
        self.assertEqual(sorted(self.cvl.keys()), ["banana"])

    def test_resolve_string_from_nothing(self):
        """ resolve values from variables where list is empty """
        resolved = self.cvl.resolve("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve("$(Kupperbush)")
        self.assertEqual(resolved, "$(Kupperbush)")
        resolved = self.cvl.resolve("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper$(bush)")
        resolved = self.cvl.resolve("$(Kupper$(bush))")
        self.assertEqual(resolved, "$(Kupper$(bush))")

    def test_resolve_string_from_empty(self):
        """ resolve values from variables where list has empty variables """
        self.cvl.get_configVar_obj("Kupperbush")
        self.cvl.get_configVar_obj("bush")
        resolved = self.cvl.resolve("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve("$(Kupperbush)")
        self.assertEqual(resolved, "")
        resolved = self.cvl.resolve("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper")
        resolved = self.cvl.resolve("$(Kupper$(bush))")
        self.assertEqual(resolved, "$(Kupper)")

    def test_resolve_string_from_partial(self):
        """ resolve values from variables where list has partial variables """
        self.cvl = configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("Kupperbush").append("kid creole")
        self.cvl.get_configVar_obj("bush").append("bush")
        resolved = self.cvl.resolve("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve("$(Kupperbush)")
        self.assertEqual(resolved, "kid creole")
        resolved = self.cvl.resolve("Kupper$(bush)")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve("$(Kupper$(bush))")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_1(self):
        """ resolve values from variables with single value with non-default separator """
        self.cvl.get_configVar_obj("Kupperbush").append("kid creole")
        self.cvl.get_configVar_obj("bush").append("bush")
        resolved = self.cvl.resolve("Kupperbush", list_sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve("$(Kupperbush)", list_sep="-")
        self.assertEqual(resolved, "kid creole")
        resolved = self.cvl.resolve("Kupper$(bush)", list_sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.resolve("$(Kupper$(bush))", list_sep="-")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_2(self):
        """ resolve values from variables with multi value with non-default separator """
        self.cvl.get_configVar_obj("name").extend(("kid","creole"))
        self.cvl.get_configVar_obj("beer").extend(("Anheuser", "Busch"))
        resolved = self.cvl.resolve("$(name) drinks $(beer)", list_sep="-")
        self.assertEqual(resolved, "kid-creole drinks Anheuser-Busch")
        resolved = self.cvl.resolve("$(name)", list_sep="-")
        self.assertEqual(resolved, "kid-creole")
        resolved = self.cvl.resolve("$(beer)", list_sep="-")
        self.assertEqual(resolved, "Anheuser-Busch")

