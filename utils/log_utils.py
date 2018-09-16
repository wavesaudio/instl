#!/usr/bin/env python3


"""
    Copyright (c) 2013, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""

import os
import re
import sys
import json
import appdirs
import inspect
import logging
import logging.handlers
from logging.config import dictConfig

from utils import misc_utils as utils


def config_logger(system_log_file_path=None):
    if system_log_file_path is None:
        system_log_file_path = utils.get_system_log_file_path()
    os.makedirs(os.path.dirname(system_log_file_path), exist_ok=True)
    config_dict = get_config_dict(system_log_file_path)
    dictConfig(config_dict)


def get_config_dict(system_log_file_path):
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'simple': {
                'class': 'logging.Formatter',
                'format': '%(message)s'
            },
            'detailed': {
                '()': CustomFormatter,
            },
            'json': {
                '()': JsonFormatter,
                'format': '%(message)s'
            }
        },
        'filters': {
            'parent': {
                '()': ParentFilter,
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'INFO',
                'formatter': 'simple',
                'stream': sys.stdout
            },
            'errors': {
                'class': 'logging.StreamHandler',
                'level': 'ERROR',
                'formatter': 'simple',
                'stream': sys.stderr
            },
            'system_log': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'DEBUG',
                'formatter': 'detailed',
                'filename': system_log_file_path,
                'mode': 'a',
                'maxBytes': 5000000,
                'backupCount': 10,
                'filters': ['parent']
            }
        },
        'root': {
            'level': 'DEBUG',  # Currently disabled. Need to add verbose mode from cmd line
            'handlers': ['console', 'errors', 'system_log'],
        },
    }


class ParentFilter(logging.Filter):
    '''Adds additional info to the log message - stack level, parent info: module, function name, line number.'''
    def filter(self, record):
        record.name = re.sub('.*\.', '', record.name)
        try:
            stack = inspect.stack()
            record.stack_lvl = '  ' * (len(stack) - 9)
            record.parent_mod = inspect.getmodulename(stack[8][1])
            record.parent_func_name = stack[8][3]
            record.parent_line_no = stack[8][2]
        except IndexError:
            record.stack_lvl = ''
            record.parent_mod = ''
            record.parent_func_name = ''
            record.parent_line_no = ''
        return True


class CustomFormatter(logging.Formatter):
    simple_format = '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s'
    detailed_format = simple_format + ' | {%(parent_mod)s.%(parent_func_name)s,%(parent_line_no)s} | {%(name)s.%(funcName)s,%(lineno)s}'
    format_for_levels = {logging.DEBUG: detailed_format, logging.ERROR: detailed_format}

    def __init__(self):
        super().__init__(fmt=CustomFormatter.simple_format, datefmt='%Y-%m-%d_%H:%M:%S', style='%')

    def format(self, record):

        # Save the original format configured by the user
        # when the logger formatter was instantiated
        format_orig = self._style._fmt

        # Replace the original format with one customized by logging level
        self._style._fmt = CustomFormatter.format_for_levels.get(record.levelno, CustomFormatter.simple_format)

        # Call the original formatter class to do the grunt work
        result = logging.Formatter.format(self, record)

        # Restore the original format configured by the user
        self._style._fmt = format_orig

        return result


class JsonFormatter(object):
    ATTR_TO_JSON = ['created', 'filename', 'funcName', 'levelname', 'lineno', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'thread', 'threadName']

    def __init__(self, **kwargs):
        super().__init__()

    def format(self, record):
        obj = {attr: getattr(record, attr)
               for attr in self.ATTR_TO_JSON}
        return json.dumps(obj, indent=4)


def get_log_folder_path(in_app_name, in_app_author):
    retVal = appdirs.user_log_dir(appname=in_app_name, appauthor=in_app_author)
    os.makedirs(retVal, exist_ok=True)
    return retVal


def get_log_file_path(in_app_name, in_app_author, debug=False):
    retVal = get_log_folder_path(in_app_name, in_app_author)
    if debug:
        retVal = os.path.join(retVal, "log.debug.txt")
    else:
        retVal = os.path.join(retVal, "log.txt")
    return retVal

default_logging_level = logging.INFO
debug_logging_level = logging.DEBUG

default_logging_started = False
debug_logging_started = False


def setup_logging(in_app_name, in_app_author):
    top_logger = logging.getLogger()
    top_logger.setLevel(default_logging_level)
    # setup INFO level logger
    log_file_path = get_log_file_path(in_app_name, in_app_author, debug=False)
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
    debug_log_file_path = get_log_file_path(in_app_name, in_app_author, debug=True)
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
        If current logging level is above the threshold the original function
        is returned, and performance is not effected.
    """
    returned_func = logged_func
    if func_log_wrapper_threshold_level >= logging.getLogger().getEffectiveLevel():
        def logged_func_wrapper(*args, **kwargs):
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

            retVal = logged_func(*args, **kwargs)

            logging.Logger.findCaller = findCaller_override
            the_logger.debug("}")
            logging.Logger.findCaller = save_findCaller_func
            return retVal
        returned_func = logged_func_wrapper
    return returned_func
