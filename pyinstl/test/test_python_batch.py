#!/usr/bin/env python3.6


import sys
import os
import pathlib
import unittest
import shutil

from pybatch import *
import io
import contextlib

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

def touch(file_path):
    with open(file_path, 'a'):
        os.utime(file_path, None)

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

class TestPythonBatch(unittest.TestCase):
    def __init__(self, which_test="banana"):
        super().__init__(which_test)
        self.which_test = which_test
        self.test_folder = pathlib.Path(__file__).joinpath("..", "..", "..").resolve().joinpath("python_batch_test_results", which_test)
        self.the_output = io.StringIO()

        #print(f"TestConfigVar.__init__ {self.test_folder}")

    def setUp(self):
        if self.test_folder.exists():
            shutil.rmtree(str(self.test_folder))  # make sure the folder is erased
        self.test_folder.mkdir(parents=True, exist_ok=False)

    def tearDown(self):
        pass

    def test_MakeDirs_1_simple(self):
        dir_to_make_1 = self.test_folder.joinpath(self.which_test+"_1").resolve()
        dir_to_make_2 = self.test_folder.joinpath(self.which_test+"_2").resolve()
        self.assertFalse(dir_to_make_1.exists())
        self.assertFalse(dir_to_make_2.exists())

        bc_repr = None
        with BatchCommandAccum() as bc:
            mkdirs_obj = MakeDirs(str(dir_to_make_1), str(dir_to_make_2), remove_obstacles=True)
            mkdirs_obj_recreated = eval(repr(mkdirs_obj))
            #explain_dict_diff(mkdirs_obj.__dict__, mkdirs_obj_recreated.__dict__)
            self.assertEqual(mkdirs_obj, mkdirs_obj_recreated, "MakeDirs.repr did not recreate MakeDirs object correctly")
            bc += mkdirs_obj
            bc += MakeDirs(str(dir_to_make_1), remove_obstacles=False)  # MakeDirs twice should be OK
            bc_repr = repr(bc)
        with capture_stdout(self.the_output):
            ops = exec(f"""{bc_repr}""", globals(), locals())

        self.assertTrue(dir_to_make_1.is_dir())
        self.assertTrue(dir_to_make_2.is_dir())

    def test_MakeDirs_2_remove_obstacles(self):
        dir_to_make = self.test_folder.joinpath("file-that-should-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{dir_to_make} should not exist at the start ot the test")

        touch(str(dir_to_make))
        self.assertTrue(dir_to_make.is_file(), f"{dir_to_make} should be a file at this stage")

        bc_repr = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=True)
            bc_repr = repr(bc)
        with capture_stdout(self.the_output):
            ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(dir_to_make.is_dir(), f"{dir_to_make} should be a dir at this stage")

    def test_MakeDirs_3_no_remove_obstacles(self):
        dir_to_make = self.test_folder.joinpath("file-that-should-not-be-dir").resolve()
        self.assertFalse(dir_to_make.exists(), f"{dir_to_make} should not exist at the start ot the test")

        touch(str(dir_to_make))
        self.assertTrue(dir_to_make.is_file(), f"{dir_to_make} should be a file at this stage")

        bc_repr = None
        with BatchCommandAccum() as bc:
            bc += MakeDirs(str(dir_to_make), remove_obstacles=False)
            bc_repr = repr(bc)
        with capture_stdout(self.the_output):
            with self.assertRaises(FileExistsError, msg="should raise FileExistsError") as context:
                ops = exec(f"""{bc_repr}""", globals(), locals())
        self.assertTrue(dir_to_make.is_file(), f"{dir_to_make} should still be a file")

if __name__ == '__main__':
    unittest.main()
