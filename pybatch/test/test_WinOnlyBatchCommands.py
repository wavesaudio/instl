#!/usr/bin/env python3.6


import unittest
import logging
log = logging.getLogger(__name__)

from pybatch import *


from .test_PythonBatchBase import *


class TestPythonBatchWin(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    @unittest.skipUnless(running_on_Win, "Win only test")
    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_WinShortcut_repr(self):
        list_of_objs = list()
        list_of_objs.append(WinShortcut("/the/memphis/belle", "/go/to/hell"))
        for run_as_admin in (True, False):
            for ignore_all_errors in (True, False):
                list_of_objs.append(WinShortcut("/the/memphis/belle", "/go/to/hell", run_as_admin=run_as_admin, ignore_all_errors=ignore_all_errors))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_WinShortcut(self):
        src = "C:\Program Files (x86)\Waves\Applications V10\Electric Grand 80.exe"
        dst = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Waves\Electric Grand 80.lnk"
        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += WinShortcut(dst, src)
        self.pbt.exec_and_capture_output()

    def test_BaseRegistryKey_repr(self):
        pass

    def test_BaseRegistryKey(self):
        pass

    def test_ReadRegistryValue_repr(self):
        list_of_objs = list()
        for reg_num_bits in (32, 64):
            for ignore_if_not_exist in (True, False):
                list_of_objs.append(ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Fax', 'ArchiveFolder', reg_num_bits=reg_num_bits, ignore_if_not_exist=ignore_if_not_exist, reply_environ_var="ReadRegistryValue_expected_value"))
        # without specifying reg_num_bits at all
        list_of_objs.append(ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Fax', 'ArchiveFolder', ignore_if_not_exist=True))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_ReadRegistryValue(self):
        for reg_num_bits in (32, 64):
            self.pbt.batch_accum.clear()
            value = None
            expected_value = r'Consolas'
            self.pbt.batch_accum += ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\Notepad\DefaultFonts', 'lfFaceName', reg_num_bits=reg_num_bits, ignore_if_not_exist=True, reply_environ_var="ReadRegistryValue_expected_value")
            self.pbt.exec_and_capture_output()
            #self.assertEqual(expected_value, value, f"ReadRegistryKey values {expected_value} != {value}")
            value_from_environ = os.environ["ReadRegistryValue_expected_value"]
            self.assertEqual(expected_value, value_from_environ, f"ReadRegistryKey values {expected_value} != {value}")

    def test_CreateRegistryKey_repr(self):
        list_of_objs = list()
        for reg_num_bits in (32, 64):
            # without default data value
            list_of_objs.append(CreateRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', reg_num_bits=reg_num_bits))

            # with default data value
            list_of_objs.append(CreateRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', "lolapaluza", reg_num_bits=reg_num_bits))

        self.pbt.reprs_test_runner(*list_of_objs)

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
        list_of_objs = list()
        for reg_num_bits in (64, 32):
            list_of_objs.append(CreateRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\Test', {'key1': 'val1', 'key2': 'val2'}, reg_num_bits=reg_num_bits))
        self.pbt.reprs_test_runner(*list_of_objs)

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
        list_of_objs = list()
        for reg_num_bits in (64, 32):
            list_of_objs.append(DeleteRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio', reg_num_bits=reg_num_bits))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_DeleteRegistryKey(self):
        for reg_num_bits in (64, 32):
            self.pbt.batch_accum.clear()
            self.pbt.batch_accum += CreateRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryKey', {"lalalal": "lilili"}, reg_num_bits=reg_num_bits)
            self.pbt.batch_accum += DeleteRegistryKey('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryKey', reg_num_bits=reg_num_bits)
            self.pbt.batch_accum += ReadRegistryValue('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryKey', "lalalal", reg_num_bits=reg_num_bits)
            self.pbt.exec_and_capture_output(expected_exception=FileNotFoundError)

    def test_DeleteRegistryKey_non_existing(self):
        for reg_num_bits in (64, 32):
            self.pbt.batch_accum.clear()
            self.pbt.batch_accum += DeleteRegistryKey('HKEY_LOCAL_MACHINE', 'SOFTWARE\Waves Audio\testךשלדגחכךדגלכ_non_existing', reg_num_bits=reg_num_bits)
            self.pbt.exec_and_capture_output()

    def test_DeleteRegistryValues_repr(self):
        list_of_objs = list()
        for reg_num_bits in (64, 32):
            list_of_objs.append(DeleteRegistryValues('HKEY_LOCAL_MACHINE', r'SOFTWARE\Waves Audio\test_DeleteRegistryValues_repr', 'key1', 'key2', reg_num_bits=reg_num_bits))
        self.pbt.reprs_test_runner(*list_of_objs)

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

    def test_ResHacker_repr(self):
        list_of_objs = list()
        list_of_objs.append(ResHackerAddResource('reshacker_path', 'exec_path', 'resource_source_path', 'res_type', 'res_id'))
        self.pbt.reprs_test_runner(*list_of_objs)

    def test_ResHacker(self):
        return # these tests are still with hard coded paths
        reshacker_path = r"C:\p4client\ProAudio\dev_main\ProAudio\bin\Win\ResHacker5.1.6\ResourceHacker.exe"
        original_exe = r"C:\p4client\ProAudio\dev_main\ProAudio\VisualStudioBuildProducts\plugin-host\x64\Release\Products\plugin-host.exe"
        copied_exe = self.pbt.path_inside_test_folder("CODEX.exe")
        icon_file = r"C:\p4client\ProAudio\dev_main\ProAudio\XPlatform\Apps\plugin-host\Resources\Win\CODEX.ico"

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += CopyFileToFile(original_exe, copied_exe)
        self.pbt.batch_accum += ResHackerAddResource(reshacker_path=reshacker_path,
                                                     trg=copied_exe,
                                                     resource_source_file=icon_file,
                                                     resource_type="ICONGROUP",
                                                     resource_name="IDI_ICON1")
        self.pbt.exec_and_capture_output()

    def test_FullACLForEveryone_repr(self):
        list_of_objs = (FullACLForEveryone('/baba/ganush'),
                        FullACLForEveryone('/baba/ganush', recursive=True),
                        FullACLForEveryone('/baba/ganush', recursive=False))

        self.pbt.reprs_test_runner(*list_of_objs)

    def test_FullACLForEveryone(self):
        """ create folder and change ACL for group Everyone to full control with inheritance
            we do not yet have code to read ACL so checking the pemissions can only be done manually
        """
        folder_to_test = self.pbt.path_inside_test_folder("folder-to-test")
        folder_to_ = self.pbt.path_inside_test_folder("folder-to-test")

        self.pbt.batch_accum.clear()
        self.pbt.batch_accum += MakeDir(folder_to_test)
        self.pbt.batch_accum += FullACLForEveryone(folder_to_test)

        self.pbt.exec_and_capture_output()
