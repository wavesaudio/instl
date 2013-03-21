#!/usr/local/bin/python2.7
from __future__ import print_function

""" Manage a list of include search paths, and help find files using the search paths.
    To do: allow adding of non existing paths. Reduce file system access (isfile, isdir,...)
"""

import os
import appdirs
import logging

class SearchPaths(object):
    """ Manage a list of include search paths, and help find files using the search paths.
    """
    def __init__(self, search_paths_var, *initial_paths_list):
        # list of paths where to search for #include-ed files
        self.search_paths_var = search_paths_var
        self.add_search_paths(*initial_paths_list)
        for dir in self.search_paths_var:
            logging.debug("__init__ initial search path: {}".format(dir))

    def __len__(self):
        return len(self.search_paths_var)

    def __iter__(self):
        return iter(self.search_paths_var)

    def add_search_paths(self, *paths):
        """ Add folders to the list of search paths
            for convenience you can add a file and it's folder will be added
        """
        for s_path in paths:
            real_s_path = os.path.realpath(s_path)
            logging.debug("add {}".format(s_path))
            if os.path.isfile(real_s_path):
                real_s_path, _ = os.path.split(real_s_path)
                #print("It a file so real adding is", real_s_path)
            # checking the list first might prevent some redundant file system access by isdir
            logging.debug("... realpath is {}".format(real_s_path))
            if not real_s_path in self.search_paths_var:
                if os.path.isdir(real_s_path):
                    self.search_paths_var.append(real_s_path)
                else:
                    logging.warning("... realpath {} is not a directory".format(real_s_path))

    def add_search_paths_recursive(self, *paths):
        """ Add folders to the list of search paths
            and also all subfolders """
        pass # to do...

    def find_file_with_search_paths(self, in_file):
        """ Find the real path to a file.
            If in_file is path to an existing file, it's real full path will be returned.
            Otherwise file will be searched in each of the search paths until found.
            Full path to file is returned, or None if not found.
            If file was found it's folder will be added to the search paths.
        """
        retVal = None
        logging.debug("find_file_with_search_paths({})".format(in_file))
        if os.path.isfile(in_file):
            real_file = os.path.realpath(in_file)
            logging.debug("... is a full file path returning {}".format(in_file))
            retVal = real_file
        else:
            for s_path in self.search_paths_var:
                logging.debug("looking in {}".format(s_path))
                real_file = os.path.join(s_path, in_file)
                if os.path.isfile(real_file):
                    real_file = os.path.realpath(real_file)
                    logging.debug("... found returning {}".format(real_file))
                    retVal = real_file
                    break
        if retVal:
            self.add_search_paths(real_file)
        return retVal

    def get_machine_config_file_path(self):
        retVal = os.path.join(appdirs.site_data_dir("myke"))
        return retVal

    def get_user_config_file_path(self):
        retVal = os.path.join(appdirs.user_data_dir("myke"))
        return retVal

if __name__ == "__main__":
    SearchPathsObj = SearchPaths("a/b/c", "/a/b/c/d")
    print (SearchPathsObj)
