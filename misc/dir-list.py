#!/usr/bin/env python
from __future__ import print_function

import sys
import os

def list_folder(folder):
    for root, dirs, files in os.walk(folder):
        prefix_len = len(folder) + 1
        for afile in files:
            afile_path = os.path.join(root, afile)
            astat = os.stat(afile_path)
            print(afile_path[prefix_len:], astat.st_ino, astat.st_nlink)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        for folder in sys.argv[1:]:
            list_folder(folder)
