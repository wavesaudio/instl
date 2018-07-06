#!/usr/bin/env python3.6

import sys
import os
import unittest
import pathlib

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..")))

from configVar import config_vars
from configVar import ConfigVarYamlReader
import aYaml

def normalize_yaml_lines(yaml_file):
    retVal = list()
    with open(yaml_file, "r") as rfd:
        for line in rfd.readlines():
            striped_line = line.strip()
            if striped_line:
                retVal.append(striped_line)
    return retVal

class TestConfigVar(unittest.TestCase):
    def setUp(self):
        config_vars.clear()

    def tearDown(self):
        pass

    def test_format(self):

        config_vars["Number"] = "434"
        config_vars["Ricki"] = ["Joe", "Merlin", "1938"]

        str1 = f"""{config_vars["Ricki"]}{config_vars["Number"].int()}{config_vars["Ricki"].list()}"""
        self.assertEqual("JoeMerlin1938434['Joe', 'Merlin', '1938']", str1)

    def test_defaults(self):
        empty_list = config_vars.get("MAMBO_JUMBO", []).list()
        self.assertEqual([], empty_list)

        full_list = config_vars.get("MAMBO_JUMBO", ["mambo", "jumbo"]).list()
        self.assertEqual(["mambo", "jumbo"], full_list)

        empty_str = config_vars.get("MAMBO_JUMBO", "").str()
        self.assertEqual("", empty_str)

        full_str = config_vars.get("MAMBO_JUMBO", "mambo jumbo").str()
        self.assertEqual("mambo jumbo", full_str)

    def test_bool(self):
        # non exiting ConfigVar should resolve to False
        self.assertFalse(config_vars.get("BEN_SHAPIRO"))

    def test_var_in_var_simple(self):
        config_vars["A"] = "$(B)"
        config_vars["B"] = "$(C)"
        config_vars["C"] = "ali baba"
        self.assertEqual("ali baba", config_vars["A"].str())
        self.assertEqual("ali baba", config_vars.resolve_str("$(A)"))

    def test_array(self):
        config_vars["PUSHKIN"] ="1", "2", "3"
        self.assertEqual("123", config_vars["PUSHKIN"].str())
        self.assertEqual("123", config_vars.resolve_str("$(PUSHKIN)"))
        self.assertEqual("1", config_vars.resolve_str("$(PUSHKIN[0])"))
        self.assertEqual("2", config_vars.resolve_str("$(PUSHKIN[1])"))
        self.assertEqual("3", config_vars.resolve_str("$(PUSHKIN[2])"))
        self.assertEqual("321", config_vars.resolve_str("$(PUSHKIN[2])$(PUSHKIN[1])$(PUSHKIN[0])"))

    def test_readFile(self):
        input_file_path = pathlib.Path(__file__).parent.joinpath("test_input.yaml")
        out_file_path = pathlib.Path(__file__).parent.joinpath("test_out.yaml")
        expected_file_path = pathlib.Path(__file__).parent.joinpath("expected_output.yaml")

        reader = ConfigVarYamlReader()
        reader.read_yaml_file(input_file_path)
        variables_as_yaml = config_vars.repr_for_yaml()
        yaml_doc = aYaml.YamlDumpDocWrap(variables_as_yaml, '!define', "",
                                              explicit_start=True, sort_mappings=True)
        with open(out_file_path, "w") as wfd:
            aYaml.writeAsYaml(yaml_doc, wfd)

        out_lines = normalize_yaml_lines(out_file_path)
        expected_lines = normalize_yaml_lines(expected_file_path)

        self.assertEqual(out_lines, expected_lines)

    def test_resolve_time(self):
        config_vars["PRINT_STATISTICS"] = "True"

        config_vars["MANDOLIN"] = "a$(A)b$(B)c$(C)d", "a$(A)b$(B)c$(C)d", "a$(A)b$(B)c$(C)d"
        config_vars["A"] = "$(B)$(B<>)$(C)"
        config_vars["B"] = "$(C)$(C<>)$(H)"
        config_vars["C"] = "bub"

        for i in range(10000):
            a = config_vars["MANDOLIN"].str()
        config_vars.print_statistics()

        print(str(config_vars["MANDOLIN"]))
