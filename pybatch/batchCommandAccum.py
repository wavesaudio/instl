import sys
import os
import io
import pathlib
from contextlib import contextmanager
import logging
import time
from collections import defaultdict

from .baseClasses import PythonBatchCommandBase
from .reportingBatchCommands import Section
python_batch_log_level = logging.WARNING


def batch_repr(batch_obj):
    assert isinstance(batch_obj, (PythonBatchCommandBase, PythonBatchCommandAccum))
    if sys.platform == "darwin":
        return batch_obj.repr_batch_mac()

    elif sys.platform == "win32":
        return batch_obj.repr_batch_win()


class PythonBatchCommandAccum(PythonBatchCommandBase, essential=True):

    section_order = ("pre", "assign", "begin", "links", "upload", "sync", "post-sync", "copy", "post-copy", "remove", "admin", "end", "post")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_section: str = None
        self.sections = dict()
        #self.context_stack = [list()]
        self.creation_time = time.strftime('%d-%m-%y_%H-%M')

    def clear(self):
        self.sections = dict()
        if self.current_section:
            self.set_current_section(self.current_section)

    def set_current_section(self, section_name):
        if section_name in PythonBatchCommandAccum.section_order:
            self.current_section = section_name
            if self.current_section not in self.sections:
                self.sections[self.current_section] = Section(self.current_section)
        else:
            raise ValueError(f"{section_name} is not a known section_name name")

    def num_batch_commands(self):
        """ count recursively the number of batch commands - not including the top sections """
        counter = 0
        for a_section in self.sections.values():
            counter += a_section.num_sub_batch_commands()
        return counter

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

    def add(self, child_commands):
        assert not self.in_sub_accum, "PythonBatchCommandAccum.add: should not be called while sub_accum is in context"
        self.sections[self.current_section].add(child_commands)

    def _python_opening_code(self):
        instl_folder = pathlib.Path(__file__).joinpath(os.pardir, os.pardir).resolve()
        opening_code_lines = list()
        opening_code_lines.append(f"""# Creation time: {self.creation_time}""")
        opening_code_lines.append(f"""import sys""")
        opening_code_lines.append(f"""sys.path.append(r'{instl_folder}')""")
        opening_code_lines.append(f"""from pybatch import *""")
        PythonBatchCommandBase.total_progress = 0
        for section in self.sections.values():
            PythonBatchCommandBase.total_progress += section.num_progress_items()
        opening_code_lines.append(f"""PythonBatchCommandBase.total_progress = {PythonBatchCommandBase.total_progress}""")
        opening_code_lines.append(f"""PythonBatchCommandBase.running_progress = {PythonBatchCommandBase.running_progress}""")

        the_oc = "\n".join(opening_code_lines)
        the_oc += "\n"

        return the_oc

    def _python_closing_code(self):
        oc = f"# eof\n\n"
        return oc

    def __repr__(self):
        def _repr_helper(batch_items, io_str, indent):
            indent_str = "    "*indent
            if isinstance(batch_items, list):
                for item in batch_items:
                    _repr_helper(item, io_str, indent)
            elif batch_items.is_context_manager:
                if batch_items.child_batch_commands:
                    if batch_items.empty__call__:
                        io_str.write(f"""{indent_str}with {repr(batch_items)}:\n""")
                    else:
                        io_str.write(f"""{indent_str}with {repr(batch_items)} as {batch_items.obj_name}:\n""")
                        io_str.write(f"""{indent_str}    {batch_items.obj_name}()\n""")
                    _repr_helper(batch_items.child_batch_commands, io_str, indent+1)
                else:
                    if batch_items.empty__call__:
                        io_str.write(f"""{indent_str}{repr(batch_items)}\n""")
                    else:
                        io_str.write(f"""{indent_str}{repr(batch_items)}()\n""")
            else:
                io_str.write(f"""{indent_str}{repr(batch_items)}\n""")

        io_str = io.StringIO()
        io_str.write(self._python_opening_code())
        for section_name in PythonBatchCommandAccum.section_order:
            if section_name in self.sections:
                if section_name == "assign":
                    _repr_helper(self.sections[section_name].sub_commands(), io_str, 0)
                else:
                    _repr_helper(self.sections[section_name], io_str, 0)
                io_str.write("\n")
        io_str.write(self._python_closing_code())
        return io_str.getvalue()

    def repr_batch_win(self):
        def _repr_helper(batch_items, io_str):
            if isinstance(batch_items, list):
                for item in batch_items:
                    _repr_helper(item, io_str)
                    _repr_helper(item.child_batch_commands, io_str)
            else:
                io_str.write(batch_repr(batch_items))
        PythonBatchCommandBase.total_progress = 0
        io_str = io.StringIO()
        #io_str.write(self._python_opening_code())
        #_repr_helper(self.context_stack[0], io_str)
        #io_str.write(self._python_closing_code())
        return io_str.getvalue()

    def repr_batch_mac(self):
        return ""

    def progress_msg_self(self):
        """ """
        return ""

    def __call__(self, *args, **kwargs):
        pass
