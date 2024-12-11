#!/usr/bin/env python3.9


"""
    Copyright (c) 2013, Shai Shasag
    All rights reserved.
    Licensed under BSD 3 clause license, see LICENSE file for details.
"""

import inspect
import json
import logging
import logging.handlers
import os
import re
import sys
from pathlib import Path

from utils import misc_utils as utils

top_logger = logging.getLogger()


def config_logger(argv=None, config_vars=None):
    if argv is None:
        argv = sys.argv

    if '--no-stdout' not in argv:
        setup_stream_hdlr()
    # command line options relating to logging are parsed here, as soon as possible
    if '--log' in argv:
        try:
            log_option_index = argv.index('--log')
            for i_log_file in range(log_option_index+1, len(argv)):
                log_file_path = argv[i_log_file]
                if not log_file_path.startswith('-'):
                    setup_file_logging(log_file_path, rotate=False, config_vars=config_vars)
                else:
                    break
        except:
            pass
    elif '--no-system-log' not in argv:
        system_log_file_path = utils.get_system_log_file_path()
        setup_file_logging(system_log_file_path, config_vars=config_vars)


def setup_stream_hdlr():
    stdout_stream_hdlr = logging.StreamHandler(stream=sys.stdout)
    stdout_stream_hdlr.setLevel(logging.INFO)

    # Setting stdout to ignore any message higher than warning,
    # which will be handled by stderr_stream_hdlr
    stdout_stream_hdlr.addFilter(SameLevelFilter(logging.WARNING))
    stdout_stream_hdlr.setFormatter(logging.Formatter('%(message)s'))
    stdout_stream_hdlr.name = "instl stdout handler"
    top_logger.addHandler(stdout_stream_hdlr)

    stderr_stream_hdlr = logging.StreamHandler(stream=sys.stderr)
    stderr_stream_hdlr.setLevel(logging.ERROR)
    stderr_stream_hdlr.setFormatter(logging.Formatter('%(message)s'))
    stderr_stream_hdlr.name = "instl stderr handler"
    top_logger.addHandler(stderr_stream_hdlr)


format_per_level = {logging.CRITICAL: '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s',
                   logging.ERROR: '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s',
                   logging.WARNING: '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s',
                   logging.INFO: '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s',
                   logging.DEBUG: '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s',
                   logging.NOTSET: '%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s'}


class PerLevelFormatter(logging.Formatter):
    def __init__(self, format_per_level, **kwargs):
        super().__init__(**kwargs)
        self.default_format = self._style._fmt
        self.format_per_level = format_per_level

    def format(self, record):
        format_orig = self._style._fmt
        self._style._fmt = self.format_per_level.get(record.levelno, format_orig)
        result = super().format(record)
        self._style._fmt = format_orig
        return result


def setup_file_logging(log_file_path, level=logging.DEBUG, rotate=True, config_vars=None):
    """ Setting up a file logging handler """
    log_file_path = Path(log_file_path).resolve()
    log_file_folder = log_file_path.parent
    os.makedirs(log_file_path.parent, exist_ok=True)
    top_logger = logging.getLogger()

    if rotate:
        fileLogHandler = logging.handlers.RotatingFileHandler(log_file_path, encoding='utf-8', maxBytes=5000000, backupCount=10)
    else:
        fileLogHandler =  logging.FileHandler(log_file_path, encoding='utf-8')
    fileLogHandler.setLevel(level)
    fileLogHandler.set_name(f"(log_file_name)_log_handler")
    formatter = PerLevelFormatter(format_per_level, fmt=format_per_level[logging.CRITICAL], datefmt='%Y-%m-%d_%H:%M:%S', style='%')

    fileLogHandler.setFormatter(formatter)
    top_logger.addHandler(fileLogHandler)
    if config_vars is not None:
        config_vars.setdefault("OPEN_LOG_FILES", [])
        config_vars["OPEN_LOG_FILES"].append(log_file_path)



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
        return json.dumps(obj, indent=4, default=utils.extra_json_serializer)


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


def close_log_hdlrs(hdlr_cls=logging.FileHandler, hdlr_name=None):
    '''Walks through all logging handlers (based on the requested handler class type), and closes them
       The default type is FileHandlerPlus'''
    root_logger = logging.getLogger()
    hdlrs_to_close = sorted(get_hdlrs(hdlr_cls=hdlr_cls, hdlr_name=hdlr_name), key=lambda hdlr: str(hdlr) == 'DEBUG')  # Placing debug handler at the end
    for hdlr in hdlrs_to_close:
        root_logger.removeHandler(hdlr)
        try:
            hdlr.close()
        except OSError:
            root_logger.warning('Failed to close log handler - %s' % hdlr)


class SameLevelFilter(logging.Filter):
    '''This filter will force the log file handler to include only messages from the same level/type. This is done to quickly count and collect messages.'''
    def __init__(self, level, **kwargs):
        self.__level = level
        super().__init__(**kwargs)

    def filter(self, logRecord):
        return logRecord.levelno <= self.__level
