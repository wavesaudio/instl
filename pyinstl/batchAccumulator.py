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
        self.current_section = None

    @func_log_wrapper
    def set_current_section(self, section):
        self.current_section = section

    @func_log_wrapper
    def add(self, instructions):
        if isinstance(instructions, basestring):
            self.instruction_lines[self.current_section].append(" " * 4 * self.indent_level + instructions)
        else:
            for instruction in instructions:
                self.add(instruction)

    def __iadd__(self, instructions):
        self.add(instructions)
        return self

    @func_log_wrapper
    def finalize_list_of_lines(self):
        lines = list()
        for section in self.sections_order:
            resolved_sync_instruction_lines = map(self.cvl.resolve_string, self.instruction_lines[section])
            lines.extend(resolved_sync_instruction_lines)
            lines.extend( ('\n', ) )
        return lines
