from typing import List, Any
import tempfile
import stat
import pathlib

from .batchCommands import *


class ShellCommands(RunProcessBase):
    def __init__(self, dir, shell_commands_var_name, **kwargs):
        kwargs["shell"] = True
        super().__init__(**kwargs)
        self.dir = dir
        self.var_name = var_name
        self.batch_file = None

    def __repr__(self):
        the_repr = f"""{self.__class__.__name__}(dir="{self.dir}", var_name="{self.var_name}")"""
        return the_repr

    def progress_msg_self(self):
        prog_mess = ""
        return prog_mess

    def create_run_args(self):
        the_lines = globals()[self.var_name]
        if isinstance(the_lines, str):
            the_lines = [the_lines]
        the_lines.insert(0,  "#!/usr/bin/env bash")
        commands_text = "\n".join(the_lines)
        batch_file_path = pathlib.Path(self.dir, self.var_name + ".command")
        self.batch_file = open(batch_file_path, "w")
        os.chmod(self.batch_file.name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self.batch_file.write(self.commands_text)
        self.batch_file.flush()
        run_args = list()
        run_args.append(self.batch_file.name)
        return run_args

    def exit_self(self, exit_return):
        if self.batch_file:
            self.batch_file.close()


class VarAssign(PythonBatchCommandBase):
    def __init__(self, param_name: str, var_value: Any):
        super().__init__(is_context_manager=False)
        self.param_name = param_name
        self.var_value = var_value

    def __repr__(self):

        the_repr = f'{self.param_name} = {repr(self.var_value)}\n'
        return the_repr

    def progress_msg_self(self):
        return ""

    def __call__(self, *args, **kwargs):
        pass
