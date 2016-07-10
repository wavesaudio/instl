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

LITERAL_STATE, VAR_NAME_STARTED_STATE, VAR_NAME_STATE, PARAMS_STATE,  VAR_NAME_ENDED_STATE, PARAMS_ENDED = range(6)

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

class VarParser(object):
    reset_yield_value = ("", None, None, "")
    def __init__(self):
        self.reset_return_tuple()
        self.parenthesis_balance = 0
        self.state = LITERAL_STATE

    def reset_return_tuple(self):
        self.literal_text, self.variable_name, self.variable_params, self.variable_str = self.reset_yield_value

    def parse_imp(self, f_string):
        """
            Yield parsed sections of f_string consisting of:
                literal_text: prefix text that is not a variable reference (or empty string)
                variable_name: name of a variable to resolve
                variable_params:
                variable_str: the original text of the variable, to be used as default in case resolving fails
        """
        self.literal_text, self.variable_name, self.variable_params, self.variable_str = ("", None, None, "")
        self.state = LITERAL_STATE
        params_text = ""
        self.parenthesis_balance = 0
        for c in f_string:
            if self.state == LITERAL_STATE:
                if c == '$':
                    self.variable_str += "$"
                    self.state = VAR_NAME_STARTED_STATE
                else:
                    self.literal_text += c
            elif self.state == VAR_NAME_STARTED_STATE:
                if c == '(':
                    self.variable_name = ""
                    self.variable_str += "("
                    self.parenthesis_balance += 1
                    self.state = VAR_NAME_STATE
                else: # not an opening parenthesis after $, go back to self.literal_text
                    self.variable_str = ""
                    self.literal_text += '$'
                    self.literal_text += c
                    self.state = LITERAL_STATE
            elif self.state == VAR_NAME_STATE:
                self.variable_str += c
                if c in variable_name_acceptable_characters:
                    self.variable_name += c
                elif c == ')':
                    self.parenthesis_balance -= 1
                    if self.parenthesis_balance == 0:
                        yield (self.literal_text, self.variable_name, self.variable_params, self.variable_str)
                        self.reset_return_tuple()
                        self.state = LITERAL_STATE
                    else:
                        self.variable_name += c
                elif c == '(':
                    self.parenthesis_balance += 1
                    self.variable_name += c
                elif c == '<':
                    self.state = PARAMS_STATE
                elif c in string.whitespace:
                    self.state = VAR_NAME_ENDED_STATE
                else: # unrecognised character so default to literal
                    self.literal_text += self.variable_str
                    self.variable_str = ""
                    self.variable_name = None
                    self.parenthesis_balance = 0
                    self.state = LITERAL_STATE
            elif self.state == VAR_NAME_ENDED_STATE:
                self.variable_str += c
                if c == ')':
                    yield (self.literal_text, self.variable_name, self.variable_params, self.variable_str)
                    self.reset_return_tuple()
                    self.state = LITERAL_STATE
                elif c == '<':
                    self.state = PARAMS_STATE
                elif c in string.whitespace:
                    pass
                else: # unrecognised character so default to literal
                    self.literal_text += self.variable_str
                    self.variable_str = ""
                    self.variable_name = None
                    self.literal_text += c
                    self.parenthesis_balance = 0
                    self.state = LITERAL_STATE
            elif self.state == PARAMS_STATE:
                self.variable_str += c
                if c == '>':
                    self.variable_params = params_text
                    params_text = ""
                    self.state = PARAMS_ENDED
                else:
                    params_text += c
            elif self.state == PARAMS_ENDED: # now only ')' is acceptable
                if c == ')':
                    self.variable_str += c
                    yield (self.literal_text, self.variable_name, self.variable_params, self.variable_str)
                    self.reset_return_tuple()
                    self.state = LITERAL_STATE
                elif c in string.whitespace:
                    self.variable_str += c
                else: # unrecognised character so default to literal
                    self.literal_text += self.variable_str
                    self.variable_str = ""
                    self.variable_name = None
                    self.literal_text += c
                    self.parenthesis_balance = 0
                    self.state = LITERAL_STATE
         # finishing touches - depend on what state was last
        if self.state in (VAR_NAME_STARTED_STATE, VAR_NAME_STATE, PARAMS_STATE, VAR_NAME_ENDED_STATE, PARAMS_ENDED): # '$' was last char in f_string
            self.literal_text += self.variable_str
            self.variable_name = None
            self.state = LITERAL_STATE         # this will force a final yield
        if self.state == LITERAL_STATE:
            yield (self.literal_text, self.variable_name, self.variable_params, self.variable_str)
        else:
            raise ValueError("failed to parse "+f_string)


def resolve_variable(var_name, var_params):
    retVal = "".join(("!",var_name))
    if var_params is not  None:
        retVal = "".join((retVal, "(", var_params, ")"))
    return retVal


def parse_str(str_to_parse):
    parsed_str = ""
    var_parse = VarParser()
    for literal_text, variable_name, variable_params, variable_str in var_parse.parse_imp(str_to_parse):
        if literal_text is not None:
            parsed_str += literal_text
        if variable_name is not None:
            parsed_str += resolve_variable(variable_name, variable_params)
    return parsed_str

if __name__ == '__main__':
    strs_to_parse = [
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
                    ]
    num_tests = len(strs_to_parse)
    num_fails = 0
    for str_to_parse in strs_to_parse:
        try:
            parsed = parse_str(str_to_parse[0])
            if parsed == str_to_parse[1]:
                result = "OK"
            else:
                result = "FAIL !!!"
                num_fails += 1
            print("'"+str_to_parse[0]+"'", "->", "'"+parsed+"'", "!= expected(",str_to_parse[1],")", result)
        except ValueError as ex:
            num_fails += 1
            print("'"+str_to_parse[0]+"'", "->", "parsing FAIL !!!", ex)
    print()
    if num_fails == 0:
        print("All", num_tests, "tests OK")
    else:
        print(num_fails, "of", num_tests, "FAILED")
