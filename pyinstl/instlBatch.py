import shlex

from configVar import var_stack
from pyinstl.cmdOptions import CommandLineOptions, read_command_line_options


def prepare_command_list_from_batch_file(batch_options):
    command_list = list()
    with open(batch_options.config_file[0], "r") as rfd:
        command_lines = rfd.readlines()

    for command_line in command_lines:
        argv = shlex.split(command_line.strip())
        print(argv)
        command_list.append(argv)
    return command_list


def do_batch_file(initial_vars, batch_options):
    """ execute a list of instl commands as give in a config file
        currently limited only to commands of mode "do_something", e.g.
        commands implemented by InstMisc.
    """
    command_list = prepare_command_list_from_batch_file(batch_options)
    from pyinstl.instlMisc import InstlMisc
    instance = InstlMisc(initial_vars)
    for argv in command_list:
        options = CommandLineOptions()
        read_command_line_options(options, argv)
        with var_stack.push_scope_context():
            instance.init_from_cmd_line_options(options)
            instance.do_command()

