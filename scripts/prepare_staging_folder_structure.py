#! /usr/local/bin/python

""" Creates the skeleton folder structure for a full staging folder
    Staging folder must exist and be the current working directory.
"""
import os

versions = ("V8", "V9","V10")
oses = ("Mac", "Win")
folders = ("Applications", "MultiRack", "ReWire", "SoundGrid", "Plugins", "Shells")

for ver in versions:
    for os_name in oses:
        for folder in folders:
            folder_path = os.path.join(ver, os_name, folder)
            if os.path.isfile(folder_path):
                raise folder_path+" exists and is a file"
            elif not os.path.isdir(folder_path):
                os.makedirs(folder_path)
            if not os.path.isdir(folder_path):
                raise folder_path+" failed to create"
