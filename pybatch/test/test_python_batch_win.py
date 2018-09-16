#!/usr/bin/env python3.6


import unittest
import logging
log = logging.getLogger()

from pybatch import *


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
        for reg_num_bits in (32, 64):
            obj = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Fax', 'ArchiveFolder', reg_num_bits=reg_num_bits, ignore_if_not_exist=True)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"ReadRegistryKey.repr did not recreate ReadRegistryKey object correctly: {diff_explanation}")

        # without specifying reg_num_bits at all
        obj = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Fax', 'ArchiveFolder', ignore_if_not_exist=True)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"ReadRegistryKey.repr did not recreate ReadRegistryKey object correctly: {diff_explanation}")

    def test_ReadRegistryValue(self):
        for reg_num_bits in (32, 64):
            expected_value = r'C:\ProgramData\Microsoft\Windows NT\MSFax'
            with ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Fax', 'ArchiveFolder', ignore_if_not_exist=True) as rrv:
                value = rrv()
            self.assertEqual(expected_value, value, f"ReadRegistryKey values {expected_value} != {value}")

    def test_CreateRegistryKey_repr(self):
        for reg_num_bits in (32, 64):
            # without default data value
            obj = CreateRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', reg_num_bits=reg_num_bits)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"CreateRegistryKey.repr (without default data value) did not recreate CreateRegistryKey object correctly: {diff_explanation}")

            # with default data value
            obj = CreateRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', "lolapaluza", reg_num_bits=reg_num_bits)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"CreateRegistryKey.repr (with default data value) did not recreate CreateRegistryKey object correctly: {diff_explanation}")

    def test_CreateRegistryKey_no_default_value(self):
        for i in range(2):
            # run twice so actual delete may occur
            for reg_num_bits in (64, 32):
                # make sure the key does not exist
                test_key_leaf = f"test_CreateRegistryKey_no_default_value_{reg_num_bits}"
                test_key_path = "SOFTWARE\\Waves Audio\\" + test_key_leaf
                self.pbt.batch_accum.clear()
                self.pbt.batch_accum += DeleteRegistryKey('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.batch_accum += ReadRegistryValue('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.exec_and_capture_output(expected_exception=FileNotFoundError)  # ReadRegistryValue should raise FileNotFoundError becuase key should not exist

            for reg_num_bits in (64, 32):
                test_key_leaf = f"test_CreateRegistryKey_no_default_value_{reg_num_bits}"
                test_key_path = "SOFTWARE\\Waves Audio\\" + test_key_leaf
                self.pbt.batch_accum.clear()
                # CreateRegistryKey without default value, run the same key twice just to make sure it does not fail when key already exists
                self.pbt.batch_accum += CreateRegistryKey('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.batch_accum += CreateRegistryKey('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.batch_accum += ReadRegistryValue('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.exec_and_capture_output(expected_exception=FileNotFoundError)  # ReadRegistryValue should raise FileNotFoundError becuase key should have default value

    def test_CreateRegistryKey_with_default_value(self):
        for i in range(2):  # run twice so actual delete may occur
            for reg_num_bits in (64, 32):
                # make sure the key does not exist
                test_key_leaf = f"test_CreateRegistryKey_with_default_value_{reg_num_bits}"
                test_key_path = "SOFTWARE\\Waves Audio\\"+test_key_leaf
                self.pbt.batch_accum.clear()
                self.pbt.batch_accum += DeleteRegistryKey('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.batch_accum += ReadRegistryValue('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.exec_and_capture_output(test_name=test_key_leaf, expected_exception=FileNotFoundError)  # ReadRegistryValue should raise FileNotFoundError becuase key should not exist

            for reg_num_bits in (64, 32):
                test_key_leaf = f"test_CreateRegistryKey_with_default_value_{reg_num_bits}"
                test_key_path = "SOFTWARE\\Waves Audio\\"+test_key_leaf
                self.pbt.batch_accum.clear()
                # CreateRegistryKey without default value, run the same key twice just to make sure it does not fail when key already exists
                self.pbt.batch_accum += CreateRegistryKey('HKEY_LOCAL_MACHINE', test_key_path, "lollapalooza_"+str(reg_num_bits), reg_num_bits=reg_num_bits)
                self.pbt.batch_accum += CreateRegistryKey('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.batch_accum += ReadRegistryValue('HKEY_LOCAL_MACHINE', test_key_path, reg_num_bits=reg_num_bits)
                self.pbt.exec_and_capture_output(test_name=test_key_leaf)

    def test_CreateRegistryValues_repr(self):
        for reg_num_bits in (64, 32):
            obj = CreateRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', {'key1': 'val1', 'key2': 'val2'}, reg_num_bits=reg_num_bits)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"CreateRegistryKey.repr did not recreate CreateRegistryKey object correctly: {diff_explanation}")

    def test_CreateRegistryValues(self):
        for reg_num_bits in (64, 32):
            test_data = {'key1_'+str(reg_num_bits): 'val1', 'key2': 'val2_'+str(reg_num_bits), 'key9999': 'val9999'}
            self.pbt.batch_accum.clear()
            self.pbt.batch_accum += CreateRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_CreateRegistryValues', test_data, reg_num_bits=reg_num_bits)
            self.pbt.exec_and_capture_output()

            for k, expected_value in test_data.items():
                value = ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_CreateRegistryValues', k, reg_num_bits=reg_num_bits)()
                self.assertEqual(value, expected_value, f"ReadRegistryKey values {expected_value} != {value}")

    def test_DeleteRegistryKey_repr(self):
        for reg_num_bits in (64, 32):
            obj = DeleteRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio', reg_num_bits=reg_num_bits)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"DeleteRegistryKey.repr did not recreate DeleteRegistryKey object correctly: {diff_explanation}")

    def test_DeleteRegistryKey(self):
        for reg_num_bits in (64, 32):
            self.pbt.batch_accum.clear()
            self.pbt.batch_accum += CreateRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryKey', {"lalalal": "lilili"}, reg_num_bits=reg_num_bits)
            self.pbt.batch_accum += DeleteRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryKey', reg_num_bits=reg_num_bits)
            self.pbt.batch_accum += ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryKey', "lalalal", reg_num_bits=reg_num_bits)
            self.pbt.exec_and_capture_output(expected_exception=FileNotFoundError)

    def test_DeleteRegistryValues_repr(self):
        for reg_num_bits in (64, 32):
            obj = DeleteRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryValues_repr', 'key1', 'key2', reg_num_bits=reg_num_bits)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"DeleteRegistryValues.repr did not recreate DeleteRegistryValues object correctly: {diff_explanation}")

    def test_DeleteRegistryValues(self):
        for reg_num_bits in (64, 32):
            test_key_leaf = f"test_DeleteRegistryValues{reg_num_bits}"
            test_key_path = "SOFTWARE\\Waves Audio\\" + test_key_leaf
            test_values = {'delete_key1': 'value1_'+str(reg_num_bits), 'delete_key2': 'value2_'+str(reg_num_bits),
                           'stay_key1': 'value1_' + str(reg_num_bits), 'stay_key2': 'value2_' + str(reg_num_bits)}
            self.pbt.batch_accum.clear()
            self.pbt.batch_accum += CreateRegistryValues('HKEY_LOCAL_MACHINE', test_key_path, test_values, reg_num_bits=reg_num_bits)
            self.pbt.exec_and_capture_output()
            for key in test_values.keys():
                stay_value = ReadRegistryValue('HKEY_LOCAL_MACHINE', test_key_path, key, reg_num_bits=reg_num_bits)()
                self.assertEqual(stay_value, test_values[key])

        for reg_num_bits in (64, 32):
            test_key_leaf = f"test_DeleteRegistryValues{reg_num_bits}"
            test_key_path = "SOFTWARE\\Waves Audio\\" + test_key_leaf
            test_values = {'delete_key1': 'value1_'+str(reg_num_bits), 'delete_key2': 'value2_'+str(reg_num_bits),
                           'stay_key1': 'value1_' + str(reg_num_bits), 'stay_key2': 'value2_' + str(reg_num_bits)}
            delete_values = [k for k in test_values.keys() if k.startswith('delete')]
            self.pbt.batch_accum.clear()
            self.pbt.batch_accum += DeleteRegistryValues('HKEY_LOCAL_MACHINE', test_key_path, *delete_values, reg_num_bits=reg_num_bits)
            self.pbt.exec_and_capture_output()

            for key in test_values.keys():
                if key.startswith('delete'):
                    with self.assertRaises(FileNotFoundError):
                        ReadRegistryValue('HKEY_LOCAL_MACHINE', test_key_path, key, reg_num_bits=reg_num_bits)()
                elif key.startswith('stay'):
                    stay_value = ReadRegistryValue('HKEY_LOCAL_MACHINE', test_key_path, key, reg_num_bits=reg_num_bits)()
                    self.assertEqual(stay_value, test_values[key])

    def test_WinShortcut_repr(self):
        if sys.platform == "win32":
            obj = WinShortcut("/the/memphis/belle", "/go/to/hell")
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"WinShortcut.repr did not recreate WinShortcut object correctly: {diff_explanation}")

            obj = WinShortcut("/the/memphis/belle", "/go/to/hell", False)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"WinShortcut.repr did not recreate WinShortcut object correctly: {diff_explanation}")

            obj = WinShortcut("/the/memphis/belle", "/go/to/hell", run_as_admin=True)
            obj_recreated = eval(repr(obj))
            diff_explanation = obj.explain_diff(obj_recreated)
            self.assertEqual(obj, obj_recreated, f"WinShortcut.repr did not recreate WinShortcut object correctly: {diff_explanation}")

    def test_WinShortcut(self):
        if sys.platform == "win32":
            pass  # TBD on windows
