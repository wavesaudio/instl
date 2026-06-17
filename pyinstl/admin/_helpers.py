#!/usr/bin/env python3.12
"""Module-level free functions extracted verbatim from pyinstl/instlAdmin.py.

This is a pure structural decomposition (extract-module refactor): the code below
is MOVED verbatim from the original god-object. No logic was changed.
"""
import json
import logging
log = logging.getLogger()

import os
import sys
import traceback
import filecmp
import multiprocessing as mp
import time
import datetime
import re
import redis
import boto3
import threading
import io

from dataclasses import dataclass
import dictdiffer

import utils
import yaml
import aYaml
from ..instlInstanceBase import InstlInstanceBase
from pybatch import *
from ..instlException import InstlException
from configVar import ConfigVarYamlReader

def start_redis_heartbeat_thread(redis_host, redis_port, heartbeat_key, heartbeat_interval):
    """ start a daemon thread that will periodically set a redis key to a string containing the current date/time
        a daemon thread will stop when the application quits, so no need to join the thread
    """
    def heartbeat_redis(redis_host, redis_port, heartbeat_key, heartbeat_interval):
        try:
            r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
            while True:
                now_time = time.time()
                r.set(heartbeat_key, str(datetime.datetime.fromtimestamp(now_time)))
                time_to_sleep = max(now_time + heartbeat_interval - time.time(), 0.01)
                #print(f"{now_time} {time_to_sleep}")
                time.sleep(time_to_sleep)
        except Exception as ex:
            print(f"Exception in heartbeat_redis {ex}")

    thread_name = "redis heartbeat"
    x = threading.Thread(target=heartbeat_redis, args=(redis_host, redis_port, heartbeat_key, heartbeat_interval), daemon=True, name=thread_name)
    x.start()


def smart_merge_dicts(by_os_dict):
    """ merge dicts by OS according to instl conventions
        by_os_dict is in the form {"Linux": {...}, "Mac": {...}, "Win": {...}}
        the dicts under by_os_dict are assumed to be different, if they are identical to begin with
        results are undefined
    """

    all_os_names = sorted(list(by_os_dict.keys()))
    merged = dict()
    for os_name in all_os_names:
        merged[os_name] = dict()

    # create a set of all top level keys
    all_keys = set()
    for os_name in all_os_names:
        all_keys.update(by_os_dict[os_name].keys())

    # items in already OS specific key should come from the corresponding os dict
    for os_name in all_os_names:
        if os_name in by_os_dict[os_name]:  # e.g "Mac" dict has a "Mac" key
            merged[os_name].update(by_os_dict[os_name][os_name])
            all_keys.remove(os_name)
    #print("all_keys", all_keys)

    # keys that are common to all oses
    keys_common_to_all_oses = all_keys.copy()
    for os_name in all_os_names:
        keys_common_to_all_oses.intersection_update(by_os_dict[os_name].keys())
    #print("keys_common_to_all_oses", keys_common_to_all_oses)
    keys_not_common_to_all_oses = all_keys - keys_common_to_all_oses
    #print("keys_not_common_to_all_oses", keys_not_common_to_all_oses)

    # separate keys_not_common_to_all_oses to those who are identical across all oses (keys_common_to_all_oses_with_same_value)
    # and those that are different between at least 2 oses (keys_common_to_all_oses_with_diff_value)
    keys_common_to_all_oses_with_same_value = set()
    keys_common_to_all_oses_with_diff_value = set()
    for key in keys_common_to_all_oses:
        # get a first one so we have something to compare against
        _curr = by_os_dict[all_os_names[0]][key]
        for os_name in all_os_names:
            _next = by_os_dict[os_name][key]
            if list(dictdiffer.diff(_curr, _next)):
                keys_common_to_all_oses_with_diff_value.add(key)
                break
            else:
                _curr = _next
        else:
            keys_common_to_all_oses_with_same_value.add(key)
    #print("keys_common_to_all_oses_with_same_value", keys_common_to_all_oses_with_same_value)
    #print("keys_common_to_all_oses_with_diff_value", keys_common_to_all_oses_with_diff_value)

    # all oses have these keys with same value, so assigned merged with a key/value from one of the oses
    for key in keys_common_to_all_oses_with_same_value:
        merged[key] = by_os_dict[all_os_names[0]][key]

    # all oses have these keys with different value, so assigned merged with a key/value from each of the oses
    for key in (keys_common_to_all_oses_with_diff_value | keys_not_common_to_all_oses):
        for os_name in all_os_names:
            if key in by_os_dict[os_name]:
                merged[os_name][key] = by_os_dict[os_name][key]

    # remove empty dicts
    all_oses = list(merged.keys())
    for os_name in all_oses:
        if not merged[os_name]:
            del merged[os_name]

    return merged

def dict_in_canonical_order(to_order, order=None, single_value=None):
    if order is None:
        order = []
    if single_value is None:
        single_value = []

    match to_order:
        case str():
            retVal = to_order
        case collections.abc.Sequence():
            retVal = [dict_in_canonical_order(item) for item in to_order]
        case collections.abc.Mapping():
            retVal = collections.OrderedDict()
            names_in_order = list()
            names_from_node = [str(_key) for _key in to_order]
            for name in order:
                if name in names_from_node:
                    names_in_order.append(name)
                    names_from_node.remove(name)
            names_in_order.extend(names_from_node)  # add names in node that do not appear in order
            for name in names_in_order:
                value = to_order[name]
                if name in single_value and isinstance(value, collections.abc.Sequence) and 1 == len(value):
                    value = value[0]
                retVal[name] = dict_in_canonical_order(value, order, single_value)
        case _: # not sequence or mapping or string - assuming scalar
            retVal = to_order
    return retVal
