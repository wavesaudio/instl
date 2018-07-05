#!/usr/bin/env python3


import sys
import os
import unittest

from configVar import old_configVarList
from configVar import newConfigVar


sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))


class TestConfigVarList(unittest.TestCase):
    def setUp(self):
        self.cvl = newConfigVar.ConfigVarStack()

    def tearDown(self):
        del self.cvl

    def test_a_resolve_array(self):
        self.cvl["A"]= ("a", "b", "c")
        resolved_str = self.cvl.ResolveStrToStr("$(A[0]), $(A[1]), $(A[2]), $(A[3])", list_sep="&")
        self.assertEqual(resolved_str, "a, b, c, $(A[3])")
        resolved_str = self.cvl.ResolveStrToStr("$(A[0]), $(A[1]), $(A[2]), $(A[3])", default="lady gaga", list_sep="&")
        self.assertEqual(resolved_str, "a, b, c, lady gaga")

        self.cvl.set_var("zero").append("0")
        self.cvl.set_var("one").append("1")
        self.cvl.set_var("two").append("2")
        self.cvl.set_var("three").append("3")
        resolved_str = self.cvl.ResolveStrToStr("$(A[$(zero)]), $(A[$(one)]), $(A[$(two)]), $(A[$(three)])", list_sep="&")
        self.assertEqual(resolved_str, "a, b, c, $(A[3])")
        resolved_str = self.cvl.ResolveStrToStr("$(A[$(zero)]), $(A[$(one)]), $(A[$(two)]), $(A[$(three)])",
                                        default="lady godiva", list_sep="&")
        self.assertEqual(resolved_str, "a, b, c, lady godiva")

        self.cvl.set_var("numbers").extend(("0", "1", "2", "3"))
        resolved_str = self.cvl.ResolveStrToStr(
            "$(A[$(numbers[0])]), $(A[$(numbers[1])]), $(A[$(numbers[2])]), $(A[$(numbers[3])])", list_sep="&")
        self.assertEqual(resolved_str, "a, b, c, $(A[3])")
        resolved_str = self.cvl.ResolveStrToStr(
            "$(A[$(numbers[0])]), $(A[$(numbers[1])]), $(A[$(numbers[2])]), $(A[$(numbers[3])])",
            default="lady madonna", list_sep="&")
        self.assertEqual(resolved_str, "a, b, c, lady madonna")

    def test_resolve_to_list(self):
        self.cvl.set_var("A").extend(("a", "b", "c"))
        resolved_str = self.cvl.ResolveStrToStr("$(A)", list_sep="&")
        self.assertEqual(resolved_str, "a&b&c")

        resolved_list = self.cvl.ResolveStrToList("$(A)", list_sep="&")
        self.assertEqual(resolved_list, ["a", "b", "c"])

        resolved_list = self.cvl.ResolveStrToList("_$(A)_", list_sep="&")
        self.assertEqual(resolved_list, ["_a&b&c_"])

        self.cvl.set_var("B").extend(("$(A)", "nunchaku", "$(A)"))
        resolved_list = self.cvl.ResolveStrToList("$(B)", list_sep="&")
        self.assertEqual(resolved_list, ["a", "b", "c", "nunchaku", "a", "b", "c"])

        self.cvl.set_var("C").extend(("$(A)", "nunchaku", "-$(A)"))
        resolved_list = self.cvl.ResolveStrToList("$(C)", list_sep="&")
        self.assertEqual(resolved_list, ["a", "b", "c", "nunchaku", "-a&b&c"])

    def test_resolve(self):
        self.cvl.set_var("A").extend(("a", "a", "a"))
        self.cvl.set_var("B").append("$(Bee)")
        self.cvl.set_var("Bee").append("bbb")
        self.cvl.set_var("C").extend(("$(B)",))
        self.cvl.set_var("LastName").append("$(LastName_for_$(FirstName))")
        self.cvl.set_var("LastName_for_Shai").append("Shasag")
        self.cvl.set_var("LastName_for_Chilik").append("Maymoni")

        self.cvl.set_var("FirstName").append("Shai")
        resolved = self.cvl.ResolveStrToStr("$(A)$(D)$(B)$(C) - $(LastName)", list_sep=".")
        self.assertEqual(resolved, "a.a.a$(D)bbbbbb - Shasag")

        self.cvl.set_var("FirstName").append("Chilik")
        resolved = self.cvl.ResolveStrToStr("$(A)$(D)$(B)$(C) - $(LastName)", list_sep=".")
        self.assertEqual(resolved, "a.a.a$(D)bbbbbb - Maymoni")

        self.cvl.set_var("FirstName").append("$(LastName)")
        with self.assertRaises(Exception):
            resolved = self.cvl.ResolveStrToStr("$(A)$(D)$(B)$(C) - $(LastName)", list_sep=".")

    def test_construction_empty(self):
        """ Construct ConfigVarList without values. """
        self.assertEqual(len(self.cvl), 0)
        self.assertFalse("no man's land" in self.cvl)
        with self.assertRaises(KeyError):
            self.cvl["no man's land"]
        self.assertEqual(self.cvl.ResolveStrToStr("no man's land"), "no man's land")
        self.assertEqual(self.cvl.ResolveStrToStr("$(no man's land)"), "$(no man's land)")
        self.assertEqual(list(self.cvl.keys()), [])

    def test_set_variable_new(self):
        """ Set one variable. """
        self.cvl.set_var("banana", "phone")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(self.cvl.get_configVar_obj("banana").description, "phone")
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.assertEqual(self.cvl.ResolveStrToList("$(banana)"), ["get", "down", "tonight"])
        self.assertEqual(self.cvl.ResolveStrToStr("$(banana)"), "get down tonight")
        self.assertEqual(list(self.cvl.keys()), ["banana"])

    def test_set_variable_reset(self):
        """ Set one variable, reset it. """
        self.cvl.set_var("banana", "phone")
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        self.cvl.set_var("banana", "kirk")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(self.cvl.get_configVar_obj("banana").description, "kirk")
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("set", "up", "tomorrow"))
        self.assertEqual(self.cvl.ResolveVarToList("banana"), ["set", "up", "tomorrow"])
        self.assertEqual(self.cvl.ResolveStrToStr("$(banana)"), "set up tomorrow")
        self.assertEqual(list(self.cvl.keys()), ["banana"])

    def test_get_configVar_obj(self):
        """ Set one variable, by getting it. """
        self.cvl.get_configVar_obj("banana")
        self.assertEqual(len(self.cvl), 1)
        self.assertTrue("banana" in self.cvl)
        self.assertIs(self.cvl.get_configVar_obj("banana"), self.cvl["banana"])
        self.assertEqual(len(self.cvl), 1)
        self.cvl.get_configVar_obj("banana").extend(("get", "down", "tonight"))
        resolved_list = [self.cvl.ResolveStrToStr(val) for val in self.cvl["banana"]]
        self.assertSequenceEqual(resolved_list, ("get", "down", "tonight"))
        self.assertEqual(self.cvl.ResolveStrToStr("$(banana)"), "get down tonight")
        self.assertEqual(list(self.cvl.keys()), ["banana"])

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
        self.assertEqual(self.cvl.ResolveStrToList("$(banana)"), self.cvl.ResolveStrToList("$(oranges)"))
        self.assertEqual(self.cvl.ResolveStrToStr("$(banana)"), self.cvl.ResolveStrToStr("$(oranges)"))
        self.assertEqual(sorted(self.cvl.keys()), ["banana", "oranges"])

    def test_duplicate_variable_bad(self):
        """ Dont's create variable, duplicate it anyway"""
        self.cvl.get_configVar_obj("banana")
        self.cvl.get_configVar_obj("banana").extend(("grease", "is", "the", "world"))
        self.assertEqual(len(self.cvl), 1)
        with self.assertRaises(KeyError):
            self.cvl.duplicate_variable("peaches", "oranges")
        self.assertEqual(len(self.cvl), 1)
        self.assertEqual(self.cvl.ResolveStrToList("$(oranges)"), ["$(oranges)"])
        self.assertEqual(self.cvl.ResolveStrToStr("$(oranges)"), "$(oranges)")
        self.assertEqual(sorted(self.cvl.keys()), ["banana"])

    def test_resolve_string_from_nothing(self):
        """ resolve values from variables where list is empty """
        resolved = self.cvl.ResolveStrToStr("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.ResolveStrToStr("$(Kupperbush)")
        self.assertEqual(resolved, "$(Kupperbush)")
        resolved = self.cvl.ResolveStrToStr("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper$(bush)")
        resolved = self.cvl.ResolveStrToStr("$(Kupper$(bush))")
        self.assertEqual(resolved, "$(Kupper$(bush))")

    def test_resolve_string_from_empty(self):
        """ resolve values from variables where list has empty variables """
        self.cvl.get_configVar_obj("Kupperbush")
        self.cvl.get_configVar_obj("bush")
        resolved = self.cvl.ResolveStrToStr("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.ResolveStrToStr("$(Kupperbush)")
        self.assertEqual(resolved, "")
        resolved = self.cvl.ResolveStrToStr("Kupper$(bush)")
        self.assertEqual(resolved, "Kupper")
        resolved = self.cvl.ResolveStrToStr("$(Kupper$(bush))")
        self.assertEqual(resolved, "$(Kupper)")

    def test_resolve_string_from_partial(self):
        """ resolve values from variables where list has partial variables """
        self.cvl = old_configVarList.ConfigVarList()
        self.cvl.get_configVar_obj("Kupperbush").append("kid creole")
        self.cvl.get_configVar_obj("bush").append("bush")
        resolved = self.cvl.ResolveStrToStr("Kupperbush")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.ResolveStrToStr("$(Kupperbush)")
        self.assertEqual(resolved, "kid creole")
        resolved = self.cvl.ResolveStrToStr("Kupper$(bush)")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.ResolveStrToStr("$(Kupper$(bush))")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_1(self):
        """ resolve values from variables with single value with non-default separator """
        self.cvl.get_configVar_obj("Kupperbush").append("kid creole")
        self.cvl.get_configVar_obj("bush").append("bush")
        resolved = self.cvl.ResolveStrToStr("Kupperbush", list_sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.ResolveStrToStr("$(Kupperbush)", list_sep="-")
        self.assertEqual(resolved, "kid creole")
        resolved = self.cvl.ResolveStrToStr("Kupper$(bush)", list_sep="-")
        self.assertEqual(resolved, "Kupperbush")
        resolved = self.cvl.ResolveStrToStr("$(Kupper$(bush))", list_sep="-")
        self.assertEqual(resolved, "kid creole")

    def test_resolve_string_with_separator_2(self):
        """ resolve values from variables with multi value with non-default separator """
        self.cvl.get_configVar_obj("name").extend(("kid", "creole"))
        self.cvl.get_configVar_obj("beer").extend(("Anheuser", "Busch"))
        resolved = self.cvl.ResolveStrToStr("$(name) drinks $(beer)", list_sep="-")
        self.assertEqual(resolved, "kid-creole drinks Anheuser-Busch")
        resolved = self.cvl.ResolveStrToStr("$(name)", list_sep="-")
        self.assertEqual(resolved, "kid-creole")
        resolved = self.cvl.ResolveStrToStr("$(beer)", list_sep="-")
        self.assertEqual(resolved, "Anheuser-Busch")

