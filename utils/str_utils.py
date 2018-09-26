#!/usr/bin/env python3


import sys
import os
import re
import collections

from typing import Any, Dict, List, Set, Tuple

import utils


def quoteme(to_quote, quote_char):
    return "".join((quote_char, to_quote, quote_char))


def quoteme_list(to_quote_list, quote_char):
    return [quoteme(to_q, quote_char) for to_q in to_quote_list]


def quoteme_single(to_quote):
    return quoteme(to_quote, "'")


def quoteme_single_list(to_quote_list, ):
    return quoteme_list(to_quote_list, "'")


def quoteme_double(to_quote):
    return quoteme(to_quote, '"')


def quoteme_double_list(to_quote_list):
    return quoteme_list(to_quote_list, '"')


def quoteme_double_list_for_sql(to_quote_list):
    return "".join(('("', '","'.join(to_quote_list), '")'))


def quoteme_single_list_for_sql(to_quote_list):
    return "".join(("('", "','".join(to_quote_list), "')"))


no_need_for_raw_re = re.compile('^[a-zA-Z0-9_\-\./${}%:+ ]+$')


def quoteme_raw_string(simple_string):
    simple_string = os.fspath(simple_string)
    quote_mark = '"'
    if quote_mark in simple_string:
        quote_mark = "'"
        if quote_mark in simple_string:
            quote_mark = quote_mark * 3
            if quote_mark in simple_string:
                raise Exception("Oy Vey, how to quote this awful string ->{simple_string}<-")

    # multiline strings need triple quotation
    if len(quote_mark) == 1 and "\n" in simple_string:
        quote_mark = quote_mark * 3

    retVal = "".join((quote_mark, simple_string, quote_mark))
    if not no_need_for_raw_re.match(simple_string):
        retVal = "".join(('r', retVal))
    return retVal


def quoteme_raw_if_string(some_thing):
    if isinstance(some_thing, str):
        return quoteme_raw_string(some_thing)
    else:
        return str(some_thing)
    return retVal


def quoteme_raw_dict(dict_of_things: Dict):
    item_strs = list()
    for k, v in dict_of_things.items():
        item_strs.append(f"""{quoteme_raw_string(k)}:{quoteme_raw_string(v)}""")
    dict_as_str = "".join(("{", ",".join(item_strs),"}"))
    return dict_as_str


def quoteme_raw_list(list_of_things):
    retVal = [quoteme_raw_if_string(something) for something in list_of_things]
    return retVal


def quoteme_raw_if_list(list_of_things, one_element_list_as_string=False):
    if isinstance(list_of_things, str):
        retVal = quoteme_raw_if_string(list_of_things)
    elif isinstance(list_of_things, collections.Sequence):
        if one_element_list_as_string and len(list_of_things) == 1:
            retVal = quoteme_raw_if_string(list_of_things[0])
        else:
            retVal = quoteme_raw_list(list_of_things)
            retVal = "".join(("[", ", ".join(retVal), "]"))
    else:
        retVal = quoteme_raw_if_string(list_of_things)
    return retVal


def quote_path_properly(path_to_quote):
    quote_char = "'"
    if "'" in path_to_quote or "${" in path_to_quote:
        quote_char = '"'
        if '"' in path_to_quote:
            raise Exception(f"""both single quote and double quote found in {path_to_quote}""")
    quoted_path = "".join((quote_char, path_to_quote, quote_char))
    return quoted_path


detect_quotations = re.compile("(?P<prefix>[\"'])(?P<the_unquoted_text>.+)(?P=prefix)")


def unquoteme(to_unquote):
    retVal = to_unquote
    has_quotations = detect_quotations.match(to_unquote)
    if has_quotations:
        retVal = has_quotations['the_unquoted_text']
    return retVal

def unicodify(in_something, encoding='utf-8'):
    if in_something is not None:
        if isinstance(in_something, str):
            retVal = in_something
        elif isinstance(in_something, bytes):
            retVal = in_something.decode(encoding)
        else:
            retVal = str(in_something)
    else:
        retVal = None
    return retVal


def bytetify(in_something):
    if in_something is not None:
        if not isinstance(in_something, bytes):
            retVal = str(in_something).encode()
        else:
            retVal = in_something
    else:
        retVal = None
    return retVal


def bool_int_to_str(in_bool_int):
    if in_bool_int == 0:
        retVal = "no"
    else:
        retVal = "yes"
    return retVal


def str_to_bool_int(the_str):
    if the_str.lower() in ("yes", "true", "y", 't'):
        retVal = 1
    elif the_str.lower() in ("no", "false", "n", "f"):
        retVal = 0
    else:
        raise ValueError(f"Cannot translate {the_str} to bool-int")
    return retVal


def is_iterable_but_not_str(obj_to_check):
    retVal = hasattr(obj_to_check, '__iter__') and not isinstance(obj_to_check, str)
    return retVal
