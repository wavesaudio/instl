import argparse


class CommandLineOptions(object):
    """ namespace object to give to parse_args
        holds command line options
    """
    def __init__(self):
        self.mode = None
        self.command = None
        self.input_file = None
        self.output_file = None
        self.run = False
        self.state_file = None
        self.props_file = None
        self.filter_in = None
        self.target_repo_rev = None
        self.base_repo_rev = None
        self.config_file = None
        self.staging_folder = None
        self.svn_folder = None
        self.sh1_checksum = None
        self.rsa_signature = None
        self.start_progress = None
        self.total_progress = None
        self.no_numbers_progress = None
        self.just_with_number = None
        self.limit_command_to = None
        self.target_path = None
        self.shortcut_path = None
        self.no_wtar_artifacts = None
        self.credentials = None
        self.base_url = None
        self.file_sizes_file = None
        self.which_revision = None
        self.define = None
        self.dock_item_path = None
        self.dock_item_label = None
        self.remove_from_dock = None
        self.restart_the_dock = None
        self.fail_exit_code = None
        self.set_run_as_admin = None
        self.output_format = None
        self.only_installed = None
        self.ls_format = None
        self.parallel = None
        self.db_file = None

    def __str__(self):
        return "\n".join([''.join((n, ": ", str(v))) for n, v in sorted(vars(self).items())])


