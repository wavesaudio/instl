#!/usr/bin/env python3.12

"""CHARACTERIZATION (golden/snapshot) tests for configVar ($()) resolution.

These tests LOCK the current observable behavior of the ``ConfigVarStack``
resolution engine before refactoring:

  * plain ``$(VAR)`` resolution (including var-in-var chains and list joining),
  * indexed ``$(VAR[n])`` access (positive and negative indices),
  * parameterized ``$(VAR<...>)`` forms (positional ``<v1,v2>`` -> ``__VAR_1__``
    and keyword ``<K=k>`` injection into a temporary scope),
  * ``!define`` vs ``!define_const`` vs ``!define_if_not_exist`` semantics as
    read from YAML (the exact current, somewhat surprising, behavior).

Style/fixtures follow the existing ``configVar/test/testConfigVar.py``: a
``unittest.TestCase`` that clears ``config_vars`` in ``setUp`` and asserts exact
resolved strings. Hermetic and deterministic (no network, no real repo).
"""

import sys
import os
import unittest
import tempfile

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))

import utils  # noqa: F401  do not remove, prevents cyclic import problems
from configVar import config_vars
from configVar import ConfigVarYamlReader


class TestConfigVarResolutionGolden(unittest.TestCase):
    """Pins the current $() resolution outputs of ConfigVarStack."""

    def setUp(self):
        config_vars.clear()

    def tearDown(self):
        config_vars.clear()

    # ------------------------------------------------------------------
    # plain $(VAR) resolution
    # ------------------------------------------------------------------
    def test_simple_resolution(self):
        config_vars["WHO"] = "World"
        self.assertEqual("Hello World!", config_vars.resolve_str("Hello $(WHO)!"))
        # a string with no resolve indicator passes through untouched
        self.assertEqual("no vars here", config_vars.resolve_str("no vars here"))

    def test_var_in_var_chain(self):
        # $(A) -> $(B) -> $(C) -> literal
        config_vars["A"] = "$(B)"
        config_vars["B"] = "$(C)"
        config_vars["C"] = "ali baba"
        self.assertEqual("ali baba", config_vars["A"].str())
        self.assertEqual("ali baba", config_vars.resolve_str("$(A)"))

    def test_list_join_on_resolution(self):
        # a list-valued configVar joins its parts with no separator when resolved
        config_vars["PARTS"] = "1", "2", "3"
        self.assertEqual("123", config_vars["PARTS"].str())
        self.assertEqual("123", config_vars.resolve_str("$(PARTS)"))

    # ------------------------------------------------------------------
    # indexed $(VAR[n]) access
    # ------------------------------------------------------------------
    def test_index_positive(self):
        config_vars["L"] = "10", "20", "30"
        self.assertEqual("10", config_vars.resolve_str("$(L[0])"))
        self.assertEqual("20", config_vars.resolve_str("$(L[1])"))
        self.assertEqual("30", config_vars.resolve_str("$(L[2])"))
        # composing several indexed refs in one string
        self.assertEqual("302010",
                         config_vars.resolve_str("$(L[2])$(L[1])$(L[0])"))

    def test_index_negative(self):
        # negative indices are normalized to count from the end
        config_vars["L"] = "10", "20", "30"
        self.assertEqual("30", config_vars.resolve_str("$(L[-1])"))
        self.assertEqual("20", config_vars.resolve_str("$(L[-2])"))

    # ------------------------------------------------------------------
    # parameterized $(VAR<...>) forms
    # ------------------------------------------------------------------
    def test_parameterized_keyword(self):
        # $(VAR<K=k>) injects K=k into a temporary scope while resolving VAR
        config_vars["GREET"] = "Hello $(WHO)!"
        self.assertEqual("Hello World!",
                         config_vars.resolve_str("$(GREET<WHO=World>)"))
        # the injected parameter must NOT leak outside the resolution scope
        self.assertNotIn("WHO", config_vars)

    def test_parameterized_positional(self):
        # $(VAR<v1,v2>) creates positional params __VAR_1__, __VAR_2__
        config_vars["ADD"] = "$(__ADD_1__)+$(__ADD_2__)"
        self.assertEqual("1+2", config_vars.resolve_str("$(ADD<1,2>)"))
        self.assertNotIn("__ADD_1__", config_vars)
        self.assertNotIn("__ADD_2__", config_vars)

    def test_empty_parameter_list_unresolved_passthrough(self):
        # $(MAMA_MIA<>) on an undefined var passes through as the raw ref text;
        # this pins the parser's unresolved-passthrough behavior.
        self.assertEqual("$(MAMA_MIA<>)",
                         config_vars.resolve_str("$(MAMA_MIA<>)"))

    # ------------------------------------------------------------------
    # define vs define_const vs define_if_not_exist (read from YAML)
    # ------------------------------------------------------------------
    def _read_yaml(self, yaml_text):
        with tempfile.NamedTemporaryFile(
                "w", suffix=".yaml", delete=False, encoding="utf-8") as wfd:
            wfd.write(yaml_text)
            path = wfd.name
        try:
            ConfigVarYamlReader(config_vars).read_yaml_file(path)
        finally:
            os.unlink(path)

    def test_define_const_is_deprecated_and_overwrites(self):
        """!define_const is deprecated: it is read as a plain (non-const) define
        and therefore OVERWRITES a previously defined value.

        This is the exact current behavior we are locking before refactor.
        """
        self._read_yaml(
            "--- !define\n"
            "A: first\n"
            "--- !define_const\n"
            "A: second\n"
            "B: const_b\n"
        )
        # !define_const overwrote A despite the 'const' name (deprecated).
        self.assertEqual("second", config_vars["A"].str())
        self.assertEqual("const_b", config_vars["B"].str())

    def test_define_if_not_exist_only_sets_new_keys(self):
        """!define_if_not_exist sets a key only when it does not already exist."""
        self._read_yaml(
            "--- !define\n"
            "A: original\n"
            "--- !define_if_not_exist\n"
            "A: ignored_because_exists\n"
            "C: only_if_new\n"
        )
        self.assertEqual("original", config_vars["A"].str())
        self.assertEqual("only_if_new", config_vars["C"].str())

    def test_plain_define_overwrites(self):
        """A later !define block overwrites an earlier value for the same key."""
        self._read_yaml(
            "--- !define\n"
            "A: first\n"
            "--- !define\n"
            "A: second\n"
        )
        self.assertEqual("second", config_vars["A"].str())


if __name__ == "__main__":
    unittest.main()
