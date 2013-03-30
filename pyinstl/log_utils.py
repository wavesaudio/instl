#!/usr/local/bin/python2.7

from __future__ import print_function

"""
    Copyright (c) 2013, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""

import os
import appdirs
import inspect
import logging
import logging.handlers

def get_log_folder_path(in_appname, in_appauthor):
    retVal = appdirs.user_log_dir(appname=in_appname, appauthor=in_appauthor)
    try:
        os.makedirs(retVal)
    except: # os.makedirs raises is the directory already exists
        pass
    return retVal

def setup_logging(in_appname, in_appauthor):
    log_folder = get_log_folder_path(in_appname, in_appauthor)
    top_logger = logging.getLogger()
    top_logger.setLevel(logging.INFO)
    # setup INFO level logger
    log_file_path = os.path.join(log_folder, "log.txt")
    rotatingHandler = logging.handlers.RotatingFileHandler(log_file_path, maxBytes=200000, backupCount=5)
    formatter = logging.Formatter('%(asctime)s, %(levelname)s, %(funcName)s: %(message)s')
    rotatingHandler.setFormatter(formatter)
    rotatingHandler.setLevel(logging.INFO)
    top_logger.addHandler(rotatingHandler)
    # if debug log file exists, setup another handler for it
    debug_log_file_path = os.path.join(log_folder, "log.debug.txt")
    if os.path.isfile(debug_log_file_path):
        top_logger.setLevel(logging.DEBUG)
        debugLogHandler = logging.FileHandler(debug_log_file_path)
        debugLogHandler.setFormatter(formatter)
        debugLogHandler.setLevel(logging.DEBUG)
        top_logger.addHandler(debugLogHandler)

func_log_wrapper_threshold_level = logging.DEBUG
def func_log_wrapper(logged_func):
    """ A decorator to print function begin/end messages to log.
        If current logging level is above the threshhold the original function
        is returned, and performance is not effected.
    """
    returned_func = logged_func
    if func_log_wrapper_threshold_level >= logging.getLogger().getEffectiveLevel():
        def logged_func_wrapper(*args, **kargs):
            """ Does tricks around deficiencies in logging API. The problem is that
                when logging a decorated function the funcName format variable returns
                the decorator name not the decorated. Using functiontools.wraps
                does not solve the problem as it should have.
            """
            the_logger = logging.getLogger()
            def findCaller_override(self):
                """ override Logger.findCaller to pass our own caller info """
                return (inspect.getsourcefile(logged_func),
                                      inspect.getsourcelines(logged_func)[1],
                                      logged_func.__name__)
            save_findCaller_func = logging.Logger.findCaller
            logging.Logger.findCaller = findCaller_override
            the_logger.debug("{")
            logging.Logger.findCaller = save_findCaller_func

            retVal = logged_func(*args, **kargs)

            logging.Logger.findCaller = findCaller_override
            the_logger.debug("}")
            logging.Logger.findCaller = save_findCaller_func
            return retVal
        returned_func = logged_func_wrapper
    return returned_func
