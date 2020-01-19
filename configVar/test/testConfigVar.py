#!/usr/bin/env python3.6

import sys
import os
import unittest
from pathlib import Path
import time, datetime

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))
sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))
sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir)))

import utils  # do not remove, prevents cyclic import problems
import aYaml

from configVar import config_vars
from configVar import ConfigVarYamlReader


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

    def test_list_issues(self):

        name_1 = ["Lili", "Marlen"]
        name_2 = ["Lili", "Allen"]
        config_vars["ALL_NAMES"] = "$(NAME_ONE)", "$(NAME_TWO)", "$(NAME_THREE)"
        config_vars["NAME_ONE"] = name_1
        config_vars["NAME_TWO"] = "shraga"
        config_vars["NAME_THREE"] = name_2

        # list() on the to configVar should return the lists of resolved values if a value is
        # and only is a configVar reference $(...)
        all_names = list(config_vars["ALL_NAMES"])
        self.assertListEqual(name_1+["shraga"]+name_2, all_names)

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
        input_file_path = Path(__file__).parent.joinpath("test_input.yaml")
        out_file_path = Path(__file__).parent.joinpath("test_out.yaml")
        expected_file_path = Path(__file__).parent.joinpath("expected_output.yaml")

        reader = ConfigVarYamlReader(config_vars)
        reader.read_yaml_file(input_file_path)
        variables_as_yaml = config_vars.repr_for_yaml()
        yaml_doc = aYaml.YamlDumpDocWrap(variables_as_yaml, '!define', "",
                                              explicit_start=True, sort_mappings=True)
        with open(out_file_path, "w") as wfd:
            aYaml.writeAsYaml(yaml_doc, wfd)

        with open(out_file_path, "r") as r_out:
            out_lines = r_out.readlines()
        with open(expected_file_path, "r") as r_expected:
            expected_lines = r_expected.readlines()

        self.assertEqual.__self__.maxDiff = None
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

    def test_dynamic_config_var(self):
        def get_now_date_time(val):
            return str(datetime.datetime.fromtimestamp(time.time()))
        config_vars.set_dynamic_var("__NOW__", get_now_date_time)

        config_vars["DYNA_VAR"] = "$(__NOW__)"
        now_1 = config_vars["DYNA_VAR"].str()
        time.sleep(1)
        now_2 = config_vars["DYNA_VAR"].str()
        self.assertNotEqual(now_1, now_2)

    def test_CompareConfigVarsAsList(self):
        config_vars["__INSTL_VERSION__"] = (2,2,3)
        config_vars["INSTL_MINIMAL_VERSION"] = (1,2,3)
        min_version_as_list = [int(v) for v in config_vars["INSTL_MINIMAL_VERSION"].list()]
        cur_version_as_list = [int(v) for v in config_vars["__INSTL_VERSION__"].list()]
        self.assertLessEqual(min_version_as_list, cur_version_as_list, f"1 failed {min_version_as_list} <= {cur_version_as_list}")
        config_vars["__INSTL_VERSION__"] = (1,2,3)
        cur_version_as_list = [int(v) for v in config_vars["__INSTL_VERSION__"].list()]
        self.assertLessEqual(min_version_as_list, cur_version_as_list, f"2 failed {min_version_as_list} <= {cur_version_as_list}")
        config_vars["__INSTL_VERSION__"] = (1,2,2)
        cur_version_as_list = [int(v) for v in config_vars["__INSTL_VERSION__"].list()]
        self.assertLessEqual(cur_version_as_list, min_version_as_list, f"3 failed {cur_version_as_list} <= {min_version_as_list}")
