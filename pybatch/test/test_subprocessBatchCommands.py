#!/usr/bin/env python3.9


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
import subprocess
import string
from threading import Timer
from collections import namedtuple

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum
from pybatch.copyBatchCommands import RsyncClone
from configVar import config_vars
from utils.parallel_run import run_process, ProcessTerminatedExternally

current_os_names = utils.get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

config_vars["__CURRENT_OS_NAMES__"] = current_os_names


from .test_PythonBatchBase import *


class TestPythonBatchSubprocess(unittest.TestCase):
    def __init__(self, which_test):
        super().__init__(which_test)
        self.pbt = TestPythonBatch(self, which_test)

    def setUp(self):
        self.pbt.setUp()

    def tearDown(self):
        self.pbt.tearDown()

    def test_RunProcessBase_repr(self):
        pass

    def test_RunProcessBase(self):
        pass

    def test_Curl_repr(self):
        """ validate Curl object recreation with Curl.__repr__() """
        url_from = r"http://www.google.com"
        file_to = "/q/w/r"
        curl_path = 'curl'
        if sys.platform == 'win32':
            curl_path = r'C:\Program Files (x86)\Waves Central\WavesLicenseEngine.bundle\Contents\Win32\curl.exe'
        obj = CUrl(url_from, file_to, curl_path)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"CUrl.repr did not recreate CUrl object correctly: {diff_explanation}")

    def test_Curl(self):
        #sample_file = Path(__file__).joinpath('../test_data/curl_sample.txt').resolve()
        #with open(sample_file, 'r') as stream:
        #    test_data = stream.read()
        url_from = 'https://en.wikipedia.org/wiki/Static_web_page'
        to_path = self.pbt.path_inside_test_folder("Static_web_page")

        if sys.platform == 'win32':
            curl_path = r'C:\Program Files (x86)\Waves Central\WavesLicenseEngine.bundle\Contents\Win32\curl.exe'
        else:
            curl_path = shutil.which("curl")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += CUrl(url_from, to_path, curl_path)
        self.pbt.exec_and_capture_output()

        with open(to_path, 'r') as stream:
            downloaded_data = stream.read()
        self.assertIn("A static web page", downloaded_data)

    def test_ShellCommand_repr(self):
        """ validate ShellCommand object recreation with ShellCommand.__repr__() """
        list_of_objs = list()
        list_of_error_to_ignore_lists = ((), (19,), (1,2,3))
        for ignore_all_errors in (True, False):
            for l in list_of_error_to_ignore_lists:
                list_of_objs.append(ShellCommand("do something", ignore_all_errors=ignore_all_errors, ignore_specific_exit_codes=l))

        self.pbt.reprs_test_runner(*list_of_objs)

    def test_ShellCommand(self):
        pass

    def test_ShellCommand_ignore_specific_exit_codes(self):
        # test that exception from exit code is suppressed with ignore_specific_exit_codes
        with self.pbt.batch_accum as batchi:
            batchi += ShellCommand("exit 19", ignore_specific_exit_codes=(19,))
        self.pbt.exec_and_capture_output()

        # test that exception from exit code is not suppressed when not in ignore_specific_exit_codes
        self.pbt.batch_accum.clear(section_name="doit")
        with self.pbt.batch_accum as batchi:
            batchi += ShellCommand("exit 19", ignore_specific_exit_codes=(17, 36, -17))
        self.pbt.exec_and_capture_output(expected_exception=subprocess.CalledProcessError)

    def test_ScriptCommand_repr(self):
        """ validate ScriptCommand object recreation with ScriptCommand.__repr__() """
        list_of_objs = list()
        list_of_error_to_ignore_lists = ((), (19,), (1,2,3))
        for ignore_all_errors in (True, False):
            for l in list_of_error_to_ignore_lists:
                list_of_objs.append(ScriptCommand("do something", ignore_all_errors=ignore_all_errors, ignore_specific_exit_codes=l))

        self.pbt.reprs_test_runner(*list_of_objs)

    def test_ShellCommands_repr(self):
        pass

    def test_ShellCommands(self):
        batches_dir = self.pbt.path_inside_test_folder("batches")
        # with ShellCommand(shell_command=r'call "C:\Users\nira\AppData\Local\Waves Audio\instl\Cache\instl\V10\Win\Utilities\uninstallshield\uninstall-previous-versions.bat"', message="Uninstall pre 9.6 versions pre-install step 1") as shell_command_010_184:  # 184
        #     shell_command_010_184()
        user_desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
        if sys.platform == 'darwin':
            geronimo = [f"""ls {user_desktop} >> "{os.fspath(batches_dir)}/geronimo.txt\"""",
                        f"""[ -f "{os.fspath(batches_dir)}/geronimo.txt" ] && echo "g e r o n i m o" >> {os.fspath(batches_dir)}/geronimo.txt"""]
        else:
            app_data_folder = os.path.join(os.getenv('LOCALAPPDATA'), 'Waves Audio')
            geronimo = [r'call "%s\instl\Cache\instl\V10\Win\Utilities\uninstallshield\uninstall-previous-versions.bat"' % app_data_folder]
            # geronimo = [r"dir %appdata% >> %appdata%\geronimo.txt",
            #             r"dir %userprofile%\desktop >> %userprofile%\desktop\geronimo.txt",
            #             r"cmd /C dir %userprofile%\desktop >> %userprofile%\desktop\geronimo.txt",
            #             r"cmd /C dir %userprofile%\desktop",]

        self.pbt.batch_accum.clear(section_name="doit")
        #self.pbt.batch_accum += ConfigVarAssign("geronimo", *geronimo)
        self.pbt.batch_accum += MakeDir(batches_dir)
        self.pbt.batch_accum += ShellCommands(shell_command_list=geronimo, message="testing ShellCommands")

        self.pbt.exec_and_capture_output()

    def test_ParallelRun_repr(self):
        """ validate ParallelRun object recreation with ParallelRun.__repr__() """
        self.pbt.reprs_test_runner(ParallelRun("/rik/ya/vik", shell=True),
                                   ParallelRun("/rik/ya/vik", action_name="pil"))

    def test_ParallelRun_shell(self):
        test_file = self.pbt.path_inside_test_folder("list-of-runs")
        ls_output = self.pbt.path_inside_test_folder("ls.out.txt")
        ps_output = self.pbt.path_inside_test_folder("ps.out.txt")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the ls\n""")
                wfd.write(f"""ls -l . > ls.out.txt\n""")
                wfd.write(f"""# meanwhile, do the ps\n""")
                wfd.write(f"""ps -x > ps.out.txt\n""")

        self.pbt.batch_accum.clear(section_name="doit")
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

        self.pbt.batch_accum.clear(section_name="doit")
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, True)

        self.pbt.exec_and_capture_output(expected_exception=SystemExit)

    def test_ParallelRun_no_shell(self):
        test_file = self.pbt.path_inside_test_folder("list-of-runs")
        zip_input = self.pbt.path_inside_test_folder("zip_in")
        zip_output = self.pbt.path_inside_test_folder("zip_in.bz2")
        zip_input_copy = self.pbt.path_inside_test_folder("zip_in.copy")

        # create a file to zip
        with open(zip_input, "w") as wfd:
            wfd.write(''.join(random.choice(string.ascii_lowercase+string.ascii_uppercase+"\n") for i in range(10 * 1024)))
        self.assertTrue(zip_input.exists(), f"{self.pbt.which_test}: {zip_input} should have been created")

        with open(test_file, "w") as wfd:
            if sys.platform == 'darwin':
                wfd.write(f"""# first, do the zip\n""")
                wfd.write(f"""bzip2 --compress -f {zip_input}\n""")
                wfd.write(f'''# also run some random program\n''')
                wfd.write(f'''bison --version\n''')

        self.pbt.batch_accum.clear(section_name="doit")
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as sub_bc:
            # save a copy of the input file
            sub_bc += CopyFileToFile(zip_input, zip_input_copy, hard_links=False)
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

        self.pbt.batch_accum.clear(section_name="doit")
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as sub_bc:
            sub_bc += ParallelRun(test_file, False)

        self.pbt.exec_and_capture_output()
        self.assertTrue(zip_input.exists(), f"{self.pbt.which_test}: {zip_input} should have been created by bzip2")
        self.assertTrue(zip_output.exists(), f"{self.pbt.which_test}: {zip_output} should not have been erased by bzip2")
        self.assertTrue(zip_input_copy.exists(), f"{self.pbt.which_test}: {zip_input_copy} should remain")

        self.assertTrue(filecmp.cmp(zip_input, zip_input_copy), f"'{zip_input}' and '{zip_input_copy}' should be identical")

    def test_RunInThread_repr(self):
        """ validate RunInThread object recreation with RunInThread.__repr__() """
        self.pbt.reprs_test_runner(RunInThread(Ls('rumba', out_file="empty.txt")),
                                   RunInThread(Ls("/per/pen/di/cular", out_file="perpendicular_ls.txt", ls_format='abc')),
                                   RunInThread(Ls(r"C:\Users\nira\AppData\Local\Waves Audio\instl\Cache/instl/V10", out_file="Lollobrigida.txt")))

    def test_RunInThread(self):
        folder_to_list = self.pbt.path_inside_test_folder("folder-to-list")
        list_out_file = self.pbt.path_inside_test_folder("list-output")

        # create the folder, with sub folder and one known file
        self.pbt.batch_accum.clear(section_name="doit")
        with self.pbt.batch_accum.sub_accum(Cd(self.pbt.test_folder)) as cd1_accum:
             cd1_accum += MakeDir(folder_to_list)
             with cd1_accum.sub_accum(Cd(folder_to_list)) as cd2_accum:
                cd2_accum += MakeRandomDirs(num_levels=3, num_dirs_per_level=2, num_files_per_dir=8, file_size=41)
             cd1_accum += RunInThread(Ls(folder_to_list, out_file=list_out_file))
        self.pbt.exec_and_capture_output()

        time.sleep(5)
        self.assertTrue(os.path.isdir(folder_to_list), f"{self.pbt.which_test} : folder to list was not created {folder_to_list}")
        self.assertTrue(os.path.isfile(list_out_file), f"{self.pbt.which_test} : list_out_file was not created {list_out_file}")

    def test_Subprocess_repr(self):
        """ validate Subprocess object recreation with Subprocess.__repr__() """
        self.pbt.reprs_test_runner(Subprocess("/rik/ya/vik", message="sababa"),
                                   Subprocess("/rik/ya/vik", "kiki di", message="sababa"),
                                   Subprocess("/rik/ya/vik", "kiki di", "Rubik Rosenthal"))

    def test_Subprocess(self):
        folder_ = self.pbt.path_inside_test_folder("folder_")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(folder_)
        self.pbt.batch_accum += Subprocess("python3.9", "--version")
        self.pbt.batch_accum += Subprocess("python3.9", "-c", "for i in range(4): print(i)")
        self.pbt.exec_and_capture_output()

    def test_Subprocess_detached(self):
        if running_on_Mac:
            path_to_exec = "/Applications/BBEdit.app/Contents/MacOS/BBEdit"
        elif running_on_Win:
            path_to_exec = "C:\\Program Files (x86)\\Notepad++\\notepad++.exe"

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += Subprocess(path_to_exec, r"C:\p4client\wlc.log", detach=True)
        self.pbt.exec_and_capture_output()

    def test_run_process_abort(self):
        '''This test validates the abort function of run_process.
        It runs a python script that never ends and tests that once the abort file is deleted the process stops'''
        test_file = os.path.join(self.pbt.test_folder, 'test.py')
        abort_file = os.path.join(self.pbt.test_folder, 'abort.txt')
        with open(test_file, 'w') as stream:
            stream.write('while True: print(0)\n')

        with open(abort_file, 'w') as stream:
            stream.write('')

        def delete_abort_file():
            os.remove(abort_file)

        t = Timer(2, delete_abort_file)
        t.start()

        cmd = ['python3.9', test_file]
        with self.assertRaises(ProcessTerminatedExternally):
            with assert_timeout(3):
                run_process(cmd, shell=(sys.platform == 'win32'), abort_file=abort_file)

    def test_KillProcess_repr(self):
        """ validate KillProcess object recreation with ParallelRun.__repr__() """
        self.pbt.reprs_test_runner(KillProcess("itsik"),
                                   KillProcess("moshe", retries=3, sleep_sec=4),
                                   KillProcess("pesach", retries=5),
                                   KillProcess("nurit", sleep_sec=0.1))

    def test_KillProcess_repr(self):
        os.system("""osascript -e 'tell app "Notes.app" to open'""")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += KillProcess("Notes", retries=3, sleep_sec=1)
        self.pbt.exec_and_capture_output()
