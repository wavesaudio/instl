import sys
import subprocess
import abc
import re
import time
from contextlib import contextmanager
from typing import List
import logging

log = logging.getLogger(__name__)
from enum import Enum, auto


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
    def __init__(self, identifier=None, **kwargs):
        PythonBatchCommandBase.instance_counter += 1
        if not isinstance(identifier, str) or not identifier.isidentifier():
            self.identifier = "obj"

        self.report_own_progress = kwargs.get('report_own_progress', True)
        self.ignore_all_errors =   kwargs.get('ignore_all_errors', False)

        self.exceptions_to_ignore = []
        self.child_batch_commands = []
        self.enter_time = None
        self.exit_time = None
        self.in_sub_accum = False
        self.own_num_progress = 1
        self.essential_action_counter = 0

    def num_progress_items(self) -> int:
        retVal = self.own_num_progress
        for sub in self.child_batch_commands:
            retVal += sub.num_progress_items()
        return retVal

    def is_essential(self) -> bool:
        retVal = self.essential
        if not retVal:
            retVal = any([child.is_essential() for child in self.child_batch_commands])
        return retVal

    def num_sub_batch_commands(self) -> int:
        counter = 0
        for batch_command in self.child_batch_commands:
            counter += batch_command.num_sub_batch_commands()
            counter += 1
        return counter

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

    @abc.abstractmethod
    def __repr__(self) -> str:
        the_repr = f"{self.__class__.__name__}(report_own_progress={self.report_own_progress}, ignore_all_errors={self.ignore_all_errors})"
        return the_repr

    @abc.abstractmethod
    def repr_batch_win(self) -> str:
        return ""

    @abc.abstractmethod
    def repr_batch_mac(self) -> str:
        return ""

    def __eq__(self, other) -> bool:
        do_not_compare_keys = ('progress', )
        dict_self = {k:  self.__dict__[k] for k in self.__dict__.keys() if k not in do_not_compare_keys}
        dict_other = {k: other.__dict__[k] for k in other.__dict__.keys() if k not in do_not_compare_keys}
        is_eq = dict_self == dict_other
        return is_eq

    def __hash__(self):
        the_hash = hash(tuple(sorted(self.__dict__.items())))
        return the_hash

    def progress_msg(self) -> str:
        PythonBatchCommandBase.running_progress += self.own_num_progress
        the_progress_msg = f"Progress {PythonBatchCommandBase.running_progress} of {PythonBatchCommandBase.total_progress};"
        return the_progress_msg

    @abc.abstractmethod
    def progress_msg_self(self) -> str:
        """ classes overriding PythonBatchCommandBase should add their own progress message
        """
        return ""

    def warning_msg_self(self) -> str:
        """ classes overriding PythonBatchCommandBase can add their own warning message
        """
        return f"{self.__class__.__name__}"

    def error_msg_self(self) -> str:
        """ classes overriding PythonBatchCommandBase can add their own error message
        """
        return f"{self.__class__.__name__}"

    def enter_self(self) -> None:
        """ classes overriding PythonBatchCommandBase can add code here without
            repeating __enter__, bit not do any actual work!
        """
        pass

    def __enter__(self):
        self.enter_time = time.perf_counter()
        try:
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
        suppress_exception = False
        if self.ignore_all_errors or exc_type is None:
            suppress_exception = True
        elif exc_type in self.exceptions_to_ignore:
            self.log_result(logging.WARNING, self.warning_msg_self(), exc_val)

            suppress_exception = True
        else:
            self.log_result(logging.ERROR, self.error_msg_self(), exc_val)
        self.exit_time = time.perf_counter()
        self.exit_self(exit_return=suppress_exception)
        command_time_ms = (self.exit_time-self.enter_time)*1000.0
        log.debug(f"{self.progress_msg()} time: {command_time_ms:.2f}ms")
        return suppress_exception

    def log_result(self, log_lvl, message, exc_val):
        log.log(log_lvl, f"{self.progress_msg()}; {message}; {exc_val.__class__.__name__}: {exc_val}")

    @abc.abstractmethod
    def __call__(self, *args, **kwargs):
        pass


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
        run_args = list(map(str, self.create_run_args()))
        print(" ".join(run_args))
        try:
            completed_process = subprocess.run(run_args, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=self.shell)
            #print("stdout:", completed_process.stdout)
            #print("stderr:", completed_process.stderr)
        except Exception as ex:
            print("subprocess.run exception:", ex)
        return None  # what to return here?

    def log_result(self, log_lvl, message, exc_val):
        if self.stderr:
            message += f'; STDERR: {self.stderr.decode()}'
        super().log_result(log_lvl, message, exc_val)

    def __repr__(self):
        raise NotImplementedError
