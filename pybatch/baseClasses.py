import sys
import subprocess
import abc
import re
import time
from contextlib import contextmanager


first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')


def camel_to_snake_case(identifier):
    identifier1 = first_cap_re.sub(r'\1_\2', identifier)
    identifier2 = all_cap_re.sub(r'\1_\2', identifier1).lower()
    return identifier2


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
        __call__: here the real
    """
    instance_counter: int = 0
    total_progress: int = 0
    essential = True
    empty__call__ = False

    def __init_subclass__(cls, essential=True, empty__call__=False, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.essential = essential
        cls.empty__call__ = empty__call__

    @abc.abstractmethod
    def __init__(self, identifier=None, **kwargs):
        PythonBatchCommandBase.instance_counter += 1
        if not isinstance(identifier, str) or not identifier.isidentifier():
            self.identifier = "obj"
        self.obj_name = camel_to_snake_case(f"{self.__class__.__name__}_{PythonBatchCommandBase.instance_counter:05}")

        self.report_own_progress = kwargs.get('report_own_progress', True)
        self.ignore_all_errors =   kwargs.get('ignore_all_errors', False)
        self.is_context_manager = kwargs.get('is_context_manager', True)

        self.progress = 0
        if self.report_own_progress:
            PythonBatchCommandBase.total_progress += 1
            self.progress = PythonBatchCommandBase.total_progress
        self.exceptions_to_ignore = []
        self.child_batch_commands = []
        self.enter_time = None
        self.exit_time = None
        self.in_sub_accum = False

    def is_essential(self):
        retVal = self.essential
        if not retVal:
            retVal = any([child.is_essential() for child in self.child_batch_commands])
        return retVal

    def num_sub_batch_commands(self):
        counter = 0
        for batch_command in self.child_batch_commands:
            counter += batch_command.num_sub_batch_commands()
            counter += 1
        return counter

    def __iadd__(self, child_commands):
        self.add(child_commands)
        return self

    def add(self, instructions):
        assert not self.in_sub_accum, "PythonBatchCommandAccum.add: should not be called while sub_accum is in context"
        if isinstance(instructions, PythonBatchCommandBase):
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
        self.add(context)

    @abc.abstractmethod
    def __repr__(self):
        the_repr = f"{self.__class__.__name__}(report_own_progress={self.report_own_progress}, ignore_all_errors={self.ignore_all_errors})"
        return the_repr

    @abc.abstractmethod
    def repr_batch_win(self):
        return ""

    @abc.abstractmethod
    def repr_batch_mac(self):
        return ""

    def __eq__(self, other):
        do_not_compare_keys = ('progress', 'obj_name')
        dict_self = {k:  self.__dict__[k] for k in self.__dict__.keys() if k not in do_not_compare_keys}
        dict_other = {k: other.__dict__[k] for k in other.__dict__.keys() if k not in do_not_compare_keys}
        is_eq = dict_self == dict_other
        return is_eq

    def __hash__(self):
        the_hash = hash(tuple(sorted(self.__dict__.items())))
        return the_hash

    def progress_msg(self):
        the_progress_msg = f"Progress {self.progress} of {PythonBatchCommandBase.total_progress};"
        return the_progress_msg

    @abc.abstractmethod
    def progress_msg_self(self):
        """ classes overriding PythonBatchCommandBase should add their own progress message
        """
        return ""

    def warning_msg_self(self):
        """ classes overriding PythonBatchCommandBase can add their own warning message
        """
        return ""

    def error_msg_self(self):
        """ classes overriding PythonBatchCommandBase can add their own error message
        """
        return ""

    def enter_self(self):
        """ classes overriding PythonBatchCommandBase can add code here without
            repeating __enter__, bit not do any actual work!
        """
        pass

    def __enter__(self):
        self.enter_time = time.perf_counter()
        try:
            if self.report_own_progress:
                print(f"{self.progress_msg()} {self.progress_msg_self()}")
            self.enter_self()
        except Exception as ex:
            suppress_exception = self.__exit__(*sys.exc_info())
            if not suppress_exception:
                raise
        return self

    def exit_self(self, exit_return):
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
            print(f"{self.progress_msg()} WARNING; {self.warning_msg_self()}; {exc_val.__class__.__name__}: {exc_val}")
            suppress_exception = True
        else:
            print(f"{self.progress_msg()} ERROR; {self.error_msg_self()}; {exc_val.__class__.__name__}: {exc_val}")
        self.exit_self(exit_return=suppress_exception)
        self.exit_time = time.perf_counter()
        command_time_ms = (self.exit_time-self.enter_time)*1000.0
        print(f"{self.progress_msg()} time: {command_time_ms:.2f}ms")
        return suppress_exception

    @abc.abstractmethod
    def __call__(self, *args, **kwargs):
        pass


class RunProcessBase(PythonBatchCommandBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.ignore_all_errors:
            self.exceptions_to_ignore.append(subprocess.CalledProcessError)
        self.shell = kwargs.get('shell', False)

    @abc.abstractmethod
    def create_run_args(self):
        raise NotImplementedError

    def __call__(self, *args, **kwargs):
        run_args = list(map(str, self.create_run_args()))
        print(" ".join(run_args))
        completed_process = subprocess.run(run_args, check=True, stdout=subprocess.PIPE, shell=self.shell)
        return None  # what to return here?

    def __repr__(self):
        raise NotImplementedError
