#!/usr/bin/env python3


import os
import fnmatch
import inspect
from typing import List
from collections import defaultdict

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


class HelpItemYaml(HelpItemBase):
    """ help item from a yaml node
        node should be a map with keys 'short', 'long'
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
        sig = str(inspect.signature(self.obj.__init__)).replace('self, ', '').replace(' -> None', '').replace(', **kwargs', '')
        doc_for_class = self.obj.__doc__.split("\n")
        doc_list = list(filter(None, (dfc.strip() for dfc in doc_for_class)))
        self.texts['short'] = f"{self.obj.__name__}{sig}"
        self.texts['long'] = "\n".join(doc_list)


class HelpHelper(object):
    def __init__(self, instlObj) -> None:
        self.topics = defaultdict(list)
        self.help_items = dict()
        self.instlObj = instlObj

    def add_item(self, new_item, *topics):
        self.help_items[new_item.name] = new_item
        for a_topic in topics:
            self.topics[a_topic].append(new_item.name)

    def read_help_file(self, help_file_path):
        with utils.open_for_read_file_or_url(help_file_path) as open_file:
            for a_node in yaml.compose_all(open_file.fd):
                if a_node.isMapping():
                    for topic_name, topic_items_node in a_node.items():
                        for item_name, item_value_node in topic_items_node.items():
                            new_item = HelpItemYaml(item_name, item_value_node)
                            self.add_item(new_item, topic_name)

    def read_pybatch_help(self):
        for name, obj in inspect.getmembers(pybatch, lambda member: inspect.isclass(member) and member.__module__.startswith(pybatch.__name__)):
            if inspect.isclass(obj):
                if obj.__doc__:
                    new_item = HelpItemObj(obj)
                    self.add_item(new_item, "pybatch")

    def topic_summery(self, topic):
        retVal = "no such topics: " + topic
        short_list = list()
        if topic in ("command", "commands"):
            short_list.extend(self.topic_summery_for_commands())
        elif topic in self.topics:
            for item_name in self.topics[topic]:
                item = self.help_items[item_name]
                short_list.append((item.name + ":", item.short_text()))
        short_list.sort()
        if len(short_list) > 0:
            width_list = [0, 0]
            for name, short_text in short_list:
                width_list[0] = max(width_list[0], len(name))
                width_list[1] = max(width_list[1], len(short_text))
            format_list = utils.gen_col_format(width_list)
            retVal = "\n".join(format_list[2].format(name, short) for name, short in short_list)
        return retVal

    def topic_summery_for_commands(self):
        actual_command_names = list(config_vars["__COMMAND_NAMES__"])
        command_to_short_text = {name: (f"{name}:", "no help for this command") for name in actual_command_names}
        for item in list(self.help_items.values()):
            if "commands" in item.topics:
                short_text_tup = (f"{item.name}:", item.short_text())
                if item.name not in actual_command_names:
                    short_text_tup = short_text_tup[0], short_text_tup[1]+ "??? command not found ???"
                command_to_short_text[item.name] = short_text_tup
        retVal = [command_to_short_text[k] for k in command_to_short_text.keys()]
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
                item.name + ": " + item.short_text(),
                "",
                long_formatted,
                ""
            ))
        return retVal

    def defaults_help(self):
        defaults_folder_path = os.fspath(config_vars["__INSTL_DEFAULTS_FOLDER__"])
        for yaml_file in os.listdir(defaults_folder_path):
            if fnmatch.fnmatch(yaml_file, '*.yaml') and yaml_file != "P4.yaml":  # hack to not read the P4 defaults
                self.instlObj.read_yaml_file(os.path.join(defaults_folder_path, yaml_file))
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

def do_help(subject, help_folder_path, instlObj):
    hh = HelpHelper(instlObj)

    for help_file in os.listdir(help_folder_path):
        if fnmatch.fnmatch(help_file, '*help.yaml'):
            hh.read_help_file(os.path.join(help_folder_path, help_file))

    hh.read_pybatch_help()

    if not subject:
        for topic in hh.topics.keys():
            print("instl", "help", "<" + topic + ">")
        print("instl", "help", "<defaults>")
    elif subject in hh.topics.keys():
        print(hh.topic_summery(subject))
    else:
        if subject == "defaults":
            hh.defaults_help()
        else:
            for sub in hh.help_items:
                if sub.startswith(subject):
                    print(hh.item_help(sub))
