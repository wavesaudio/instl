#!/usr/bin/env python3


import os
import sys

sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))

import unittest
#from test.test_configVar import TestConfigVar
#from test.test_configVarList import TestConfigVarList
#from svnTree.test import TestSVNItem
#from svnTree.test import TestSVNTree
#from test.test_InstallItem import TestInstallItem
#from test.test_utils import TestUtils
#from test.test_platformSpecificHelper import TestPlatformSpecificHelper

from test.test_itemTable import TestItemTable

if __name__ == '__main__':
    unittest.main(verbosity=3)
