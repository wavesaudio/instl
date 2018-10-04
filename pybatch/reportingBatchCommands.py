from pathlib import Path
import keyword
import json
import re
from typing import List

import utils

from .baseClasses import *
log = logging.getLogger()

need_path_resolving_re = re.compile(".+(DIR|PATH|FOLDER|FOLDERS)(__)?$")


class AnonymousAccum(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False, is_anonymous=True):

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


class RaiseException(PythonBatchCommandBase, essential=True):
    """ raise a specific exception - for debugging """
    def __init__(self, exception_type, exception_message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.exception_type = exception_type
        self.exception_type_name = self.exception_type.__name__
        self.exception_message = exception_message
        self.non_representative__dict__keys.append('exception_type')

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.exception_type_name)
        all_args.append(utils.quoteme_raw_string(self.exception_message))

    def progress_msg_self(self) -> str:
        return f'''Raising exception {self.exception_type.__name__}("{self.exception_message}")'''

    def __call__(self, *args, **kwargs) -> None:
        raise self.exception_type(self.exception_message)


class Stage(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=True):
    """ Stage: a container for other PythonBatchCommands, that has a name and is used as a context manager ("with").
        Stage itself preforms no action only the contained commands will be preformed
    """
    def __init__(self, stage_name, stage_extra=None, **kwargs):
        super().__init__(**kwargs)
        self.stage_name = stage_name
        self.stage_extra = stage_extra
        self.own_progress_count = 0

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(self.stage_name))
        if self.stage_extra:
            all_args.append(utils.quoteme_raw_string(self.stage_extra))

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


class Progress(PythonBatchCommandBase, essential=False, call__call__=True, is_context_manager=False):
    """ issue a progress message, increasing progress count
    """
    def __init__(self, message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(self.message))

    def progress_msg_self(self) -> str:
        return self.message

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.running_progress += self.own_progress_count
        log.info(f"{self.progress_msg()} {self.progress_msg_self()}")


class Echo(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False):
    """ issue a message without increasing progress count
    """
    def __init__(self, message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.own_progress_count = 0

    def __repr__(self) -> str:
        the_repr = f'''print("{self.message}")'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class Remark(PythonBatchCommandBase, call__call__=False, is_context_manager=False):
    """ write a remark in code
    """
    def __init__(self, remark, **kwargs) -> None:
        super().__init__(**kwargs)
        self.remark = remark
        self.own_progress_count = 0

    def __repr__(self) -> str:
        the_repr = f'''# {self.remark}'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class PythonDoSomething(PythonBatchCommandBase, essential=True, call__call__=False, is_context_manager=False):

    def __init__(self, some_python_code, **kwargs) -> None:
        super().__init__(**kwargs)
        self.some_python_code = some_python_code
        self.own_progress_count = 0

    def __repr__(self) -> str:
        the_repr = self.some_python_code
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class PythonVarAssign(PythonBatchCommandBase, essential=True, call__call__=False, is_context_manager=False):
    """ creates a python variable assignment, e.g.
        x = y
    """
    def __init__(self, var_name, *var_values, **kwargs) -> None:
        super().__init__(**kwargs)
        assert var_name.isidentifier(), f"{var_name} is not a valid identifier"
        assert not keyword.iskeyword(var_name), f"{var_name} is not a python key word"
        self.var_name = var_name
        self.var_values = var_values
        self.own_progress_count = 0

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
                    adjusted_values.append(utils.quoteme_raw_string(val))
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


class ConfigVarAssign(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False):
    """ creates a configVar assignment, e.g.
        config_vars["x"] = y
    """
    def __init__(self, var_name, *var_values, **kwargs) -> None:
        super().__init__(**kwargs)
        assert var_name.isidentifier(), f"{var_name} is not a valid identifier"
        assert not keyword.iskeyword(var_name), f"{var_name} is not a python key word"
        self.var_name = var_name
        self.var_values = var_values
        self.own_progress_count = 0

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
                    adjusted_values.append(utils.quoteme_raw_string(val))
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


class PythonBatchRuntime(PythonBatchCommandBase, essential=True, call__call__=False, is_context_manager=True):
    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.own_progress_count = 0
        self.name = name

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit_time = time.perf_counter()
        suppress_exception = False
        if exc_val:
            self.log_error(exc_type, exc_val, exc_tb)
            log.info("Shakespeare says: The Comedy of Errors")
        time_diff = self.exit_time-self.enter_time
        hours, remainder = divmod(time_diff, 3600)
        minutes, seconds = divmod(remainder, 60)
        log.info(f"{self.name} Time: {int(hours):02}:{int(minutes):02}:{int(seconds):02}")
        PythonBatchCommandBase.stage_stack.clear()
        return suppress_exception

    def log_error(self, exc_type, exc_val, exc_tb):
        error_dict = exc_val.raising_obj.error_dict(exc_type, exc_val, exc_tb)
        error_json = json.dumps(error_dict, separators=(',\n', ': '), sort_keys=True)
        log.error(f"{error_json}")

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(f'''"{self.name}"''')

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
