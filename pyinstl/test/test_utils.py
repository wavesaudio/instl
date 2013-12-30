#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import os
import unittest

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
import utils

class TestUtils(unittest.TestCase):

    def setUp(self):
       pass
    def tearDown(self):
        pass

    def test_construction_with_name_only(self):
        #utils.download_from_file_or_url("http://lachouffe/links/V9_test/abc.html", "test_construction_with_name_only.txt")
        pass

    def test_ContinuationIter(self):
        the_source_list = [1, 2, 3]
        the_target_list = []
        num_iterations = 6
        for i in utils.ContinuationIter(the_source_list, 0):
            the_target_list.append(i)
            num_iterations -= 1
            if not num_iterations:
                break
        self.assertEquals(the_target_list, [1, 2, 3, 0, 0, 0])

    def test_ParallelContinuationIter(self):
        list_1 = [1, 2, 3, 4, 5]
        list_a = ["a", "b", "c"]
        list_None = []
        result_list = []
        for i in utils.ParallelContinuationIter(list_1, list_a, list_None):
            result_list.extend(i)
        self.assertEquals(result_list, [1, 'a', None, 2, 'b', None, 3, 'c', None, 4, None, None, 5, None, None])

    """
    def test_gen_col_format(self):
        varoom = utils.gen_col_format([5, 3, 12])
        strings = ("yoyo", "bb", "abracadabra")
        for i in len(strings):
            print(varoom[i].format(strings))
    """