#!/usr/bin/env python2.7
from __future__ import print_function
import abc
import logging
import datetime
import yaml

import appdirs

import pyinstl.log_utils
from pyinstl.log_utils import func_log_wrapper
from configVarList import ConfigVarList, value_ref_re
from aYaml import augmentedYaml
from pyinstl.utils import *
from pyinstl.searchPaths import SearchPaths
from instlException import InstlException
from platformSpecificHelper_Base import PlatformSpecificHelperFactory
from batchAccumulator import BatchAccumulator

current_os_names = get_current_os_names()
os_family_name = current_os_names[0]
os_second_name = current_os_names[0]
if len(current_os_names) > 1:
    os_second_name = current_os_names[1]

INSTL_VERSION=(0, 5, 0)
this_program_name = "instl"


class InstlInstanceBase(object):
    """ Main object of instl. Keeps the state of variables and install index
        and knows how to create a batch file for installation. InstlInstanceBase
        must be inherited by platform specific implementations, such as InstlInstance_mac
        or InstlInstance_win.
    """
    __metaclass__ = abc.ABCMeta
    @func_log_wrapper
    def __init__(self, initial_vars=None):
        # init objects owned by this class
        self.cvl = ConfigVarList()
        self.platform_helper = PlatformSpecificHelperFactory(os_family_name)
        self.batch_accum = BatchAccumulator(self.cvl)

        self.out_file_realpath = None
        self.init_default_vars(initial_vars)

        # initialize the search paths helper with the current directory and dir where instl is now
        self.search_paths_helper = SearchPaths(self.cvl.get_configVar_obj("__SEARCH_PATHS__"))
        self.search_paths_helper.add_search_path(os.getcwd())
        self.search_paths_helper.add_search_path(os.path.dirname(os.path.realpath(sys.argv[0])))
        self.search_paths_helper.add_search_path(self.cvl.get_str("__INSTL_EXE_PATH__"))

        self.guid_re = re.compile("""
                        [a-f0-9]{8}
                        (-[a-f0-9]{4}){3}
                        -[a-f0-9]{12}
                        $
                        """, re.VERBOSE)

    @func_log_wrapper
    def init_default_vars(self, initial_vars):
        if initial_vars:
            var_description = "from initial_vars"
            for var, value in initial_vars.iteritems():
                self.cvl.add_const_config_variable(var, var_description, value)

        var_description = "from InstlInstanceBase.init_default_vars"
        self.cvl.add_const_config_variable("CURRENT_OS", var_description, os_family_name)
        self.cvl.add_const_config_variable("CURRENT_OS_SECOND_NAME", var_description, os_second_name)
        self.cvl.add_const_config_variable("CURRENT_OS_NAMES", var_description, *current_os_names)
        self.cvl.set_variable("TARGET_OS", var_description).append(os_family_name)
        self.cvl.set_variable("TARGET_OS_NAMES", var_description).extend(current_os_names)
        self.cvl.add_const_config_variable("__INSTL_VERSION__", var_description, *INSTL_VERSION)

        log_file = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=False)
        self.cvl.set_variable("LOG_FILE", var_description).append(log_file)
        debug_log_file = pyinstl.log_utils.get_log_file_path(this_program_name, this_program_name, debug=True)
        self.cvl.set_variable("LOG_FILE_DEBUG", var_description).extend( (debug_log_file, logging.getLevelName(pyinstl.log_utils.debug_logging_level), pyinstl.log_utils.debug_logging_started) )
        for identifier in self.cvl:
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))


    @func_log_wrapper
    def init_from_cmd_line_options(self, cmd_line_options_obj):
        """ turn command line options into variables """
        if cmd_line_options_obj.input_file:
            self.cvl.add_const_config_variable("__MAIN_INPUT_FILE__", "from command line options", cmd_line_options_obj.input_file[0])
        if cmd_line_options_obj.output_file:
            self.cvl.add_const_config_variable("__MAIN_OUT_FILE__", "from command line options", cmd_line_options_obj.output_file[0])
        if cmd_line_options_obj.state_file:
            self.cvl.add_const_config_variable("__MAIN_STATE_FILE__", "from command line options", cmd_line_options_obj.state_file)
        if cmd_line_options_obj.props_file:
            self.cvl.add_const_config_variable("__PROPS_FILE__", "from command line options", cmd_line_options_obj.props_file[0])
        if cmd_line_options_obj.filter_out:
            self.cvl.add_const_config_variable("__FILTER_OUT_PATHS__", "from command line options", *cmd_line_options_obj.filter_out)
        if cmd_line_options_obj.filter_in:
            self.cvl.add_const_config_variable("__FILTER_IN_VERSION__", "from command line options", cmd_line_options_obj.filter_in[0])
        if cmd_line_options_obj.run:
            self.cvl.add_const_config_variable("__RUN_BATCH_FILE__", "from command line options", "yes")
        if cmd_line_options_obj.command:
            self.cvl.set_variable("__MAIN_COMMAND__", "from command line options").append(cmd_line_options_obj.command)

        if cmd_line_options_obj.svn_url:
            self.cvl.add_const_config_variable("__SVN_URL__", "from command line options", cmd_line_options_obj.svn_url[0])
        if cmd_line_options_obj.root_links_folder:
            root_links_folder = cmd_line_options_obj.root_links_folder[0].rstrip("/\\")
            self.cvl.add_const_config_variable("__ROOT_LINKS_FOLDER__", "from command line options", root_links_folder)
        if cmd_line_options_obj.repo_rev:
            self.cvl.add_const_config_variable("__REPO_REV__", "from command line options", cmd_line_options_obj.repo_rev[0])
        if cmd_line_options_obj.s3_config:
            self.cvl.add_const_config_variable("__S3_CONFIG_FILE__", "from command line options", cmd_line_options_obj.s3_config[0])
        if cmd_line_options_obj.base_rev:
            self.cvl.add_const_config_variable("__BASE_REPO_REV__", "from command line options", cmd_line_options_obj.base_rev[0])
        else:
            self.cvl.add_const_config_variable("__BASE_REPO_REV__", "from command line options", "0")

        for identifier in self.cvl:
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))


    @func_log_wrapper
    def read_yaml_file(self, file_path):
        try:
            logging.info("... Reading input file %s", file_path)
            with open_for_read_file_or_url(file_path, self.search_paths_helper) as file_fd:
                for a_node in yaml.compose_all(file_fd):
                    if a_node.tag == '!define':
                        self.read_defines(a_node)
                    elif a_node.tag == '!index':
                        self.read_index(a_node)
                    else:
                        logging.error("Unknown document tag '%s' while reading file %s; Tag should be one of: !define, !index'", a_node.tag, file_path)
        except InstlException as ie:
            raise # re-raise in case of recursive call to read_file
        except yaml.YAMLError as ye:
            raise InstlException(" ".join( ("YAML error while reading file", "'"+file_path+"':\n", str(ye)) ), ye)
        except IOError as ioe:
            raise InstlException(" ".join(("Failed to read file", "'"+file_path+"'", ":")), ioe)

    internal_identifier_re = re.compile("""
                                        __                  # dunder here
                                        (?P<internal_identifier>\w*)
                                        __                  # dunder there
                                        """, re.VERBOSE)
    @func_log_wrapper
    def read_defines(self, a_node):
        # if document is empty we get a scalar node
        if a_node.isMapping():
            for identifier, contents in a_node:
                logging.debug("... %s: %s", identifier, str(contents))
                if not self.internal_identifier_re.match(identifier): # do not read internal state identifiers
                    self.cvl.set_variable(identifier, str(contents.start_mark)).extend([item.value for item in contents])
                elif identifier == '__include__':
                    for file_name in contents:
                        resolved_file_name = self.cvl.resolve_string(file_name.value)
                        self.read_yaml_file(resolved_file_name)

    @func_log_wrapper
    def create_variables_assignment(self):
        self.batch_accum.set_current_section("assign")
        for identifier in self.cvl:
            if not self.internal_identifier_re.match(identifier) or pyinstl.log_utils.debug_logging_started: # do not write internal state identifiers, unless in debug mode
                self.batch_accum += self.platform_helper.var_assign(identifier,self.cvl.get_str(identifier))

    @func_log_wrapper
    def get_default_sync_dir(self):
        retVal = None
        if os_family_name == "Mac":
            user_cache_dir_param = self.cvl.get_str("COMPANY_NAME")+"/"+this_program_name
            user_cache_dir = appdirs.user_cache_dir(user_cache_dir_param)
        elif os_family_name == "Win":
            user_cache_dir = appdirs.user_cache_dir(this_program_name, self.cvl.get_str("COMPANY_NAME"))
        from_url = main_url_item(self.cvl.get_str("SYNC_BASE_URL"))
        if from_url:
            from_url = from_url.lstrip("/\\")
            from_url = from_url.rstrip("/\\")
            retVal = os.path.join(user_cache_dir, from_url)
        else:
            raise ValueError("'SYNC_BASE_URL' was not properly defined")
        #print("1------------------", user_cache_dir, "-", from_url, "-", retVal)
        return retVal

    @func_log_wrapper
    def init_copy_vars(self):
        var_description = "from InstlInstanceBase.init_copy_vars"
        if "SET_ICON_PATH" in self.cvl:
            setIcon_full_path = self.search_paths_helper.find_file_with_search_paths(self.cvl.get_str("SET_ICON_PATH"))
            self.cvl.set_variable("SET_ICON_PATH", var_description).append(setIcon_full_path)
