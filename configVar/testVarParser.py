#!/usr/bin/env python3

import os
import sys
import stat
import grp
import pwd
import time
import numbers
import re
import appdirs
import string
import ast
from pathlib import PurePath

# Unfortunatly '(', ')' are also acceptable in variable name on Windows, these will get special attention in the code
# However, '(', ')' in a variable name must be balanced
variable_name_acceptable_characters = set((c for c in string.ascii_letters+string.digits+'_'))
print("variable_name_acceptable_characters:", "".join(sorted(list(variable_name_acceptable_characters))))

LITERAL_STATE, VAR_REF_STARTED_STATE, VAR_NAME_STATE, PARAMS_STATE,  VAR_NAME_ENDED_STATE, PARAMS_ENDED = range(6)

vars_split_level_1_re = re.compile("\s*,\s*", re.X)
vars_split_level_2_re = re.compile("\s*=\s*", re.X)


def params_to_dict(params_text):
    retVal = {}
    if params_text:
        var_assign_list = vars_split_level_1_re.split(params_text)
        for var_assign in var_assign_list:
            single_var_assign = vars_split_level_2_re.split(var_assign, 1)
            if len(single_var_assign) == 2:
                retVal[single_var_assign[0]] = single_var_assign[1]
    return retVal


class parse_imp_context(object):
    reset_yield_value = ("", None, None, "")

    def __init__(self):
        self.literal_text = None
        self.variable_name = None
        self.variable_params = None
        self.variable_str = None
        self.parenthesis_balance = 0
        self.state = LITERAL_STATE

    def reset_return_tuple(self):
        (self.literal_text, self.variable_name, self.variable_params, self.variable_str) = self.reset_yield_value

    def get_return_tuple(self):
        return self.literal_text, self.variable_name, self.variable_params, self.variable_str

    def discard_variable(self, c):
        self.literal_text += self.variable_str
        self.variable_str = ""
        self.variable_name = None
        self.variable_params = None
        self.parenthesis_balance = 0
        self.state = LITERAL_STATE
        if c == '$':
            self.literal_text = self.literal_text[:-1]
            self.variable_str += "$"
            self.state = VAR_REF_STARTED_STATE


def parse_imp(f_string):
    """
        Yield parsed sections of f_string consisting of:
            literal_text: prefix text that is not a variable reference (or empty string)
            variable_name: name of a variable to resolve
            variable_params:
            variable_str: the original text of the variable, to be used as default in case resolving fails
    """
    cont = parse_imp_context()
    cont.reset_return_tuple()
    cont.state = LITERAL_STATE
    cont.parenthesis_balance = 0
    for c in f_string:
        if cont.state == LITERAL_STATE:
            if c == '$':
                cont.variable_str += "$"
                cont.state = VAR_REF_STARTED_STATE
            else:
                cont.literal_text += c
        elif cont.state == VAR_REF_STARTED_STATE:
            cont.variable_str += c
            if c == '(':
                cont.variable_name = ""
                cont.parenthesis_balance += 1
                cont.state = VAR_NAME_STATE
            else: # not an opening parenthesis after $, go back to cont.literal_text
                cont.discard_variable(c)
        elif cont.state == VAR_NAME_STATE:
            cont.variable_str += c
            if c in variable_name_acceptable_characters:
                cont.variable_name += c
            elif c == ')':
                cont.parenthesis_balance -= 1
                if cont.parenthesis_balance == 0:
                    yield cont.get_return_tuple()
                    cont.reset_return_tuple()
                    cont.state = LITERAL_STATE
                else:
                    cont.variable_name += c
            elif c == '(':
                cont.parenthesis_balance += 1
                cont.variable_name += c
            elif c == '<':
                cont.variable_params = ""
                cont.state = PARAMS_STATE
            elif c in string.whitespace:
                cont.state = VAR_NAME_ENDED_STATE
            else:  # unrecognised character so default to literal
                cont.discard_variable(c)
        elif cont.state == VAR_NAME_ENDED_STATE:
            cont.variable_str += c
            if c == ')':
                cont.parenthesis_balance -= 1
                yield cont.get_return_tuple()
                cont.reset_return_tuple()
                cont.state = LITERAL_STATE
            elif c == '<':
                cont.variable_params = ""
                cont.state = PARAMS_STATE
            elif c in string.whitespace:
                pass
            else: # unrecognised character so default to literal
                cont.discard_variable(c)
        elif cont.state == PARAMS_STATE:
            cont.variable_str += c
            if c == '>':
                cont.state = PARAMS_ENDED
            else:
                cont.variable_params += c
        elif cont.state == PARAMS_ENDED:
            cont.variable_str += c
            if c == ')':
                cont.parenthesis_balance -= 1
                yield cont.get_return_tuple()
                cont.reset_return_tuple()
                cont.state = LITERAL_STATE
            elif c in string.whitespace:
                pass
            else: # unrecognised character so default to literal
                cont.discard_variable(c)
    # finishing touches - depend on what state was last
    if cont.state in (VAR_REF_STARTED_STATE, VAR_NAME_STATE, PARAMS_STATE, VAR_NAME_ENDED_STATE, PARAMS_ENDED): # '$' was last char in f_string
        cont.literal_text += cont.variable_str
        cont.variable_name = None
        cont.state = LITERAL_STATE         # this will force a final yield
    if cont.state == LITERAL_STATE:
        yield cont.get_return_tuple()
    else:
        raise ValueError("failed to parse "+f_string)


