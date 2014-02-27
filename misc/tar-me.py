#!/usr/bin/env python2.7
from __future__ import print_function
#/opt/local/bin/gnutar  -c -M --tape-length=1024 --file=archive.{0..100} --new-volume-script='touch archive.${TAR_VOLUME}'  s3-mac-sync.command.before

import os
import sys
import tarfile

def tar_em(to_tar):
    tar = tarfile.open(to_tar+".tar", "w")
    tar_gz = tarfile.open(to_tar+".tar.gz", "w:gz")
    tar_bz2 = tarfile.open(to_tar+".tar.bz2", "w:bz2")
    tar.add(to_tar)
    tar_gz.add(to_tar)
    tar_bz2.add(to_tar)
    tar.close()
    tar_gz.close()
    tar_bz2.close()
    
if __name__ == "__main__":
    tar_em(sys.argv[1])
