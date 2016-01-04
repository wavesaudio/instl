#!/usr/bin/env python
from __future__ import print_function

class InstlException(Exception):
    def __init__(self, in_message, in_original_exception=None):
        super(InstlException, self).__init__(in_message)
        self.original_exception = in_original_exception


def InstlFatalException(Exception):
    def __init__(self, *messages):
        super(InstlFatalException, self).__init__()
        self.message = " ".join([str(mess) for mess in messages])
    def __str__(self):
        return self.message
