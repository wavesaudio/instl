#!/usr/bin/env python2.7
from __future__ import print_function

import sys
import os
import unittest
#sys.path.append(os.path.realpath(os.path.join(__file__, "..", "..")))
from test_SVNItem import TestSVNItem
from test_SVNTree import TestSVNTree

if __name__ == '__main__':
    unittest.main(verbosity=0)
