#!/usr/bin/env python3.6

import sys
import os
import unittest
import pathlib
import filecmp

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))

from configVar import configVarList
from configVar import newConfigVar
from newConfigVarYamlReader import ConfigVarYamlReader_new
from newConfigVar import var_stack_new
import aYaml
import difflib

def normalize_yaml_lines(yaml_file):
    retVal = list()
    with open(yaml_file, "r") as rfd:
        for line in rfd.readlines():
            striped_line = line.strip()
            if striped_line:
                retVal.append(striped_line)
    return retVal

class TestConfigVarL(unittest.TestCase):
    def setUp(self):
        var_stack_new.clear()

    def tearDown(self):
        pass

    def test_var_in_var_simple(self):
        var_stack_new["A"] = "$(B)"
        var_stack_new["B"] = "$(C)"
        var_stack_new["C"] = "ali baba"
        self.assertEqual("ali baba", str(var_stack_new["A"]))
        self.assertEqual("ali baba", var_stack_new.resolve_str("$(A)"))

    def test_array(self):
        var_stack_new["PUSHKIN"] ="1", "2", "3"
        self.assertEqual("123", str(var_stack_new["PUSHKIN"]))
        self.assertEqual("123", var_stack_new.resolve_str("$(PUSHKIN)"))
        self.assertEqual("1", var_stack_new.resolve_str("$(PUSHKIN[0])"))
        self.assertEqual("2", var_stack_new.resolve_str("$(PUSHKIN[1])"))
        self.assertEqual("3", var_stack_new.resolve_str("$(PUSHKIN[2])"))
        self.assertEqual("321", var_stack_new.resolve_str("$(PUSHKIN[2])$(PUSHKIN[1])$(PUSHKIN[0])"))

    def test_readFile(self):
        input_file_path = pathlib.Path(__file__).parent.joinpath("test_input.yaml")
        out_file_path = pathlib.Path(__file__).parent.joinpath("test_out.yaml")
        expected_file_path = pathlib.Path(__file__).parent.joinpath("expected_output.yaml")

        reader = ConfigVarYamlReader_new()
        reader.read_yaml_file(input_file_path)
        variables_as_yaml = var_stack_new.repr_for_yaml()
        yaml_doc = aYaml.YamlDumpDocWrap(variables_as_yaml, '!define', "",
                                              explicit_start=True, sort_mappings=True)
        with open(out_file_path, "w") as wfd:
            aYaml.writeAsYaml(yaml_doc, wfd)

        out_lines = normalize_yaml_lines(out_file_path)
        expected_lines = normalize_yaml_lines(expected_file_path)

        self.assertEqual(out_lines, expected_lines)
