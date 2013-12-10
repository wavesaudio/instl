#!/usr/bin/env python2.7
from __future__ import print_function

from collections import OrderedDict, defaultdict

import pyinstl.log_utils
from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *

class BatchAccumulator(object):
    """ accumulate batch instructions and prepare them for writing to file
    """
    @func_log_wrapper
    def __init__(self, in_cvl_obj):
        self.cvl = in_cvl_obj
        self.variables_assignment_lines = list()
        self.instruction_lines = defaultdict(list)
        self.indent_level = 0
        self.sections_order = ("pre", "assign", "sync", "copy", "admin", "post")

    @func_log_wrapper
    def extend_instructions(self, which, instruction_list):
        #print("extend_instructions indent", self.indent_level)
        self.instruction_lines[which].extend( map(lambda line: " " * 4 * self.indent_level + line, instruction_list))

    @func_log_wrapper
    def append_instructions(self, which, single_instruction):
        #print("append_instructions indent", self.indent_level)
        self.instruction_lines[which].append(" " * 4 * self.indent_level + single_instruction)

    @func_log_wrapper
    def finalize_list_of_lines(self):
        lines = list()
        for section in self.sections_order:
            resolved_sync_instruction_lines = map(self.cvl.resolve_string, self.instruction_lines[section])
            lines.extend(resolved_sync_instruction_lines)
            lines.extend( ('\n', ) )
        return lines
