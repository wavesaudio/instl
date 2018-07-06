import os
import sys
import shlex

from pyinstl.instlMisc import InstlMisc
from configVar import config_vars
from pyinstl.cmdOptions import CommandLineOptions, read_command_line_options
import utils


class CommandListRunner(object):
    def __init__(self, initial_vars, options):
        self.initial_vars = initial_vars
        self.options = options
        self.child_pids = list()

        self.instance = InstlMisc(initial_vars, "command-list")
        self.instance.init_from_cmd_line_options(self.options)

    def run(self, parallel=False):
        command_list = self.prepare_command_list_from_file()
        command_list_dir, command_list_leaf = os.path.split(self.options.config_file[0])
        if parallel:
            self.instance.batch_accum += self.instance.platform_helper.echo(f"Running {len(command_list} commands in parallel from {command_list_leaf}")
            for argv in command_list:
                self.do_forked_command(argv)

            for child_pid in self.child_pids:
                wait_val = os.waitpid(child_pid, 0)
                print(child_pid, wait_val)
            self.instance.batch_accum += self.instance.platform_helper.echo(f"Running {len(command_list)} commands in parallel done")
        else:
            self.instance.batch_accum += self.instance.platform_helper.echo(f"Running {len(command_list)} commands one by one from {command_list_leaf}")
            for argv in command_list:
                self.run_one_command(argv)
            self.instance.batch_accum += self.instance.platform_helper.echo(f"Running {len(command_list)} commands one by one done")

    def prepare_command_list_from_file(self):
        command_list = list()
        with utils.utf8_open(self.options.config_file[0], "r") as rfd:
            command_lines = rfd.readlines()

        for command_line in command_lines:
            resolved_command_line = config_vars.resolve_str(command_line.strip())
            argv = shlex.split(resolved_command_line)
            command_list.append(argv)
        return command_list

    def run_one_command(self, argv):
        options = CommandLineOptions()
        read_command_line_options(options, argv)
        with config_vars.push_scope_context():
            self.instance.init_from_cmd_line_options(options)
            self.instance.do_command()

    def do_forked_command(self, argv):
        #rpipe, wpipe = os.pipe()
        new_pid = os.fork()
        if 0 == new_pid:
            #os.close(rpipe)
            #os.dup2(wpipe, sys.stdout.fileno())
            #os.dup2(wpipe, sys.stderr.fileno())
            #os.close(wpipe)
            self.run_one_command(argv)
            exit(0)
        else:
            print("new_pid:", new_pid)
            self.child_pids.append(new_pid)
"""
rpipe, wpipe = os.pipe()

pid = os.fork()
if pid == -1:
    raise TestError("Failed to fork() in prepare_test_dir")

if pid == 0:
    # Child -- do the copy, print log to pipe and exit
    try:
        os.close(rpipe)
        os.dup2(wpipe, sys.stdout.fileno())
        os.dup2(wpipe, sys.stderr.fileno())
        os.close(wpipe)
"""


def run_commands_from_file(initial_vars, options):
    """ execute a list of instl commands as give in a config file
        currently limited only to commands of mode "do_something", e.g.
        commands implemented by InstMisc.
    """
    config_vars.setdefault("__START_DYNAMIC_PROGRESS__", "0")
    config_vars.setdefault("__TOTAL_DYNAMIC_PROGRESS__", "0")

    runner = CommandListRunner(initial_vars, options)

    parallel_run = "__RUN_COMMAND_LIST_IN_PARALLEL__" in config_vars
    runner.run(parallel=parallel_run)
