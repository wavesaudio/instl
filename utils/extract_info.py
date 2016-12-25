#!/usr/bin/env python3

import os
import plistlib


def default_extract_info(in_path):
    return None


def Mac_bundle(in_path):
    retVal = None
    plist_path = os.path.join(in_path, 'Contents/Info.plist')
    if os.path.exists(plist_path):
        with open(plist_path, 'rb') as fp:
            pl = plistlib.load(fp)
            version = pl.get('CFBundleShortVersionString')
            if version:
                retVal = (in_path, version, None)
    return retVal


def Mac_framework(in_path):
    retVal = None
    plist_path = os.path.join(in_path, 'Versions/Current/Resources/Info.plist')
    if os.path.exists(plist_path):
        with open(plist_path, 'rb') as fp:
            pl = plistlib.load(fp)
            version = pl.get('CFBundleShortVersionString')
            if version:
                retVal = (in_path, version, None)
    return retVal


def Win_bundle(in_path):
    pass


def Win_exe(in_path):
    pass

extract_info_funcs_by_extension = {
    'Mac': {
        '.bundle': Mac_bundle,
        '.aaxplugin': Mac_bundle,
        '.component': Mac_bundle,
        '.app': Mac_bundle,
        '.framework': Mac_framework,
        },
    'Win': {
        '.bundle': Win_bundle,
        '.exe': Win_exe,
        }
}


def extract_binary_info(in_os, in_path):
    filename, file_extension = os.path.splitext(in_path)
    func = extract_info_funcs_by_extension[in_os].get(file_extension, default_extract_info)
    retVal = func(in_path)
    return retVal
