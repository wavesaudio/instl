#!/usr/bin/env python2.7
from __future__ import print_function

"""
    Manage list of include search paths, and help find files
    using the search paths.
    To do:  allow adding of non existing paths.
            Reduce file system access (isfile, isdir,...)
"""

import os
import appdirs
import logging

from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *

class SearchPaths(object):
    """
        Manage list of include search paths, and help find files
        using the search paths.
    """
    def __init__(self, search_paths_var):
        # list of paths where to search for #include-ed files
        self.search_paths_var = search_paths_var

    def __len__(self):
        return len(self.search_paths_var)

    def __iter__(self):
        return iter(self.search_paths_var)

    @func_log_wrapper
    def add_search_path(self, a_path):
        """ Add a folder to the list of search paths
        """
        if a_path not in self.search_paths_var:
            self.search_paths_var.append(a_path)
            logging.info("adding %s to search paths",  a_path)

    @func_log_wrapper
    def add_search_path_recursive(self, *paths):
        """ Add folders to the list of search paths
            and also all subfolders """
        pass  # to do...

    @func_log_wrapper
    def find_file_with_search_paths(self, in_file):
        """
        Find the real path to a file.
        If in_file is path to an existing file, it's real full path will be returned.
        Otherwise file will be searched in each of the search paths until found.
        Full path to file is returned, or None if not found.
        If file was found it's folder will be added to the search paths. This might
        look redundant: if a file was found it's folder must be in the list of search paths!
        There are two cases when this will not be the case:
        1. A full path to a file was given. The folder might not be in the search paths.
            In fact, the reason a full path was given is that it's folder would be added.
        2. A partial path was given, such as 'somelib/somelib.h". In which case the path
            up to and including somelib would be added.
        """
        retVal = None
        logging.debug("... find %s", in_file)
        if os.path.isfile(in_file):
            real_file = os.path.realpath(in_file)
            logging.debug("...... is an existing file path returning %s", real_file)
            real_folder, _ = os.path.split(real_file)
            self.add_search_path(real_folder)
            retVal = real_file
        else:
            for try_path in self.search_paths_var:
                logging.debug("...... looking in %s", try_path)
                real_file = os.path.join(try_path, in_file)
                if os.path.isfile(real_file):
                    real_file = os.path.realpath(real_file)
                    logging.debug("......... found returning %s", real_file)
                    # in_file might be a relative path so must add the file's
                    # real folder so it's in the list.
                    real_folder, _ = os.path.split(real_file)
                    self.add_search_path(real_folder)
                    retVal = real_file
                    break
        if not retVal:
            logging.info("%s was not found ", in_file)
        return retVal

    @func_log_wrapper
    def get_machine_config_file_path(self, in_app_name):
        retVal = os.path.join(appdirs.site_data_dir(in_app_name))
        logging.debug("... %s", retVal)
        return retVal

    @func_log_wrapper
    def get_user_config_file_path(self, in_app_name):
        retVal = os.path.join(appdirs.user_data_dir(in_app_name))
        logging.debug("... %s", retVal)
        return retVal


if __name__ == "__main__":
    SearchPathsObj = SearchPaths("var")
    print (SearchPathsObj.get_machine_config_file_path("myke"))
    print (SearchPathsObj.get_user_config_file_path("myke"))
