#!/usr/bin/env python3

import re
import string
from collections import namedtuple
from typing import Optional, Callable, Dict

def params_to_dict(params_text) -> Dict:
    retVal = {}
    if params_text:
        var_assign_list = vars_split_level_1_re.split(params_text)
        for var_assign in var_assign_list:
            single_var_assign = vars_split_level_2_re.split(var_assign, 1)
            if len(single_var_assign) == 2:
                retVal[single_var_assign[0]] = single_var_assign[1]
    return retVal


# return value for a partial parse. example strings to parse: "blah $(ABC<a, b, c=7, d=8>)" or "blah $(ABC[5])"
ParseRetVal = namedtuple('ParseRetVal',
                         ['literal_text',         # literal part e.g. "blah " or "" if only a variable was found
                          'variable_str',         # the whole variable part e.g. "$(ABC<a, b, c=7, d=8>)"
                          'variable_params_str',  # the whole variable params part, as string e.g. "a, b, c=7, d=8" or None of no variable or no params were found
                          'variable_name',        # variable name e.g. "ABC" or None of no variable was found
                          'positional_params',    # list of positional params e.g. [a, b], or None
                          'key_word_params',      # dict of key word params e.g. {c: 7, d: 8}, or None
                          'array_index_str',      # the whole variable array index part, as string e.g. "[5]" or None
                          'array_index_int'       # variable array index as integer or None
                          ])


class VarParseImpContext(object):
    reset_yield_value: ParseRetVal = ParseRetVal(literal_text="",
                                    variable_str=None,
                                    variable_params_str=None,
                                    variable_name=None,
                                    positional_params=None,
                                    key_word_params=None,
                                    array_index_str=None,
                                    array_index_int=None)
    # Unfortunately '(', ')' are also acceptable in variable name on Windows, these will get special attention in the code
    # However, '(', ')' in a variable name must be balanced
    variable_name_acceptable_characters = set((c for c in string.ascii_letters + string.digits + '_' + '-'))

    def __init__(self):
        (self.literal_text,
            self.variable_str,
            self.variable_params_str,
            self.variable_name,
            self.positional_params,
            self.key_word_params,
            self.array_index_str,
            self.array_index_int) = self.reset_yield_value
        self.parenthesis_balance: int = 0

    def reset_return_tuple(self):
        (self.literal_text,
         self.variable_str,
         self.variable_params_str,
         self.variable_name,
         self.positional_params,
         self.key_word_params,
         self.array_index_str,
         self.array_index_int) = self.reset_yield_value

    def get_return_tuple(self) -> ParseRetVal:
        return ParseRetVal(self.literal_text,
                           self.variable_str,
                           self.variable_params_str,
                           self.variable_name,
                           self.positional_params,
                           self.key_word_params,
                           self.array_index_str,
                           self.array_index_int)


vars_split_level_1_re = re.compile("\s*,\s*", re.X)
vars_split_level_2_re = re.compile("\s*=\s*", re.X)


