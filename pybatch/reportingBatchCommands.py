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

    def repr_batch_win(self) -> str:
        raise NotImplementedError("AnonymousAccum.repr_batch_win should not be called")

    def repr_batch_mac(self) -> str:
        raise NotImplementedError("AnonymousAccum.repr_batch_mac should not be called")

    def progress_msg_self(self) -> str:
        raise NotImplementedError("AnonymousAccum.progress_msg_self should not be called")

    def __call__(self, *args, **kwargs) -> None:
        raise NotImplementedError("AnonymousAccum.__call__ should not be called")

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class RaiseException(PythonBatchCommandBase, essential=True):
    def __init__(self, exception_type, exception_message, identifier=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.exception_type = exception_type
        self.exception_message = exception_message

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({self.exception_type.__name__}, "{self.exception_message}")'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        raise self.exception_type(self.exception_message)

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({"dummy_exception": self.exception_message})


class Section(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=True):
    """ Section: a container for other PythonBatchCommands, that has a name and is used as a context manager ("with").
        Section itself preforms no action only the contained commands will be preformed
    """
    def __init__(self, *titles):
        super().__init__()
        self.titles = titles

    def __repr__(self):
        if len(self.titles) == 1:
            quoted_titles = utils.quoteme_double(self.titles[0])
        else:
            quoted_titles = ", ".join((utils.quoteme_double(title) for title in self.titles))
        the_repr = f"""{self.__class__.__name__}({quoted_titles})"""
        return the_repr

    def repr_batch_win(self):
        retVal = list()
        retVal.append(f"""echo section: {self.self.titles}""")
        return retVal

    def repr_batch_mac(self):
        retVal = list()
        retVal.append(f"""echo section: {self.titles}""")
        return retVal

    def progress_msg_self(self):
        the_progress_msg = f'''{", ".join(self.titles)}'''
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        pass

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class Progress(PythonBatchCommandBase, essential=False, call__call__=True, is_context_manager=False):
    """
        just issue a progress message
    """
    def __init__(self, message, inc_progress_by: int=1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.own_num_progress = inc_progress_by

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.message)}'''
        if self.own_num_progress > 1:
            the_repr += f", inc_progress_by={self.own_num_progress}"
        the_repr += ')'
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return self.message

    def __call__(self, *args, **kwargs) -> None:
        log.info(f"{self.progress_msg()} {self.progress_msg_self()}")

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class Echo(PythonBatchCommandBase, essential=False, call__call__=False, is_context_manager=False):
    """
        just issue a (non progress) message
    """
    def __init__(self, message, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.own_num_progress = 0

    def __repr__(self) -> str:
        the_repr = f'''print("{self.message}")'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class Remark(PythonBatchCommandBase, call__call__=False, is_context_manager=False):
    """
        write a remark in code
    """
    def __init__(self, remark, **kwargs) -> None:
        super().__init__(**kwargs)
        self.remark = remark
        self.own_num_progress = 0

    def __repr__(self) -> str:
        the_repr = f'''# {self.remark}'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


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
        self.own_num_progress = 0

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

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


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
        self.own_num_progress = 0

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

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})


class PythonBatchRuntime(PythonBatchCommandBase, essential=True, call__call__=False, is_context_manager=True):
    def __init__(self, name, **kwargs):
        super().__init__(**kwargs)
        self.name = name

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit_time = time.perf_counter()
        suppress_exception = False
        if exc_val:
            self.log_error(exc_val, exc_tb)
            log.info("Shakespeare says: The Comedy of Errors")
        time_diff = self.exit_time-self.enter_time
        hours, remainder = divmod(time_diff, 3600)
        minutes, seconds = divmod(remainder, 60)
        log.info(f"{self.name} Time: {int(hours):02}:{int(minutes):02}:{int(seconds):02}")
        return suppress_exception

    def log_error(self, exc_val, exc_tb):
        error_dict = exc_val.raising_obj.error_dict(exc_val)
        error_dict.update({
            "file": exc_tb.tb_frame.f_code.co_filename,
            "line": exc_tb.tb_lineno
        })
        error_json = json.dumps(error_dict)
        log.error(f"{error_json}")

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}("{self.name}")'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass

    def error_dict_self(self, exc_val):
        super().error_dict_self(exc_val)
        self._error_dict.update({})
