#!/usr/bin/env python2.7
from __future__ import print_function

import logging

from pyinstl.utils import *
from pyinstl import svnTree
from instlInstanceSyncBase import InstlInstanceSync
from batchAccumulator import BatchAccumulator
from configVarStack import var_stack



class InstlInstanceSync_boto(InstlInstanceSync):
    """  Class to create sync instruction using static links.
    """

    def __init__(self, instlObj):
        super(InstlInstanceSync_boto, self).__init__(instlObj)

    def init_sync_vars(self):
        super(InstlInstanceSync_boto, self).init_sync_vars()
        self.local_sync_dir = var_stack.resolve("$(LOCAL_REPO_SYNC_DIR)")