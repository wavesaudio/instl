#!/usr/local/bin/python2.7

from __future__ import print_function

import sys
import os
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
import configVar

class TestConfigVar(unittest.TestCase):

    def setUp(self):
        """ Create ConfigVar objects indirectly so it's possible for 
            TestConstConfigVar to override TestConfigVar.
        """
        self.constructor = configVar.ConfigVar
    def tearDown(self):
        pass

    def test_construction_with_name_only(self):
        """ Construct ConfigVar without values, without description. """
        cv1 = self.constructor("test_construction_with_name_only")
        self.assertEqual(cv1.name(), "test_construction_with_name_only")
        self.assertEqual(cv1.description(), "")
        self.assertEqual(len(cv1), 0)

    def test_construction_with_name_and_description(self):
        """ Construct ConfigVar without values, with description. """
        cv2 = self.constructor("test_construction_with_name_and_description", "some text")
        self.assertEqual(cv2.name(), "test_construction_with_name_and_description")
        self.assertEqual(cv2.description(), "some text")
        self.assertEqual(len(cv2), 0)

    def test_set_description_from_empty(self):
        """ Change description after construction with empty description. """
        cv3 = self.constructor("test_set_description_from_empty")
        self.assertEqual(cv3.name(), "test_set_description_from_empty")
        self.assertEqual(cv3.description(), "")
        cv3.set_description("New description 3")
        self.assertEqual(cv3.description(), "New description 3")
        self.assertEqual(len(cv3), 0)

    def test_set_description_from_initial(self):
        """ Change description after construction with initial description. """
        cv4 = self.constructor("test_set_description_from_initial", "some initial description")
        self.assertEqual(cv4.name(), "test_set_description_from_initial")
        self.assertEqual(cv4.description(), "some initial description")
        cv4.set_description("New description 4")
        self.assertEqual(cv4.description(), "New description 4")
        self.assertEqual(len(cv4), 0)

    def test_construction_with_single_value(self):
        """ Construct ConfigVar with single value, with description. """
        cv5 = self.constructor("test_construction_with_single_value", "some initial description", "mambo jumbo")
        self.assertEqual(cv5.name(), "test_construction_with_single_value")
        self.assertEqual(cv5.description(), "some initial description")
        self.assertEqual(len(cv5), 1)
        self.assertEqual(cv5[0], "mambo jumbo")

    def test_construction_with_multiple_values(self):
        """ Construct ConfigVar with multiple values, with description. """
        cv5 = self.constructor("test_construction_with_multiple_values", "some initial description", "methodist", "alchemist", "pessimist")
        self.assertEqual(cv5.name(), "test_construction_with_multiple_values")
        self.assertEqual(cv5.description(), "some initial description")
        self.assertEqual(len(cv5), 3)
        self.assertEqual(tuple(cv5), ("methodist", "alchemist", "pessimist"))

    def test_construction_with_list_of_values(self):
        """ Construct ConfigVar with a list of multiple values, with description. """
        cv6 = self.constructor("test_construction_with_list_of_values", "some initial description", *["methodist", "alchemist", "pessimist"])
        self.assertEqual(cv6.name(), "test_construction_with_list_of_values")
        self.assertEqual(cv6.description(), "some initial description")
        self.assertEqual(len(cv6), 3)
        self.assertEqual(tuple(cv6), ("methodist", "alchemist", "pessimist"))

    def test_construction_with_non_string_values(self):
        """ Construct ConfigVar with multiple values that are not string, with description.
            Non string values should be converted to strings on assignment. """
        cv7 = self.constructor("test_construction_with_non_string_values", "some initial description", 1, 2.0, ("smutsmik", "beatnik"))
        self.assertEqual(cv7.name(), "test_construction_with_non_string_values")
        self.assertEqual(cv7.description(), "some initial description")
        self.assertEqual(len(cv7), 3)
        self.assertEqual(cv7[0], "1")
        self.assertNotEqual(cv7[0], 1)
        self.assertEqual(cv7[1], "2.0")
        self.assertNotEqual(cv7[1], 2.0)
        self.assertEqual(cv7[2], "('smutsmik', 'beatnik')")

    def test_append_values(self):
        """ Call append """
        cv8 = self.constructor("test_append_values")
        cv8.append("one")
        self.assertEqual(len(cv8), 1)
        self.assertEqual(tuple(cv8), ("one",))
        cv8.append("two")
        self.assertEqual(len(cv8), 2)
        self.assertEqual(tuple(cv8), ("one", "two"))

    def test_extend_values(self):
        """ Call extend """
        cv9 = self.constructor("sababa9")
        self.assertEqual(cv9.name(), "sababa9")
        cv9.extend(("one","two"))
        self.assertEqual(len(cv9), 2)
        self.assertEqual(tuple(cv9), ("one", "two"))
        cv9.extend(("three","four"))
        self.assertEqual(len(cv9), 4)
        self.assertEqual(tuple(cv9), ("one", "two", "three", "four"))

    def test_clear_values(self):
        """ Call clear_values """
        cv10 = self.constructor("test_clear_values")
        cv10.extend(("one","two"))
        self.assertEqual(len(cv10), 2)
        self.assertEqual(tuple(cv10), ("one", "two"))
        cv10.clear_values()
        self.assertEqual(len(cv10), 0)

    def test___setitem__(self):
        """ Call __setitem__ """
        cv11 = self.constructor("test___setitem__")
        cv11.extend(("one","two"))
        self.assertEqual(len(cv11), 2)
        self.assertEqual(tuple(cv11), ("one", "two"))
        cv11[1] = "mel-u-michel"
        self.assertEqual(len(cv11), 2)
        self.assertEqual(tuple(cv11), ("one", "mel-u-michel"))
        cv11[0] = "shevet-achim-gum-yachad"
        self.assertEqual(len(cv11), 2)
        self.assertEqual(tuple(cv11), ("shevet-achim-gum-yachad", "mel-u-michel"))

    def test___delitem__(self):
        """ Call __delitem__ """
        cv12 = self.constructor("test___delitem__")
        cv12.extend(("one","two", "three"))
        self.assertEqual(len(cv12), 3)
        self.assertEqual(tuple(cv12), ("one", "two", "three"))
        del cv12[1]
        self.assertEqual(tuple(cv12), ("one", "three"))
        del cv12[1]
        self.assertEqual(tuple(cv12), ("one", ))
        del cv12[0]
        self.assertEqual(tuple(cv12), ())

    def test___iter__(self):
        """ Call __iter__ """
        cv13 = self.constructor("test___iter__")
        cv13.extend(("one","two", "three"))
        self.assertEqual(len(cv13), 3)
        self.assertEqual(list(("one","two", "three")), [item for item in cv13.__iter__()])

    def test_reverse(self):
        """ Call reverse """
        cv14 = self.constructor("test_reverse")
        cv14.extend(("one","two", "three"))
        self.assertEqual(len(cv14), 3)
        self.assertEqual(tuple(reversed(cv14)), ("three","two", "one"))

