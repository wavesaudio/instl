#!/usr/bin/env python2.7
from __future__ import print_function

import os
import sys

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))

import unittest
from test.test_configVar import TestConfigVar
from test.test_configVarList import TestConfigVarList
from test.test_SVNItem import TestSVNItem
from test.test_SVNTree import TestSVNTree
from test.test_InstallItem import TestInstallItem
from test.test_utils import TestUtils
from test.test_platformSpecificHelper import TestPlatformSpecificHelper

if __name__ == '__main__':
    unittest.main(verbosity=3)
