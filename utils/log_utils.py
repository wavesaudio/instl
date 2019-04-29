#!/usr/bin/env python3.6


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
import pathlib
import logging
import logging.handlers

from utils import misc_utils as utils

top_logger = logging.getLogger()


def config_logger():
    if '--no-stdout' not in sys.argv:
        setup_stream_hdlr()
    if '--no-system-log' not in sys.argv:
        system_log_file_path = utils.get_system_log_file_path()
        setup_file_logging(system_log_file_path)

    # command line options relating to logging are parsed here, as soon as possible
    if '--log' in sys.argv:
        try:
            log_option_index = sys.argv.index('--log')
            for i_log_file in range(log_option_index+1, len(sys.argv)):
                log_file_path = sys.argv[i_log_file]
                if not log_file_path.startswith('-'):
                    setup_file_logging(log_file_path)
                else:
                    break
        except:
            pass


def setup_stream_hdlr():
    stdout_stream_hdlr = logging.StreamHandler(stream=sys.stdout)
    stderr_stream_hdlr = logging.StreamHandler(stream=sys.stderr)
    for strm_hdlr in [stdout_stream_hdlr, stderr_stream_hdlr]:
        strm_hdlr.setLevel(logging.INFO if strm_hdlr == stdout_stream_hdlr else logging.ERROR)
        strm_hdlr.setFormatter(logging.Formatter('%(message)s'))
        top_logger.addHandler(strm_hdlr)


def setup_file_logging(log_file_path, level=logging.DEBUG):
    '''Setting up a logging handler'''
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    top_logger = logging.getLogger()

    fileLogHandler = logging.handlers.RotatingFileHandler(log_file_path, maxBytes=5000000, backupCount=10)
    fileLogHandler.setLevel(level)
    fileLogHandler.set_name(f"(log_file_name)_log_handler")
    formatter = logging.Formatter(fmt='%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s | {%(name)s.%(funcName)s,%(lineno)s}', datefmt='%Y-%m-%d_%H:%M:%S', style='%')

    fileLogHandler.setFormatter(formatter)
    top_logger.addHandler(fileLogHandler)


class ParentLogFilter(logging.Filter):
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


class CustomLogFormatter(logging.Formatter):
    simple_format = '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s'
    detailed_format = simple_format + ' | {%(parent_mod)s.%(parent_func_name)s,%(parent_line_no)s} | {%(name)s.%(funcName)s,%(lineno)s}'
    format_for_levels = {logging.DEBUG: detailed_format, logging.ERROR: detailed_format}

    def __init__(self):
        super().__init__(fmt=CustomLogFormatter.simple_format, datefmt='%Y-%m-%d_%H:%M:%S', style='%')

    def format(self, record):

        # Save the original format configured by the user
        # when the logger formatter was instantiated
        format_orig = self._style._fmt

        # Replace the original format with one customized by logging level
        self._style._fmt = CustomLogFormatter.format_for_levels.get(record.levelno, CustomLogFormatter.simple_format)

        # Call the original formatter class to do the grunt work
        result = logging.Formatter.format(self, record)

        # Restore the original format configured by the user
        self._style._fmt = format_orig

        return result


class JsonLogFormatter(object):
    ATTR_TO_JSON = ['created', 'filename', 'funcName', 'levelname', 'lineno', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'thread', 'threadName']

    def __init__(self, **kwargs):
        super().__init__()

    def format(self, record):
        obj = {attr: getattr(record, attr)
               for attr in self.ATTR_TO_JSON}
        return json.dumps(obj, indent=4)


default_logging_level = logging.INFO
debug_logging_level = logging.DEBUG

default_logging_started = False
debug_logging_started = False


def find_file_log_handler(log_file_path):
    retVal = None
    top_logger = logging.getLogger()
    for handler in top_logger.handlers:
        if hasattr(handler, 'stream'):
            if handler.stream.name == os.fspath(log_file_path):
                retVal = handler
                break
    return retVal


def get_hdlrs(hdlr_cls=logging.FileHandler, hdlr_name=None):
    '''Returning a list of all logger handlers, based on the requested handler class type.
       The default type is FileHandlerPlus. hdlr_name is an optional argument to be able to fetch specific handler'''
    root_logger = logging.getLogger()
    return [hdlr for hdlr in root_logger.handlers if isinstance(hdlr, hdlr_cls) and (not hdlr_name or hdlr_name == hdlr.baseFilename)]


def teardown_file_logging(log_file_path):
    return
    top_logger = logging.getLogger()
    fileLogHandler = find_file_log_handler(log_file_path)
    if fileLogHandler:
        top_logger.setLevel(fileLogHandler.previous_level)
        fileLogHandler.close()
        top_logger.removeHandler(fileLogHandler)
        del fileLogHandler
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


def remove_log_handler(handler_to_remove_name):
    the_logger = logging.getLogger()
    for handler in the_logger.handlers:
        if handler.name == handler_to_remove_name:
            print(f"remove log handler {handler.name}")
            the_logger.removeHandler(handler)
