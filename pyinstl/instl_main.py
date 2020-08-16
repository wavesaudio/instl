import sys
import os
import string
import appdirs
import tempfile
import random
import sqlite3
import datetime
import logging
import platform
from pathlib import Path
from functools import lru_cache
import json
from configVar import config_vars
from pybatch import PythonBatchRuntime
from pyinstl.cmdOptions import CommandLineOptions, read_command_line_options

from pyinstl.instlException import InstlException
import utils

#utils.set_max_open_files(2048)

from utils.log_utils import config_logger

log = logging.getLogger()
log.setLevel(logging.DEBUG)


current_os_names = utils.get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]


@lru_cache(maxsize=None)
def get_path_to_instl_app():
    """
    @return: returns the path to this
    """
    application_path = None
    if getattr(sys, 'frozen', False):
        application_path = Path(sys.executable).resolve()
    elif __file__:
        application_path = Path(__file__).resolve().parent.parent.joinpath('instl')
    return application_path


@lru_cache(maxsize=None)
def get_instl_launch_command():
    """
    @return: returns the path to this
    """
    launch_command = None
    exec_path = get_path_to_instl_app()
    if getattr(sys, 'frozen', False):
        launch_command = utils.quoteme_double(os.fspath(exec_path))
    elif __file__:
        if os_family_name == "Win":
            launch_command = " ".join((utils.quoteme_double(sys.executable), utils.quoteme_double(os.fspath(exec_path))))
        else:
            launch_command = utils.quoteme_double(os.fspath(exec_path))
    return launch_command


@lru_cache(maxsize=None)
def get_data_folder():
    """ get the path to where we can find data folders such as defaults or help
        data folder should be the instl folder where either instl (in case running directly form python)
        or instl.exe (in case running frozen). In both cases this is the parent folder of instl.
    """
    application_path = get_path_to_instl_app()
    data_folder = Path(application_path).parent
    return data_folder


class InvocationReporter(PythonBatchRuntime):

    def __init__(self, argv, **kwargs) -> None:
        super().__init__(name="InvocationReporter", **kwargs) #TODO: ask Shai about the name arg
        self.start_time = datetime.datetime.now()
        self.random_invocation_name = ''.join(random.choice(string.ascii_lowercase) for i in range(16))
        self.argv = argv.copy()  # argument argv is usually sys.argv, which might change with recursive process calls

    def enter_self(self) -> None:
        try:
            vendor_name = os.environ.setdefault("VENDOR_NAME", "Waves Audio")
            app_name = os.environ.setdefault("APPLICATION_NAME", "Waves Central")
            config_logger(argv=self.argv, config_vars=config_vars)
            log.debug(f"===== {self.random_invocation_name} =====")
            log.debug(f"Start: {self.start_time}")
            log.debug(f"instl: {self.argv[0]}")
            log.debug(f'argv: {" ".join(self.argv[1:])}')
        except Exception as e:
            log.warning(f'instl log file report start failed - {e}')

    def exit_self(self, exit_return) -> None:
        self.doing = self.doing if self.doing else utils.get_latest_action_from_stack()
        try:
            end_time = datetime.datetime.now()
            log.debug(f"Run time: {self.command_time_sec}")
            log.debug(f"End: {end_time}")
            log.debug(f"===== {self.random_invocation_name} =====")
        except Exception as e:
            log.warning(f'InvocationReporter.__exit__ internal exception - {e}')


