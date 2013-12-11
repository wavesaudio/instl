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
        utils.download_from_file_or_url("https://s3.amazonaws.com/waves_instl/v9/test1/V9/Win/Plugins/API-560.bundle/Contents/Resources/XSig/1", "test_construction_with_name_only.txt")