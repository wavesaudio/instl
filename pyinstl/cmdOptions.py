import collections
import argparse
from configVar import config_vars


class OptionToConfigVar:
    """ when attribute of CommandLineOptions is get or set
        OptionToConfigVar will read/write it to configVar

        if default is provided to __init__ the configVar is a priori set with this value
        if set_value is provided to __init__ when __set__ is called, the configVar is set
        to this value regardless of the value provided as param to __set__, useful
        for example when boolean "yes" value is required to mark the value was set.
    """

    def __init__(self, default=None, set_value=None):
        self.set_value = set_value
        self.default = default

    def __set_name__(self, owner, name):
        self.var_name = name
        if self.default is not None:
            config_vars[self.var_name] = self.default

    def __get__(self, instance, owner):
        retVal = None
        if self.var_name in config_vars:
            retVal = str(config_vars[self.var_name])
        return retVal

    def __set__(self, instance, value):
        if value is not None:
            if self.set_value is not None:
                config_vars[self.var_name] = self.set_value
            else:
                if isinstance(value, collections.abc.Sequence):
                    config_vars[self.var_name] = value
                else:
                    config_vars[self.var_name] = str(value)


class CommandLineOptions(object):
    """ namespace object to give to parse_args
        holds command line options
    """
    __BASE_URL__ = OptionToConfigVar()
    __CONFIG_FILE__ = OptionToConfigVar()
    __CREDENTIALS__ = OptionToConfigVar()
    __MAIN_DB_FILE__ = OptionToConfigVar()
    __DOCK_ITEM_LABEL__ = OptionToConfigVar()
    __DOCK_ITEM_PATH__ = OptionToConfigVar()
    __FAIL_EXIT_CODE__ = OptionToConfigVar()
    __FAIL_SLEEP_TIME__ = OptionToConfigVar()
    __FILE_SIZES_FILE__ = OptionToConfigVar()
    __JUST_WITH_NUMBER__ = OptionToConfigVar(default="0")
    __LIMIT_COMMAND_TO__ = OptionToConfigVar()
    __MAIN_COMMAND__ = OptionToConfigVar()
    __MAIN_INPUT_FILE__ = OptionToConfigVar()
    __MAIN_OUT_FILE__ = OptionToConfigVar()
    __NO_NUMBERS_PROGRESS__ = OptionToConfigVar()
    __NO_WTAR_ARTIFACTS__ = OptionToConfigVar()
    __OUTPUT_FORMAT__ = OptionToConfigVar()
    __PROPS_FILE__ = OptionToConfigVar()
    __REMOVE_FROM_DOCK__ = OptionToConfigVar()
    __REPORT_ONLY_INSTALLED__ = OptionToConfigVar()
    __RESTART_THE_DOCK__ = OptionToConfigVar()
    __RUN_AS_ADMIN__ = OptionToConfigVar()
    __RUN_BATCH__ = OptionToConfigVar()
    __RUN_COMMAND_LIST_IN_PARALLEL__ = OptionToConfigVar()
    __SHA1_CHECKSUM__ = OptionToConfigVar()
    __SHORTCUT_PATH__ = OptionToConfigVar()
    __SHORTCUT_TARGET_PATH__ = OptionToConfigVar()
    __START_DYNAMIC_PROGRESS__ = OptionToConfigVar()
    __TOTAL_DYNAMIC_PROGRESS__ = OptionToConfigVar()
    BASE_REPO_REV = OptionToConfigVar()
    LS_FORMAT = OptionToConfigVar()
    TARGET_REPO_REV = OptionToConfigVar()
    ABORT_FILE = OptionToConfigVar()
    SHELL = OptionToConfigVar()
    RUN_PROCESS_ARGUMENTS = OptionToConfigVar()
    __SILENT__ = OptionToConfigVar()

    def __init__(self) -> None:
        self.mode = None
        self.which_revision = None
        self.define = None

    def __str__(self):
        return "\n".join([''.join((n, ": ", str(v))) for n, v in sorted(vars(self).items())])


