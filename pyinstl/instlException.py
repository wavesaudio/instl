#!/usr/local/bin/python2.7

from __future__ import print_function

class InstlException(Exception):
    def __init__(self, in_message, in_original_exception):
        super(InstlException, self).__init__(in_message)
        self.original_exception = in_original_exception
