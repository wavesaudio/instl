#!/usr/bin/env python2.7
from __future__ import print_function

from __future__ import print_function

import sys
import os
import unittest
import filecmp

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..", "..")))
from aYaml.augmentedYaml import YamlDumpWrap, writeAsYaml
from svnTree import *

def timing(f):
    def wrap(*args):
        time1 = time.time()
        ret = f(*args)
        time2 = time.time()
        print ('%s function took %0.3f ms' % (f.func_name, (time2-time1)*1000.0))
        return ret
    return wrap

class TestSVNTree(unittest.TestCase):

    def setUp(self):
        """ .
        """
        pass
    def tearDown(self):
        pass
    
    def test_pickling(self):
        this_dir, this_script = os.path.split(__file__)
        SVNInfoTestFile1 = os.path.join(this_dir, "SVNInfoTest1.txt")

        tree = SVNTree()
        tree.read_svn_info_file(SVNInfoTestFile1)
        beforePickleFile = os.path.join(this_dir, "beforePickleFile.txt")
        tree.save_as_text(beforePickleFile)
        
        pickleOut = os.path.join(this_dir, "out.pickle")
        tree.pickle(pickleOut)

        tree2 = SVNTree()
        tree2.unpickle(pickleOut)
        afterPickleFile = os.path.join(this_dir, "afterPickleFile.txt")
        tree2.save_as_text(afterPickleFile)
        
        self.assertTrue(filecmp.cmp(beforePickleFile, afterPickleFile), "{afterPickleFile} file is different from expected {beforePickleFile}".format(**locals()))
        
    def test_read_svn_info_file(self):
        this_dir, this_script = os.path.split(__file__)
        SVNInfoTestFile1 = os.path.join(this_dir, "SVNInfoTest1.txt")

        tree = SVNTree()
        tree.read_svn_info_file(SVNInfoTestFile1)

        SVNInfoTestFile1Out = os.path.join(this_dir, "SVNInfoTest1.out.txt")
        tree.save_as_text(SVNInfoTestFile1Out)

        SVNInfoTestFileRef1 = os.path.join(this_dir, "SVNInfoTest1.ref.txt")
        self.assertTrue(filecmp.cmp(SVNInfoTestFileRef1, SVNInfoTestFile1Out), "{SVNInfoTestFile1Out} file is different from expected {SVNInfoTestFileRef1}".format(**locals()))
