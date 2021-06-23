#!/usr/bin/env python3.9


import os
import sys
import unittest
import filecmp

sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir)))
sys.path.append(os.path.realpath(os.path.join(__file__, os.pardir, os.pardir, os.pardir)))
from svnTree import *


def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print('%s function took %0.3f ms' % (f.__name__, (time2 - time1) * 1000.0))
        return ret

    return wrap


class TestSVNTree(unittest.TestCase):
    def setUp(self):
        """ .
        """
        pass

    def tearDown(self):
        pass

    def test_read_svn_info_file(self):
        this_dir, this_script = os.path.split(__file__)
        SVNInfoTestFile1 = os.path.join(this_dir, "SVNInfoTest1.info")
        tree = SVNTree()
        tree.info_map_table.read_from_file(SVNInfoTestFile1, a_format="info")

        SVNInfoTestFile1Out = os.path.join(this_dir, "SVNInfoTest1.out.txt")
        tree.write_to_file(SVNInfoTestFile1Out, in_format="text", comments=False)

        SVNInfoTestFileRef1 = os.path.join(this_dir, "SVNInfoTest1.ref.txt")
        self.assertTrue(filecmp.cmp(SVNInfoTestFileRef1, SVNInfoTestFile1Out, shallow=False),
                        f"{SVNInfoTestFile1Out} file is different from expected {SVNInfoTestFileRef1}")