def instl_own_main(argv):
    """ Main instl entry point. Reads command line options and decides if to go into interactive or client mode.
    """
    with InvocationReporter(argv):

        argv = argv.copy()  # argument argv is usually sys.argv, which might change with recursive process calls
        options = CommandLineOptions()
        command_names = read_command_line_options(options, argv[1:])
        initial_vars = {"__INSTL_EXE_PATH__": get_path_to_instl_app(),
                        "__CURR_WORKING_DIR__": utils.safe_getcwd(),  # the working directory when instl was launched
                        "__INSTL_LAUNCH_COMMAND__": get_instl_launch_command(),
                        "__INSTL_DATA_FOLDER__": get_data_folder(),
                        "__INSTL_DEFAULTS_FOLDER__": "$(__INSTL_DATA_FOLDER__)/defaults",
                        "__INSTL_COMPILED__": str(getattr(sys, 'frozen', False)),
                        "__PYTHON_VERSION__": sys.version_info,
                        "__PLATFORM_NODE__": platform.node(),
                        "__PYSQLITE3_VERSION__": sqlite3.version,
                        "__SQLITE_VERSION__": sqlite3.sqlite_version,
                        "__COMMAND_NAMES__": command_names,
                        "__CURRENT_OS__": os_family_name,
                        "__CURRENT_OS_SECOND_NAME__": os_second_name,
                        "__CURRENT_OS_NAMES__": current_os_names,
                        "__CURRENT_OS_DESCRIPTION__": utils.get_os_description(),
                        "__SITE_DATA_DIR__": os.path.normpath(appdirs.site_data_dir()),
                        "__SITE_CONFIG_DIR__": os.path.normpath(appdirs.site_config_dir()),
                        "__USER_DATA_DIR__": os.path.normpath(appdirs.user_data_dir()),
                        "__USER_CONFIG_DIR__": os.path.normpath(appdirs.user_config_dir()),
                        "__USER_HOME_DIR__": os.path.normpath(os.path.expanduser("~")),
                        "__USER_DESKTOP_DIR__": os.path.normpath("$(__USER_HOME_DIR__)/Desktop"),
                        "__USER_TEMP_DIR__": os.path.normpath(os.path.join(tempfile.gettempdir(), "$(SYNC_BASE_URL_MAIN_ITEM)/$(REPO_NAME)")),
                        "__SYSTEM_LOG_FILE_PATH__": utils.get_system_log_file_path(),
                        "__INVOCATION_RANDOM_ID__": ''.join(random.choice(string.ascii_lowercase) for _ in range(16)),
                        "__SUDO_USER__": os.environ.get("SUDO_USER", "no set"),
                        # VENDOR_NAME, APPLICATION_NAME need to be set so logging can be redirected to the correct folder
                        "VENDOR_NAME": os.environ.get("VENDOR_NAME", "Waves Audio"),
                        "APPLICATION_NAME": os.environ.get("APPLICATION_NAME", "Waves Central"),
                        "__ARGV__": argv,
                        "ACTING_UID": -1,
                        "ACTING_GID": -1,
                        }

        if os_family_name != "Win":
            initial_vars.update(
                        {"__USER_ID__": str(os.getuid()),
                         "__GROUP_ID__": str(os.getgid())})
        else:
            initial_vars.update(
                        {"__USER_ID__": -1,
                         "__GROUP_ID__": -1,
                         "__WHO_LOCKS_FILE_DLL_PATH__": "$(__INSTL_DATA_FOLDER__)/who_locks_file.dll"})

        instance = None
        if options.__MAIN_COMMAND__ == "command-list":
            from pyinstl.instlCommandList import run_commands_from_file
            run_commands_from_file(initial_vars, options)
        elif options.mode == "client": #shai, maybe add a log here?  before all imports
            log.debug("begin, importing instl object") #added by oren
            from pyinstl.instlClient import InstlClientFactory
            instance = InstlClientFactory(initial_vars, options.__MAIN_COMMAND__)
            instance.progress("welcome to instl", instance.get_version_str(short=True), options.__MAIN_COMMAND__)
            instance.init_from_cmd_line_options(options)
            instance.do_command()# after all preprartion is done, we execute the command itself
        elif options.mode == "doit":
            from pyinstl.instlDoIt import InstlDoIt
            instance = InstlDoIt(initial_vars)
            instance.progress("welcome to instl", instance.get_version_str(short=True), options.__MAIN_COMMAND__)
            instance.init_from_cmd_line_options(options)
            instance.do_command()
        elif options.mode == "do_something":
            from pyinstl.instlMisc import InstlMisc
            instance = InstlMisc(initial_vars, options.__MAIN_COMMAND__)
            instance.progress("welcome to instl", instance.get_version_str(short=True), options.__MAIN_COMMAND__)
            instance.init_from_cmd_line_options(options)
            instance.do_command()
        elif not getattr(sys, 'frozen', False):  # these modes are not available in compiled instl to avoid issues such as import errors for users
            if options.mode == "admin":
                if os_family_name not in ("Linux", "Mac"):
                    raise EnvironmentError("instl admin commands can only run under Mac or Linux")
                from pyinstl.instlAdmin import InstlAdmin
                instance = InstlAdmin(initial_vars)
                instance.progress("welcome to instl", instance.get_version_str(short=True), options.__MAIN_COMMAND__)
                instance.init_from_cmd_line_options(options)
                instance.do_command()
            elif options.mode == "interactive":
                from pyinstl.instlClient import InstlClient
                client = InstlClient(initial_vars)
                client.init_from_cmd_line_options(options)
                from pyinstl.instlAdmin import InstlAdmin
                from pyinstl.instlInstanceBase_interactive import go_interactive
                admin = InstlAdmin(initial_vars)
                admin.init_from_cmd_line_options(options)
                go_interactive(client, admin)
            elif options.mode == "gui":
                from pyinstl.instlGui import InstlGui
                instance = InstlGui(initial_vars)
                instance.init_from_cmd_line_options(options)
                instance.do_command()

        # make sure instance's dispose functions are called
        if instance is not None:
            instance.close()
