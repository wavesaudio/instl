#!/usr/bin/env python2.7

from __future__ import print_function
import stat
import time
from collections import OrderedDict, defaultdict
import logging

from pyinstl.utils import *
from installItem import InstallItem, guid_list, iids_from_guid
from aYaml import augmentedYaml

from instlInstanceBase import InstlInstanceBase
from configVarStack import var_stack
import svnTree

def do_sync(self):
    logging.info("Creating sync instructions")
    if var_stack.resolve("$(REPO_TYPE)") == "BOTO":
        from instlInstanceSync_boto import InstlInstanceSync_boto
        syncer = InstlInstanceSync_boto(self)
    elif var_stack.resolve("$(REPO_TYPE)") == "URL":
        from instlInstanceSync_url import InstlInstanceSync_url
        syncer = InstlInstanceSync_url(self)
    elif var_stack.resolve("$(REPO_TYPE)") == "SVN":
        from instlInstanceSync_svn import InstlInstanceSync_svn
        syncer = InstlInstanceSync_svn(self)
    elif var_stack.resolve("$(REPO_TYPE)") == "P4":
        from instlInstanceSync_p4 import InstlInstanceSync_p4
        syncer = InstlInstanceSync_p4(self)
    else:
        raise ValueError('REPO_TYPE is not defined in input file')

    self.read_name_specific_defaults_file(type(syncer).__name__)
    syncer.init_sync_vars()
    syncer.create_sync_instructions(self.installState)
    self.batch_accum += self.platform_helper.progress("Done sync")
