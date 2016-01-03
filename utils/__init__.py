from utils import *
from searchPaths import SearchPaths
from instlException import InstlException, InstlFatalException
from parallel_run import run_processes_in_parallel
import platform
current_os = platform.system()
if current_os == 'Darwin':
    from dockutil import dock_util
