#!/usr/bin/env python3.6


import sys
import os
from pathlib import Path
from unittest import TestCase
import shutil
import stat
import ctypes
import io
import contextlib
import filecmp
import random
import string
from collections import namedtuple
import unittest

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum
from configVar import config_vars


from testPythonBatch import *


class TestPythonBatchWin(unittest.TestCase):
    def __init__(self, which_test="pineapple"):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_ReadRegistryValue_repr(self):
        if sys.platform == 'darwin':
            return
        reg_obj = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Fax', 'ArchiveFolder')
        reg_obj_recreated = eval(repr(reg_obj))
        self.assertEqual(reg_obj, reg_obj_recreated, "ReadRegistryKey.repr did not recreate ReadRegistryKey object correctly")

    def test_CreateRegistryKey_repr(self):
        if sys.platform == 'darwin':
            return
        reg_obj = CreateRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', 'test_val1')
        reg_obj_recreated = eval(repr(reg_obj))
        self.assertEqual(reg_obj, reg_obj_recreated, "CreateRegistryKey.repr did not recreate CreateRegistryKey object correctly")

    def test_CreateRegistryValues_repr(self):
        if sys.platform == 'darwin':
            return
        reg_obj = CreateRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', {'key1': 'val1', 'key2': 'val2'})
        reg_obj_recreated = eval(repr(reg_obj))
        self.assertEqual(reg_obj, reg_obj_recreated, "CreateRegistryKey.repr did not recreate CreateRegistryKey object correctly")

    def test_DeleteRegistryKey_repr(self):
        if sys.platform == 'darwin':
            return
        reg_obj = DeleteRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio', 'Test')
        reg_obj_recreated = eval(repr(reg_obj))
        self.assertEqual(reg_obj, reg_obj_recreated, "DeleteRegistryKey.repr did not recreate DeleteRegistryKey object correctly")

    def test_DeleteRegistryValues_repr(self):
        if sys.platform == 'darwin':
            return
        reg_obj = DeleteRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', ('key1', 'key2'))
        reg_obj_recreated = eval(repr(reg_obj))
        self.assertEqual(reg_obj, reg_obj_recreated, "DeleteRegistryValues.repr did not recreate DeleteRegistryValues object correctly")

    def test_ReadRegistryValue(self):
        # reg.exe add HKEY_LOCAL_MACHINE\SOFTWARE\Waves /V LocationV10 /T REG_SZ /D "%CD%" /F'
        expected_value = r'C:\ProgramData\Microsoft\Windows NT\MSFax'
        value = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Fax', 'ArchiveFolder')()
        self.assertEqual(expected_value, value, f"ReadRegistryKey values {expected_value} != {value}")

    def test_CreateRegistryKey(self):
        self.batch_accum.clear()
        self.batch_accum += CreateRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio', 'Test')
        self.exec_and_capture_output()

        test_key = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', '')
        self.assertTrue(test_key.exists, f'Key not created - {test_key.hkey}\\{test_key.key}')

    def test_CreateRegistryValues(self):
        test_data = {'key1': 'val1', 'key2': 'val2'}
        self.batch_accum.clear()
        self.batch_accum += CreateRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', test_data)
        self.exec_and_capture_output()

        for k, expected_value in test_data.items():
            value = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', k)()
            self.assertEqual(value, expected_value, f"ReadRegistryKey values {expected_value} != {value}")

    def test_DeleteRegistryKey(self):
        self.batch_accum.clear()
        self.batch_accum += DeleteRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio', 'Test')
        self.exec_and_capture_output()

        test_key = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', '')
        self.assertFalse(test_key.exists, f'Key should not exist - {test_key.hkey}\\{test_key.key}')

    def test_DeleteRegistryValues(self):
        test_values = ('key1', 'key2')
        self.batch_accum.clear()
        self.batch_accum += DeleteRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', test_values)
        self.exec_and_capture_output()

        for value in test_values:
            with self.assertRaises(FileNotFoundError):
                ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', value)()

    def test_WinShortcut_repr(self):
        if sys.platform == "win32":
            win_shortcut_obj = WinShortcut("/the/memphis/belle", "/go/to/hell")
            win_shortcut_obj_recreated = eval(repr(win_shortcut_obj))
            self.assertEqual(win_shortcut_obj, win_shortcut_obj_recreated, "WinShortcut.repr did not recreate WinShortcut object correctly")

            win_shortcut_obj = WinShortcut("/the/memphis/belle", "/go/to/hell", False)
            win_shortcut_obj_recreated = eval(repr(win_shortcut_obj))
            self.assertEqual(win_shortcut_obj, win_shortcut_obj_recreated, "WinShortcut.repr did not recreate WinShortcut object correctly")

            win_shortcut_obj = WinShortcut("/the/memphis/belle", "/go/to/hell", run_as_admin=True)
            win_shortcut_obj_recreated = eval(repr(win_shortcut_obj))
            self.assertEqual(win_shortcut_obj, win_shortcut_obj_recreated, "WinShortcut.repr did not recreate WinShortcut object correctly")

    def test_WinShortcut(self):
        if sys.platform == "win32":
            pass  # TBD on windows
