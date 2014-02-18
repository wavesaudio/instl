#!/usr/bin/env python2.7
from __future__ import print_function

import fnmatch
import yaml
from pyinstl.utils import *

class HelpItem(object):
    def __init__(self, topic, name):
        self.topic = topic
        self.name = name
        self.texts = dict()

    def read_from_yaml(self, item_value_node):
        for value_name, value_text in item_value_node:
            self.texts[value_name] = value_text.value

    def short_text(self):
        return self.texts.get("short", "?")

    def long_text(self):
        return self.texts.get("long", "")

class HelpHelper(object):
    def __init__(self):
        self.help_items = dict()

    def read_help_file(self, help_file_path):
        with open_for_read_file_or_url(help_file_path, None) as file_fd:
            for a_node in yaml.compose_all(file_fd):
                if a_node.isMapping():
                    for topic_name, topic_items_node  in a_node:
                        for item_name, item_value_node  in topic_items_node:
                            newItem = HelpItem(topic_name, item_name)
                            newItem.read_from_yaml(item_value_node)
                            self.help_items[item_name] = newItem

    def topics(self):
        topics = set()
        for item in self.help_items.values():
            topics.add(item.topic)
        return topics

    def topic_summery(self, topic):
        retVal = "no such topic: "+topic
        short_list = list()
        for item in self.help_items.values():
            if item.topic == topic:
                short_list.append( (item.name+":", item.short_text()) )
        short_list.sort()
        if len(short_list) > 0:
            width_list = [0, 0]
            for name, short_text in short_list:
                width_list[0] = max(width_list[0], len(name))
                width_list[1] = max(width_list[1], len(short_text))
            format_list = gen_col_format(width_list)
            retVal = "\n".join(format_list[2].format(name, short) for name, short in short_list)
        return retVal

    def item_help(self, item_name):
        retVal = "no such item: "+item_name
        item = self.help_items.get(item_name)
        if item:
            import textwrap
            long_formated = "\n\n".join([textwrap.fill(line, 90,
                                          replace_whitespace=False,
                                          initial_indent='    ',
                                          subsequent_indent='    ')for line in item.long_text().splitlines()])
            retVal = "\n".join((
                            item.name+": "+item.short_text(),
                            "",
                            long_formated
                            ))
        return retVal

def do_help(subject, help_folder_path):
    hh = HelpHelper()
    for help_file in os.listdir(help_folder_path):
        if fnmatch.fnmatch(help_file, '*help.yaml'):
            hh.read_help_file(os.path.join(help_folder_path, help_file))

    help_file_path = os.path.join(os.environ.get("_MEIPASS2", ""), "pyinstl/help/instl_help.yaml")
    if not subject:
        for topic in hh.topics():
            print("instl", "help", "<"+topic+">")
    elif subject in hh.topics():
        print(hh.topic_summery(subject))
    else:
        print(hh.item_help(subject))