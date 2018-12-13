#!/usr/bin/env python3.6


"""
    Manage list of include search paths, and help find files
    using the search paths.
    To do:  allow adding of non existing paths.
            Reduce file system access (isfile, isdir,...)
"""

import os
from pathlib import Path

# noinspection PyPep8Naming
class SearchPaths(object):
    """
        Manage list of include search paths, and help find files
        using the search paths.
        SearchPaths is getting access to config_vars via parameter to __init__
        instead of using the global singleton. This is to avoid cyclic import issues.
    """
    def __init__(self, config_vars, search_paths_var: str) -> None:
        self.config_vars = config_vars
        self.search_paths_var: str = search_paths_var
        self.config_vars.setdefault(self.search_paths_var, [])  # make sure ConfigVar obj exists for self.search_paths_var

    def __len__(self):
        return len(self.config_vars[self.search_paths_var])

    def __iter__(self):
        return iter(self.config_vars[self.search_paths_var])

    def add_search_path(self, a_path):
        """ Add a folder to the list of search paths
        """
        if a_path not in iter(self.config_vars[self.search_paths_var]):
            if os.path.isdir(a_path):
                self.config_vars[self.search_paths_var].append(a_path)

    def add_search_paths(self, some_paths):
        """ Add a folder to the list of search paths
        """
        for some_path in some_paths:
            some_real_path = os.path.realpath(some_path)
            self.add_search_path(some_real_path)

    def add_search_path_recursive(self, *paths):
        """ Add folders to the list of search paths
            and also all sub folders """
        pass  # to do...

    def find_file(self, in_file, return_original_if_not_found=False):
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
        2. A partial path was given, such as 'some_lib/some_lib.h". In which case the path
            up to and including some_lib would be added.
        If return_original_if_not_found is True, then the function will return original
        input path if file was not found, instead of None.
        """
        retVal = None
        if os.path.isfile(in_file):
            real_file = Path(in_file).resolve()
            real_folder = real_file.parent
            self.add_search_path(str(real_folder))
            retVal = str(real_file)
        else:
            for try_path in iter(self.config_vars[self.search_paths_var]):
                try:
                    real_file = Path(try_path, in_file).resolve()
                    if os.path.isfile(str(real_file)):
                        # in_file might be a relative path so must add the file's
                        # real folder so it's in the list.
                        real_folder = real_file.parent
                        self.add_search_path(str(real_folder))
                        retVal = str(real_file)
                        break
                except FileNotFoundError:
                    pass  # file was not found at try_path

            else:  # nobreak, retVal is None:
                if return_original_if_not_found:
                    retVal = in_file
        return retVal


if __name__ == "__main__":
    SearchPathsObj = SearchPaths("var")
