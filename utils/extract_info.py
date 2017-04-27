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
    try:
        xml_path = os.path.join(in_path, 'Contents', 'Resources', 'InfoXML', '1000.xml')
        if os.path.exists(xml_path):
            tree = ET.parse(xml_path)
            xml = tree.getroot()
            for child in xml.iter('LicenseGUID'):
                guid = child.text.lower()
    except:
        pass
    return guid


def get_wfi_version(in_path):
    retVal = None
    try:
        version = None
        version_str = 'comment version'
        if 'SGS' in in_path:
            version_str = 'version value'
        with codecs.open(in_path, 'r', encoding='utf-8', errors='ignore') as rfd:
            for line in rfd:
                if version_str in line:
                    version = line.split('"')[1]
                    break
        if version:
            retVal = (in_path, version, None)
    except:
        pass
    return retVal


# Mac
def Mac_bundle(in_path):
    retVal = None
    try:
        plist_path = os.path.join(in_path, 'Contents/Info.plist')
        if os.path.exists(plist_path):
            with open(plist_path, 'rb') as fp:
                pl = plistlib.load(fp)
                version = pl.get('CFBundleGetInfoString', "").split()
                if len(version) > 0:
                    version = version[0]
                else:
                    version = None
                guid = get_guid(in_path)

                if version or guid:
                    retVal = (in_path, version, guid)
    except:
        pass
    return retVal


def Mac_framework(in_path):
    retVal = None
    try:
        plist_path = os.path.join(in_path, 'Versions/Current/Resources/Info.plist')
        if os.path.exists(plist_path):
            with open(plist_path, 'rb') as fp:
                pl = plistlib.load(fp)
                version = pl.get('CFBundleGetInfoString', "").split()
                if len(version) > 0:
                    version = version[0]
                else:
                    version = None
                if version:
                    retVal = (in_path, version, None)
    except:
        pass
    return retVal


def Mac_dylib(in_path):
    """ otool is available only on systems where developer tools were installed,
        so usage of otool cannot be deployed to users
    """
    retVal = None
    try:
        out = subprocess.Popen(['otool', '-L', in_path], stdout=subprocess.PIPE).stdout
        lines = out.readlines()
        out.close()
        #print ('DEBUG: lines =', lines)
        #lines = out_string.split('\n')
        version = str(lines[1], 'utf-8)').strip('\n').strip(')').split(' ')[-1]
        if version:
            retVal = (in_path, version, None)
    except:
        pass
    return retVal


def Mac_pkg(in_path):
    retVal = None
    try:
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
    except:
        pass
    return retVal


# Windows
def Win_bundle(in_path):
    retVal = None
    try:
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
    except:
        pass
    return retVal


def Win_aaxplugin(in_path):
    retVal = None
    try:
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
    except:
        pass
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
        #  '.dylib': Mac_dylib,  # otool is available only on systems where developer tools were installed, so usage of otool cannot be deployed to users
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


def check_binaries_versions_in_folder(current_os, in_path, in_compiled_ignore_folder_regex, in_compiled_ignore_file_regex):
    retVal = list()
    for root_path, dirs, files in os.walk(in_path, followlinks=False):
        if in_compiled_ignore_folder_regex and in_compiled_ignore_folder_regex.search(root_path):
            del dirs[:]  # skip root_path and it's siblings
            del files[:]
        else:
            info = extract_binary_info(current_os, root_path)
            if info is not None:
                retVal.append(info)
                del dirs[:]  # info was found for root_path, no need to dig deeper
                del files[:]
            else:
                for a_file in files:
                    file_full_path = os.path.join(root_path, a_file)
                    if in_compiled_ignore_file_regex and in_compiled_ignore_file_regex.search(file_full_path):
                        continue
                    if not os.path.islink(file_full_path):
                        info = extract_binary_info(current_os, file_full_path)
                        if info is not None:
                            retVal.append(info)
    return retVal



