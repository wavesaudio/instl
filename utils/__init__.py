from .files import *
from .misc_utils import *
from .str_utils import *
from .searchPaths import SearchPaths
from .parallel_run import run_processes_in_parallel, run_process
from .multi_file import MultiFileReader
from .extract_info import extract_binary_info, check_binaries_versions_in_folder, check_binaries_versions_filter_with_ignore_regexes, get_info_from_plugin
from .ls import disk_item_listing
from .log_utils import *
import platform
current_os = platform.system()
if current_os == 'Darwin':
    from .dockutil import dock_util
from .redisClient import RedisClient
from .email import send_email, send_email_from_template_file

if sys.platform in ('darwin', 'linux'):
    def disk_item_listing(the_path, ls_format, root_folder=None):
        from .ls import unix_item_ls, list_of_dicts_describing_disk_items_to_text_lines
        item_ls_dict = unix_item_ls(the_path, ls_format, root_folder)
        item_ls_lines = list_of_dicts_describing_disk_items_to_text_lines([item_ls_dict], ls_format)
        return item_ls_lines[0]
elif sys.platform == 'win32':
    def disk_item_listing(the_path, ls_format, root_folder=None):
        from .ls import win_item_ls, list_of_dicts_describing_disk_items_to_text_lines
        item_ls_dict = win_item_ls(the_path, ls_format, root_folder)
        item_ls_lines = list_of_dicts_describing_disk_items_to_text_lines([item_ls_dict], ls_format)
        return item_ls_lines[0]
