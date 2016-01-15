#!/usr/bin/env python3


import logging

from configVar import var_stack


def do_sync(self):
    repo_type = var_stack.resolve("$(REPO_TYPE)")
    if repo_type == "URL":
        from .instlInstanceSync_url import InstlInstanceSync_url

        syncer = InstlInstanceSync_url(self)
    elif repo_type == "BOTO":
        from .instlInstanceSync_boto import InstlInstanceSync_boto

        syncer = InstlInstanceSync_boto(self)
    elif repo_type == "SVN":
        from .instlInstanceSync_svn import InstlInstanceSync_svn

        syncer = InstlInstanceSync_svn(self)
    elif repo_type == "P4":
        from .instlInstanceSync_p4 import InstlInstanceSync_p4

        syncer = InstlInstanceSync_p4(self)
    else:
        raise ValueError('REPO_TYPE is not defined in input file')

    self.read_name_specific_defaults_file(type(syncer).__name__)
    syncer.init_sync_vars()
    syncer.create_sync_instructions(self.installState)
    self.batch_accum += self.platform_helper.progress("Done sync")
