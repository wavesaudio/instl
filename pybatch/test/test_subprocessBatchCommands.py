#!/usr/bin/env python3.12


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
        """ validate Curl object recreation with Curl.__repr__ """
        url_from = r"http://www.google.com"
        file_to = "/q/w/r"
        curl_path = 'curl'
        if sys.platform == 'win32':
            curl_path = r'C:\Program Files (x86)\Waves Central\WavesLicenseEngine.bundle\Contents\Win32\curl.exe'
        obj = CUrl(url_from, file_to, curl_path)
        obj_recreated = eval(repr(obj))
        diff_explanation = obj.explain_diff(obj_recreated)
        self.assertEqual(obj, obj_recreated, f"CUrl.repr did not recreate CUrl object correctly: {diff_explanation}")

    @unittest.skipUnless(shutil.which("curl"), "curl binary not installed")
    def test_Curl(self):
        # Hermetic: instead of fetching a live web page (whose content drifts),
        # serve a known local file over a file:// URL so the round-trip is
        # deterministic and offline. Still exercises the real CUrl batch command.
        curl_path = shutil.which("curl")

        source_file = self.pbt.path_inside_test_folder("curl_source.txt")
        expected_content = "A static web page"
        source_file.write_text(expected_content)

        to_path = self.pbt.path_inside_test_folder("curl_downloaded.txt")
        url_from = source_file.as_uri()

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += CUrl(url_from, to_path, curl_path)
        self.pbt.exec_and_capture_output()

        with open(to_path, 'r') as stream:
            downloaded_data = stream.read()
        self.assertIn(expected_content, downloaded_data)

    def test_ShellCommand_repr(self):
        """ validate ShellCommand object recreation with ShellCommand.__repr__ """
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
        """ validate ScriptCommand object recreation with ScriptCommand.__repr__ """
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
        #     shell_command_010_184
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
        """ validate ParallelRun object recreation with ParallelRun.__repr__ """
        self.pbt.reprs_test_runner(ParallelRun("/rik/ya/vik", shell=True),
                                   ParallelRun("/rik/ya/vik", action_name="pil"))

    @unittest.skipUnless(running_on_Mac, "Mac only test")
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
            sub_bc += ParallelRun(test_file, shell=True)

        self.pbt.exec_and_capture_output()
        self.assertTrue(ls_output.exists(), f"{self.pbt.which_test}: {ls_output} was not created")
        self.assertTrue(ps_output.exists(), f"{self.pbt.which_test}: {ps_output} was not created")

    @unittest.skipUnless(running_on_Mac, "Mac only test")
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
            sub_bc += ParallelRun(test_file, shell=True)

        self.pbt.exec_and_capture_output(expected_exception=SystemExit)

    @unittest.skipUnless(running_on_Mac, "Mac only test")
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
            sub_bc += ParallelRun(test_file, shell=False)

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
            sub_bc += ParallelRun(test_file, shell=False)

        self.pbt.exec_and_capture_output()
        self.assertTrue(zip_input.exists(), f"{self.pbt.which_test}: {zip_input} should have been created by bzip2")
        self.assertTrue(zip_output.exists(), f"{self.pbt.which_test}: {zip_output} should not have been erased by bzip2")
        self.assertTrue(zip_input_copy.exists(), f"{self.pbt.which_test}: {zip_input_copy} should remain")

        self.assertTrue(filecmp.cmp(zip_input, zip_input_copy), f"'{zip_input}' and '{zip_input_copy}' should be identical")

    def test_RunInThread_repr(self):
        """ validate RunInThread object recreation with RunInThread.__repr__ """
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
        """ validate Subprocess object recreation with Subprocess.__repr__ """
        self.pbt.reprs_test_runner(Subprocess("/rik/ya/vik", message="sababa"),
                                   Subprocess("/rik/ya/vik", "kiki di", message="sababa"),
                                   Subprocess("/rik/ya/vik", "kiki di", "Rubik Rosenthal"))

    def test_Subprocess(self):
        folder_ = self.pbt.path_inside_test_folder("folder_")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(folder_)
        self.pbt.batch_accum += Subprocess("python3.12", "--version")
        self.pbt.batch_accum += Subprocess("python3.12", "-c", "for i in range(4): print(i)")
        self.pbt.exec_and_capture_output()

    def test_Subprocess_detached(self):
        if running_on_Mac:
            path_to_exec = "/Applications/BBEdit.app/Contents/MacOS/BBEdit"
        elif running_on_Win:
            path_to_exec = "C:\\Program Files (x86)\\Notepad++\\notepad++.exe"
        else:
            path_to_exec = None

        if not path_to_exec or not os.path.exists(path_to_exec):
            self.skipTest(f"detached-launch target not installed on this machine: {path_to_exec}")

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

        cmd = ['python3.12', test_file]
        with self.assertRaises(ProcessTerminatedExternally):
            with assert_timeout(3):
                run_process(cmd, shell=(sys.platform == 'win32'), abort_file=abort_file)

    def test_KillProcess_repr(self):
        """ validate KillProcess object recreation with ParallelRun.__repr__ """
        self.pbt.reprs_test_runner(KillProcess("itsik"),
                                   KillProcess("moshe", retries=3, sleep_sec=4),
                                   KillProcess("pesach", retries=5),
                                   KillProcess("nurit", sleep_sec=0.1))

    # launches and kills a real GUI app, so it has side effects and is timing-flaky;
    # left runnable on demand with INSTL_RUN_GUI_TESTS=1
    @unittest.skipUnless(os.environ.get("INSTL_RUN_GUI_TESTS") == "1", "launches a real GUI app")
    def test_KillProcess(self):
        app_base_name = ""
        if sys.platform == 'win32':
            app_base_name = "notepad++"
            os.system(f"start {app_base_name}")
        elif sys.platform == 'darwin':
            app_base_name = "Notes"
            os.system(f"open -a {app_base_name}.app")

        time.sleep(2)

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += KillProcess(app_base_name, retries=3, sleep_sec=1)
        self.pbt.exec_and_capture_output()

    def test_CurlInternalParallel_repr(self):
        """ validate CurlWithInternalParallel object recreation with CurlWithInternalParallel.__repr__ """
        self.pbt.reprs_test_runner(CurlWithInternalParallel("curl", "mongo.config", 3, 1, 1024))

    # downloads ~2GB from live third-party URLs, so it is neither hermetic nor quick
    @unittest.skip("non-hermetic: downloads ~2GB from live third-party URLs")
    def test_CurlInternalParallel(self):
        config_file = self.pbt.path_inside_test_folder("config_file")
        downloads_dir = self.pbt.path_inside_test_folder("downloads")
        config_file_text = f"""
            parallel
            progress-bar
            raw
            fail
            show-error
            compressed
            create-dirs
            url = https://www.youtube.com/
            output = {downloads_dir}/youtube.txt
            url = https://stackoverflow.com/
            output = {downloads_dir}/stackoverflow.txt
            url = https://svnbook.red-bean.com/en/1.7/svn-book.html
            output = {downloads_dir}/svn-book.html
            url = https://svnbook.red-bean.com/en/1.7/svn-book.pdf
            output = {downloads_dir}/svn-book.pdf
            url = http://www.oss4aix.org/download/KDE/kdebase-3.4.3-1ssl.aix5.1.ppc.rpm
            output = {downloads_dir}/kdebase-3.4.3-1ssl.aix5.1.ppc.rpm
            url = http://www.oss4aix.org/download/KDE/kdebindings-3.4.3-1.aix5.1.ppc.rpm
            output = {downloads_dir}/kdebindings-3.4.3-1.aix5.1.ppc.rpm
            url = http://www.oss4aix.org/download/KDE/qt-devel-3.3.5-1.aix5.1.ppc.rpm
            output = {downloads_dir}/qt-devel-3.3.5-1.aix5.1.ppc.rpm
            url = http://www.oss4aix.org/download/KDE/kdevelop-3.2.3-1.aix5.1.ppc.rpm
            output = {downloads_dir}/kdevelop-3.2.3-1.aix5.1.ppc.rpm
            url = http://speedtest.ftp.otenet.gr/files/test10Mb.db
            output = {downloads_dir}/test10Mb.db
            url = https://speed.hetzner.de/1GB.bin
            output = {downloads_dir}/1GB.pip

            url = https://www.youtube.com/
            output = {downloads_dir}/youtube2.txt
            url = https://stackoverflow.com/
            output = {downloads_dir}/stackoverflow2.txt
            url = https://svnbook.red-bean.com/en/1.7/svn-book.html
            output = {downloads_dir}/svn-book2.html
            url = https://svnbook.red-bean.com/en/1.7/svn-book.pdf
            output = {downloads_dir}/svn-book2.pdf
            url = http://www.oss4aix.org/download/KDE/kdebase-3.4.3-1ssl.aix5.1.ppc.rpm
            output = {downloads_dir}/kdebase-3.4.3-1ssl.aix5.1.ppc2.rpm
            url = http://www.oss4aix.org/download/KDE/kdebindings-3.4.3-1.aix5.1.ppc.rpm
            output = {downloads_dir}/kdebindings-3.4.3-1.aix5.1.ppc2.rpm
            url = http://www.oss4aix.org/download/KDE/qt-devel-3.3.5-1.aix5.1.ppc.rpm
            output = {downloads_dir}/qt-devel-3.3.5-1.aix5.1.ppc2.rpm
            url = http://www.oss4aix.org/download/KDE/kdevelop-3.2.3-1.aix5.1.ppc.rpm
            output = {downloads_dir}/kdevelop-3.2.3-1.aix5.1.ppc2.rpm
            url = http://speedtest.ftp.otenet.gr/files/test10Mb.db
            output = {downloads_dir}/test10Mb2.db
            url = https://speed.hetzner.de/1GB.bin
            output = {downloads_dir}/1GB2.pip
           """

        config_file = self.pbt.path_inside_test_folder("config_file")
        config_file.write_text(config_file_text)
        curl_path = Path("/usr/bin/curl")

        self.pbt.batch_accum.clear(section_name="doit")
        self.pbt.batch_accum += MakeDir(downloads_dir)
        self.pbt.batch_accum += CurlWithInternalParallel(curl_path, config_file)
        self.pbt.exec_and_capture_output()

    def test_CurlInternalParallel_progress_tick_throttle_and_ema(self):
        """_maybe_emit_progress_tick throttles to one emit per
        interval and reports an EMA-smoothed throughput plus cumulative bytes/
        files, so Central can compute a live ETA during the download."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc

        obj = CurlWithInternalParallel(
            Path("curl"), Path("cfg"),
            total_files_to_download=10,
            previously_downloaded_files=0,
            total_bytes_to_download=10000,
        )
        # State normally seeded in __call__ before the curl loop.
        obj._ema_throughput_bps = 0.0
        obj._last_emit_monotonic = None
        obj._last_emit_bytes = 0
        obj._session_id = "sess-1"

        emit = mock.MagicMock(return_value="line")
        # monotonic is called once per _maybe_emit_progress_tick.
        clock = [100.0, 100.5, 101.5]
        with mock.patch.object(sbc.time, "monotonic", side_effect=clock), \
                mock.patch("pyinstl.downloadEvents.emit_session_state", emit):
            obj._maybe_emit_progress_tick(0, 0)        # t=100.0: seed + emit (EMA still 0)
            obj._maybe_emit_progress_tick(500, 1)      # t=100.5: dt<1.0 -> throttled, no emit
            obj._maybe_emit_progress_tick(1500, 3)     # t=101.5: dt=1.5 -> emit w/ EMA>0

        self.assertEqual(emit.call_count, 2, "throttle should suppress the mid-interval tick")

        first = emit.call_args_list[0].kwargs
        self.assertEqual(first["state"], "downloading")
        self.assertEqual(first["session_id"], "sess-1")
        self.assertEqual(first["bytes_received"], 0)
        self.assertEqual(first["observed_throughput_bytes_per_second"], 0)

        second = emit.call_args_list[1].kwargs
        self.assertEqual(second["bytes_received"], 1500)
        self.assertEqual(second["files_completed"], 3)
        # inst = (1500-0)/1.5 = 1000 b/s; EMA seeds to the first sample.
        self.assertEqual(second["observed_throughput_bytes_per_second"], 1000)

    def test_CurlInternalParallel_progress_tick_never_raises(self):
        """Instrumentation must never break a download: a failing emitter is
        swallowed, not propagated."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc

        obj = CurlWithInternalParallel(
            Path("curl"), Path("cfg"),
            total_files_to_download=1,
            previously_downloaded_files=0,
            total_bytes_to_download=100,
        )
        obj._ema_throughput_bps = 0.0
        obj._last_emit_monotonic = None
        obj._last_emit_bytes = 0
        obj._session_id = "sess-1"

        boom = mock.MagicMock(side_effect=RuntimeError("emit failed"))
        with mock.patch.object(sbc.time, "monotonic", return_value=100.0), \
                mock.patch("pyinstl.downloadEvents.emit_session_state", boom):
            obj._maybe_emit_progress_tick(10, 1)  # must not raise

    def test_CurlInternalParallel_parse_part_output_paths(self):
        """Root-cause fix: the poller's byte source is the curl config's
        ``output =`` entries (the .part files), parsed once and cached; blank and
        non-output lines are ignored."""
        import tempfile
        obj = CurlWithInternalParallel(
            Path("curl"), Path("cfg"),
            total_files_to_download=2, previously_downloaded_files=0,
            total_bytes_to_download=100,
        )
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "dl.config"
            cfg.write_text(
                'parallel\nprogress-bar\n\n'
                'continue-at = -\n'
                'url = "https://x/a"\n'
                f'output = "{d}/a.part"\n\n'
                'continue-at = -\n'
                'url = "https://x/b"\n'
                f'output = "{d}/b.part"\n',
                encoding="utf-8",
            )
            obj.config_file_path = cfg
            paths = obj._download_part_output_paths()
            self.assertEqual(paths, [f"{d}/a.part", f"{d}/b.part"])
            # parsed once and cached (same list object returned)
            self.assertIs(obj._download_part_output_paths(), paths)

    def test_CurlInternalParallel_sum_part_bytes_monotonic(self):
        """Cumulative bytes = sum of on-disk .part sizes; a not-yet-created part
        is skipped (never raises); the file estimate is byte-proportional and
        never regresses even if a part shrinks (resume/continue-at safety)."""
        import tempfile
        obj = CurlWithInternalParallel(
            Path("curl"), Path("cfg"),
            total_files_to_download=4, previously_downloaded_files=0,
            total_bytes_to_download=1000,
        )
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a.part"
            b = Path(d) / "b.part"
            missing = Path(d) / "c.part"
            obj._part_output_paths_cache = [str(a), str(b), str(missing)]

            a.write_bytes(b"x" * 250)                       # 250 B, b & c absent
            total, files = obj._sum_downloaded_part_bytes()
            self.assertEqual(total, 250)                    # missing parts skipped
            self.assertEqual(files, int(4 * 250 / 1000))    # proportional -> 1

            b.write_bytes(b"y" * 250)                       # 500 B total
            total2, files2 = obj._sum_downloaded_part_bytes()
            self.assertEqual(total2, 500)
            self.assertEqual(files2, 2)

            a.write_bytes(b"z" * 10)                         # total drops to 260
            total3, files3 = obj._sum_downloaded_part_bytes()
            self.assertEqual(total3, 260)
            self.assertGreaterEqual(files3, files2)          # estimate never regresses

    def test_CurlInternalParallel_poller_emits_and_stops(self):
        """The .part poller emits >=1 download_progress tick with climbing bytes
        (and verify-parity phase_bytes) from growing part files, then joins
        promptly when signaled -- it must never wedge the process (P7-010)."""
        from unittest import mock
        from threading import Event, Thread
        import time as _t
        import tempfile
        import pybatch.subprocessBatchCommands as sbc

        obj = CurlWithInternalParallel(
            Path("curl"), Path("cfg"),
            total_files_to_download=2, previously_downloaded_files=0,
            total_bytes_to_download=1000,
        )
        obj._ema_throughput_bps = 0.0
        obj._last_emit_monotonic = None
        obj._last_emit_bytes = 0
        obj._session_id = "sess-poll"

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.part"
            p.write_bytes(b"x" * 100)
            obj._part_output_paths_cache = [str(p)]

            emit = mock.MagicMock(return_value="line")
            # Shrink the poll/throttle interval so the test runs fast; the poller
            # reads the module global at call time, so patching it takes effect.
            with mock.patch.object(sbc, "_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC", 0.02), \
                    mock.patch("pyinstl.downloadEvents.emit_session_state", emit):
                stop = Event()
                th = Thread(target=obj._run_download_progress_poller, args=(stop,), daemon=True)
                th.start()
                _t.sleep(0.1)                    # first poll seeds baseline; later polls emit
                p.write_bytes(b"x" * 600)        # bytes climb
                _t.sleep(0.1)
                stop.set()
                th.join(timeout=2.0)
                self.assertFalse(th.is_alive(), "poller must join promptly on stop")

        self.assertGreaterEqual(emit.call_count, 1)
        last = emit.call_args_list[-1].kwargs
        self.assertEqual(last["state"], "downloading")
        self.assertEqual(last["reason"], "download_progress")
        self.assertGreaterEqual(last["bytes_received"], 600)
        self.assertEqual(last["phase_bytes_done"], last["bytes_received"])
        self.assertEqual(last["phase_bytes_planned"], 1000)

    # -- post-run completeness reconciliation ------------------

    @staticmethod
    def _make_curl_obj(config_file_path, total_files=3, total_bytes=300):
        obj = CurlWithInternalParallel(
            Path("curl"), Path(config_file_path),
            total_files_to_download=total_files,
            previously_downloaded_files=0,
            total_bytes_to_download=total_bytes,
        )
        obj._session_id = "sess-test"
        obj._hold_seconds_used = 0.0
        obj._offline_probe_attempt = 0
        return obj

    @staticmethod
    def _write_internal_parallel_config(cfg_path, outputs, headers_for=()):
        """Write a curlHelper-shaped internal-parallel config: header block +
        one entry (no-fail/continue-at/url/output) per output path."""
        lines = [
            "parallel", "progress-bar", "raw", "fail", "show-error",
            "compressed", "create-dirs", "connect-timeout = 16", "max-time = 600",
            "retry = 12", "retry-delay = 12", "retry-connrefused",
            "retry-max-time = 90", "retry-all-errors", "cookie = test=1",
            "parallel-max = 50", "",
        ]
        for out_i, out_path in enumerate(outputs):
            lines.append("no-fail")
            lines.append("continue-at = -")
            if out_i in headers_for:
                lines.append('header = "If-None-Match: abc"')
            lines.append(f'url = "https://cdn.example.com/file{out_i}.wtar"')
            lines.append(f'output = "{out_path}"')
            lines.append("")
        Path(cfg_path).write_text("\n".join(lines), encoding="utf-8")

    def test_CurlInternalParallel_reconcile_parses_header_and_entries(self):
        """The reconciliation parser must split a curlHelper-generated config
        into header lines and per-download entries, preserving each entry's
        original no-fail/continue-at/header/url/output lines."""
        cfg = self.pbt.path_inside_test_folder("dl-00")
        out_dir = self.pbt.path_inside_test_folder("outs")
        out_dir.mkdir(exist_ok=True)
        outputs = [str(out_dir / f"f{i}.wtar.instl-x.part") for i in range(3)]
        self._write_internal_parallel_config(cfg, outputs, headers_for={1})

        obj = self._make_curl_obj(cfg)
        header_lines, entries, uses_next = obj._parse_curl_config_for_reconcile(cfg)

        self.assertFalse(uses_next)
        self.assertIn("parallel", header_lines)
        self.assertIn("retry-all-errors", header_lines)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["output_path"], outputs[0])
        self.assertEqual(entries[0]["pre_lines"], ["no-fail", "continue-at = -"])
        self.assertEqual(entries[1]["pre_lines"],
                         ["no-fail", "continue-at = -", 'header = "If-None-Match: abc"'])
        self.assertEqual(entries[2]["url_line"], 'url = "https://cdn.example.com/file2.wtar"')

    def test_CurlInternalParallel_reconcile_redownloads_only_missing(self):
        """curl --parallel can exit 0 while transfers failed permanently; the
        reconciliation pass must re-run curl with a config containing ONLY the
        entries whose expected output is missing on disk."""
        from unittest import mock
        cfg = self.pbt.path_inside_test_folder("dl-00")
        out_dir = self.pbt.path_inside_test_folder("outs")
        out_dir.mkdir(exist_ok=True)
        outputs = [str(out_dir / f"f{i}.wtar.instl-x.part") for i in range(3)]
        self._write_internal_parallel_config(cfg, outputs)
        Path(outputs[0]).write_bytes(b"x")   # present
        Path(outputs[2]).write_bytes(b"y")   # present; outputs[1] missing

        obj = self._make_curl_obj(cfg)
        ran_configs = []

        def fake_run(config_path_fixed, pause_check, channel):
            ran_configs.append(config_path_fixed)
            Path(outputs[1]).write_bytes(b"z")  # the re-run "downloads" it
            return 0

        with mock.patch.object(obj, "_run_config_with_recovery", side_effect=fake_run):
            return_code = obj._reconcile_missing_outputs(None, None)

        self.assertEqual(return_code, 0)
        self.assertEqual(len(ran_configs), 1, "one reconciliation round should suffice")
        retry_text = Path(f"{os.fspath(cfg)}.reconcile-01").read_text(encoding="utf-8")
        self.assertIn('url = "https://cdn.example.com/file1.wtar"', retry_text)
        self.assertNotIn("file0.wtar", retry_text)
        self.assertNotIn("file2.wtar", retry_text)
        self.assertIn("continue-at = -", retry_text)   # entry lines preserved
        self.assertIn("parallel", retry_text)          # header preserved

    def test_CurlInternalParallel_reconcile_rounds_are_bounded(self):
        """When outputs never appear, reconciliation must stop after
        DOWNLOAD_RECONCILE_MAX_ROUNDS and leave recovery to the checksum
        phase (no exception, no endless loop)."""
        from unittest import mock
        cfg = self.pbt.path_inside_test_folder("dl-00")
        out_dir = self.pbt.path_inside_test_folder("outs")
        out_dir.mkdir(exist_ok=True)
        outputs = [str(out_dir / "never.wtar.instl-x.part")]
        self._write_internal_parallel_config(cfg, outputs)

        obj = self._make_curl_obj(cfg, total_files=1, total_bytes=100)
        config_vars["DOWNLOAD_RECONCILE_MAX_ROUNDS"] = "2"
        try:
            with mock.patch.object(obj, "_run_config_with_recovery", return_value=0) as run_mock:
                return_code = obj._reconcile_missing_outputs(None, None)
        finally:
            config_vars["DOWNLOAD_RECONCILE_MAX_ROUNDS"] = "3"
        self.assertEqual(return_code, 0)
        self.assertEqual(run_mock.call_count, 2, "must re-run exactly max_rounds times")

    def test_CurlInternalParallel_reconcile_kill_switch(self):
        """DOWNLOAD_RECONCILE_MISSING_OUTPUTS=no must restore the old behavior:
        trust curl's exit code, run nothing."""
        from unittest import mock
        cfg = self.pbt.path_inside_test_folder("dl-00")
        outputs = [str(self.pbt.path_inside_test_folder("missing.part"))]
        self._write_internal_parallel_config(cfg, outputs)

        obj = self._make_curl_obj(cfg, total_files=1, total_bytes=100)
        config_vars["DOWNLOAD_RECONCILE_MISSING_OUTPUTS"] = "no"
        try:
            with mock.patch.object(obj, "_run_config_with_recovery") as run_mock:
                return_code = obj._reconcile_missing_outputs(None, None)
        finally:
            config_vars["DOWNLOAD_RECONCILE_MISSING_OUTPUTS"] = "yes"
        self.assertEqual(return_code, 0)
        run_mock.assert_not_called()

    # -- offline-hold with structured events -------------------

    def test_CurlInternalParallel_offline_hold_emits_events_and_resumes(self):
        """While offline the hold loop must emit a paused session_state whose
        reason looks offline to Central plus a network-class retry_decision per
        failed probe (feeding Central's >=3 streak detector), then emit a
        resuming 'downloading' session_state when connectivity returns.
        Requires the client to have declared the backend-hold capability
        (DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD) -- a new Central sets it."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"))
        obj._part_output_paths_cache = []

        emit_state = mock.MagicMock(return_value="line")
        emit_retry = mock.MagicMock(return_value="line")
        probes = [(False, "tcp_connect"), (False, "dns_resolution"), (True, None)]
        config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "yes"
        try:
            with mock.patch.object(obj, "_probe_connectivity", side_effect=probes), \
                    mock.patch.object(sbc.time, "sleep"), \
                    mock.patch("pyinstl.downloadEvents.emit_session_state", emit_state), \
                    mock.patch("pyinstl.downloadEvents.emit_retry_decision", emit_retry):
                came_back = obj._hold_until_online(None)
        finally:
            config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "no"

        self.assertTrue(came_back)
        # session_state: first is the offline-flavored pause, last is the resume
        first_state = emit_state.call_args_list[0].kwargs
        self.assertEqual(first_state["state"], "paused")
        self.assertIn("offline", first_state["reason"])
        last_state = emit_state.call_args_list[-1].kwargs
        self.assertEqual(last_state["state"], "downloading")
        self.assertEqual(last_state["reason"], "resuming_after_offline")
        # retry_decision: one per failed probe, network-class failureClass
        self.assertEqual(emit_retry.call_count, 2)
        failure_classes = [call.args[0].failure_class.value for call in emit_retry.call_args_list]
        self.assertEqual(failure_classes, ["tcp_connect", "dns_resolution"])
        reasons = [call.args[0].reason for call in emit_retry.call_args_list]
        self.assertEqual(reasons, ["offline_hold_probe_failed"] * 2)

    def test_CurlInternalParallel_offline_hold_overall_timeout(self):
        """The hold is bounded: once the overall hold budget is spent the loop
        returns False so the old retries-exhausted path applies."""
        from unittest import mock
        import itertools
        import pybatch.subprocessBatchCommands as sbc

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"))
        obj._part_output_paths_cache = []

        config_vars["DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS"] = "5"
        try:
            with mock.patch.object(obj, "_probe_connectivity", return_value=(False, "tcp_connect")), \
                    mock.patch.object(sbc.time, "sleep"), \
                    mock.patch.object(sbc.time, "monotonic",
                                      side_effect=itertools.count(start=0.0, step=1.0)), \
                    mock.patch("pyinstl.downloadEvents.emit_session_state", mock.MagicMock()), \
                    mock.patch("pyinstl.downloadEvents.emit_retry_decision", mock.MagicMock()):
                came_back = obj._hold_until_online(None)
        finally:
            config_vars["DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS"] = "1800"
        self.assertFalse(came_back, "hold must give up after the overall timeout")

    def test_CurlInternalParallel_network_error_emits_retry_decision_then_holds(self):
        """A network-class curl exit must emit a retry_decision DOWNLOAD_EVENT
        (curlExitCode preserved, network failureClass) and, when the probe says
        offline, enter the hold instead of burning the backoff budget."""
        from unittest import mock

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"))
        emit_retry = mock.MagicMock(return_value="line")
        runs = [(7, False), (0, False)]
        config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "yes"
        try:
            with mock.patch.object(obj, "_run_curl_once", side_effect=runs), \
                    mock.patch.object(obj, "_probe_connectivity", return_value=(False, "tcp_connect")), \
                    mock.patch.object(obj, "_hold_until_online", return_value=True) as hold_mock, \
                    mock.patch("pyinstl.downloadEvents.emit_retry_decision", emit_retry):
                return_code = obj._run_config_with_recovery("cfg", None, None)
        finally:
            config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "no"

        self.assertEqual(return_code, 0)
        hold_mock.assert_called_once()
        self.assertEqual(emit_retry.call_count, 1)
        decision = emit_retry.call_args_list[0].args[0]
        self.assertEqual(decision.failure_class.value, "tcp_connect")
        self.assertEqual(decision.curl_exit_code, 7)
        self.assertEqual(decision.reason, "bulk_curl_network_error")

    def test_CurlInternalParallel_offline_hold_kill_switch_keeps_backoff(self):
        """DOWNLOAD_OFFLINE_HOLD_ENABLED=no restores the legacy bounded-backoff
        path: no probe, no hold, just the short sleep-and-retry loop."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"))
        runs = [(7, False), (0, False)]
        config_vars["DOWNLOAD_OFFLINE_HOLD_ENABLED"] = "no"
        try:
            with mock.patch.object(obj, "_run_curl_once", side_effect=runs), \
                    mock.patch.object(obj, "_probe_connectivity") as probe_mock, \
                    mock.patch.object(obj, "_hold_until_online") as hold_mock, \
                    mock.patch.object(sbc.time, "sleep") as sleep_mock, \
                    mock.patch("pyinstl.downloadEvents.emit_retry_decision", mock.MagicMock()):
                return_code = obj._run_config_with_recovery("cfg", None, None)
        finally:
            config_vars["DOWNLOAD_OFFLINE_HOLD_ENABLED"] = "yes"

        self.assertEqual(return_code, 0)
        probe_mock.assert_not_called()
        hold_mock.assert_not_called()
        sleep_mock.assert_called_once()  # legacy backoff slept once before the re-run

    # -- stall watchdog (poller backstop) -----------------------

    def test_CurlInternalParallel_poller_emits_stalled_signal(self):
        """When on-disk bytes stop growing for the watchdog interval while the
        poller runs, it must log and emit a stalled-flavored session_state --
        without killing anything (enforcement is curl's speed-time)."""
        from unittest import mock
        from threading import Event, Thread
        import time as _t
        import tempfile
        import pybatch.subprocessBatchCommands as sbc

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"),
                                  total_files=1, total_bytes=1000)
        obj._ema_throughput_bps = 0.0
        obj._last_emit_monotonic = None
        obj._last_emit_bytes = 0

        with tempfile.TemporaryDirectory() as d:
            part = Path(d) / "a.part"
            part.write_bytes(b"x" * 100)     # static: never grows
            obj._part_output_paths_cache = [str(part)]

            emit = mock.MagicMock(return_value="line")
            config_vars["DOWNLOAD_STALL_WATCHDOG_SECONDS"] = "1"
            config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "yes"
            try:
                with mock.patch.object(sbc, "_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC", 0.05), \
                        mock.patch("pyinstl.downloadEvents.emit_session_state", emit):
                    stop = Event()
                    th = Thread(target=obj._run_download_progress_poller, args=(stop,), daemon=True)
                    th.start()
                    _t.sleep(2.5)            # comfortably > watchdog interval with zero growth
                    stop.set()
                    th.join(timeout=2.0)
                    self.assertFalse(th.is_alive(), "poller must join promptly on stop")
            finally:
                config_vars["DOWNLOAD_STALL_WATCHDOG_SECONDS"] = "180"
                config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "no"

        stalled = [call.kwargs for call in emit.call_args_list
                   if call.kwargs.get("reason") == "stalled_no_progress"]
        self.assertGreaterEqual(len(stalled), 1, "expected a stalled session_state signal")
        self.assertEqual(stalled[0]["state"], "downloading")
        self.assertEqual(stalled[0]["bytes_received"], 100)

    def test_CurlInternalParallel_poller_offline_probe_raises_hold_fast(self):
        """Fast offline detection (field finding 2026-07-30): when bytes stop
        growing and the connectivity probe fails, the poller must raise the
        paused/offline_no_network hold within DOWNLOAD_STALL_PROBE_SECONDS --
        long before curl's speed-time -- and announce resuming_after_offline
        (before any further progress tick) once bytes grow again."""
        from unittest import mock
        from threading import Event, Thread
        import time as _t
        import tempfile
        import pybatch.subprocessBatchCommands as sbc

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"),
                                  total_files=1, total_bytes=1000)
        obj._ema_throughput_bps = 0.0
        obj._last_emit_monotonic = None
        obj._last_emit_bytes = 0

        with tempfile.TemporaryDirectory() as d:
            part = Path(d) / "a.part"
            part.write_bytes(b"x" * 100)     # static at first: stalls immediately
            obj._part_output_paths_cache = [str(part)]

            emit = mock.MagicMock(return_value="line")
            config_vars["DOWNLOAD_STALL_PROBE_SECONDS"] = "1"
            config_vars["DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS"] = "1"
            config_vars["DOWNLOAD_STALL_WATCHDOG_SECONDS"] = "600"  # backstop must not fire here
            config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "yes"
            try:
                with mock.patch.object(sbc, "_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC", 0.05), \
                        mock.patch.object(obj, "_probe_connectivity", return_value=(False, "tcp_connect")), \
                        mock.patch("pyinstl.downloadEvents.emit_session_state", emit):
                    stop = Event()
                    th = Thread(target=obj._run_download_progress_poller, args=(stop,), daemon=True)
                    th.start()
                    _t.sleep(2.5)                    # > probe threshold with zero growth
                    part.write_bytes(b"x" * 500)     # bytes grow: outage over
                    _t.sleep(1.0)
                    stop.set()
                    th.join(timeout=2.0)
                    self.assertFalse(th.is_alive(), "poller must join promptly on stop")
            finally:
                config_vars["DOWNLOAD_STALL_PROBE_SECONDS"] = "8"
                config_vars["DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS"] = "5"
                config_vars["DOWNLOAD_STALL_WATCHDOG_SECONDS"] = "180"
                config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "no"

        reasons = [call.kwargs.get("reason") for call in emit.call_args_list]
        self.assertIn("offline_no_network", reasons, "expected a fast offline hold from the poller")
        self.assertIn("resuming_after_offline", reasons, "expected a resume announcement after bytes grew")
        hold_at = reasons.index("offline_no_network")
        resume_at = reasons.index("resuming_after_offline")
        self.assertGreater(resume_at, hold_at, "resume must be announced after the hold")
        hold_call = emit.call_args_list[hold_at]
        self.assertEqual(hold_call.kwargs["state"], "paused")
        # while the hold is active the poller must not interleave non-paused
        # progress ticks (they would churn Central's backend-hold flag)
        between = [call.kwargs.get("state") for call in emit.call_args_list[hold_at + 1:resume_at]]
        self.assertNotIn("downloading", between,
                         "no downloading session_state may be emitted while the stall hold is active")

    def test_CurlInternalParallel_poller_probe_online_no_false_hold(self):
        """A stalled transfer on a HEALTHY network (probe succeeds -- e.g. a
        slow CDN moment) must not raise the offline hold."""
        from unittest import mock
        from threading import Event, Thread
        import time as _t
        import tempfile
        import pybatch.subprocessBatchCommands as sbc

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"),
                                  total_files=1, total_bytes=1000)
        obj._ema_throughput_bps = 0.0
        obj._last_emit_monotonic = None
        obj._last_emit_bytes = 0

        with tempfile.TemporaryDirectory() as d:
            part = Path(d) / "a.part"
            part.write_bytes(b"x" * 100)     # static: never grows
            obj._part_output_paths_cache = [str(part)]

            emit = mock.MagicMock(return_value="line")
            config_vars["DOWNLOAD_STALL_PROBE_SECONDS"] = "1"
            config_vars["DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS"] = "1"
            config_vars["DOWNLOAD_STALL_WATCHDOG_SECONDS"] = "600"
            config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "yes"
            try:
                with mock.patch.object(sbc, "_DOWNLOAD_PROGRESS_EMIT_MIN_INTERVAL_SEC", 0.05), \
                        mock.patch.object(obj, "_probe_connectivity", return_value=(True, None)), \
                        mock.patch("pyinstl.downloadEvents.emit_session_state", emit):
                    stop = Event()
                    th = Thread(target=obj._run_download_progress_poller, args=(stop,), daemon=True)
                    th.start()
                    _t.sleep(2.5)
                    stop.set()
                    th.join(timeout=2.0)
            finally:
                config_vars["DOWNLOAD_STALL_PROBE_SECONDS"] = "8"
                config_vars["DOWNLOAD_OFFLINE_PROBE_INTERVAL_SECONDS"] = "5"
                config_vars["DOWNLOAD_STALL_WATCHDOG_SECONDS"] = "180"
                config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "no"

        reasons = [call.kwargs.get("reason") for call in emit.call_args_list]
        self.assertNotIn("offline_no_network", reasons,
                         "probe success must not raise an offline hold")

    def test_CurlInternalParallel_probe_host_from_base_links_url(self):
        """The connectivity probe targets the validated download host from
        BASE_LINKS_URL; without it, the first url in the curl config; and
        fails open (assume online) when neither is available."""
        cfg = self.pbt.path_inside_test_folder("dl-00")
        self._write_internal_parallel_config(cfg, [str(self.pbt.path_inside_test_folder("f.part"))])

        config_vars["BASE_LINKS_URL"] = "https://cdn.wavescdn.example:8443/links"
        try:
            obj = self._make_curl_obj(cfg)
            self.assertEqual(obj._probe_host_and_port(), ("cdn.wavescdn.example", 8443))
        finally:
            config_vars["BASE_LINKS_URL"] = ""

        obj2 = self._make_curl_obj(cfg)   # falls back to the config's first url
        self.assertEqual(obj2._probe_host_and_port(), ("cdn.example.com", 443))

    # -- Capability handshake: emissions gated on the driving client ---------

    @staticmethod
    def _proxy_env(**overrides):
        """A patch.dict mapping that neutralizes every proxy env var curl
        honors, then applies overrides — so the test is hermetic no matter
        what the host machine's environment contains."""
        env = {name: "" for name in ("https_proxy", "http_proxy", "all_proxy",
                                     "HTTP_PROXY", "ALL_PROXY", "HTTPS_PROXY")}
        env.update(overrides)
        return env

    def test_CurlInternalParallel_no_backend_hold_events_without_capability(self):
        """With DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD off (the shipped default,
        i.e. an OLD Central that never declared the capability) the engine
        must still perform the silent recovery — hold, probe, resume — but
        emit ZERO new retry_decision / session_state events: an old Central's
        3-streak online detector would answer them with a stdin pause that
        nothing auto-resumes on Windows, deadlocking the engine."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"))
        obj._part_output_paths_cache = []

        emit_state = mock.MagicMock(return_value="line")
        emit_retry = mock.MagicMock(return_value="line")
        probes = [(False, "tcp_connect"), (False, "dns_resolution"), (True, None)]
        config_vars["DOWNLOAD_CLIENT_HANDLES_BACKEND_HOLD"] = "no"
        with mock.patch.object(obj, "_probe_connectivity", side_effect=probes), \
                mock.patch.object(sbc.time, "sleep"), \
                mock.patch("pyinstl.downloadEvents.emit_session_state", emit_state), \
                mock.patch("pyinstl.downloadEvents.emit_retry_decision", emit_retry):
            came_back = obj._hold_until_online(None)

        self.assertTrue(came_back, "silent recovery must still hold and resume")
        emit_state.assert_not_called()
        emit_retry.assert_not_called()

        # The bulk network-exit path is likewise silent without the capability.
        obj2 = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"))
        emit_retry2 = mock.MagicMock(return_value="line")
        runs = [(7, False), (0, False)]
        with mock.patch.object(obj2, "_run_curl_once", side_effect=runs), \
                mock.patch.object(obj2, "_probe_connectivity", return_value=(False, "tcp_connect")), \
                mock.patch.object(obj2, "_hold_until_online", return_value=True), \
                mock.patch("pyinstl.downloadEvents.emit_retry_decision", emit_retry2):
            return_code = obj2._run_config_with_recovery("cfg", None, None)
        self.assertEqual(return_code, 0)
        emit_retry2.assert_not_called()

    def test_CurlInternalParallel_hold_budget_excludes_paused_time(self):
        """Time spent blocked in channel.wait_if_paused (a user/Central
        pause) must NOT burn the cumulative offline-hold budget — otherwise
        one paused outage would spend the whole budget and a LATER outage in
        the same command would get zero hold protection."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc

        class _FakeClock:
            def __init__(self):
                self.t = 0.0

            def monotonic(self):
                return self.t

            def advance(self, seconds):
                self.t += seconds

        clock = _FakeClock()

        class _PausingChannel:
            """Simulates being paused for 100s on every wait_if_paused."""
            def wait_if_paused(self, poll_seconds=0.5):
                clock.advance(100.0)

            def sleep_or_wake(self, seconds):
                clock.advance(seconds)

        obj = self._make_curl_obj(self.pbt.path_inside_test_folder("dl-00"))
        obj._part_output_paths_cache = []
        probes = [(False, "tcp_connect")] * 3 + [(True, None)]

        config_vars["DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS"] = "30"
        try:
            with mock.patch.object(obj, "_probe_connectivity", side_effect=probes), \
                    mock.patch.object(sbc.time, "monotonic", clock.monotonic):
                came_back = obj._hold_until_online(_PausingChannel())
        finally:
            config_vars["DOWNLOAD_OFFLINE_HOLD_TIMEOUT_SECONDS"] = "1800"

        # Wall time was ~420s (4x100s paused + 4x5s probe waits) but only the
        # ~20s of ACTIVE hold count; without the exclusion the 30s budget
        # would have expired on the second loop and returned False.
        self.assertTrue(came_back, "paused time must not expire the hold budget")
        self.assertAlmostEqual(obj._hold_seconds_used, 20.0, places=3)

    def test_CurlInternalParallel_reconcile_rewrites_missing_as_fresh_start(self):
        """Reconciliation must never replay a resume entry's original
        'continue-at = N' (N>0) or its stale conditional headers for an output
        that no longer exists: curl -C N with a nonexistent output writes the
        ranged body at offset 0 — a silently corrupt file missing its first N
        bytes. Such entries are rewritten as fresh-start."""
        from unittest import mock
        cfg = self.pbt.path_inside_test_folder("dl-00")
        out_dir = self.pbt.path_inside_test_folder("outs")
        out_dir.mkdir(exist_ok=True)
        out_path = str(out_dir / "resume.wtar.instl-x.part")
        lines = [
            "parallel", "retry = 12", "retry-max-time = 360", "",
            "no-fail",
            "continue-at = 12345",
            'header = "If-None-Match: etag-abc"',
            'header = "X-Custom: keep-me"',
            'url = "https://cdn.example.com/resume.wtar"',
            f'output = "{out_path}"',
            "",
        ]
        Path(cfg).write_text("\n".join(lines), encoding="utf-8")

        obj = self._make_curl_obj(cfg, total_files=1, total_bytes=100)

        def fake_run(config_path_fixed, pause_check, channel):
            Path(out_path).write_bytes(b"z")  # the re-run "downloads" it
            return 0

        with mock.patch.object(obj, "_run_config_with_recovery", side_effect=fake_run):
            return_code = obj._reconcile_missing_outputs(None, None)

        self.assertEqual(return_code, 0)
        retry_text = Path(f"{os.fspath(cfg)}.reconcile-01").read_text(encoding="utf-8")
        self.assertNotIn("continue-at = 12345", retry_text,
                         "must not replay a byte offset for a missing output")
        self.assertIn("continue-at = -", retry_text)
        self.assertNotIn("If-None-Match", retry_text,
                         "stale conditional headers must be dropped")
        self.assertIn('header = "X-Custom: keep-me"', retry_text,
                      "non-conditional headers are preserved")
        self.assertIn("no-fail", retry_text)
        self.assertIn('url = "https://cdn.example.com/resume.wtar"', retry_text)

    def test_CurlInternalParallel_probe_goes_through_proxy_when_configured(self):
        """On proxy-only networks a direct TCP connect to the download host
        always fails while curl (which honors the proxy env vars) is fine —
        so when a proxy is configured the probe must target the PROXY
        endpoint, not the origin host."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc
        cfg = self.pbt.path_inside_test_folder("dl-00")
        self._write_internal_parallel_config(cfg, [str(self.pbt.path_inside_test_folder("f.part"))])
        obj = self._make_curl_obj(cfg)

        with mock.patch.dict(os.environ,
                             self._proxy_env(HTTPS_PROXY="http://proxy.corp.example:3128")), \
                mock.patch.object(sbc.socket, "create_connection") as connect_mock:
            online, failure_class = obj._probe_connectivity()

        self.assertTrue(online)
        self.assertIsNone(failure_class)
        (address,), kwargs = connect_mock.call_args
        self.assertEqual(address, ("proxy.corp.example", 3128),
                         "probe must connect to the proxy, not the origin host")

    def test_CurlInternalParallel_probe_fails_open_on_unparsable_proxy(self):
        """A proxy that is configured but whose endpoint cannot be determined
        (no explicit port) makes the probe INCONCLUSIVE: it must fail open
        (report online -> legacy bounded backoff), never guess a port and
        risk a 30-minute false offline hold on a healthy network."""
        from unittest import mock
        import pybatch.subprocessBatchCommands as sbc
        cfg = self.pbt.path_inside_test_folder("dl-00")
        self._write_internal_parallel_config(cfg, [str(self.pbt.path_inside_test_folder("f.part"))])
        obj = self._make_curl_obj(cfg)

        with mock.patch.dict(os.environ, self._proxy_env(HTTPS_PROXY="proxy.corp.example")), \
                mock.patch.object(sbc.socket, "create_connection") as connect_mock:
            online, failure_class = obj._probe_connectivity()

        self.assertTrue(online, "unparsable proxy must be inconclusive, not offline")
        self.assertIsNone(failure_class)
        connect_mock.assert_not_called()

    def test_Dummy(self):
        pass
