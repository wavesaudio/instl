#!/usr/bin/env python2.7
from __future__ import print_function
#/opt/local/bin/gnutar  -c -M --tape-length=1024 --file=archive.{0..100} --new-volume-script='touch archive.${TAR_VOLUME}'  s3-mac-sync.command.before

import os
import sys
import tarfile

def untar_em(to_untar):
    tar = tarfile.open(to_untar, "r")
    tar.extractall()
    tar.close()
    
if __name__ == "__main__":
    untar_em(sys.argv[1])
