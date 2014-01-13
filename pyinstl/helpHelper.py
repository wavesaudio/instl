#!/usr/bin/env python2.7
from __future__ import print_function
import yaml
from collections import defaultdict
from pyinstl.utils import *

class HelpHelper(object):
    def __init__(self, search_paths_helper=None):
        self.search_paths_helper = search_paths_helper
        self.help_topics = defaultdict(dict)

    def read_help_file(self, help_file_path):
        with open_for_read_file_or_url(help_file_path, self.search_paths_helper) as file_fd:
            for a_node in yaml.compose_all(file_fd):
                if a_node.isSequence():
                    for sub_node in a_node:
                        if sub_node.isMapping():
                            sub_node_dict = {name: val.value for name, val in sub_node}
                            self.help_topics[sub_node_dict['type']][sub_node_dict['name']] = sub_node_dict

    def topics(self):
        return elf.help_topics.keys()

    def type_summery(self, type):
        retVal = "no such topic: "+type
        if type in self.help_topics:
            short_list = list()
            for name, val in self.help_topics[type].iteritems():
                short_list.append( (name, val['short']) )
            retVal = "\n".join(name+": "+short for name, short in short_list)
        return retVal

