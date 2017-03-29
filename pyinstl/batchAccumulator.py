#!/usr/bin/env python3


from collections import defaultdict

from configVar import var_stack


class BatchAccumulator(object):
    """ from batchAccumulator import BatchAccumulator
        accumulate batch instructions and prepare them for writing to file
    """
    section_order = ("pre", "assign", "begin", "links", "upload", "sync", "post-sync", "copy", "post-copy", "remove", "admin", "end", "post")

    def __init__(self):
        self.__instruction_lines = defaultdict(list)
        self.current_section = None
        self.__instruction_counter = 0
        self.__transaction_stack = list()

    def set_current_section(self, section):
        if section in BatchAccumulator.section_order:
            self.current_section = section
        else:
            raise ValueError(section + " is not a known section name")

    def add(self, instructions):
        if isinstance(instructions, str):
            self.__add_single_line__(instructions)
        else:
            for instruction in instructions:
                self.add(instruction)

    def __iadd__(self, instructions):
        self.add(instructions)
        return self

    def __add_single_line__(self, single_line):
        """ make sure only strings are added """
        if isinstance(single_line, str):
            self.__instruction_lines[self.current_section].append(single_line)
            self.__instruction_counter += 1
        else:
            raise TypeError("Not a string", type(single_line), single_line)

    def __len__(self):
        retVal = 0
        for section, section_lines in self.__instruction_lines.items():
            retVal += len(section_lines)
        return retVal

    def finalize_list_of_lines(self):
        lines = list()
        for section in BatchAccumulator.section_order:
            section_lines = self.__instruction_lines[section]
            if section_lines:
                if section == "assign":
                    section_lines.sort()
                for section_line in section_lines:
                    resolved_line = var_stack.ResolveStrToListIfSingleVar(section_line)
                    lines.extend(resolved_line)
                lines.append("")  # empty string will cause to emit new line
        return lines

    def merge_with(self, another_accum):
        save_section = self.current_section
        for section in BatchAccumulator.section_order:
            self.set_current_section(section)
            # noinspection PyMethodFirstArgAssignment
            self += another_accum.instruction_lines[section]
        self.current_section = save_section

    @property
    def instruction_counter(self):
        return self.__instruction_counter
    
    def begin_transaction(self):
        self.__transaction_stack.append(self.__instruction_counter)
        return self.__instruction_counter

    def end_transaction(self):
        prev_counter = self.__transaction_stack.pop()
        num_instructions_in_transaction = self.__instruction_counter - prev_counter
        return num_instructions_in_transaction

    def cancel_transaction(self):
        num_instructions_in_transaction = self.end_transaction()
        # remove the instructions_ added since the beginning of the transaction
        del self.__instruction_lines[self.current_section][-num_instructions_in_transaction:]
