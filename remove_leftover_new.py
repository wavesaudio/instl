#!/usr/bin/env python3
# Go over bundles check info list, check version, go over the shell
# and see that there is no compatible version artists dll with waves lib - both direction?
# 1. Scan all plugins and get the info (plugin/ shells ) create some table
# 2. What should we do with it ?
# 3. Go over per each items and what was decided and see what’s  what

# Scan all plug-ins in the different installed major version plug-ins folders, use the Info.xml to identify the “required” files/folders,
# and analyze and remove the unreferenced ones

# first create the scanning thingy and create the table: used/unused
# Scan all plug-ins in the different installed major version plug-ins folders, use the Info.xml to identify the “required” files/folders,
# and analyze and remove the unreferenced ones
# take a look at required_shells - exapand it to artists dlls and waveslib

# breakdown::
# scan:
# what are the relevant plugins folders?
# per folder: scan it's info.xml and get the required

import os
import xml.dom.minidom
import re
from pybatch import *
from configVar import config_vars

MAX_PLUGIN_VERSION = 12
MIN_PLUGIN_VERSION = 9


def get_possible_plugins_folders(waves_main_folder):
    global MAX_PLUGIN_VERSION, MIN_PLUGIN_VERSION
    plugin_folders = {}
    for i in range(MIN_PLUGIN_VERSION, MAX_PLUGIN_VERSION + 1):
        plugin_folders[i] = {'used': waves_main_folder / f'Plug-Ins V{i}',
                             'unused': waves_main_folder / f'Unused Plug-Ins V{i}'}
    return plugin_folders


def find_resoruces(folder_path, resource, search_format='*/{}'):
    """Return Path object for the relevant path according to the resource"""
    return [Path(file_path) for file_path in Path(folder_path).glob(search_format.format(resource))]


def find_existing_path_by_expr(paths,expr='WaveShell'):
    exists_folders = [find_resoruces(_path, expr, '{}*') for k, _path in paths.items()]
    return list(itertools.chain.from_iterable(exists_folders))


# TODO: switch with variables from config_vars?
def get_shells_system_paths():
    if sys.platform == 'darwin':
        system_plugin_paths = {
            'AAX': Path('/Library', 'Application Support', 'Avid', 'Audio', 'Plug-Ins'),  # Avid
            'DAE': Path('/Library', 'Application Support', 'Digidesign', 'Plug-Ins'),
            'AU': Path('/Library', 'Audio', 'Plug-Ins', 'Components'),
            'VST3': Path('/Library', 'Audio', 'Plug-Ins', 'VST3'),
            'VST': Path('/Library', 'Audio', 'Plug-Ins', 'VST'),
            'WPAPI_1': Path('/Library', 'Audio', 'Plug-Ins', 'WPAPI'),
            'WPAPI_2': Path('/Library', 'Audio', 'Plug-Ins', 'WPAPI')  # TODO:??
        }
        return system_plugin_paths




# todo: cross this data with the data you found from parsing the plugins info.xml
def get_waveslib_parent_path():  # think of changin the name
    """ return paths of all existing  waveslib in all existing plugins folder"""
    waveslib_paths = get_possible_plugins_folders(waves_main_folder)
    used_waveslib_paths = [_path for key, path in waveslib_paths.items() for is_used, _path in path.items() if
                           is_used == "used"]
    used_waveslib_paths = {i: val for i, val in enumerate(used_waveslib_paths)}
    exists_waveslib = [find_resoruces(_path, 'WavesLib', '{}*') for k, _path in used_waveslib_paths.items()]
    return list(itertools.chain.from_iterable(exists_waveslib))


# for example :/Applications/Waves/Plug-Ins V11/WavesLib1.2_11.0.framework


def filter_bundles_from_list(plugins_exists, product_to_filter="Insert"):
    bundles_to_filter = [p for p in plugins_exists if p['product_name'] == product_to_filter]
    for to_filter in bundles_to_filter:
        plugins_exists.remove(to_filter)

        # waves_lib_basename[0].attributes._attrs['OS'].firstChild.data


def get_data_from_xml_by_tag_name(xmldoc, tag_name, tag_idx=0):
    return xmldoc.getElementsByTagName(tag_name)[tag_idx].firstChild.data


def get_relevant_waveslib_index(xmldoc, tag_name, os_type="Mac"):
    tags_list = xmldoc.getElementsByTagName(tag_name)
    for idx, tag in enumerate(tags_list):
        if tag.attributes._attrs['OS'].firstChild.data == os_type:
            return idx


