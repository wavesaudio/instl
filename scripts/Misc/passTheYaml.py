#!/usr/local/bin/python

import sys
import yaml

if __name__ == "__main__":
    for file_path in sys.argv[1:]:
        with open(file_path, "r") as file_fd:
            for a_node in yaml.compose_all(file_fd):
                print yaml.serialize(a_node)
                print a_node
                print '========='