# check which variables are needed for for offline install....
        if "REL_SRC_PATH" not in self.cvl: #?
            if "SYNC_BASE_URL" not in self.cvl:
                raise ValueError("'SYNC_BASE_URL' was not defined")
            if "BASE_SRC_URL" not in self.cvl:
                self.cvl.set_variable("BASE_SRC_URL", var_description).append("$(SYNC_BASE_URL)/$(TARGET_OS)")
            rel_sources = relative_url(self.cvl.get_str("SYNC_BASE_URL"), self.cvl.get_str("BASE_SRC_URL"))
            self.cvl.set_variable("REL_SRC_PATH", var_description).append(rel_sources)

        self.cvl.set_value_if_var_does_not_exist("LOCAL_SYNC_DIR", self.get_default_sync_dir(), description=var_description)

        if "COPY_TOOL" not in self.cvl:
            from platformSpecificHelper_Base import DefaultCopyToolName
            self.cvl.set_variable("COPY_TOOL", var_description).append(DefaultCopyToolName(self.cvl.get_str("TARGET_OS")))
        for identifier in ("REL_SRC_PATH", "COPY_TOOL"):
            logging.debug("... %s: %s", identifier, self.cvl.get_str(identifier))

    @func_log_wrapper
    def relative_sync_folder_for_source(self, source):
        retVal = None
        if source[1] in ('!dir', '!file'):
            retVal = "/".join(source[0].split("/")[0:-1])
        elif source[1] in ('!dir_cont', '!files'):
            retVal = source[0]
        else:
            raise ValueError("unknown tag for source "+source[0]+": "+source[1])
        return retVal

    @func_log_wrapper
    def write_batch_file(self):
        self.batch_accum.set_current_section('pre')
        self.batch_accum += self.platform_helper.get_install_instructions_prefix()
        self.batch_accum += self.platform_helper.remark(datetime.datetime.today().isoformat())
        self.batch_accum.set_current_section('post')
        self.batch_accum += self.platform_helper.get_install_instructions_postfix()
        lines = self.batch_accum.finalize_list_of_lines()
        lines_after_var_replacement = '\n'.join([value_ref_re.sub(self.platform_helper.var_replacement_pattern, line) for line in lines])

        from utils import write_to_file_or_stdout
        out_file = self.cvl.get_str("__MAIN_OUT_FILE__")
        logging.info("... %s", out_file)
        with write_to_file_or_stdout(out_file) as fd:
            fd.write(lines_after_var_replacement)

        if out_file != "stdout":
            self.out_file_realpath = os.path.realpath(out_file)
            os.chmod(self.out_file_realpath, 0755)

    @func_log_wrapper
    def run_batch_file(self):
        logging.info("running batch file %s", self.out_file_realpath)
        from subprocess import Popen
        p = Popen(self.out_file_realpath)
        stdout, stderr = p.communicate()

    @func_log_wrapper
    def write_program_state(self):
        from utils import write_to_file_or_stdout
        state_file = self.cvl.get_str("__MAIN_STATE_FILE__")
        with write_to_file_or_stdout(state_file) as fd:
            augmentedYaml.writeAsYaml(self, fd)
