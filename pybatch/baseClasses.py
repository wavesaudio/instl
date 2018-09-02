import os
import sys
import subprocess
import abc
from typing import Dict
import time
from contextlib import contextmanager
from typing import List
import logging

log = logging.getLogger()
import utils


class PythonBatchCommandBase(abc.ABC):
    """ PythonBatchCommandBase is the base class for all classes implementing batch commands.
        PythonBatchCommandBase implement context manager interface:
        __enter__: will print progress message (if needed)
                    derived classes should not override __enter__ and should not do any actual work here but implement
                    the work in __call__. If something must be done in __enter__ override enter_self
        __exit__: will handle exceptions and print warning/error messages, or ignore errors if needed
                 derived classes should not override __exit__. If something must be done in __exit__ override exit_self
        Derived classes must implement some additional methods:
        __repr__: must be implemented correctly so the returned string can be passed to eval to recreate the object
        __init__: must record all parameters needed to implement __repr__ and must not do any actual work!
        __call__: here the real work is done (if any)

        members:
        self.doing - the most possible detailed description of what the object is doing. Derived classes should update this member
            during operations, e.g. if a folder is copied file by file, self.doing will be rewritten as each file is copied.
                self.doing is often very similar to what is returned by progress_msg_self, however progress_msg_self is description
                of what was *asked* to be done, while doing is meant to describe what was actually being done when an error occurred.

        non_representative__dict__keys - list of keys of self.__dict__ that should not be used when comparing or displaying self
    """
    instance_counter: int = 0
    total_progress: int = 0
    running_progress: int = 0
    essential = True
    call__call__: bool = True         # when false no need to call
    is_context_manager: bool = True   # when true need to be created as context manager
    is_anonymous: bool = False        # anonymous means the object is just a container for child_batch_commands and should not be used by itself

    def __init_subclass__(cls, essential=True, call__call__=True, is_context_manager=True, is_anonymous=False, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.essential = essential
        cls.call__call__ = call__call__
        cls.is_context_manager = is_context_manager
        cls.is_anonymous = is_anonymous

    @abc.abstractmethod
    def __init__(self, **kwargs):
        PythonBatchCommandBase.instance_counter += 1

        self.own_progress_count = kwargs.get('progress_count', 1)
        self.report_own_progress = kwargs.get('report_own_progress', True)
        self.ignore_all_errors =   kwargs.get('ignore_all_errors', False)

        self.exceptions_to_ignore = []
        self.child_batch_commands = []
        self.enter_time = None
        self.exit_time = None
        self.in_sub_accum = False
        self.essential_action_counter = 0
        self._error_dict = None
        self.doing = None  # description of what the object is doing, derived classes should update this member during operations
        self.non_representative__dict__keys = ['non_representative__dict__keys', 'progress', '_error_dict', "doing", 'exceptions_to_ignore']

    @abc.abstractmethod
    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}(report_own_progress={self.report_own_progress}, ignore_all_errors={self.ignore_all_errors})"
        return the_repr

    @abc.abstractmethod
    def progress_msg_self(self) -> str:
        """ classes overriding PythonBatchCommandBase should add their own progress message
        """
        return f"{self.__class__.__name__}"

    def error_dict_self(self, exc_type, exc_val, exc_tb) -> None:
        pass

    @abc.abstractmethod
    def __call__(self, *args, **kwargs):
        pass

    def unnamed__init__param(self, value):
        value_str = utils.quoteme_raw_if_string(value)
        return value_str

    def named__init__param(self, name, value):
        value_str = utils.quoteme_raw_if_string(value)
        param_repr = f"{name}={value_str}"
        return param_repr

    def optional_named__init__param(self, name, value, default=None):
        param_repr = None
        if value != default:
            value_str = utils.quoteme_raw_if_string(value)
            param_repr = f"{name}={value_str}"
        return param_repr

    def total_progress_count(self) -> int:
        retVal = self.own_progress_count
        for sub in self.child_batch_commands:
            retVal += sub.total_progress_count()
        return retVal

    def is_essential(self) -> bool:
        retVal = self.essential
        if not retVal:
            retVal = any([child.is_essential() for child in self.child_batch_commands])
        return retVal

    def sub_commands(self) -> List:
        return self.child_batch_commands

    def __iadd__(self, child_commands):
        self.add(child_commands)
        return self

    def add(self, instructions):
        assert not self.in_sub_accum, "PythonBatchCommandAccum.add: should not be called while sub_accum is in context"
        if isinstance(instructions, PythonBatchCommandBase):
            if instructions.is_anonymous:  # no need for the parent, just the children
                self.child_batch_commands.extend(instructions.child_batch_commands)
            else:
                self.child_batch_commands.append(instructions)
        else:
            for instruction in instructions:
                self.add(instruction)

    @contextmanager
    def sub_accum(self, context):
        assert not self.in_sub_accum, "PythonBatchCommandAccum.sub_accum: should not be called while another sub_accum is in context"
        self.in_sub_accum = True
        yield context
        self.in_sub_accum = False
        if context.is_essential():
            self.add(context)

    def representative_dict(self):
        """  return a partial self.__dict__ without keys tha should not be used for presentation or comparing"""
        return {k: self.__dict__[k] for k in self.__dict__.keys() if k not in self.non_representative__dict__keys}

    def __eq__(self, other) -> bool:
        is_eq = self.representative_dict() == other.representative_dict()
        return is_eq

    def __hash__(self):
        the_hash = hash(tuple(sorted(self.__dict__.items())))
        return the_hash

    def progress_msg(self) -> str:
        the_progress_msg = f"Progress {PythonBatchCommandBase.running_progress} of {PythonBatchCommandBase.total_progress};"
        return the_progress_msg

    def warning_msg_self(self) -> str:
        """ classes overriding PythonBatchCommandBase can add their own warning message
        """
        return f"{self.__class__.__name__}"

    def enter_self(self) -> None:
        """ classes overriding PythonBatchCommandBase can add code here without
            repeating __enter__, bit not do any actual work!
        """
        pass

    def error_dict(self, exc_type, exc_val, exc_tb) -> Dict:
        if self._error_dict is None:
            self._error_dict = dict()
        self.error_dict_self(exc_type, exc_val, exc_tb)
        if not self.doing:
            self.doing = self.progress_msg_self()
        self._error_dict.update({
            'doing': self.doing,
            'exception_type': str(type(exc_val).__name__),
            'exception_str': str(exc_val),
            'instl_class': repr(self),
            'obj__dict__': self.representative_dict(),
            'local_time': time.strftime("%Y-%m-%d_%H.%M.%S"),
            'progress_counter': PythonBatchCommandBase.running_progress,
            'current_working_dir': os.getcwd(),
            "batch_file": exc_tb.tb_frame.f_code.co_filename,
            "batch_line": exc_tb.tb_lineno
             })
        return self._error_dict

    def __enter__(self):
        self.enter_time = time.perf_counter()
        try:
            PythonBatchCommandBase.running_progress += self.own_progress_count
            if self.report_own_progress:
                log.info(f"{self.progress_msg()} {self.progress_msg_self()}")
            self.enter_self()
        except Exception as ex:
            suppress_exception = self.__exit__(*sys.exc_info())
            if not suppress_exception:
                raise
        return self

    def exit_self(self, exit_return) -> None:
        """ classes overriding PythonBatchCommandBase can add code here without
            repeating __exit__.
            exit_self will be called regardless of exceptions
            param exit_return is what __exit__ will return
        """
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit_time = time.perf_counter()
        suppress_exception = False
        if exc_type is None or self.ignore_all_errors:
            suppress_exception = True
        elif exc_type in self.exceptions_to_ignore:
            self.log_result(logging.WARNING, self.warning_msg_self(), exc_val)
            suppress_exception = True
        else:
            if not hasattr(exc_val, "raising_obj"):
                setattr(exc_val, "raising_obj", self)
        self.exit_self(exit_return=suppress_exception)
        command_time_ms = (self.exit_time-self.enter_time)*1000.0
        #log.debug(f"{self.progress_msg()} time: {command_time_ms:.2f}ms")
        return suppress_exception

    def log_result(self, log_lvl, message, exc_val):
        log.log(log_lvl, f"{self.progress_msg()}; {message}; {exc_val.__class__.__name__}: {exc_val}")


class RunProcessBase(PythonBatchCommandBase, essential=True, call__call__=True, is_context_manager=True):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.ignore_all_errors:
            self.exceptions_to_ignore.append(subprocess.CalledProcessError)
        self.shell = kwargs.get('shell', False)
        self.stdout = ''
        self.stderr = ''

    @abc.abstractmethod
    def create_run_args(self):
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        run_args = self.create_run_args()
        run_args = list(map(str, run_args))
        self.doing = f"""calling subprocess '{" ".join(run_args)}'"""
        completed_process = subprocess.run(run_args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=self.shell)
        self.stdout = utils.unicodify(completed_process.stdout)
        self.stderr = utils.unicodify(completed_process.stderr)
        #log.debug(completed_process.stdout)
        completed_process.check_returncode()
        return None  # what to return here?

    def log_result(self, log_lvl, message, exc_val):
        if self.stderr:
            message += f'; STDERR: {self.stderr.decode()}'
        super().log_result(log_lvl, message, exc_val)

    def __repr__(self):
        raise NotImplementedError
