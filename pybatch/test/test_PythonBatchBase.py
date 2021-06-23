#!/usr/bin/env python3.9


import sys
import os
from pathlib import Path
import shutil
import stat
import signal
import threading
import _thread
import ctypes
import io
import contextlib
import filecmp
import logging
import random
import string
import itertools as it

import utils
from pybatch import *
from pybatch import PythonBatchCommandAccum, FixAllPermissions
from pybatch.copyBatchCommands import RsyncClone
from configVar import config_vars

current_os_names = utils.get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

config_vars["__CURRENT_OS_NAMES__"] = current_os_names
log = logging.getLogger(__name__)

running_on_Mac = sys.platform == 'darwin'
running_on_Win = sys.platform == 'win32'


@contextlib.contextmanager
def capture_stdout(in_new_stdout=None):
    old_stdout = sys.stdout
    if in_new_stdout is None:
        new_stdout = io.StringIO()
    else:
        new_stdout = in_new_stdout
    sys.stdout = new_stdout
    yield new_stdout
    new_stdout.seek(0)
    sys.stdout = old_stdout


def explain_dict_diff(d1, d2):
    keys1 = set(d1.keys())
    keys2 = set(d2.keys())
    if keys1 != keys2:
        print("keys in d1 not in d2", keys1-keys2)
        print("keys in d2 not in d1", keys2-keys1)
    else:
        for k in keys1:
            if d1[k] != d2[k]:
                print(f"d1['{k}']({d1[k]}) != d2['{k}']({d2[k]})")


def is_identical_dircmp(a_dircmp: filecmp.dircmp):
    """ filecmp.dircmp does not have straight forward way to ask are directories the same?
        is_identical_dircmp attempts to fill this gap
    """
    retVal = len(a_dircmp.left_only) == 0 and len(a_dircmp.right_only) == 0 and len(a_dircmp.diff_files) == 0
    if retVal:
        for sub_dircmp in a_dircmp.subdirs.values():
            retVal = is_identical_dircmp(sub_dircmp)
            if not retVal:
                break
    return retVal


def is_identical_dircomp_with_ignore(a_dircmp: filecmp.dircmp, filen_names_to_ignore):
    '''A non recusive function that tests that two folders are the same, but testing that the ignore list has been ignored (and not copied to trg folder)'''
    return a_dircmp.left_only == filen_names_to_ignore and len(a_dircmp.right_only) == 0 and len(a_dircmp.diff_files) == 0


def is_same_inode(file_1, file_2):
    retVal = os.stat(file_1)[stat.ST_INO] == os.stat(file_2)[stat.ST_INO]
    return retVal


def is_hard_linked(a_dircmp: filecmp.dircmp):
    """ check that all same_files are hard link of each other"""
    retVal = True
    for a_file in a_dircmp.same_files:
        left_file = os.path.join(a_dircmp.left, a_file)
        right_file = os.path.join(a_dircmp.right, a_file)
        retVal = is_same_inode(left_file, right_file)
        if not retVal:
            break
    if retVal:
        for sub_dircmp in a_dircmp.subdirs.values():
            retVal = is_hard_linked(sub_dircmp)
            if not retVal:
                break
    return retVal


def compare_chmod_recursive(folder_path, expected_file_mode, expected_dir_mode):
    root_mode = stat.S_IMODE(os.stat(folder_path).st_mode)
    if root_mode != expected_dir_mode:
        return False
    for root, dirs, files in os.walk(folder_path, followlinks=False):
        for item in files:
            item_path = os.path.join(root, item)
            item_mode = stat.S_IMODE(os.stat(item_path).st_mode)
            if item_mode != expected_file_mode:
                return False
        for item in dirs:
            item_path = os.path.join(root, item)
            item_mode = stat.S_IMODE(os.stat(item_path).st_mode)
            if item_mode != expected_dir_mode:
                return False
    return True


class TimeoutException(Exception):
    def __init__(self, msg=''):
        self.msg = msg


@contextmanager
def assert_timeout(seconds, msg=''):
    timer = threading.Timer(seconds, lambda: _thread.interrupt_main())
    timer.start()
    try:
        yield
    except KeyboardInterrupt:
        raise TimeoutException(f"Timed out after {seconds} for operation {msg}")
    finally:
        # if the action ends in specified time, timer is canceled
        timer.cancel()


