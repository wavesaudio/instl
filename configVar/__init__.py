
from .configVarStack import config_vars
from .configVarStack import private_config_vars
from .configVarYamlReader import ConfigVarYamlReader, eval_conditional, smart_resolve_yaml
from .accessors import current_os, current_os_names, is_current_os, main_input_file_path
var_stack = config_vars  # for backward compatibility of scripts executed with "exec" command
