import sys
import os
import io
from pathlib import Path
import re
import logging
import time
import datetime

from .baseClasses import PythonBatchCommandBase
from .reportingBatchCommands import Stage, PythonBatchRuntime, PatchPyBatchWithTimings
from .subprocessBatchCommands import ShellCommand

from pybatch import *

from configVar import config_vars
import utils


first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')


def camel_to_snake_case(identifier):
    identifier1 = first_cap_re.sub(r'\1_\2', identifier)
    identifier2 = all_cap_re.sub(r'\1_\2', identifier1).lower()
    return identifier2


class PythonBatchCommandAccum(PythonBatchCommandBase):

    section_order = ("prepare", "assign", "begin", "links", "upload", "pre", "pre-sync", "sync", "post-sync",
                     "copy", "post-copy", "remove", "admin", "pre_doit", "doit", "post_doit", "end",
                     "post", "epilog")
    special_sections = ("assign", "epilog")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_section: str = None
        self.sections = dict()
        self.creation_time = time.strftime('%d-%m-%y_%H-%M')
        self.initial_progress = 0

    def clear(self, section_name=None):
        self.sections = dict()
        if section_name is None:
            self.set_current_section(self.current_section)
        else:
            self.set_current_section(section_name)
        PythonBatchCommandBase.running_progress = 0

    def set_current_section(self, section_name):
        if section_name is None:
            self.current_section: str = None
        elif section_name in PythonBatchCommandAccum.section_order:
            self.current_section = section_name
            if self.current_section not in self.sections:
                self.sections[self.current_section] = Stage(self.current_section)
        else:
            raise ValueError(f"{section_name} is not a known section_name name")

    def total_progress_count(self):
        """ count recursively the number of batch commands - not including the top sections """
        counter = 0
        for a_section in self.sections.values():
            counter += a_section.total_progress_count()
        return counter

    def finalize_list_of_lines(self):
        lines = list()
        for section in PythonBatchCommandAccum.section_order:
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
        instl_folder = Path(__file__).joinpath(os.pardir, os.pardir).resolve()
        opening_code_lines = list()
        opening_code_lines.append(f"""# Creation time: {self.creation_time}""")
        opening_code_lines.append(f"""import os""")
        opening_code_lines.append(f"""import sys""")
        opening_code_lines.append(f"""sys.path.append({utils.quoteme_raw_by_type(instl_folder)})""")
        opening_code_lines.append(f"""import logging""")
        opening_code_lines.append(f"""log = logging.getLogger(__name__)""")
        opening_code_lines.append(f"""import utils""")
        opening_code_lines.append(f"""from configVar import config_vars""")
        opening_code_lines.append(f"""utils.set_acting_ids(config_vars.get("ACTING_UID", -1).int(), config_vars.get("ACTING_GID", -1).int())""")
        opening_code_lines.append(f"""from pybatch import *""")
        opening_code_lines.append(f"""PythonBatchCommandBase.total_progress = {PythonBatchCommandBase.total_progress+self.initial_progress}""")
        opening_code_lines.append(f"""PythonBatchCommandBase.running_progress = {PythonBatchCommandBase.running_progress+self.initial_progress}""")
        opening_code_lines.append(f"""if __name__ == '__main__':""")
        opening_code_lines.append(f"""    from utils import log_utils""")
        opening_code_lines.append(f"""    log_utils.config_logger()""")

        the_oc = "\n".join(opening_code_lines)
        the_oc += "\n\n"

        return the_oc

    def _python_closing_code(self):
        cc = f"""\nlog.info("Shakespeare says: All's Well That Ends Well")\n# eof\n\n"""
        return cc

    def __repr__(self):
        single_indent = "    "
        running_progress_count = self.initial_progress
        PythonBatchCommandBase.config_vars_for_repr = config_vars  # so __repr__ of object derived from PythonBatchCommandBase will resolve config_vars values

        def _create_unique_obj_name(obj, prog_count):
            try:
                _create_unique_obj_name.instance_counter += 1
            except AttributeError:
                _create_unique_obj_name.instance_counter = 1
            obj_name = camel_to_snake_case(f"{obj.__class__.__name__}_{_create_unique_obj_name.instance_counter:03}_{prog_count}")
            return obj_name

        def _remark_helper(*the_remarks):
            retVal = ", ".join(str(remark) for remark in filter(None, the_remarks))
            if retVal:
                retVal = f"""  # {retVal}"""
            return retVal

        def _repr_helper(batch_items, io_str, indent):
            nonlocal running_progress_count
            indent_str = single_indent*indent
            if isinstance(batch_items, list):
                for item in batch_items:
                    _repr_helper(item, io_str, indent)
            else:
                running_progress_count += batch_items.own_progress_count
                batch_items.prog_num = running_progress_count
                if batch_items.call__call__ is False and batch_items.is_context_manager is False:
                    text_to_write = f"""{indent_str}{repr(batch_items)}\n"""
                    io_str.write(text_to_write)
                    _repr_helper(batch_items.child_batch_commands, io_str, indent)
                elif batch_items.call__call__ is False and batch_items.is_context_manager is True:
                    text_to_write = f"""{indent_str}with {repr(batch_items)}:\n"""
                    io_str.write(text_to_write)
                    if batch_items.child_batch_commands:
                        _repr_helper(batch_items.child_batch_commands, io_str, indent+1)
                    else:
                        text_to_write = f"""{indent_str}{single_indent}pass\n"""
                        io_str.write(text_to_write)
                elif batch_items.call__call__ is True and batch_items.is_context_manager is False:
                    text_to_write = f"""{indent_str}{repr(batch_items)}()\n"""
                    io_str.write(text_to_write)
                    _repr_helper(batch_items.child_batch_commands, io_str, indent)
                elif batch_items.call__call__ is True and batch_items.is_context_manager is True:
                    obj_name = _create_unique_obj_name(batch_items, running_progress_count)
                    text_to_write = f"""{indent_str}with {repr(batch_items)} as {obj_name}:\n"""
                    io_str.write(text_to_write)

                    text_to_write = f"""{indent_str}{single_indent}{obj_name}("""
                    text_to_write += ")\n"
                    io_str.write(text_to_write)
                    _repr_helper(batch_items.child_batch_commands, io_str, indent+1)

        self.set_current_section('epilog')
        self += PatchPyBatchWithTimings(config_vars['__MAIN_OUT_FILE__'])

        PythonBatchCommandBase.total_progress = 0
        for name, section in self.sections.items():
            progress_count_for_section = section.total_progress_count()
            PythonBatchCommandBase.total_progress += progress_count_for_section
        PythonBatchCommandBase.total_progress += 1  # count the PythonBatchRuntime, todo: a better way to add PythonBatchRuntime's progress count to the total

        prolog_str = io.StringIO()
        prolog_str.write(self._python_opening_code())
        if 'assign' in self.sections:
            _repr_helper(self.sections['assign'], prolog_str, 0)

        main_str = io.StringIO()
        the_command = config_vars.get("__MAIN_COMMAND__", "woolly mammoth")
        runtimer = PythonBatchRuntime(the_command)
        for section_name in PythonBatchCommandAccum.section_order:
            if section_name in self.sections:
                if section_name not in PythonBatchCommandAccum.special_sections:
                    runtimer += self.sections[section_name]
        main_str.write("\n")
        _repr_helper(runtimer, main_str, 0)

        epilog_str = io.StringIO()
        if 'epilog' in self.sections:
            main_str.write("\n")
            _repr_helper(self.sections['epilog'], epilog_str, 0)

        epilog_str.write(self._python_closing_code())

        main_str_resolved = config_vars.resolve_str(main_str.getvalue())
        main_str_resolved = config_vars.replace_unresolved_with_native_var_pattern(main_str_resolved, list(config_vars["__CURRENT_OS_NAMES__"])[0])

        the_whole_repr = prolog_str.getvalue()+main_str_resolved+epilog_str.getvalue()

        PythonBatchCommandBase.config_vars_for_repr = None

        return the_whole_repr

    def progress_msg_self(self):
        """ """
        return ""

    def __call__(self, *args, **kwargs):
        pass