def resolve_variable_1(var_name, var_params, default=""):
    retVal = "".join(("!",var_name))
    if var_params is not  None:
        retVal = "".join((retVal, "(", var_params, ")"))
    return retVal


def resolve_variable_2(var_name, var_params, default=""):
    return default


def parse_str(str_to_parse, var_resolver):
    parsed_str = ""
    for literal_text, variable_name, variable_params, variable_str in parse_imp(str_to_parse):
        if literal_text is not None:
            parsed_str += literal_text
        if variable_name is not None:
            parsed_str += var_resolver(variable_name, variable_params, variable_str)
    return parsed_str

if __name__ == '__main__':
    strs_to_parse = [("$(a)$(b<>)$(c)", "!a!b()!c"),
                    ("", ""),
                    ("chunga chunga", "chunga chunga"),
                    ("chunga$chunga", "chunga$chunga"),
                    ("abc$(def)gh$kl$(BOO<aaaa=bbbb>)nm$(op", "abc!defgh$kl!BOO(aaaa=bbbb)nm$(op"),
                    ("$(MAMA_MIA)", "!MAMA_MIA"),
                    ("$(MAMA_MIA<>)", "!MAMA_MIA()"),
                    ("$(MAMA_MIA<K=k>)","!MAMA_MIA(K=k)"),
                    ("$(MAMA_MIA<K=k,L=l>)", "!MAMA_MIA(K=k,L=l)"),
                    ("aaa $(DDD<GGG=SSS>bonbon", "aaa $(DDD<GGG=SSS>bonbon"),
                    ("aaa $(DDD<GGG=SSS>bonbon$(LILI)", "aaa $(DDD<GGG=SSS>bonbon!LILI"),
                    ("aaa $(DDD<GGG=SSS> )", "aaa !DDD(GGG=SSS)"),
                    ("aaa $(DDD <GGG=SSS>)", "aaa !DDD(GGG=SSS)"),
                    ("aaa $(DDD <GGG=SSS> )", "aaa !DDD(GGG=SSS)"),
                    ("$(a)$(b)$(c)", "!a!b!c"),
                    ("$(a)$(b$(c)", "!a$(b!c"),
                    ("1$(a)2$(b)3$(c)4", "1!a2!b3!c4"),
                    ("1$(a)2$(b3$(c)4", "1!a2$(b3!c4"),
                    ("$(a)$(b<>)$(c)", "!a!b()!c"),
                    ]
    num_tests = len(strs_to_parse) * 2
    num_fails = 0
    for str_to_parse in strs_to_parse:
        try:
            parsed_1 = parse_str(str_to_parse[0], resolve_variable_1)
            parsed_2 = parse_str(str_to_parse[0], resolve_variable_2)
            if parsed_1 == str_to_parse[1]:
                print("parse_1: '" + str_to_parse[0] + "'", "->", "'" + parsed_1 + "'", "OK")
            else:
                print("parse_1: '" + str_to_parse[0] + "'", "->", "'" + parsed_1 + "'", "!= expected(", str_to_parse[1],
                      ")", "FAIL !!!")
                num_fails += 1

            if parsed_2 == str_to_parse[0]:
                print("parse_2: '" + str_to_parse[0] + "'", "->", "'" + parsed_2 + "'", "OK")
            else:
                print("parse_2: '" + str_to_parse[0] + "'", "->", "'" + parsed_2 + "'", "!= expected(", str_to_parse[0],
                      ")", "FAIL !!!")
                num_fails += 1
        except ValueError as ex:
            num_fails += 1
            print("'"+str_to_parse[0]+"'", "->", "parsing FAIL !!!", ex)
    print()
    if num_fails == 0:
        print("All", num_tests, "tests OK")
    else:
        print(num_fails, "of", num_tests, "FAILED")
