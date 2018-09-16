#!/usr/bin/env python3.6


import sys
import os
from pathlib import Path
import unittest
import shutil
import stat
import ctypes
import io
import contextlib
import filecmp
import random
import string
from collections import namedtuple

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum
from pybatch.copyBatchCommands import RsyncClone
from configVar import config_vars

current_os_names = utils.get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

config_vars["__CURRENT_OS_NAMES__"] = current_os_names


from testPythonBatch import *


class TestPythonBatchSubprocess(unittest.TestCase):
    def __init__(self, which_test="apple"):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_ShellCommands_repr(self):
        # ShellCommands.repr() cannot replicate it's original construction exactly
        # therefor the usual repr tests do not apply
        pass

    def test_ShellCommands(self):
        batches_dir = self.pbt.path_inside_test_folder("batches")
        self.assertFalse(batches_dir.exists(), f"{self.pbt.which_test}: {batches_dir} should not exist before test")
        # with ShellCommand(shell_command=r'call "C:\Users\nira\AppData\Local\Waves Audio\instl\Cache\instl\V10\Win\Utilities\uninstallshield\uninstall-previous-versions.bat"', message="Uninstall pre 9.6 versions pre-install step 1") as shell_command_010_184:  # 184
        #     shell_command_010_184()
        if sys.platform == 'darwin':
            geronimo = [f"""ls /Users/shai/Desktop >> "{os.fspath(batches_dir)}/geronimo.txt\"""",
                        f"""[ -f "{os.fspath(batches_dir)}/geronimo.txt" ] && echo "g e r o n i m o" >> {os.fspath(batches_dir)}/geronimo.txt"""]
        else:

            geronimo = [r'call "C:\Users\nira\AppData\Local\Waves Audio\instl\Cache\instl\V10\Win\Utilities\uninstallshield\uninstall-previous-versions.bat"']
            # geronimo = [r"dir %appdata% >> %appdata%\geronimo.txt",
            #             r"dir %userprofile%\desktop >> %userprofile%\desktop\geronimo.txt",
            #             r"cmd /C dir %userprofile%\desktop >> %userprofile%\desktop\geronimo.txt",
            #             r"cmd /C dir %userprofile%\desktop",]

        self.pbt.batch_accum.clear()
        #self.pbt.batch_accum += ConfigVarAssign("geronimo", *geronimo)
        self.pbt.batch_accum += MakeDirs(batches_dir)
        self.pbt.batch_accum += ShellCommands(shell_commands_list=geronimo, message="testing ShellCommands")

        self.pbt.exec_and_capture_output()

    def test_ParallelRun_repr(self):
        pr_obj = ParallelRun("/rik/ya/vik", True)
        pr_obj_recreated = eval(repr(pr_obj))
        self.assertEqual(pr_obj, pr_obj_recreated, "ParallelRun.repr did not recreate ParallelRun object correctly")

    def test_ParallelRun_shell(self):
        test_file = self.pbt.path_inside_test_folder("list-of-runs")
        self.assertFalse(test_file.exists(), f"{self.pbt.which_test}: {test_file} should not exist before test")
        ls_output = self.pbt.path_inside_test_folder("ls.out.txt")
        self.assertFalse(ls_output.exists(), f"{self.pbt.which_test}: {ls_output} should not exist before test")
        ps_output = self.pbt.path_inside_test_folder("ps.out.txt")
        self.assertFalse(ps_output.exists(), f"{self.pbt.which_test}: {ps_output} should not exist before test")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the ls\n""")
                wfd.write(f"""ls -l . > ls.out.txt\n""")
                wfd.write(f"""# meanwhile, do the ps\n""")
                wfd.write(f"""ps -x > ps.out.txt\n""")

        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, True)

        self.pbt.exec_and_capture_output()
        self.assertTrue(ls_output.exists(), f"{self.pbt.which_test}: {ls_output} was not created")
        self.assertTrue(ps_output.exists(), f"{self.pbt.which_test}: {ps_output} was not created")

    def test_ParallelRun_shell_bad_exit(self):
        test_file = self.pbt.path_inside_test_folder("list-of-runs")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the some good\n""")
                wfd.write(f"""true\n""")
                wfd.write(f"""# while also doing some bad\n""")
                wfd.write(f"""false\n""")

        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, True)

        self.pbt.exec_and_capture_output(expected_exception=SystemExit)

    def test_ParallelRun_no_shell(self):
        test_file = self.pbt.path_inside_test_folder("list-of-runs")
        self.assertFalse(test_file.exists(), f"{self.pbt.which_test}: {test_file} should not exist before test")

        zip_input = self.pbt.path_inside_test_folder("zip_in")
        self.assertFalse(zip_input.exists(), f"{self.pbt.which_test}: {zip_input} should not exist before test")
        zip_output = self.pbt.path_inside_test_folder("zip_in.bz2")
        self.assertFalse(zip_output.exists(), f"{self.pbt.which_test}: {zip_output} should not exist before test")
        zip_input_copy = self.pbt.path_inside_test_folder("zip_in.copy")
        self.assertFalse(zip_input_copy.exists(), f"{self.pbt.which_test}: {zip_input_copy} should not exist before test")

        # create a file to zip
        with open(zip_input, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(zip_input.exists(), f"{self.pbt.which_test}: {zip_input} should have been created")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the zip\n""")
                wfd.write(f"""bzip2 --compress {zip_input}\n""")
                wfd.write(f'''# also run some random program\n''')
                wfd.write(f'''bison --version\n''')

        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as sub_bc:
            # save a copy of the input file
            sub_bc += CopyFileToFile(zip_input, zip_input_copy)
            # zip the input file, bzip2 will remove it
            sub_bc += ParallelRun(test_file, False)

        self.pbt.exec_and_capture_output()
        self.assertFalse(zip_input.exists(), f"{self.pbt.which_test}: {zip_input} should have been erased by bzip2")
        self.assertTrue(zip_output.exists(), f"{self.pbt.which_test}: {zip_output} should have been created by bzip2")
        self.assertTrue(zip_input_copy.exists(), f"{self.pbt.which_test}: {zip_input_copy} should have been copied")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the unzip\n""")
                # unzip the zipped file an keep the
                wfd.write(f"""bzip2 --decompress --keep {zip_output}\n""")
                wfd.write(f'''# also run some random program\n''')
                wfd.write(f'''bison --version\n''')

        self.pbt.batch_accum.clear()
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, False)

        self.pbt.exec_and_capture_output()
        self.assertTrue(zip_input.exists(), f"{self.pbt.which_test}: {zip_input} should have been created by bzip2")
        self.assertTrue(zip_output.exists(), f"{self.pbt.which_test}: {zip_output} should not have been erased by bzip2")
        self.assertTrue(zip_input_copy.exists(), f"{self.pbt.which_test}: {zip_input_copy} should remain")

        self.assertTrue(filecmp.cmp(zip_input, zip_input_copy), f"'{zip_input}' and '{zip_input_copy}' should be identical")

    def test_Curl_repr(self):
        url_from = r"http://www.google.com"
        file_to = "/q/w/r"
        curl_path = 'curl'
        if sys.platform == 'win32':
            curl_path = r'C:\Program Files (x86)\Waves Central\WavesLicenseEngine.bundle\Contents\Win32\curl.exe'
        curl_obj = CUrl(url_from, file_to, curl_path)
        curl_obj_recreated = eval(repr(curl_obj))
        self.assertEqual(curl_obj, curl_obj_recreated, "CUrl.repr did not recreate CUrl object correctly")

    def test_Curl_download(self):
        sample_file = Path(__file__).joinpath('../test_data/curl_sample.txt').resolve()
        with open(sample_file, 'r') as stream:
            test_data = stream.read()
        url_from = 'https://www.sample-videos.com/text/Sample-text-file-10kb.txt'
        to_path = self.pbt.path_inside_test_folder("curl")
        curl_path = 'curl'
        if sys.platform == 'win32':
            curl_path = r'C:\Program Files (x86)\Waves Central\WavesLicenseEngine.bundle\Contents\Win32\curl.exe'
        os.makedirs(to_path, exist_ok=True)
        downloaded_file = os.path.join(to_path, 'Sample.txt')
        with self.pbt.batch_accum as batchi:
            batchi += CUrl(url_from, downloaded_file, curl_path)
        self.pbt.exec_and_capture_output("Download file")
        with open(downloaded_file, 'r') as stream:
            downloaded_data = stream.read()
        self.assertEqual(test_data, downloaded_data)
