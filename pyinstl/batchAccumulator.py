#!/usr/bin/env python3


from collections import defaultdict

from configVar import config_vars
from pybatch import PythonBatchCommandBase
from pybatch import PythonBatchCommandAccum


class BatchAccumulator(object):
    """ from batchAccumulator import BatchAccumulator
        accumulate batch instructions and prepare them for writing to file
    """
    section_order = ("pre", "assign", "begin", "links", "upload", "sync", "post-sync", "copy", "post-copy", "remove", "admin", "end", "post")

    def __init__(self) -> None:
        self.instruction_lines = defaultdict(list)
        self.current_section: str = None
        self.transaction_stack = list()

    def instruction_counters(self):
        retVal = {section_name: len(section_lines) for section_name, section_lines in self.instruction_lines.items()}
        return retVal

    def set_current_section(self, section):
        if section in BatchAccumulator.section_order:
            self.current_section = section
        else:
            raise ValueError(f"{section} is not a known section name")

    def __iadd__(self, instructions):
        self.add(instructions)
        return self

    def add(self, instructions):
        if isinstance(instructions, str):
            assert instructions != '~', "~ in instructions previous instruction: "+self.instruction_lines[self.current_section][-1]
            self.__add_single_line__(instructions)
        else:
            for instruction in instructions:
                self.add(instruction)

    def __add_single_line__(self, single_line):
        """ make sure only strings are added """
        if isinstance(single_line, str):
            self.instruction_lines[self.current_section].append(single_line)
        else:
            raise TypeError(f"Not a string {type(single_line)} {single_line}")

    def __len__(self):
        retVal = 0
        for section, section_lines in self.instruction_lines.items():
            retVal += len(section_lines)
        return retVal

    def finalize_list_of_lines(self):
        lines = list()
        for section in BatchAccumulator.section_order:
            # config_vars["CURRENT_PHASE"] = section
            section_lines = self.instruction_lines[section]
            if section_lines:
                if section == "assign":
                    section_lines.sort()
                for section_line in section_lines:
                    resolved_line = config_vars.resolve_str_to_list(section_line)
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

    def begin_transaction(self):
        self.transaction_stack.append(self.instruction_counters())

    def commit_transaction(self):
        self.transaction_stack.pop()

    def cancel_transaction(self):
        prev_counters = self.transaction_stack.pop()
        # remove the instructions_ added since the beginning of the transaction
        for section_name, section_counter in prev_counters.items():
            if section_name in self.instruction_lines:
                del self.instruction_lines[section_name][prev_counters[section_name]:]

    def commit_transaction_if(self, condition):
        if condition:
            self.commit_transaction()
        else:
            self.cancel_transaction()


class BatchAccumulatorTransaction(object):
    def __init__(self, batchAccum, transaction_name="") -> None:
        self.transaction_name = transaction_name
        self.batchAccum = batchAccum
        self.essential_action_counter = 0

    def __enter__(self):
        self.batchAccum.begin_transaction()
        return self

    def __exit__(self, *_):
        self.batchAccum.commit_transaction_if(self.essential_action_counter)

    def __iadd__(self, inc):
        self.essential_action_counter += inc
        return self


def BatchAccumulatorFactory(use_python_batch: bool) -> BatchAccumulator:
    if use_python_batch:
        return PythonBatchCommandAccum()
    else:
        return BatchAccumulator()