def prepare_args_parser(in_command):
    """
    Prepare the parser for command line arguments
    """

    all_command_details = dict()

    # client commands
    all_command_details.update({
        'copy':             {'mode': 'client', 'options': ('in', 'out', 'run', 'cred'), 'help': 'copy files to target paths'},
        'read-yaml':        {'mode': 'client', 'options': ('in', 'out', 'db'), 'help': "reads a yaml file to verify it's contents"},
        'remove':           {'mode': 'client', 'options': ('in', 'out', 'run',), 'help': 'remove items installed by copy'},
        'report-versions':  {'mode': 'client', 'options': ('in', 'out', 'output_format', 'only_installed'), 'help': 'report what is installed and what needs update'},
        'sync':             {'mode': 'client', 'options': ('in', 'out', 'run', 'cred'), 'help': 'sync files to be installed from server to local disk'},
        'synccopy':         {'mode': 'client', 'options': ('in', 'out', 'run', 'cred'), 'help': 'sync files to be installed from server to  local disk and copy files to target paths'},
        'uninstall':        {'mode': 'client', 'options': ('in', 'out', 'run',), 'help': 'uninstall previously copied files, considering dependencies'},
    })

    if in_command not in all_command_details:
        # do_something commands
        all_command_details.update({
            'check-checksum':       {'mode': 'do_something', 'options': ('in', 'prog',), 'help':  'check checksum for a list of files from info_map file'},
            'checksum':             {'mode': 'do_something', 'options': ('in',), 'help':  'calculate checksum for a file or folder'},
            'command-list':         {'mode': 'do_something', 'options': ('conf', 'prog', 'parallel'), 'help': 'do a list of commands from a file'},
            'exec':                 {'mode': 'do_something', 'options': ('in', 'out', 'conf_opt'), 'help':  'Execute a python scrip'},
            'fail':                 {'mode': 'do_something', 'options': (), 'help': "fail and return exit code"},
            'help':                 {'mode': 'do_something', 'options': (), 'help':  'help'},
            'ls':                   {'mode': 'do_something', 'options': ('in', 'out', 'limit'), 'help':  'create a directory listing'},
            'parallel-run':         {'mode': 'do_something', 'options': ('in', ), 'help':  'Run processes in parallel'},
            'resolve':              {'mode': 'do_something', 'options': ('in', 'out', 'conf'), 'help':  'read --in file resolve $() style variables and write result to --out, definitions are given in --config-file'},
            'run-process':          {'mode': 'do_something', 'options': ('in_opt',), 'help':  'Run a processes with optional abort file'},
            'test-import':          {'mode': 'do_something', 'options': (), 'help':  'test the import of required modules'},
            'translate_url':        {'mode': 'do_something', 'options': ('in',  'cred'), 'help':  'translate a url to be compatible with current connection'},
            'unwtar':               {'mode': 'do_something', 'options': ('in_opt', 'prog', 'out'), 'help':  'uncompress .wtar files in current (or in the --out) folder'},
            'version':              {'mode': 'do_something', 'options': (), 'help':  'display instl version'},
            'wtar':                 {'mode': 'do_something', 'options': ('in', 'out'), 'help':  'create .wtar files from specified files and folders'},
            'wzip':                 {'mode': 'do_something', 'options': ('in', 'out'), 'help':  'create .wzip file from specified file'},
            })

    if in_command not in all_command_details:
        # admin commands
        all_command_details.update({
            # converted to instl 2 style
            'activate-repo-rev':          {'mode': 'admin', 'options': ('out', 'run', 'conf',), 'help':  'upload repository revision file to admin folder'},
            'depend':               {'mode': 'admin', 'options': ('in', 'out',), 'help':  'output a dependencies map for an index file'},
            'dump-config-vars':     {'mode': 'admin', 'options': ('in_opt', 'out','conf_opt'), 'help':  'dump values of all configVars to file'},
            'file-sizes':           {'mode': 'admin', 'options': ('in', 'out'), 'help':  'Create a list of files and their sizes'},
            'fix-perm':             {'mode': 'admin', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'Fix Mac OS permissions'},
            'fix-props':            {'mode': 'admin', 'options': ('out', 'run', 'conf'), 'help':  'create svn commands to remove redundant properties such as executable bit from files that should not be marked executable'},
            'fix-symlinks':         {'mode': 'admin', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'replace symlinks with .symlinks files'},
            'gather-manifest-files':{'mode': 'admin', 'options': ('out', 'run', 'conf', 'limit'), 'help': 'gather manifest.yaml files to single index.yaml' },
            'stage2svn':            {'mode': 'admin', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'add/remove files in staging to svn sync repository'},
            'svn2stage':            {'mode': 'admin', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'svn sync repository and copy to staging folder'},
            'verify-repo':          {'mode': 'admin', 'options': ('conf',), 'help':  'Verify a local repository against its index'},
            'up2s3':                {'mode': 'admin', 'options': ('conf', 'out', 'run'), 'help': 'upload revision to s3'},
            'up-short-index':       {'mode': 'admin', 'options': ('conf', 'out', 'run'), 'help': 'upload short index'},
            'wait-on-action-trigger': {'mode': 'admin', 'options': ('conf',), 'help': 'wait for svn commit and upload revision to s3'},

            'check-instl-folder-integrity': {'mode': 'admin', 'options': ('in',), 'help': 'check that index and info_maps have correct checksums, and other attributes'},
            'read-info-map':        {'mode': 'admin', 'options': ('in+', 'db'), 'help':  "reads an info-map file to verify it's contents"},
            'short-index':          {'mode': 'admin', 'options': {'in', 'out'}, 'help': 'create short version of the index so report-versions will be faster'},
            'translate-guids':      {'mode': 'admin', 'options': ('in',  'conf'), 'help':  'translate guids to iids'},
            'verify-index':         {'mode': 'admin', 'options': ('in', 'cred'), 'help':  'Verify that index and info map are compatible'},
            'wtar-staging-folder':  {'mode': 'admin', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'create .wtar files inside staging folder'},
            })

    if in_command not in all_command_details:
        # misc commands, gui, doit
        all_command_details.update({
            'doit':                 {'mode': 'doit', 'options': ('in', 'out', 'run'), 'help':  'Do something'},
            'gui':                  {'mode': 'gui', 'options': (), 'help':  'graphical user interface'}
            })

    command_names = sorted(all_command_details.keys())

    # if in_command is None - just return the command names
    if in_command is None:
        return None, command_names

    def decent_convert_arg_line_to_args(self, arg_line):
        """ parse a file with options so that we do not have to write one sub-option
            per line.  Remove empty lines, comment lines, and end of line comments.
            ToDo: handle quotes
        """
        line_no_whitespace = arg_line.strip()
        if line_no_whitespace and line_no_whitespace[0] != '#':
            for arg in line_no_whitespace.split():
                if not arg:
                    continue
                elif arg[0] == '#':
                    break
                yield arg

    parser = argparse.ArgumentParser(description='instl: cross platform installer',
                    prefix_chars='-+',
                    fromfile_prefix_chars='@',
                    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    argparse.ArgumentParser.convert_arg_line_to_args = decent_convert_arg_line_to_args

    subparsers = parser.add_subparsers(dest='__MAIN_COMMAND__', help='sub-command help')

    command_details = all_command_details[in_command]
    command_parser = subparsers.add_parser(in_command, help=command_details['help'])
    command_parser.set_defaults(mode=command_details['mode'])

    # optional --in
    if 'in_opt' in command_details['options']:
        input_options = command_parser.add_argument_group(description='input arguments:')
        input_options.add_argument('--in', '-i',
                                    required=False,
                                    nargs=1,
                                    metavar='path-to-input-file',
                                    dest='__MAIN_INPUT_FILE__',
                                    help="file to act upon")

    # required --in
    if 'in' in command_details['options']:
        input_options = command_parser.add_argument_group(description='input arguments:')
        input_options.add_argument('--in', '-i',
                                    required=True,
                                    nargs=1,
                                    metavar='path-to-input-folder',
                                    dest='__MAIN_INPUT_FILE__',
                                    help="file or folder to act upon")

    # required multi --in
    if 'in+' in command_details['options']:
        input_options = command_parser.add_argument_group(description='input arguments:')
        input_options.add_argument('--in', '-i',
                                    required=True,
                                    nargs='+',
                                    metavar='path-to-input-folder',
                                    dest='__MAIN_INPUT_FILE__',
                                    help="files or folders to act upon")

    # optional --out
    if 'out' in command_details['options']:
        output_options = command_parser.add_argument_group(description='output arguments:')
        output_options.add_argument('--out', '-o',
                                    required=False,
                                    nargs=1,
                                    metavar='path-to-output-file',
                                    dest='__MAIN_OUT_FILE__',
                                    help="output file")

    if 'run' in command_details['options']:
        run_option = command_parser.add_argument_group(description='run arguments:')
        run_option.add_argument('--run', '-r',
                                    required=False,
                                    default=False,
                                    action='store_true',
                                    dest='__RUN_BATCH__',
                                    help="run the installation instructions script")

    if 'output_format' in command_details['options']:
        output_format_option = command_parser.add_argument_group(description='output_format arguments:')
        output_format_option.add_argument('--output-format',
                                    required=False,
                                    nargs=1,
                                    dest='__OUTPUT_FORMAT__',
                                    help="specify output format")

    if 'cred' in command_details['options']:
        credentials_option = command_parser.add_argument_group(description='credentials:')
        credentials_option.add_argument('--credentials',
                                    required=False,
                                    nargs=1,
                                    metavar='credentials',
                                    dest='__CREDENTIALS__',
                                    help="credentials to file server")

    if ('conf' in command_details['options']) or ('conf_opt' in command_details['options']):
        config_file_options = command_parser.add_argument_group(description='admin arguments:')
        is_required = 'conf' in command_details['options']
        config_file_options.add_argument('--config-file', '-s',
                                    required=is_required,
                                    nargs='+',
                                    metavar='path-to-config-file',
                                    dest='__CONFIG_FILE__',
                                    help="path to config-file")

    if 'prog' in command_details['options']:
        progress_options = command_parser.add_argument_group(description='dynamic progress report')
        progress_options.add_argument('--start-progress',
                                    required=False,
                                    nargs=1,
                                    metavar='start-progress-number',
                                    dest='__START_DYNAMIC_PROGRESS__',
                                    help="num progress items to begin with")
        progress_options.add_argument('--total-progress',
                                    required=False,
                                    nargs=1,
                                    metavar='total-progress-number',
                                    dest='__TOTAL_DYNAMIC_PROGRESS__',
                                    help="num total progress items")
        progress_options.add_argument('--no-numbers-progress',
                                    required=False,
                                    default=False,
                                    action='store_true',
                                    dest='__NO_NUMBERS_PROGRESS__',
                                    help="display progress but without specific numbers")

    if 'limit' in command_details['options']:
        limit_options = command_parser.add_argument_group(description='limit command to specific folder')
        limit_options.add_argument('--limit',
                                    required=False,
                                    nargs='+',
                                    metavar='limit-command-to',
                                    dest='__LIMIT_COMMAND_TO__',
                                    help="list of command to limit the action to")

    if 'parallel' in command_details['options']:
        parallel_option = command_parser.add_argument_group(description='parallel execution')
        parallel_option.add_argument('--parallel', '-p',
                                    required=False,
                                    default=False,
                                    action='store_true',
                                    dest='__RUN_COMMAND_LIST_IN_PARALLEL__',
                                    help="run the command-list in parallel")

    # optional --db
    if 'db' in command_details['options']:
        db_options = command_parser.add_argument_group(description='database path:')
        db_options.add_argument('--db', '-d',
                                    required=False,
                                    nargs=1,
                                    metavar='path-to-db-file',
                                    dest='__MAIN_DB_FILE__',
                                    help="database file")

    if 'rev' in command_details['options']:
        rev_options = command_parser.add_argument_group(description='revision:')
        rev_options.add_argument('--rev',
                                required=True,
                                nargs=1,
                                metavar='revision',
                                dest='TARGET_REPO_REV',
                                help="revision to create work on")

    # the following option groups each belong only to a single command
    if 'read-yaml' == in_command:#__SILENT__
        read_yaml_options = command_parser.add_argument_group(description=in_command+' arguments:')
        read_yaml_options.add_argument('--silent',
                            required=False,
                            default=False,
                            action='store_true',
                            dest='__SILENT__',
                            help="minimal output")

    elif 'activate-repo-rev' == in_command:
        up_repo_rev_options = command_parser.add_argument_group(description=in_command+' arguments:')
        up_repo_rev_options.add_argument('--just-with-number', '-j',
                            required=False,
                            nargs=1,
                            metavar='just-with-number',
                            dest='__JUST_WITH_NUMBER__',
                            help="up load just the repo-rev file that ends with a specific number, not the general one")

    elif 'unwtar' == in_command:
        unwtar_options = command_parser.add_argument_group(description=in_command+' arguments:')
        unwtar_options.add_argument('--no-artifacts',
                                required=False,
                                default=False,
                                action='store_true',
                                dest='__NO_WTAR_ARTIFACTS__',
                                help="remove all .wtar files and .done files")
    elif in_command in ('up2s3',):
        which_revision_options = command_parser.add_argument_group(description=in_command+' arguments:')
        which_revision_options.add_argument('--revision',
                                required=False,
                                nargs=1,
                                default=False,
                                dest='which_revision',
                                help="all==work on all revisions even if above repo-rev, num=work on specific revision")

    elif 'ls' == in_command:
        ls_options = command_parser.add_argument_group(description='output_format arguments:')
        ls_options.add_argument('--output-format',
                                    required=False,
                                    nargs=1,
                                    dest='LS_FORMAT',
                                    help="specify output format")
    elif 'fail' == in_command:
        fail_options = command_parser.add_argument_group(description=in_command+' arguments:')
        fail_options.add_argument('--exit-code',
                                required=False,
                                nargs=1,
                                metavar='exit-code-to-return',
                                dest='__FAIL_EXIT_CODE__',
                                help="exit code to return")
        fail_options.add_argument('--sleep',
                                required=False,
                                nargs=1,
                                metavar='time-to-sleep',
                                dest='__FAIL_SLEEP_TIME__',
                                help="time to sleep")
    elif 'report-versions' == in_command:
        report_versions_options = command_parser.add_argument_group(description=in_command+' arguments:')
        report_versions_options.add_argument('--only-installed',
                                required=False,
                                default=False,
                                action='store_true',
                                dest='__REPORT_ONLY_INSTALLED__',
                                help="report only installed products")

    elif 'help' == in_command:
        help_options = command_parser.add_argument_group(description='help subject:')
        help_options.add_argument('subject', nargs='?')

    elif 'run-process' == in_command:
        run_process_options  = command_parser.add_argument_group(description='run-process:')
        run_process_options.add_argument('--abort-file',
                            required=False,
                            default=None,
                            nargs=1,
                            metavar='abort_file',
                            dest='ABORT_FILE',
                            help="run a process with optional abort file")
        run_process_options.add_argument('--shell',
                            required=False,
                            default=False,
                            action='store_true',
                            dest='SHELL',
                            help="run a process in shell")
        run_process_options.add_argument(dest='RUN_PROCESS_ARGUMENTS',
                            nargs='...',
                            )

    general_options = command_parser.add_argument_group(description='general:')
    general_options.add_argument('--define',
                            required=False,
                            default=False,
                            nargs=1,
                            metavar='define',
                            dest='define',
                            help="define variable(s) format: X=y,A=b")
    general_options.add_argument('--no-stdout',
                            required=False,
                            action='store_const',
                            metavar='no_stdout',
                            const='__NO_STDOUT__',
                            help="do not output to stdout")
    general_options.add_argument('--no-system-log',
                            required=False,
                            action='store_const',
                            metavar='no_system_log',
                            const='__NO_SYSLOG__',
                            help="do not output to system log")
    general_options.add_argument('--log',
                            required=False,
                            nargs='+',
                            metavar='log_file',
                            dest='__LOG_FILE__',
                            help="log to file(s)")

    return parser, command_names


def read_command_line_options(name_space_obj, arg_list=None):
    """ parse command line options """

    command_name = arg_list[0] if arg_list else None
    parser, command_names = prepare_args_parser(command_name)
    if parser:
        # Command line options were given or auto run file was found
        parser.parse_args(arg_list, namespace=name_space_obj)
    else:
        # No command line options were given
        name_space_obj.mode = "interactive"
    return command_names