def var_parse_imp(f_string):
    """
        Yield parsed sections of f_string consisting of:
            literal_text: prefix text that is not a variable reference (or empty string)
            variable_name: name of a variable to resolve
            variable_params_str:
            variable_str: the original text of the variable, to be used as default in case resolving fails
    """

    def parse_var_params(cont: VarParseImpContext):
        if cont.variable_params_str:  # might be None (no params) or "" (empty params, i.e. $(A<>))
            cont.positional_params = []
            cont.key_word_params = {}
            comma_separated_list = vars_split_level_1_re.split(cont.variable_params_str.strip())
            for csi in comma_separated_list:
                single_param = vars_split_level_2_re.split(csi.strip(), 1)
                if len(single_param) > 1:
                    if single_param[0] and single_param[1]:
                        cont.key_word_params[single_param[0]] = single_param[1]
                    else:  # "=", '=a' or 'a=' should translate to a single param
                        cont.positional_params.append(csi.strip())
                else:
                    if single_param[0]:
                        cont.positional_params.append(single_param[0])
    
    def discard_variable(c, cont: VarParseImpContext):
        next_state = literal_state
        new_literal_text = cont.literal_text + cont.variable_str
        cont.reset_return_tuple()
        cont.literal_text = new_literal_text
        cont.parenthesis_balance = 0
        if c == '$':
            cont.literal_text = cont.literal_text[:-1]
            cont.variable_str = "$"
            next_state = var_ref_started_state
        return next_state

    def literal_state(c, cont: VarParseImpContext):
        if c == '$':
            cont.variable_str = "$"
            next_state = var_ref_started_state
        else:
            cont.literal_text += c
            next_state = literal_state
        return next_state, None

    def var_name_state(c, cont: VarParseImpContext):
        next_state = var_name_state
        yield_val: Optional[ParseRetVal] = None
        cont.variable_str += c
        if c in cont.variable_name_acceptable_characters:
            cont.variable_name += c
        elif c == ')':
            cont.parenthesis_balance -= 1
            if cont.parenthesis_balance == 0:
                yield_val = cont.get_return_tuple()
                cont.reset_return_tuple()
                next_state = literal_state
            else:
                cont.variable_name += c
        elif c == '(':
            cont.parenthesis_balance += 1
            cont.variable_name += c
        elif c == '<':
            cont.variable_params_str = ""
            next_state = params_state
        elif c == '[':
            cont.array_index_str = ""
            next_state = array_state
        elif c in string.whitespace:
            next_state = var_name_ended_state
        else:  # unrecognised character so default to literal
            next_state = discard_variable(c, cont)
        return next_state, yield_val

    def var_ref_started_state(c, cont: VarParseImpContext):  # '$' was found
        cont.variable_str += c
        if c == '(':
            cont.variable_name = ""
            cont.parenthesis_balance += 1
            next_state = var_name_state
        else:  # not an opening parenthesis after $, go back to cont.literal_text
            next_state = discard_variable(c, cont)
        return next_state, None

    def var_name_ended_state(c, cont: VarParseImpContext):
        next_state = var_name_ended_state
        yield_val: Optional[ParseRetVal] = None
        cont.variable_str += c
        if c == ')':
            cont.parenthesis_balance -= 1
            yield_val = cont.get_return_tuple()
            cont.reset_return_tuple()
            next_state = literal_state
        elif c == '<':
            cont.variable_params_str = ""
            next_state = params_state
        elif c in string.whitespace:
            pass
        else: # unrecognised character so default to literal
            next_state = discard_variable(c, cont)
        return next_state, yield_val

    def params_state(c, cont: VarParseImpContext):
        next_state = params_state
        cont.variable_str += c
        if c == '>':
            next_state = params_ended_state
        else:
            cont.variable_params_str += c
        return next_state, None

    def array_state(c, cont: VarParseImpContext):
        next_state = array_state
        cont.variable_str += c
        if c == ']':
            next_state = array_ended_state
        else:
            cont.array_index_str += c
        return next_state, None

    # params_ended_state & array_ended_state are used to track whitespace after > or ] and before the closing )
    def params_ended_state(c, cont: VarParseImpContext):
        next_state = params_ended_state
        yield_val: Optional[ParseRetVal] = None
        cont.variable_str += c
        if c == ')':
            cont.parenthesis_balance -= 1
            parse_var_params(cont)
            yield_val = cont.get_return_tuple()
            cont.reset_return_tuple()
            next_state = literal_state
        elif c in string.whitespace:
            pass
        else:  # unrecognised character so default to literal
            next_state = discard_variable(c, cont)
        return next_state, yield_val

    def array_ended_state(c, cont: VarParseImpContext):
        next_state = array_ended_state
        yield_val: Optional[ParseRetVal] = None
        cont.variable_str += c
        if c == ')':
            cont.parenthesis_balance -= 1
            try:
                cont.array_index_int = int(cont.array_index_str)
                yield_val = cont.get_return_tuple()
                cont.reset_return_tuple()
                next_state = literal_state
            except ValueError:
                next_state = discard_variable(c, cont)
        elif c in string.whitespace:
            pass
        else:  # unrecognised character so default to literal
            next_state = discard_variable(c, cont)
        return next_state, yield_val

    cont: VarParseImpContext = VarParseImpContext()
    next_state_func: Callable[[str], VarParseImpContext] = literal_state
    for c in f_string:
        next_state_func, yield_val = next_state_func(c, cont)
        if yield_val is not None:
            yield yield_val

    # Any of the following states means that parsing stopped while in variable
    # and therefor the whole variable string becomes part of the literal text
    if next_state_func in (var_ref_started_state, var_name_state, params_state, array_state,
                      var_name_ended_state, params_ended_state, array_ended_state):
        cont.literal_text += cont.variable_str
        cont.variable_name = None
        next_state_func = literal_state         # this will force a final yield

    if next_state_func == literal_state:
        yield cont.get_return_tuple()
    else:
        raise ValueError("failed to parse "+f_string)


def resolve_variable_1(parse_retVal, default=""):
    retVal = "".join(("!", parse_retVal.variable_name))
    if parse_retVal.array_index_str is not None:
        retVal = "".join((retVal, "[", parse_retVal.array_index_str, "]"))
    if parse_retVal.variable_params_str is not None:
        retVal = "".join((retVal, "(", parse_retVal.variable_params_str, ")"))
    return retVal


def resolve_variable_2(parse_retVal, default=""):
    del parse_retVal
    return default


def parse_str(str_to_parse, var_resolver):
    parsed_str = ""
    for parse_retVal in var_parse_imp(str_to_parse):
        if parse_retVal.literal_text:
            parsed_str += parse_retVal.literal_text
        if parse_retVal.variable_name is not None:
            parsed_str += var_resolver(parse_retVal, parse_retVal.variable_str)
    return parsed_str

if __name__ == '__main__':
    strs_to_parse = [
                    ("$(a[0)", "$(a[0)"),
                    ("$(a[)", "$(a[)"),
                    ("$(a[!)", "$(a[!)"),
                    ("$(A)", "!A"),
                    ("$(A", "$(A"),
                    ("$(a)$(b<>)$(c)", "!a!b()!c"),
                    ("$(a[0])", "!a[0]"),
                    ("$(a[])", "$(a[])"),
                    ("$(a[!])", "$(a[!])"),
                    ("$(a[0]", "$(a[0]"),
                    ("$(a[]", "$(a[]"),
                    ("$(a[!]", "$(a[!]"),
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
                    ("$(a)$(b<)>)$(c)", "!a!b())!c"),
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