def prepare_args_parser(in_command):
    """
    Prepare the parser for command line arguments
    """

    mode_codes = {'ct': 'client', 'an': 'admin', 'ds': 'do_something', 'gi': 'gui', 'di': 'doit'}
    commands_details = {
        'check-checksum':       {'mode': 'ds', 'options': ('in', 'prog',), 'help':  'check checksum for a list of files from info_map file'},
        'check-instl-folder-integrity': {'mode': 'an', 'options': ('in',), 'help': 'check that index and info_maps have correct checksums, and other attributes'},
        'check-sig':            {'mode': 'an', 'options': ('in', 'conf',), 'help':  'check sha1 checksum and/or rsa signature for a file'},
        'checksum':             {'mode': 'ds', 'options': ('in',), 'help':  'calculate checksum for a file or folder'},
        'command-list':         {'mode': 'ds', 'options': ('conf', 'prog', 'parallel'), 'help': 'do a list of commands from a file'},
        'copy':                 {'mode': 'ct', 'options': ('in', 'out', 'run', 'cred'), 'help':  'copy files to target paths'},
        'create-folders':       {'mode': 'ds', 'options': ('in',  'prog',), 'help':  'create folders from info_map file'},
        'create-infomap':       {'mode': 'an', 'options': ('conf', 'out', 'run'), 'help': 'create infomap file for repository'},
        'create-links':         {'mode': 'an', 'options': ('out', 'run', 'conf',), 'help':  'create links from the base SVN checkout folder for a specific version'},
        'create-repo-rev-file': {'mode': 'an', 'options': ('conf',), 'help':  'create repo rev file for a specific revision'},
        'create-rsa-keys':      {'mode': 'an', 'options': ('conf',), 'help':  'create private and public keys'},
        'depend':               {'mode': 'an', 'options': ('in', 'out',), 'help':  'output a dependencies map for an index file'},
        'doit':                 {'mode': 'di', 'options': ('in', 'out', 'run'), 'help':  'Do something'},
        'exec':                 {'mode': 'ds', 'options': ('in', 'out', 'conf_opt'), 'help':  'Execute a python scrip'},
        'fail':                 {'mode': 'ds', 'options': (), 'help': "fail and return exit code"},
        'file-sizes':           {'mode': 'an', 'options': ('in', 'out'), 'help':  'Create a list of files and their sizes'},
        'filter-infomap':        {'mode': 'an', 'options': ('in',), 'help':  'filter infomap.txt to sub files according to index.yaml'},
        'fix-perm':             {'mode': 'an', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'Fix Mac OS permissions'},
        'fix-props':            {'mode': 'an', 'options': ('out', 'run', 'conf'), 'help':  'create svn commands to remove redundant properties such as executable bit from files that should not be marked executable'},
        'fix-symlinks':         {'mode': 'an', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'replace symlinks with .symlinks files'},
        'gui':                  {'mode': 'gi', 'options': (), 'help':  'graphical user interface'},
        'help':                 {'mode': 'ds', 'options': (), 'help':  'help'},
        'ls':                   {'mode': 'ds', 'options': ('in', 'out', 'limit'), 'help':  'create a directory listing'},
        'mac-dock':             {'mode': 'ds', 'options': (), 'help': "add or remove to Mac OS's Dock"},
        'make-sig':             {'mode': 'an', 'options': ('in', 'conf',), 'help':  'create sha1 checksum and rsa signature for a file'},
        'parallel-run':         {'mode': 'ds', 'options': ('in', ), 'help':  'Run processes in parallel'},
        'read-info-map':        {'mode': 'an', 'options': ('in+', 'db'), 'help':  "reads an info-map file to verify it's contents"},
        'read-yaml':            {'mode': 'an', 'options': ('in', 'out', 'db'), 'help':  "reads a yaml file to verify it's contents"},
        'remove-empty-folders': {'mode': 'ds', 'options': ('in', ), 'help':  'remove folders is they are empty'},
        'remove':               {'mode': 'ct', 'options': ('in', 'out', 'run',), 'help':  'remove items installed by copy'},
        'report-versions':      {'mode': 'ct', 'options': ('in', 'out', 'output_format', 'only_installed'), 'help': 'report what is installed and what needs update'},
        'resolve':              {'mode': 'ds', 'options': ('in', 'out', 'conf'), 'help':  'read --in file resolve $() style variables and write result to --out, definitions are given in --config-file'},
        'set-exec':             {'mode': 'ds', 'options': ('in', 'prog',), 'help':  'set executable bit for appropriate files'},
        'stage2svn':            {'mode': 'an', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'add/remove files in staging to svn sync repository'},
        'svn2stage':            {'mode': 'an', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'svn sync repository and copy to staging folder'},
        'sync':                 {'mode': 'ct', 'options': ('in', 'out', 'run', 'cred'), 'help':  'sync files to be installed from server to local disk'},
        'synccopy':             {'mode': 'ct', 'options': ('in', 'out', 'run', 'cred'), 'help':  'sync files to be installed from server to  local disk and copy files to target paths'},
        'test-import':          {'mode': 'ds', 'options': (), 'help':  'test the import of required modules'},
        'trans':                {'mode': 'an', 'options': ('in', 'out',), 'help':  'translate svn map files from one format to another'},
        'translate_url':        {'mode': 'ds', 'options': ('in',  'cred'), 'help':  'translate a url to be compatible with current connection'},
        'unwtar':               {'mode': 'ds', 'options': ('in_opt', 'prog', 'out'), 'help':  'uncompress .wtar files in current (or in the --out) folder'},
        'up-repo-rev':          {'mode': 'an', 'options': ('out', 'run', 'conf',), 'help':  'upload repository revision file to admin folder'},
        'up2s3':                {'mode': 'an', 'options': ('out', 'run', 'conf',), 'help':  'upload installation sources to S3'},
        'verify-index':         {'mode': 'an', 'options': ('in', 'cred'), 'help':  'Verify that index and info map are compatible'},
        'verify-repo':          {'mode': 'an', 'options': ('conf',), 'help':  'Verify a local repository against its index'},
        'version':              {'mode': 'ds', 'options': (), 'help':  'display instl version'},
        'win-shortcut':         {'mode': 'ds', 'options': (), 'help':  'create a Windows shortcut'},
        'wtar-staging-folder':  {'mode': 'an', 'options': ('out', 'run', 'conf', 'limit'), 'help':  'create .wtar files inside staging folder'},
        'wtar':                 {'mode': 'ds', 'options': ('in', 'out'), 'help':  'create .wtar files from specified files and folders'},
        'wzip':                 {'mode': 'ds', 'options': ('in', 'out'), 'help':  'create .wzip file from specified file'},
        'uninstall':            {'mode': 'ct', 'options': ('in', 'out', 'run',), 'help':  'uninstall previously copied files, considering dependencies'},
    }

    command_names = sorted(commands_details.keys())

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

    parser = argparse.ArgumentParser(description='instl: cross platform svn based installer',
                    prefix_chars='-+',
                    fromfile_prefix_chars='@',
                    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    argparse.ArgumentParser.convert_arg_line_to_args = decent_convert_arg_line_to_args

    subparsers = parser.add_subparsers(dest='command', help='sub-command help')

    command_details = commands_details[in_command]
    command_parser = subparsers.add_parser(in_command, help=command_details['help'])
    command_parser.set_defaults(mode=mode_codes[command_details['mode']])

    # optional --in
    if 'in_opt' in command_details['options']:
        input_options = command_parser.add_argument_group(description='input arguments:')
        input_options.add_argument('--in', '-i',
                                    required=False,
                                    nargs=1,
                                    metavar='path-to-input-file',
                                    dest='input_file',
                                    help="file to act upon")

    # required --in
    if 'in' in command_details['options']:
        input_options = command_parser.add_argument_group(description='input arguments:')
        input_options.add_argument('--in', '-i',
                                    required=True,
                                    nargs=1,
                                    metavar='path-to-input-folder',
                                    dest='input_file',
                                    help="file or folder to act upon")

    # required multi --in
    if 'in+' in command_details['options']:
        input_options = command_parser.add_argument_group(description='input arguments:')
        input_options.add_argument('--in', '-i',
                                    required=True,
                                    nargs='+',
                                    metavar='path-to-input-folder',
                                    dest='input_file',
                                    help="files or folders to act upon")

    # optional --out
    if 'out' in command_details['options']:
        output_options = command_parser.add_argument_group(description='output arguments:')
        output_options.add_argument('--out', '-o',
                                    required=False,
                                    nargs=1,
                                    metavar='path-to-output-file',
                                    dest='output_file',
                                    help="output file")

    if 'run' in command_details['options']:
        run_option = command_parser.add_argument_group(description='run arguments:')
        run_option.add_argument('--run', '-r',
                                    required=False,
                                    default=False,
                                    action='store_true',
                                    dest='run',
                                    help="run the installation instructions script")

    if 'output_format' in command_details['options']:
        output_format_option = command_parser.add_argument_group(description='output_format arguments:')
        output_format_option.add_argument('--output-format',
                                    required=False,
                                    nargs=1,
                                    dest='output_format',
                                    help="specify output format")

    if 'cred' in command_details['options']:
        credentials_option = command_parser.add_argument_group(description='credentials:')
        credentials_option.add_argument('--credentials',
                                    required=False,
                                    nargs=1,
                                    metavar='credentials',
                                    dest='credentials',
                                    help="credentials to file server")

    if ('conf' in command_details['options']) or ('conf_opt' in command_details['options']):
        config_file_options = command_parser.add_argument_group(description='admin arguments:')
        is_required = 'conf' in command_details['options']
        config_file_options.add_argument('--config-file', '-s',
                                    required=is_required,
                                    nargs=1,
                                    metavar='path-to-config-file',
                                    dest='config_file',
                                    help="path to config-file")

    if 'prog' in command_details['options']:
        progress_options = command_parser.add_argument_group(description='dynamic progress report')
        progress_options.add_argument('--start-progress',
                                    required=False,
                                    nargs=1,
                                    metavar='start-progress-number',
                                    dest='start_progress',
                                    help="num progress items to begin with")
        progress_options.add_argument('--total-progress',
                                    required=False,
                                    nargs=1,
                                    metavar='total-progress-number',
                                    dest='total_progress',
                                    help="num total progress items")
        progress_options.add_argument('--no-numbers-progress',
                                    required=False,
                                    default=False,
                                    action='store_true',
                                    dest='no_numbers_progress',
                                    help="display progress but without specific numbers")

    if 'limit' in command_details['options']:
        limit_options = command_parser.add_argument_group(description='limit command to specific folder')
        limit_options.add_argument('--limit',
                                    required=False,
                                    nargs='+',
                                    metavar='limit-command-to',
                                    dest='limit_command_to',
                                    help="list of command to limit the action to")

    if 'parallel' in command_details['options']:
        parallel_option = command_parser.add_argument_group(description='parallel execution')
        parallel_option.add_argument('--parallel', '-p',
                                    required=False,
                                    default=False,
                                    action='store_true',
                                    dest='',
                                    help="run the command-list in parallel")

    # optional --db
    if 'db' in command_details['options']:
        db_options = command_parser.add_argument_group(description='database path:')
        db_options.add_argument('--db', '-d',
                                    required=False,
                                    nargs=1,
                                    metavar='path-to-db-file',
                                    dest='db_file',
                                    help="database file")

    # the following option groups each belong only to a single command
    if 'trans' == in_command:
        trans_options = command_parser.add_argument_group(description=in_command+' arguments:')
        trans_options.add_argument('--props', '-p',
                                required=False,
                                nargs=1,
                                metavar='path-to-props-file',
                                dest='props_file',
                                help="file to read svn properties from")

        trans_options.add_argument('--base-repo-rev',
                                required=False,
                                nargs=1,
                                metavar='base-repo-rev',
                                dest='base_repo_rev',
                                help="minimal version, all version below will be changed to base-repo-rev")
        trans_options.add_argument('--base-url',
                                    required=False,
                                    nargs=1,
                                    metavar='base-url',
                                    dest='base_url',
                                    help="")
        trans_options.add_argument('--file-sizes',
                                    required=False,
                                    nargs=1,
                                    metavar='file-sizes-file',
                                    dest='file_sizes_file',
                                    help="")

    elif 'check-sig' == in_command:
        check_sig_options = command_parser.add_argument_group(description=in_command+' arguments:')
        check_sig_options.add_argument('--sha1',
                                required=False,
                                nargs=1,
                                metavar='sh1-checksum',
                                dest='sh1_checksum',
                                help="expected sha1 checksum")
        check_sig_options.add_argument('--rsa',
                                required=False,
                                nargs=1,
                                metavar='rsa-sig',
                                dest='rsa_signature',
                                help="expected rsa SHA-512 signature")

    elif 'create-repo-rev-file' == in_command:
        create_repo_rev_file_options = command_parser.add_argument_group(description=in_command+' arguments:')
        create_repo_rev_file_options.add_argument('--rev',
                                required=False,
                                nargs=1,
                                metavar='revision-to-create-file-for',
                                dest='target_repo_rev',
                                help="revision to create file for")

    elif 'up-repo-rev' == in_command:
        up_repo_rev_options = command_parser.add_argument_group(description=in_command+' arguments:')
        up_repo_rev_options.add_argument('--just-with-number', '-j',
                            required=False,
                            nargs=1,
                            metavar='just-with-number',
                            dest='just_with_number',
                            help="up load just the repo-rev file that ends with a specific number, not the general one")

    elif 'win-shortcut' == in_command:
        short_cut_options = command_parser.add_argument_group(description=in_command+' arguments:')
        short_cut_options.add_argument('--shortcut',
                            required=True,
                            nargs=1,
                            metavar='shortcut',
                            dest='shortcut_path',
                            help="path to the shortcut itself")
        short_cut_options.add_argument('--target',
                                       required=True,
                                       nargs=1,
                                       metavar='target',
                                       dest='target_path',
                                       help="path to the item being shortcut")
        short_cut_options.add_argument('--run-as-admin',
                                       required=False,
                                       default=False,
                                       action='store_true',
                                       dest='set_run_as_admin',
                                       help="set run as admin flag")

    elif 'mac-dock' == in_command:
        mac_dock_options = command_parser.add_argument_group(description=in_command+' arguments:')
        mac_dock_options.add_argument('--path',
                                required=False,
                                nargs=1,
                                metavar='dock-item-path',
                                dest='dock_item_path',
                                help="path to dock item")
        mac_dock_options.add_argument('--label',
                                required=False,
                                nargs=1,
                                metavar='dock-item-label',
                                dest='dock_item_label',
                                help="label for dock item")
        mac_dock_options.add_argument('--remove',
                                required=False,
                                default=False,
                                action='store_true',
                                dest='remove_from_dock',
                                help="remove from dock")
        mac_dock_options.add_argument('--restart',
                                required=False,
                                default=False,
                                action='store_true',
                                dest='restart_the_dock',
                                help="restart the dock")

    elif 'unwtar' == in_command:
        unwtar_options = command_parser.add_argument_group(description=in_command+' arguments:')
        unwtar_options.add_argument('--no-artifacts',
                                required=False,
                                default=False,
                                action='store_true',
                                dest='no_wtar_artifacts',
                                help="remove all .wtar files and .done files")
    elif in_command in ('create-links', 'up2s3'):
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
                                    dest='ls_format',
                                    help="specify output format")
    elif 'fail' == in_command:
        mac_dock_options = command_parser.add_argument_group(description=in_command+' arguments:')
        mac_dock_options.add_argument('--exit-code',
                                required=False,
                                nargs=1,
                                metavar='exit-code-to-return',
                                dest='fail_exit_code',
                                help="exit code to return")
    elif 'report-versions' == in_command:
        report_versions_options = command_parser.add_argument_group(description=in_command+' arguments:')
        report_versions_options.add_argument('--only-installed',
                                required=False,
                                default=False,
                                action='store_true',
                                dest='only_installed',
                                help="report only installed products")

    elif 'help' == in_command:
        help_options = command_parser.add_argument_group(description='help subject:')
        help_options.add_argument('subject', nargs='?')

    define_options = command_parser.add_argument_group(description='define:')
    define_options.add_argument('--define',
                            required=False,
                            default=False,
                            nargs=1,
                            metavar='define',
                            dest='define',
                            help="define variable(s) format: X=y,A=b")

    return parser, command_names


def read_command_line_options(name_space_obj, arg_list=None):
    """ parse command line options """

    command_name = arg_list[0] if arg_list else None
    parser, command_names = prepare_args_parser(command_name)
    if parser:
        # Command line options were given or auto run file was found
        options = parser.parse_args(arg_list, namespace=name_space_obj)
    else:
        # No command line options were given
        name_space_obj.mode = "interactive"
    return command_names
