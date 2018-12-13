#!/usr/bin/env python3.6


import sys
import tarfile

def untar_em(to_untar):
    tar = tarfile.open(to_untar, "r")
    tar.extractall()
    tar.close()

if __name__ == "__main__":
    untar_em(sys.argv[1])
