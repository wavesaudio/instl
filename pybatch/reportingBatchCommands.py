import os
from pathlib import Path
import keyword
import json
import re
from typing import List
import logging

from configVar import config_vars
from configVar import ConfigVarYamlReader
import utils

import pybatch

log = logging.getLogger(__name__)

need_path_resolving_re = re.compile(".+(DIR|PATH|FOLDER|FOLDERS)(__)?$")


class AnonymousAccum(pybatch.PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False, is_anonymous=True):

    """ AnonymousAccum: a container for other PythonBatchCommands,
        AnonymousAccum is not meant to be written to python-batch file or executed - only the
        contained commands will be.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.i_am_anonymous=True

    def repr_own_args(self, all_args: List[str]) -> None:
        raise NotImplementedError("AnonymousAccum.repr_own_args should not be called")

    def progress_msg_self(self) -> str:
        raise NotImplementedError("AnonymousAccum.progress_msg_self should not be called")

    def __call__(self, *args, **kwargs) -> None:
        raise NotImplementedError("AnonymousAccum.__call__ should not be called")


class RaiseException(pybatch.PythonBatchCommandBase):
    """ raise a specific exception - for debugging """
    def __init__(self, exception_type, exception_message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.exception_type = exception_type
        self.exception_type_name = self.exception_type.__name__
        self.exception_message = exception_message
        self.non_representative__dict__keys.append('exception_type')

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.exception_type_name)
        all_args.append(self.unnamed__init__param(self.exception_message))

    def progress_msg_self(self) -> str:
        return f'''Raising exception {self.exception_type.__name__}("{self.exception_message}")'''

    def __call__(self, *args, **kwargs) -> None:
        raise self.exception_type(self.exception_message)


class Stage(pybatch.PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=True):
    """ Stage: a container for other PythonBatchCommands, that has a name and is used as a context manager ("with").
        Stage itself preforms no action only the contained commands will be preformed
    """
    def __init__(self, stage_name, stage_extra=None, **kwargs):
        super().__init__(**kwargs)
        self.stage_name = stage_name
        self.stage_extra = stage_extra

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.stage_name))
        if self.stage_extra:
            all_args.append(self.unnamed__init__param(self.stage_extra))

    def stage_str(self):
        the_str = f"""{self.stage_name}"""
        if self.stage_extra:
            the_str += f"""<{self.stage_extra}>"""
        return the_str

    def progress_msg_self(self):
        the_progress_msg = f'''{self.stage_name}'''
        if self.stage_extra:
            the_progress_msg += f""" {self.stage_extra}"""
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        super().__exit__(exc_type, exc_val, exc_tb)
        if self.stage_name in pybatch.PythonBatchCommandAccum.section_order:
            config_var_name = f"__TIMING_{self.stage_name}_sec__".upper()
            config_vars[config_var_name] = self.command_time_sec


class Progress(pybatch.PythonBatchCommandBase, essential=False, call__call__=True, is_context_manager=False):
    """ issue a progress message, increasing progress count
    """
    def __init__(self, message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.message))

    def progress_msg_self(self) -> str:
        return self.message

    def __call__(self, *args, **kwargs) -> None:
        with self.timing_contextmanager():
            self.increment_and_output_progress()


class Echo(pybatch.PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False, kwargs_defaults={'own_progress_count': 0}):
    """ issue a message without increasing progress count
        !! message is printed in the prepare stage NOT when running the created python !!
    """
    def __init__(self, message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def __repr__(self) -> str:
        the_repr = f'''print("{self.message}")'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class Print(pybatch.PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False, kwargs_defaults={'own_progress_count': 0}):
    """ issue a message without increasing progress count
        !! message is printed when running the created python NOT in the prepare stage !!
    """
    def __init__(self, message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.message))

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        print(self.message)


class Remark(pybatch.PythonBatchCommandBase, call__call__=False, is_context_manager=False, kwargs_defaults={'own_progress_count': 0}):
    """ write a remark in code
    """
    def __init__(self, remark, **kwargs) -> None:
        super().__init__(**kwargs)
        self.remark_text = remark

    def __repr__(self) -> str:
        the_repr = f'''# {self.remark_text}'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class PythonDoSomething(pybatch.PythonBatchCommandBase, call__call__=False, is_context_manager=False, kwargs_defaults={'own_progress_count': 0}):

    def __init__(self, some_python_code, **kwargs) -> None:
        super().__init__(**kwargs)
        self.some_python_code = some_python_code

    def __repr__(self) -> str:
        the_repr = self.some_python_code
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        with self.timing_contextmanager():
            pybatch.PythonBatchCommandBase.__call__(self, *args, **kwargs)


class PythonVarAssign(pybatch.PythonBatchCommandBase, call__call__=False, is_context_manager=False, kwargs_defaults={'own_progress_count': 0}):
    """ creates a python variable assignment, e.g.
        x = y
    """
    def __init__(self, var_name, *var_values, **kwargs) -> None:
        super().__init__(**kwargs)
        assert var_name.isidentifier(), f"{var_name} is not a valid identifier"
        assert not keyword.iskeyword(var_name), f"{var_name} is not a python key word"
        self.var_name = var_name
        self.var_values = var_values

    def __repr__(self) -> str:
        the_repr = ""
        if any(self.var_values):
            need_path_resolving = need_path_resolving_re.match(self.var_name) is not None
            adjusted_values = list()
            for val in self.var_values:
                try:
                    adjusted_values.append(int(val))
                except:
                    if need_path_resolving:
                        val = os.fspath(Path(os.path.expandvars(val)).resolve())
                    adjusted_values.append(utils.quoteme_raw_by_type(val))
            if len(adjusted_values) == 1:
                the_repr = f'''{self.var_name} = {adjusted_values[0]}'''
            else:
                values = "".join(('(', ", ".join(str(adj) for adj in adjusted_values), ')'))
                the_repr = f'''{self.var_name} = {values}'''
        else:
            the_repr = f'''{self.var_name} = ""'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class ConfigVarAssign(pybatch.PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False, kwargs_defaults={'own_progress_count': 0}):
    """ creates a configVar assignment, e.g.
        config_vars["x"] = y
    """
    def __init__(self, var_name, *var_values, **kwargs) -> None:
        super().__init__(**kwargs)
        assert var_name.isidentifier(), f"{var_name} is not a valid identifier"
        assert not keyword.iskeyword(var_name), f"{var_name} is not a python key word"
        self.var_name = var_name
        self.var_values = var_values

    def __repr__(self) -> str:
        the_repr = ""
        if any(self.var_values):
            adjusted_values = list()
            for val in self.var_values:
                try:
                    adjusted_values.append(int(val))
                except:
                    adjusted_values.append(utils.quoteme_raw_by_type(val))
            if len(adjusted_values) == 1:
                the_repr = f'''config_vars['{self.var_name}'] = {adjusted_values[0]}'''
            else:
                values = "".join(('(', ", ".join(str(adj) for adj in adjusted_values), ')'))
                the_repr = f'''config_vars['{self.var_name}'] = {values}'''
        else:
            the_repr = f'''config_vars['{self.var_name}'] = ""'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class ConfigVarPrint(pybatch.PythonBatchCommandBase, call__call__=True, is_context_manager=False):
    """
    """
    def __init__(self, var_name, **kwargs) -> None:
        super().__init__(**kwargs)
        self.var_name = var_name

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.var_name))

    def progress_msg_self(self) -> str:
        resolved = config_vars[self.var_name].str()
        return resolved

    def __call__(self, *args, **kwargs) -> None:
        with self.timing_contextmanager():
            resolved = config_vars[self.var_name].str()
            log.info(resolved)


class PythonBatchRuntime(pybatch.PythonBatchCommandBase, call__call__=False, is_context_manager=True):
    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.name = name

    def __exit__(self, exc_type, exc_val, exc_tb):
        suppress_exception = False
        if exc_val:
            self.log_error(exc_type, exc_val, exc_tb)
            log.info("Shakespeare says: The Comedy of Errors")

        self.exit_timing_measure()
        time_diff = self.exit_time-self.enter_time
        hours, remainder = divmod(time_diff, 3600)
        minutes, seconds = divmod(remainder, 60)
        log.info(f"{self.name} Time: {int(hours):02}:{int(minutes):02}:{int(seconds)}")
        pybatch.PythonBatchCommandBase.stage_stack.pop()
        self.exit_self(suppress_exception)

        return suppress_exception

    def log_error(self, exc_type, exc_val, exc_tb):
        if hasattr(exc_val, 'raising_obj'):
            error_dict = exc_val.raising_obj.error_dict(exc_type, exc_val, exc_tb)
        else:
            error_dict = self.error_dict(exc_type, exc_val, exc_tb)
        error_json = json.dumps(error_dict, separators=(',', ':'), sort_keys=True, default=utils.extra_json_serializer)
        log.error(f"---\n{error_json}\n...\n")

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.name))

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pybatch.PythonBatchCommandBase.__call__(self, *args, **kwargs)


class ResolveConfigVarsInFile(pybatch.PythonBatchCommandBase):
    def __init__(self, unresolved_file, resolved_file=None, config_files=None, raise_if_unresolved=False,
                 temp_config_vars=None, avoid_resolve_marker='$', **kwargs):
        """
        read a file and resolve all references to config_vars.
        :param unresolved_file: file to resolve
        :param resolved_file: file to write resolved output, if None will overwrite unresolved_file
        :param config_files: additional files to read config_vars definitions from
        :param raise_if_unresolved: when True, will raise exception if any unresolved $(...) references are left
        :param avoid_resolve_marker: config vars marked with this char (if != '$') will be ignored and after
        the resolve will be replaced by '$'. This will enable to mark certain config vars so they are not resolved
        """
        super().__init__(**kwargs)
        self.unresolved_file = unresolved_file
        if resolved_file:
            self.resolved_file = resolved_file
        else:
            self.resolved_file = self.unresolved_file
        self.config_files = config_files
        self.raise_if_unresolved = raise_if_unresolved
        self.temp_config_vars = temp_config_vars
        self.avoid_resolve_marker = avoid_resolve_marker

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.unresolved_file))
        if self.resolved_file != self.unresolved_file:
            all_args.append(self.unnamed__init__param(self.resolved_file))
        all_args.append(self.optional_named__init__param("config_files", self.config_files, None))
        all_args.append(self.optional_named__init__param("avoid_resolve_marker", self.avoid_resolve_marker, '$'))
        if self.temp_config_vars:
            complete_repr = f"temp_config_vars="+json.dumps(self.temp_config_vars)
            all_args.append(complete_repr)
        all_args.append(self.optional_named__init__param("config_files", self.config_files, None))

    def progress_msg_self(self) -> str:
        return f'''resolving {self.unresolved_file} to {self.resolved_file}'''

    def __call__(self, *args, **kwargs) -> None:
        pybatch.PythonBatchCommandBase.__call__(self, *args, **kwargs)
        with config_vars.push_scope_context() as scope_context:
            if self.temp_config_vars:
                config_vars.update(self.temp_config_vars)
            if self.config_files is not None:
                reader = ConfigVarYamlReader(config_vars)
                for config_file in self.config_files:
                    reader.read_yaml_file(config_file)
            with utils.utf8_open_for_read(self.unresolved_file, "r") as rfd:
                text_to_resolve = rfd.read()
            resolved_text = config_vars.resolve_str(text_to_resolve)

            if self.raise_if_unresolved:
                unresolved_re = re.compile(r"""\$\(.*?\)""")
                all_unresolved = unresolved_re.findall(resolved_text)
                if all_unresolved:
                    unresolved_references = ", ".join(list(set(all_unresolved)))
                    raise ValueError(f"unresolved config_vars in {self.unresolved_file}: {unresolved_references}")

            if self.avoid_resolve_marker != '$':
                resolved_text = resolved_text.replace(f"self.avoid_resolve_marker(", "$(")

            with utils.utf8_open_for_write(self.resolved_file, "w") as wfd:
                wfd.write(resolved_text)


class ReadConfigVarsFromFile(pybatch.PythonBatchCommandBase):
    def __init__(self, file_to_read, **kwargs):
        super().__init__(**kwargs)
        self.file_to_read = file_to_read

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.file_to_read))

    def progress_msg_self(self) -> str:
        return f'''reading configVars from {self.file_to_read}'''

    def __call__(self, *args, **kwargs) -> None:
        pybatch.PythonBatchCommandBase.__call__(self, *args, **kwargs)
        reader = ConfigVarYamlReader(config_vars)
        reader.read_yaml_file(self.file_to_read)


class ReadConfigVarValueFromTextFile(pybatch.PythonBatchCommandBase, essential=True):
    """
    Read a file and assign the file's whole contents to a configVar
    """
    def __init__(self, file_path_to_read, var_name, **kwargs):
        super().__init__(**kwargs)
        self.file_path_to_read = file_path_to_read
        self.var_name = var_name

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.file_path_to_read))
        all_args.append(self.unnamed__init__param(self.var_name))

    def progress_msg_self(self) -> str:
        return f'''Reading config variable:{self.var_name}, from {self.file_path_to_read}'''

    def __call__(self, *args, **kwargs) -> None:
        pybatch.PythonBatchCommandBase.__call__(self, *args, **kwargs)
        with utils.utf8_open_for_read(self.file_path_to_read, 'r') as f:
            value = f.read()
            value = value.strip()
            config_vars[self.var_name] = value


class EnvironVarAssign(PythonDoSomething, call__call__=False, is_context_manager=False, kwargs_defaults={'own_progress_count': 0}):
    """ assigns an environment variable
    """
    def __init__(self, var_name, var_value, **kwargs) -> None:
        assert var_name.isidentifier(), f"{var_name} is not a valid identifier"
        self.var_name = var_name
        self.var_value = var_value
        the_repr = f'''os.environ["{self.var_name}"]="{self.var_value}"'''
        super().__init__(the_repr, **kwargs)


def convertSeconds(seconds):
    whole_seconds = int(seconds)
    whole_ms = round((seconds-whole_seconds)*1000)
    m = int(whole_seconds/60)
    s = int(whole_seconds-(m*60))
    converted_str = f"{m}m:{s}.{whole_ms:03}s"
    return converted_str


class PatchPyBatchWithTimings(pybatch.PythonBatchCommandBase):

    def __init__(self, path_to_py_batch, **kwargs) -> None:
        pybatch.PythonBatchCommandBase.__init__(self, **kwargs)
        self.path_to_py_batch = utils.ExpandAndResolvePath(path_to_py_batch)

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.unnamed__init__param(self.path_to_py_batch))

    def progress_msg_self(self) -> str:
        """ classes overriding PythonBatchCommandBase should add their own progress message
        """
        return super(PatchPyBatchWithTimings, self).progress_msg_self()

    def __call__(self, *args, **kwargs):
        progress_comment_re = re.compile(""".+prog_num=(?P<progress>\d+).+\s+$""")
        py_batch_with_timings = self.path_to_py_batch.with_suffix(".timings.py")
        last_progress_reported = 0
        with utils.utf8_open_for_read(self.path_to_py_batch) as rfd, utils.utf8_open_for_write(py_batch_with_timings, "w") as wfd:
            for line in rfd.readlines():
                line_to_print = line
                match = progress_comment_re.fullmatch(line)
                if match:
                    progress_num = int(match.group("progress"))
                    if progress_num > last_progress_reported:  # some items have the same progress num, so report only the first
                        last_progress_reported = progress_num
                        progress_time = pybatch.PythonBatchCommandBase.runtime_duration_by_progress.get(progress_num, None)
                        if progress_time is not None:
                            progress_time_str = convertSeconds(progress_time)
                        else:
                            progress_time_str = '?'
                        line_to_print = f"""{line.rstrip()}  # {progress_time_str}\n"""
                wfd.write(line_to_print)

            sync_timing_config_var_name = f"__TIMING_SYNC_SEC__"
            if sync_timing_config_var_name in config_vars:
                bytes_to_download = config_vars['__NUM_BYTES_TO_DOWNLOAD__'].int()
                if bytes_to_download:
                    download_time_sec = config_vars[sync_timing_config_var_name].float()
                    bytes_per_second = int(bytes_to_download / download_time_sec)
                    sync_timing_line = f"# downloaded {bytes_to_download} bytes in {convertSeconds(download_time_sec)}, {bytes_per_second} bytes per second\n"
                    wfd.write(sync_timing_line)
            for stage in ('copy', 'remove', 'doit'):
                stage_timing_config_var_name = f"__TIMING_{stage}_SEC__".upper()
                if stage_timing_config_var_name in config_vars:
                    stage_time_sec = config_vars[stage_timing_config_var_name].float()
                    stage_timing_line = f"# {stage} time {convertSeconds(stage_time_sec)}\n"
                    wfd.write(stage_timing_line)