main_test_folder_name = "python_batch_test_results"


class TestPythonBatch(object):
    def __init__(self, uni_test_obj, which_test):
        self.uni_test_obj = uni_test_obj
        self.which_test = which_test.lstrip("test_")
        self.test_folder = Path(__file__).joinpath(os.pardir, os.pardir, os.pardir).resolve().joinpath(main_test_folder_name, uni_test_obj.__class__.__name__, self.which_test)
        self.batch_accum: PythonBatchCommandAccum = PythonBatchCommandAccum()
        self.sub_test_counter = 0
        self.output_file_name = None

    def setUp(self):
        """ for each test create it's own test sub-fold
            if sub-folder already exists - remove it.
        """
        if self.test_folder.exists():
            with FixAllPermissions(self.test_folder, recursive=True, report_own_progress=False)as fixer:
                fixer()
            shutil.rmtree(self.test_folder)  # make sure the folder is erased
        self.test_folder.mkdir(parents=True, exist_ok=False)
        self.batch_accum.set_current_section("doit")

    def tearDown(self):
        if self.output_file_name:
            utils.teardown_file_logging(self.output_file_name)

    def path_inside_test_folder(self, *name, assert_not_exist=True):
        retVal = self.test_folder.joinpath(*name).resolve()
        if assert_not_exist:
            self.uni_test_obj.assertFalse(retVal.exists(), f"{self.which_test}: {retVal} should not exist before test")
        return retVal

    def write_file_in_test_folder(self, file_name, contents):
        with open(self.path_inside_test_folder(file_name), "w") as wfd:
            wfd.write(contents)

    def exec_and_capture_output(self, test_name=None, expected_exception=None):
        self.sub_test_counter += 1
        if test_name is None:
            test_name = self.which_test
        test_name = f"{self.sub_test_counter}_{test_name}"

        self.python_batch_file_path = os.fspath(self.path_inside_test_folder(test_name+".py"))
        config_vars["__MAIN_OUT_FILE__"] = self.python_batch_file_path
        config_vars["__MAIN_COMMAND__"] = f"{self.which_test} test #{self.sub_test_counter};"
        bc_repr = repr(self.batch_accum)
        with open(self.python_batch_file_path, "w", encoding='utf-8', errors='replace') as wfd:
            wfd.write(bc_repr)
        bc_compiled = compile(bc_repr, self.python_batch_file_path, 'exec')
        output_file_name = self.path_inside_test_folder(f'{test_name}_output.txt')
        if output_file_name != self.output_file_name:
            if self.output_file_name:
                utils.teardown_file_logging(self.output_file_name)
            self.output_file_name = output_file_name
            utils.setup_file_logging(self.output_file_name, level=logging.INFO)

        if not expected_exception:
            try:
                ops = exec(bc_compiled, globals(), locals())
            except SyntaxError:
                log.error(f"> > > > SyntaxError in {test_name}")
                raise
        else:
            with self.uni_test_obj.assertRaises(expected_exception):
                ops = exec(bc_compiled, globals(), locals())

    def reprs_test_runner(self, *list_of_objs, remark_list=None):
        if remark_list is None:
            remark_list = it.repeat("")
        out_file = self.path_inside_test_folder(self.which_test+".out.txt")
        with open(out_file, "w") as wfd:
            for obj, remark in zip(list_of_objs, remark_list):
                obj_repr = repr(obj)
                obj_recreated = eval(obj_repr)
                diff_explanation = ""
                if hasattr(obj, "explain_diff"):
                    diff_explanation = obj.explain_diff(obj_recreated)
                else:
                    if obj != obj_recreated:
                        diff_explanation = f"{obj_repr} != {repr(obj_recreated)}"
                if remark:
                    remark = f"  # {remark}"
                if diff_explanation:  # there was a problem
                    wfd.write(f"X  {obj_repr}\n  {repr(obj_recreated)}{remark}\n")
                else:
                    wfd.write(f"OK {obj_repr}{remark}\n")

                self.uni_test_obj.assertEqual(obj, obj_recreated, f"{obj.__class__.__name__}.repr did not recreate the object correctly: {diff_explanation}")
