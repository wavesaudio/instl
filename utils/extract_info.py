#!/usr/bin/env python3

import os
import sys
import plistlib
import subprocess
import xml.etree.ElementTree as ET
import re
import codecs

if sys.platform == 'win32':
    import win32api


def default_extract_info(in_path):
    return None

# cross platform

def get_guid(in_path):
    guid = None
    xml_path = os.path.join(in_path, 'Contents', 'Resources', 'InfoXML', '1000.xml')
    if os.path.exists(xml_path):
        tree = ET.parse(xml_path)
        xml = tree.getroot()
        for child in xml.iter('LicenseGUID'):
            guid = child.text.lower()

    return guid


def get_wfi_version(in_path):
    #print ('DEGUB: checking version for: %s' % os.path.basename(in_path))
    retVal = None
    version = None
    with codecs.open(in_path, 'r', encoding='utf-8', errors='ignore') as f:
        raw = f.readlines()
        #print('DEBUG: raw =', type(raw), raw)
    for line in raw:
        if 'version value' in line:
            #print('DEBUG: line =', type(line), line)
            version = line.split('"')[1]
            # print 'wfi version string =', version
            break
    if version:
        retVal = (in_path, version, None)
    return retVal

# Mac

def Mac_bundle(in_path):
    retVal = None
    plist_path = os.path.join(in_path, 'Contents/Info.plist')
    if os.path.exists(plist_path):
        with open(plist_path, 'rb') as fp:
            pl = plistlib.load(fp)
            version = pl.get('CFBundleGetInfoString').split(' ')[0]
            guid = get_guid(in_path)

            if version:
                retVal = (in_path, version, guid)
    return retVal


def Mac_framework(in_path):
    retVal = None
    plist_path = os.path.join(in_path, 'Versions/Current/Resources/Info.plist')
    if os.path.exists(plist_path):
        with open(plist_path, 'rb') as fp:
            pl = plistlib.load(fp)
            version = pl.get('CFBundleGetInfoString').split(' ')[0]
            if version:
                retVal = (in_path, version, None)
    return retVal


def Mac_dylib(in_path):
    retVal = None
    #ipdpath = '/Library/Application Support/Waves/Modules/InnerProcessDictionary.dylib'
    out = subprocess.Popen(['otool', '-L', in_path], stdout=subprocess.PIPE).stdout
    lines = out.readlines()
    out.close()
    #print ('DEBUG: lines =', lines)
    #lines = out_string.split('\n')
    version = str(lines[1], 'utf-8)').strip('\n').strip(')').split(' ')[-1]
    if version:
        retVal = (in_path, version, None)
    return retVal


def Mac_pkg(in_path):
    retVal = None

    # define args
    clr_tmp = 'rm -rf /tmp/forSGDriverVersion'
    extract_pkg_to_tmp = 'pkgutil --expand %s /tmp/forSGDriverVersion' % in_path
    # clear tmp from any remaining SGdriver version info
    subprocess.call(clr_tmp.split(' '))
    # extract pkg to tmp
    subprocess.call(extract_pkg_to_tmp.split(' '))
    dist_path = '/tmp/forSGDriverVersion/Distribution'
    with open (dist_path, 'r') as fo:
        lines = fo.readlines()

    version = lines[-2].split('"')[1]
    #clear tmp
    subprocess.call(clr_tmp.split(' '))
    retVal = (in_path, version, None)
    return retVal

# Windows

def Win_bundle(in_path):
    retVal = None
    dllname = os.path.basename(in_path).replace('bundle', 'dll')
    dllpath = os.path.join(in_path, 'Contents', 'Win64', dllname)
    if not os.path.exists(dllpath):
        dllpath = os.path.join(in_path, 'Contents', 'Win32', dllname)
    if not os.path.exists(dllpath):
        version = None
    else:
        info = win32api.GetFileVersionInfo(dllpath, "\\")
        ms = info['FileVersionMS']
        ls = info['FileVersionLS']
        version = '%d.%d.%d.%d' % (win32api.HIWORD(ms), win32api.LOWORD(ms), win32api.HIWORD(ls), win32api.LOWORD(ls))
    if version:
        guid = get_guid(in_path)
        retVal = (in_path, version, guid)
    return retVal


def Win_aaxplugin(in_path):
    retVal = None
    dllname = os.path.basename(in_path).replace('bundle', 'aaxplugin')
    dllpath = os.path.join(in_path, 'Contents', 'x64', dllname)
    try:
        info = win32api.GetFileVersionInfo(dllpath, "\\")
        ms = info['FileVersionMS']
        ls = info['FileVersionLS']
    except:
        version = None
    else:
        version = '%d.%d.%d.%d' % (win32api.HIWORD(ms), win32api.LOWORD(ms), win32api.HIWORD(ls), win32api.LOWORD(ls))
    if version:
        retVal = (in_path, version, None)
    return retVal


def Win_file(in_path):
    retVal = None
    try:
        info = win32api.GetFileVersionInfo(in_path, "\\")
        ms = info['FileVersionMS']
        ls = info['FileVersionLS']
    except:
        version = None
    else:
        version = '%d.%d.%d.%d' % (win32api.HIWORD(ms), win32api.LOWORD(ms), win32api.HIWORD(ls), win32api.LOWORD(ls))
    if version:
        retVal = (in_path, version, None)
    return retVal



def extract_binary_info(in_os, in_path):
    filename, file_extension = os.path.splitext(in_path)
    func = extract_info_funcs_by_extension[in_os].get(file_extension, default_extract_info)
    retVal = func(in_path)
    return retVal


extract_info_funcs_by_extension = {
    'Mac': {
        '.bundle': Mac_bundle,
        '.dpm': Mac_bundle,
        '.vst': Mac_bundle,
        '.vst3': Mac_bundle,
        '.aaxplugin': Mac_bundle,
        '.component': Mac_bundle,
        '.app': Mac_bundle,
        '.framework': Mac_framework,
        '.dylib': Mac_dylib,
        '.pkg': Mac_pkg,
        '.wfi': get_wfi_version
        },
    'Win': {
        '.bundle': Win_bundle,
        '.aaxplugin': Win_aaxplugin,
        '.exe': Win_file,
        '.dll': Win_file,
        '.dpm': Win_file,
        '.vst3': Win_file,
        '.wfi': get_wfi_version
        }
}



