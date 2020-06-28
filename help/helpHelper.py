#!/usr/bin/env python3.6


import os
import fnmatch
import inspect
from typing import List
from collections import defaultdict
from pathlib import Path

import yaml

import utils
from configVar import config_vars
import pybatch


class HelpItemBase(object):
    def __init__(self, name) -> None:
        self.name = name
        self.texts = dict()

    def get_help_texts(self):
        raise NotImplementedError(f"HelpItemBase did not implement get_help_texts")

    def short_text(self):
        if not self.texts:
            self.get_help_texts()
        retVal = self.texts.get("short", "")
        return retVal

    def long_text(self):
        if not self.texts:
            self.get_help_texts()
        retVal = self.texts.get("long", "")
        return retVal


class HelpItemFixed(HelpItemBase):
    """ help item initialized from code """
    def __init__(self, name, help_text_dict) -> None:
        super().__init__(name)
        self.texts.update(help_text_dict)

    def get_help_texts(self):
        pass  # help text already initialized in __init__


class HelpItemYaml(HelpItemBase):
    """ help item from a yaml node
        item_node should be a map with keys 'short', 'long'
    """
    def __init__(self, name, item_node) -> None:
        super().__init__(name)
        self.item_node = item_node

    def get_help_texts(self):
        for value_name, value_text in self.item_node.items():
            self.texts[value_name] = value_text.value


class HelpItemObj(HelpItemBase):
    """ help item from a class declaration (the "obj")
        signature of obj.__init__ is the 'short' help text
        obj.__doc__ is the 'long' help text
    """
    def __init__(self, obj) -> None:
        super().__init__(obj.__name__)
        self.obj = obj

    def get_help_texts(self):
        def get_full_dict_strings(obj):
            """ get class members that are strings from obj's class in super classes """
            retVal = dict()
            for cls in obj.mro():
                if cls.__name__ != "object":
                    for k, v in cls.__dict__.items():
                        if isinstance(v, str):
                            retVal[k] = v.strip()
            return retVal

        def prepare_doc_string(doc_str):
            lines = list(filter(None, [line.strip() for line in doc_str.split("\n")]))
            retVal = "\n".join(lines)
            return retVal

        sig = str(inspect.signature(self.obj.__init__)).replace('self, ', '').replace(' -> None', '').replace(', **kwargs', '')
        #doc_for_class = self.obj.__doc__.split("\n")
        #doc_list = list(filter(None, (dfc.strip() for dfc in doc_for_class)))
        self.texts['short'] = f"{self.obj.__name__}{sig}"
        dict_o_strings = get_full_dict_strings(self.obj)
        long_text = prepare_doc_string(self.obj.__doc__).format(**dict_o_strings)
        self.texts['long'] = long_text


class HelpHelper(object):
    def __init__(self, instlObj, help_folder_path: Path) -> None:
        self.help_items = dict()
        self.topic_items = defaultdict(list)
        self.instlObj = instlObj

        for help_file in os.listdir(help_folder_path):
            if fnmatch.fnmatch(help_file, '*help.yaml'):
                help_file_path = help_folder_path.joinpath(help_file)
                self.read_help_file(help_file_path)

        self.read_pybatch_help()
        self.additional_commands_help()

    def add_item(self, new_item, *topics):
        self.help_items[new_item.name] = new_item
        for a_topic in topics:
            self.topic_items[a_topic].append(new_item.name)

    def read_help_file(self, help_file_path):
        with utils.utf8_open_for_read(help_file_path) as open_file:
            for a_node in yaml.compose_all(open_file):
                if a_node.isMapping():
                    for topic_name, topic_items_node in a_node.items():
                        for item_name, item_value_node in topic_items_node.items():
                            new_item = HelpItemYaml(item_name, item_value_node)
                            self.add_item(new_item, topic_name)

    def additional_commands_help(self):
        """  add help items for commands that do not have help text in .yaml file
        """
        actual_command_names = list(config_vars["__COMMAND_NAMES__"])
        for command_name in actual_command_names:
            if command_name not in self.topic_items['command']:
                new_item = HelpItemFixed(command_name, {"short": "no help for this command"})
                self.add_item(new_item, "command")

    def read_pybatch_help(self):
        for name, obj in inspect.getmembers(pybatch, lambda member: inspect.isclass(member) and member.__module__.startswith(pybatch.__name__)):
            if inspect.isclass(obj):
                if obj.__doc__:
                    new_item = HelpItemObj(obj)
                    self.add_item(new_item, "pybatch")

    def topic_summery(self, topic):
        retVal = "no such topics: " + topic
        short_list = list()
        if topic in self.topic_items:
            for item_name in self.topic_items[topic]:
                short_list.append((item_name + ":", self.help_items[item_name].short_text()))
        short_list.sort()
        if len(short_list) > 0:
            width_list = [0, 0]
            for name, short_text in short_list:
                width_list[0] = max(width_list[0], len(name))
                width_list[1] = max(width_list[1], len(short_text))
            format_list = utils.gen_col_format(width_list)
            retVal = "\n".join(format_list[2].format(name, short) for name, short in short_list)
        return retVal

    def item_help(self, item_name):
        retVal = "no such item: " + item_name
        item = self.help_items.get(item_name)
        if item:
            import textwrap

            long_formatted = "\n\n".join([textwrap.fill(line, 200,
                                                       replace_whitespace=False,
                                                       initial_indent='    ',
                                                       subsequent_indent='    ') for line in
                                         item.long_text().splitlines()])
            retVal = "\n".join((
                item.name + ":\n" + item.short_text(),
                item.long_text(),
            ))
        return retVal

    def defaults_help(self, var_name=None):
        defaults_folder_path = config_vars["__INSTL_DEFAULTS_FOLDER__"].Path()
        for yaml_file in os.listdir(defaults_folder_path):
            if fnmatch.fnmatch(yaml_file, '*.yaml'):
                self.instlObj.read_yaml_file(defaults_folder_path.joinpath(yaml_file))
        defaults_list = [("Variable name", "Raw value", "Resolved value"),
                         ("_____________", "_________", "______________")]
        for var in sorted(config_vars.keys()):
            if not var.startswith("__"):
                raw_value = config_vars[var].raw(join_sep=" ")
                resolved_value = str(config_vars[var])
                if raw_value != resolved_value:
                    defaults_list.append((var, raw_value, resolved_value))
                else:
                    defaults_list.append((var, raw_value))

        width_list, align_list = utils.max_widths(defaults_list)
        col_format = utils.gen_col_format(width_list, align_list)
        for res_line in defaults_list:
            a_line = col_format[len(res_line)].format(*res_line)
            print(a_line)

    def print_help(self, subject):
        if not subject:
            for topic_name in sorted(self.topic_items.keys()):
                if topic_name != "topic":
                    print(f"instl help <{topic_name}>: {self.help_items[topic_name].short_text()}")
            if "topic" in self.topic_items:
                print(f"""instl help <topic>: {self.help_items["topic"].short_text()}""")
        elif subject in self.topic_items.keys():
            print(self.topic_summery(subject))
        else:
            if subject == "defaults":
                self.defaults_help()
            else:
                subject_lower_case = subject.lower()
                for sub in self.help_items:
                    if sub.lower().startswith(subject_lower_case):
                        print(self.item_help(sub))


def do_help(subject, help_folder_path, instlObj):
    hh = HelpHelper(instlObj, help_folder_path)
    hh.print_help(subject)