# TODO: this function seems way to long, think of a way to shorten it
def parse_plugin(plugin_path):
    '''A function that parses the info xml of a plugin and stores the data in a dictionary for all plugins'''
    info_xml = str(find_resoruces(plugin_path, 'Info.xml')[0])
    try:
        xmldoc = xml.dom.minidom.parse(info_xml)
        license_guid = get_data_from_xml_by_tag_name(xmldoc, "LicenseGUID")
        version = get_data_from_xml_by_tag_name(xmldoc, "PluginExternalVersion")
        waveshell_basename = get_data_from_xml_by_tag_name(xmldoc, "WaveShellsBaseName")
        artist_dll_basename = get_data_from_xml_by_tag_name(xmldoc, "ArtistDlls")
        waves_lib_version = get_data_from_xml_by_tag_name(xmldoc,
                                                          "WavesLibExternalVersion")  # TODO: is this really needed?
        relevant_os_idx = get_relevant_waveslib_index(xmldoc, "DynamicPluginLibName")
        waves_lib_basename = get_data_from_xml_by_tag_name(xmldoc, "DynamicPluginLibName", relevant_os_idx)
        major_minor = version.split(".")[0] + "." + version.split(".")[1]
        # TODO: maybe this returned dict can also be transfered to a callable class or function which will return it according to some enum?
        return {'product_name': Path(plugin_path).stem
            , 'version': int(version.split('.')[0])  #
            , 'guid': license_guid
            , 'src_path': plugin_path
            , 'dst_path': ''  # TODO: is this item can be relevant?
            , 'shell_name': waveshell_basename
            , 'wavesshell': f"{waveshell_basename}-{major_minor}"
            , 'wavesshell_rgx': f"{waveshell_basename}.*{major_minor}"  # constructing Referenced Shells according to requirements
            , "waveslib": waves_lib_basename
            , "waveslib_rgx": f"{waves_lib_basename.split('/')[0]}.*"
            , "artist_dll": artist_dll_basename
            , "artist_dll_rgx": artist_dll_basename
            }
    except Exception as e:
        log.info(f'Exception in parsing {info_xml} --- {e}')
        raise e


def sort_plugins_by_guid_version(plugin_folders):
    """return a sorted list of dictionary, where each item has the relevant info extracted from the info.xml """
    plugins_list = []
    for p_folders in plugin_folders.values():
        for plugin_folder in p_folders.values():
            if not os.path.exists(plugin_folder):
                continue
            for plugin_path in list(plugin_folder.glob('*.bundle')):
                try:
                    plugin_info = parse_plugin(plugin_path)  # TODO: what is the return value here?
                except IndexError:
                    log.info(f'cannot find Info.xml file in {plugin_path}')
                    continue
                except Exception:
                    continue
                plugins_list.append(plugin_info)
    plugins_sorted = sorted(plugins_list, key=lambda p: (p['guid'], p['version']), reverse=True)
    return plugins_sorted


def get_all_unref_items(path, type='all'):
    pass


def get_folders_to_remove(folders, plugins_info_table, type_to_remove='waveslib_rgx'):
    to_be_left_out = []
    # folder_names = list(map(lambda folder: folder.stem, folders))
    for info in plugins_info_table:
        searched_item = Path(info[type_to_remove])
        searched_item = searched_item.parts[0]
        for folder in folders:
            # TODO: might change this code
            if re.search(searched_item,folder.name) and folder not in to_be_left_out:
            # if folder.stem in searched_item and folder not in to_be_left_out:
                to_be_left_out.append(folder)
    to_be_removed = [folder for folder in folders if folder not in to_be_left_out]
    return to_be_removed

waves_main_folder = Path('/Applications', 'Waves')  # TODO: extract from index?

to_be_removed = {}
plugins_folders = get_possible_plugins_folders(waves_main_folder)
used_plugins_folder_dict = {f"used{key}":_path for key, path in plugins_folders.items() for is_used, _path in path.items() if is_used=="used"}
unused_plugins_folder_dict = {f"unused{key}":_path for key, path in plugins_folders.items() for is_used, _path in path.items() if is_used=="unused"}
if True: #can be here something like a pram
    used_plugins_folder_dict.update(unused_plugins_folder_dict)
waveslib = get_waveslib_parent_path()
shells = find_existing_path_by_expr( get_shells_system_paths(),"WaveShell")
artistDlls = find_existing_path_by_expr(used_plugins_folder_dict,"ArtistDlls")
plugins_info_table = sort_plugins_by_guid_version(plugins_folders)
to_be_removed['waveslib'] = get_folders_to_remove(waveslib, plugins_info_table)
to_be_removed['wavesshell'] = get_folders_to_remove(shells, plugins_info_table,'wavesshell_rgx')
to_be_removed['artistDlls'] = get_folders_to_remove(artistDlls, plugins_info_table,'artist_dll_rgx')




print(plugins_info_table)
