
from .configVarStack import config_vars
from .configVarStack import private_config_vars
from .configVarYamlReader import ConfigVarYamlReader, eval_conditional, smart_resolve_yaml
from .accessors import (current_os, current_os_names, is_current_os,
                        main_input_file_path, main_input_file_str,
                        main_out_file_path, run_batch, repo_rev,
                        target_repo_rev, instl_version, target_os,
                        target_os_names,
                        config_var_str, config_var_bool, config_var_int, config_var_list)
var_stack = config_vars  # for backward compatibility of scripts executed with "exec" command
