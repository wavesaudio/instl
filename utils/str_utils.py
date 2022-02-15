#!/usr/bin/env python3.9


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


#no_need_for_raw_re = re.compile('^[a-zA-Z0-9_\-\./${}%:+ ]+$')
escape_quotations_re = re.compile("['\"\\\\]")
def escape_quotations(simple_string):
    """ escape the characters ', '. \ """
    retVal = escape_quotations_re.sub(lambda match_obj: '\\'+match_obj.group(0), simple_string)
    return retVal


def quoteme_raw_string(simple_string):
    assert isinstance(simple_string, str), f"{simple_string} is not of type str"

    if not simple_string:
        retVal = 'r""'

    else:
        simple_string = os.fspath(simple_string)

        possible_quote_marks = ('"', "'", '"""', "'''")
        if "\n" in simple_string:  # multiline strings need triple quotation
            possible_quote_marks = ('"""', "'''")

        for quote_mark in possible_quote_marks:
            # 1st priority is to create a raw string. Strings that end with the quotation mark or with \ cannot be raw.
            if quote_mark not in simple_string and quote_mark[-1] != simple_string[-1] and simple_string[-1] != '\\':
                retVal = "".join(('r', quote_mark, simple_string, quote_mark))
                break
        else:
            # if all possible quotations marks are present in the string - do proper escaping and return non-raw string
            retVal = "".join(('"', escape_quotations(simple_string), '"'))

    return retVal


types_that_do_not_need_quotation = (int, float, bool)


def quoteme_raw_if_string(some_thing):
    if not isinstance(some_thing, types_that_do_not_need_quotation):
        return quoteme_raw_string(str(some_thing))
    else:
        return str(some_thing)


def quoteme_raw_by_type(some_thing, config_vars=None):
    retVal = None
    if isinstance(some_thing, types_that_do_not_need_quotation):
        retVal = str(some_thing)
    elif isinstance(some_thing, str):
        if config_vars is not None:
            some_thing = config_vars.resolve_str(some_thing)
        retVal = quoteme_raw_string(some_thing)
    elif isinstance(some_thing, os.PathLike):
        retVal = quoteme_raw_by_type(os.fspath(some_thing), config_vars)
    elif isinstance(some_thing, collections.abc.Sequence):
       retVal = "".join(("[", ",".join(quoteme_raw_by_type(t, config_vars) for t in some_thing),"]"))
    elif isinstance(some_thing, collections.abc.Mapping):
        item_strs = list()
        for k, v in sorted(some_thing.items()):
            item_strs.append(f"""{quoteme_raw_by_type(k)}:{quoteme_raw_by_type(v, config_vars)}""")
        retVal = "".join(("{", ",".join(item_strs), "}"))
    return retVal


def quoteme_raw_list(list_of_things):
    retVal = [quoteme_raw_if_string(something) for something in list_of_things]
    return retVal


def quoteme_raw_if_list(list_of_things, one_element_list_as_string=False):
    if isinstance(list_of_things, str):
        retVal = quoteme_raw_if_string(list_of_things)
    elif isinstance(list_of_things, collections.abc.Sequence):
        if one_element_list_as_string and len(list_of_things) == 1:
            retVal = quoteme_raw_if_string(list_of_things[0])
        else:
            retVal = quoteme_raw_list(list_of_things)
            retVal = "".join(("[", ",".join(retVal), "]"))
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
            retVal = in_something.decode(encoding, errors='backslashreplace')
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
    if the_str.lower() in ("yes", "true", "y", 't', '1'):
        retVal = 1
    elif the_str.lower() in ("no", "false", "n", "f", '0'):
        retVal = 0
    else:
        raise ValueError(f"Cannot translate {the_str} to bool-int")
    return retVal


def is_iterable_but_not_str(obj_to_check):
    retVal = hasattr(obj_to_check, '__iter__') and not isinstance(obj_to_check, str)
    return retVal


if __name__ == "__main__":
    #print(quoteme_raw_string(r'''"$(LOCAL_REPO_SYNC_DIR)/Mac/Utilities/plist/plist_creator.sh" "$(__Plist_for_native_instruments_1__)"'''))
    #print(quoteme_raw_string("""single-single(') triple-single(''') single-double(") single-triple(\"\"\")"""))

    rere = re.compile("['\"\\\\]")
    s = r"""A"B'C'''D'\\EFG"""
    rs = rere.sub(lambda matchobj: '\\'+matchobj.group(0), s)
    print(rs)