class TestConstConfigVar(TestConfigVar):
    """ inherit tests from TestConfigVar, override those that should raise exceptions,
        and those that should be implemented differently.
    """
    
    def setUp(self):
        self.constructor = configVar.ConstConfigVar
    
    def test_set_description_from_empty(self):
        """ Change description after construction with empty description. """
        with self.assertRaises(Exception):
            super(TestConstConfigVar, self).test_set_description_from_empty()

    def test_set_description_from_initial(self):
        """ Change description after construction with initial description. """
        with self.assertRaises(Exception):
            super(TestConstConfigVar, self).test_set_description_from_initial()

    def test___setitem__(self):
        """ Call __setitem__ """
        with self.assertRaises(Exception):
            super(TestConstConfigVar, self).test___setitem__()

    def test___delitem__(self):
        """ Call __delitem__ """
        with self.assertRaises(Exception):
            super(TestConstConfigVar, self).test___delitem__()
    
    def test_append_values(self):
        """ Call append """
        with self.assertRaises(Exception):
            super(TestConstConfigVar, self).test_append_values()

    def test_extend_values(self):
        """ Call extend """
        with self.assertRaises(Exception):
            super(TestConstConfigVar, self).test_extend_values()

    def test_clear_values(self):
        """ Call clear_values """
        with self.assertRaises(Exception):
            super(TestConstConfigVar, self).test_clear_values()

    def test___iter__(self):
        """ Call __iter__ """
        cv13 = self.constructor("test___iter__", "", *("one","two", "three"))
        self.assertEqual(len(cv13), 3)
        self.assertEqual(list(("one","two", "three")), [item for item in cv13.__iter__()])

    def test_reverse(self):
        """ Call reverse """
        cv14 = self.constructor("test_reverse", "", *("one","two", "three"))
        self.assertEqual(len(cv14), 3)
        self.assertEqual(tuple(reversed(cv14)), ("three","two", "one"))
