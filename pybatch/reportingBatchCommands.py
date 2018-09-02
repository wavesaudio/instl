import keyword
import json

import utils

from .baseClasses import *
log = logging.getLogger(__name__)


class AnonymousAccum(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False, is_anonymous=True):

    """ AnonymousAccum: a container for other PythonBatchCommands,
        AnonymousAccum is not meant to be written to python-batch file or executed - only the
        contained commands will be.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.i_am_anonymous=True

    def __repr__(self) -> str:
        raise NotImplementedError("AnonymousAccum.__repr__ should not be called")

    def progress_msg_self(self) -> str:
        raise NotImplementedError("AnonymousAccum.progress_msg_self should not be called")

    def __call__(self, *args, **kwargs) -> None:
        raise NotImplementedError("AnonymousAccum.__call__ should not be called")


class RaiseException(PythonBatchCommandBase, essential=True):
    def __init__(self, exception_type, exception_message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.exception_type = exception_type
        self.exception_type_name = self.exception_type.__name__
        self.exception_message = exception_message
        self.non_representative__dict__keys.append('exception_type')

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({self.exception_type_name}, "{self.exception_message}")'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f'''Raising exception {self.exception_type.__name__}("{self.exception_message}")'''

    def __call__(self, *args, **kwargs) -> None:
        raise self.exception_type(self.exception_message)

section_stack = list()


class Section(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=True):
    """ Section: a container for other PythonBatchCommands, that has a name and is used as a context manager ("with").
        Section itself preforms no action only the contained commands will be preformed
    """
    def __init__(self, *titles):
        super().__init__()
        self.titles = titles
        self.own_progress_count = 0

    def __repr__(self):
        if len(self.titles) == 1:
            quoted_titles = utils.quoteme_double(self.titles[0])
        else:
            quoted_titles = ", ".join((utils.quoteme_double(title) for title in self.titles))
        the_repr = f"""{self.__class__.__name__}({quoted_titles})"""
        return the_repr

    def progress_msg_self(self):
        the_progress_msg = f'''{", ".join(self.titles)}'''
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        pass

    def __enter__(self):
        global section_stack
        section_stack.append(self.titles)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            global section_stack
            section_stack.pop()


class Progress(PythonBatchCommandBase, essential=False, call__call__=True, is_context_manager=False):
    """
        just issue a progress message
    """
    def __init__(self, message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.message)}'''
        if self.own_progress_count > 1:
            the_repr += f", progress_count={self.own_progress_count}"
        the_repr += ')'
        return the_repr

    def progress_msg_self(self) -> str:
        return self.message

    def __call__(self, *args, **kwargs) -> None:
        PythonBatchCommandBase.running_progress += self.own_progress_count
        log.info(f"{self.progress_msg()} {self.progress_msg_self()}")


class Echo(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False):
    """
        just issue a (non progress) message
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
    """
        write a remark in code
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


class PythonVarAssign(PythonBatchCommandBase, essential=True, call__call__=False, is_context_manager=False):
    """
        creates a python variable assignment, e.g.
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
            adjusted_values = list()
            for val in self.var_values:
                try:
                    adjusted_values.append(int(val))
                except:
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
    """
        creates a configVar assignment, e.g.
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
            adjusted_values = list()
            for val in self.var_values:
                try:
                    adjusted_values.append(int(val))
                except:
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
        return suppress_exception

    def log_error(self, exc_type, exc_val, exc_tb):
        error_dict = exc_val.raising_obj.error_dict(exc_type, exc_val, exc_tb)
        error_json = json.dumps(error_dict, separators=(',\n', ': '), sort_keys=True)
        log.error(f"{error_json}")

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}("{self.name}")'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
