#!/usr/bin/env python3


from collections import defaultdict

from configVar import var_stack


class BatchAccumulator(object):
    """ from batchAccumulator import BatchAccumulator
        accumulate batch instructions and prepare them for writing to file
    """
    section_order = ("pre", "assign", "begin", "links", "upload", "sync", "post-sync", "copy", "post-copy", "remove", "admin", "end", "post")

    def __init__(self):
        self.instruction_lines = defaultdict(list)
        self.indent_level = 0
        self.current_section = None

    def set_current_section(self, section):
        if section in BatchAccumulator.section_order:
            self.current_section = section
        else:
            raise ValueError(section + " is not a known section name")

    def add(self, instructions):
        if isinstance(instructions, str):
            self.instruction_lines[self.current_section].append(" " * 4 * self.indent_level + instructions)
        else:
            for instruction in instructions:
                self.add(instruction)

    def __iadd__(self, instructions):
        self.add(instructions)
        return self

    def __len__(self):
        for section, section_lines in self.instruction_lines.items():
            retVal += len(section_lines)
        return retVal

    def finalize_list_of_lines(self):
        lines = list()
        for section in BatchAccumulator.section_order:
            section_lines = self.instruction_lines[section]
            if section_lines:
                if section == "assign":
                    section_lines.sort()
                resolved_sync_instruction_lines = list(map(var_stack.resolve, section_lines))
                lines.extend(resolved_sync_instruction_lines)
                lines.append("")  # empty string will cause to emit new line
        return lines

    def merge_with(self, another_accum):
        save_section = self.current_section
        for section in BatchAccumulator.section_order:
            self.set_current_section(section)
            # noinspection PyMethodFirstArgAssignment
            self += another_accum.instruction_lines[section]
        self.current_section = save_section
