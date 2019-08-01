#!/usr/bin/env python3.6

import os
import sys
import plistlib
import subprocess
import xml.etree.ElementTree as ET
import codecs
import re

import utils

if sys.platform == 'win32':
    import win32api


def default_extract_info(in_os, in_path):
    return None

plugin_version_and_guid_re = re.compile("""
    .+?
    <LicenseGUID>\s*
    (?P<guid>[a-fA-F0-9-]{36})
    \s*</LicenseGUID>
    .+
    <PluginExternalVersion>\s*
    (?P<version>\d+\.\d+\.\d+)
    (\.\d+)?
    \s*
    </PluginExternalVersion>""", re.MULTILINE | re.DOTALL | re.VERBOSE)


# cross platform
def plugin_bundle(in_os, in_path):
    retVal = None
    xml_path = os.path.join(in_path, 'Contents', 'Info.xml')
    if os.path.exists(xml_path):
        with utils.utf8_open_for_read(xml_path, "r") as rfd:
            info_xml = rfd.read()
            match = plugin_version_and_guid_re.match(info_xml)
            if match:
                retVal = (in_path, match['version'], match['guid'])
    else:
        if in_os == 'Mac':
            retVal = Mac_bundle(in_os, in_path)
        elif in_os == 'Win':
            retVal = Win_bundle(in_os, in_path)
    return retVal


def get_info_from_plugin(in_os, in_path):
    retVal = dict()
    try:
        xml_path = os.path.join(in_path, 'Contents', 'Info.xml')
        if not os.path.exists(xml_path):
            xml_path = os.path.join(in_path, 'Contents', 'Resources', 'InfoXML', '1000.xml')
        tree = ET.parse(xml_path)
        xml = tree.getroot()
        retVal['path'] = os.path.realpath(in_path)
        for child in xml.iter('LicenseGUID'):
            retVal['LicenseGUID'] = child.text.lower()
            break
        for child in xml.iter('PluginExternalVersion'):
            retVal['PluginExternalVersion'] = child.text
            break
        for child in xml.iter('WaveShellsBaseName'):
            retVal['WaveShellsBaseName'] = child.text
            break
        for child in xml.iter('ArtistDlls'):
            retVal['ArtistDlls'] = child.text
            break
        retVal['DynamicPluginLibName'] = list()
        for child in xml.iter('DynamicPluginLibName'):
            retVal['DynamicPluginLibName'].append(child.text)
    except:
        pass
    return retVal

def get_guid(in_os, in_path):
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


def get_wfi_version(in_os, in_path):
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
def Mac_bundle(in_os, in_path):
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
                guid = get_guid(in_os, in_path)

                if version or guid:
                    retVal = (in_path, version, guid)
    except Exception as ex:
        pass
    return retVal


def Mac_framework(in_os, in_path):
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


def Mac_dylib(in_os, in_path):
    """ otool is available only on systems where developer tools were installed,
        so usage of otool cannot be deployed to users
    """
    retVal = None
    try:
        out = subprocess.Popen(['otool', '-L', in_path], stdout=subprocess.PIPE).stdout
        lines = out.readlines()
        out.close()
        version = str(lines[1], 'utf-8)').strip('\n').strip(')').split(' ')[-1]
        if version:
            retVal = (in_path, version, None)
    except:
        pass
    return retVal


def Mac_pkg(in_os, in_path):
    retVal = None
    try:
        # define args
        clr_tmp = 'rm -rf /tmp/forSGDriverVersion'
        extract_pkg_to_tmp = 'pkgutil --expand %s /tmp/forSGDriverVersion' % in_path
        # clear tmp from any remaining SG driver version info
        subprocess.call(clr_tmp.split(' '))
        # extract pkg to tmp
        subprocess.call(extract_pkg_to_tmp.split(' '))
        dist_path = '/tmp/forSGDriverVersion/Distribution'
        with open(dist_path, 'r') as fo:
            lines = fo.readlines()

        version = lines[-2].split('"')[1]
        subprocess.call(clr_tmp.split(' '))
        retVal = (in_path, version, None)
    except:
        pass
    return retVal


# Windows
def Win_bundle(in_os, in_path):
    retVal = None
    try:
        dll_name = os.path.basename(in_path).replace('bundle', 'dll')
        dll_path = os.path.join(in_path, 'Contents', 'Win64', dll_name)
        if not os.path.exists(dll_path):
            dll_path = os.path.join(in_path, 'Contents', 'Win32', dll_name)
        if not os.path.exists(dll_path):
            version = None
        else:
            info = win32api.GetFileVersionInfo(dll_path, "\\")
            ms = info['FileVersionMS']
            ls = info['FileVersionLS']
            version = '%d.%d.%d.%d' % (win32api.HIWORD(ms), win32api.LOWORD(ms), win32api.HIWORD(ls), win32api.LOWORD(ls))
        if version:
            guid = get_guid(in_os, in_path)
            retVal = (in_path, version, guid)
    except:
        pass
    return retVal


def Win_aaxplugin(in_os, in_path):
    retVal = None
    try:
        dll_name = os.path.basename(in_path).replace('bundle', 'aaxplugin')
        dll_path = os.path.join(in_path, 'Contents', 'x64', dll_name)
        try:
            info = win32api.GetFileVersionInfo(dll_path, "\\")
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


def Win_file(in_os, in_path):
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
    retVal = func(in_os, in_path)
    return retVal


extract_info_funcs_by_extension = {
    'Mac': {
        '.bundle': plugin_bundle,
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
        '.bundle': plugin_bundle,
        '.aaxplugin': Win_aaxplugin,
        '.exe': Win_file,
        '.dll': Win_file,
        '.dpm': Win_file,
        '.vst3': Win_file,
        '.wfi': get_wfi_version
        }
}


class check_binaries_versions_filter_with_ignore_regexes(object):
    def __init__(self, ignore_file_regexes=[".^"], ignore_folder_regexes=[".^"]):
        self.compiled_ignore_file_regex = None
        self.compiled_ignore_folder_regex = None
        self.set_file_ignore_regexes(ignore_file_regexes)
        self.set_folder_ignore_regexes(ignore_folder_regexes)

    def set_file_ignore_regexes(self, file_ignore_regex_list):
        self.compiled_ignore_file_regex  = utils.compile_regex_list_ORed(file_ignore_regex_list)

    def set_folder_ignore_regexes(self, folder_ignore_regex_list):
        self.compiled_ignore_folder_regex  = utils.compile_regex_list_ORed(folder_ignore_regex_list)

    def __call__(self, in_path):
        retVal = True
        if os.path.isfile(in_path):
            if self.compiled_ignore_file_regex.search(in_path):
                retVal = False
        elif os.path.isdir(in_path):
            if self.compiled_ignore_folder_regex.search(in_path):
                retVal = False
        return retVal


def check_binaries_versions_in_folder(current_os, in_path, in_filter=lambda p: True):
    retVal = list()
    for root_path, dirs, files in os.walk(in_path, followlinks=False):
        if not in_filter(root_path):
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
                    if not in_filter(file_full_path):
                        continue
                    if not os.path.islink(file_full_path):
                        info = extract_binary_info(current_os, file_full_path)
                        if info is not None:
                            retVal.append(info)
    return retVal
