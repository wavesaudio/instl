#!/usr/bin/env python3


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
    except:  # os.makedirs raises is the directory already exists
        pass
    return retVal


def get_log_file_path(in_appname, in_appauthor, debug=False):
    retVal = get_log_folder_path(in_appname, in_appauthor)
    if debug:
        retVal = os.path.join(retVal, "log.debug.txt")
    else:
        retVal = os.path.join(retVal, "log.txt")
    return retVal

default_logging_level = logging.INFO
debug_logging_level = logging.DEBUG

default_logging_started = False
debug_logging_started = False


def setup_logging(in_appname, in_appauthor):
    top_logger = logging.getLogger()
    top_logger.setLevel(default_logging_level)
    # setup INFO level logger
    log_file_path = get_log_file_path(in_appname, in_appauthor, debug=False)
    rotatingHandler = logging.handlers.RotatingFileHandler(
        log_file_path, maxBytes=200000, backupCount=5)
    rotatingHandler.set_name("instl_log_handler")
    formatter = logging.Formatter(
        '%(asctime)s, %(levelname)s, %(funcName)s: %(message)s')
    rotatingHandler.setFormatter(formatter)
    rotatingHandler.setLevel(default_logging_level)
    top_logger.addHandler(rotatingHandler)
    global default_logging_started
    default_logging_started = True
    # if debug log file exists, setup another handler for it
    debug_log_file_path = get_log_file_path(in_appname, in_appauthor, debug=True)
    if os.path.isfile(debug_log_file_path):
        setup_file_logging(debug_log_file_path, debug_logging_level)
        global debug_logging_started
        debug_logging_started = True


def find_file_handler(log_file_path):
    retVal = None
    top_logger = logging.getLogger()
    for handler in top_logger.handlers:
        if hasattr(handler, 'stream'):
            if handler.stream.name == log_file_path:
                retVal = handler
                break
    return retVal


def setup_file_logging(log_file_path, level):
    top_logger = logging.getLogger()
    top_logger.setLevel(debug_logging_level)
    fileLogHandler = find_file_handler(log_file_path)
    if not fileLogHandler:
        fileLogHandler = logging.FileHandler(log_file_path)
        fileLogHandler.set_name("instl_debug_log_handler")
        formatter = logging.Formatter(
            '%(asctime)s, %(levelname)s, %(funcName)s: %(message)s')
        fileLogHandler.setFormatter(formatter)
        top_logger.addHandler(fileLogHandler)
    fileLogHandler.setLevel(level)


def teardown_file_logging(log_file_path, restore_level):
    top_logger = logging.getLogger()
    top_logger.setLevel(restore_level)
    fileLogHandler = find_file_handler(log_file_path)
    if fileLogHandler:
        fileLogHandler.flush()
        top_logger.removeHandler(fileLogHandler)
        del fileLogHandler
        os.remove(log_file_path)
    global debug_logging_started
    debug_logging_started = False


func_log_wrapper_threshold_level = debug_logging_level


def func_log_wrapper(logged_func):
    """ A decorator to print function begin/end messages to log.
        If current logging level is above the threshhold the original function
        is returned, and performance is not effected.
    """
    returned_func = logged_func
    if func_log_wrapper_threshold_level >= logging.getLogger().getEffectiveLevel():
        def logged_func_wrapper(*args, **kargs):
            """ Does tricks around deficiencies in logging API.
                The problem is that when logging a decorated function, the funcName
                format variable returns the decorator name not the decorated.
                functiontools.wraps does not solve the problem as it should have.
            """
            the_logger = logging.getLogger()

            def findCaller_override(self):
                """ override Logger.findCaller to pass our own caller info """
                return (
                    inspect.getsourcefile(logged_func),
                    # 2nd value was supposed to be inspect.getsourcelines(logged_func)[1],
                    # however it does not work when compiled with pyinstaller
                    None, 
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
