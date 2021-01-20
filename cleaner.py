#!/usr/bin/env python3
import json
import sys
from collections import namedtuple
from subprocess import PIPE, run
import utils
from pybatch import *

MAX_PLUGIN_VERSION = 12
MIN_PLUGIN_VERSION = 9
INCLUDE_UNUSED = False


class WleAux:  # TODO: change this name once you see what is the functionallity moved

    @staticmethod
    def get_licenses(plugins_sorted):
        ''' A wle action that runs the licenses command and return a dictionary with the latest licenses'''
        wle_exec = config_vars.get('WLE_EXEC_PATH', None)
        if wle_exec:
            wle_exec = Path(config_vars['WLE_EXEC_PATH'])
        wle_exec_path = Path(config_vars['WLE_EXEC_REL_PATH'])
        latest = {}
        GuidFields = namedtuple('GuidFields', ('guid', 'version', 'expired', 'name'))
        if not os.path.exists(wle_exec):
            log.info('WLE NOT FOUND IN WAVES FOLDER!')
            # could have made a direct path to central's wle but since there is an option where it won't be installed to the
            # default folder it is made this way
            wle_exec = os.path.join(os.path.dirname(sys.argv[0]), os.pardir, os.pardir, os.pardir, wle_exec_path)
            if not os.path.exists(wle_exec):
                log.info(f'WLE NOT FOUND IN WAVES CENTRAL FOLDER! {wle_exec}')
                return latest
        stdout = run([str(wle_exec), 'licenses'], stdout=PIPE)
        stdout = stdout.stdout.decode('utf-8')
        if 'failed' in stdout:
            raise RuntimeError(f'Critical license error - failed during sync - {stdout}')
        all_licenses = []
        for line in stdout.split('\n'):
            if 'Antidisestablishmentarianism' in line or not line:
                continue
            try:
                fields = re.search('([\S]{36}) ([\S]*) ([\S]*) (.*)', line).groups()
            except AttributeError:
                if line == '\r': pass
            else:
                all_licenses.append(GuidFields(*fields[0:]))

        for license in sorted(all_licenses, key=lambda l: (l.guid, int(l.version.split('.')[0])), reverse=True):
            if license.guid not in latest:  # TODO: will work with tuples?
                latest[license.guid] = (int(license.version.split('.')[0]), license.name)

        for i in range(0, len(plugins_sorted)):
            for j in range(i + 1, len(plugins_sorted)):
                if plugins_sorted[i]['product_name'] != plugins_sorted[j]['product_name'] and plugins_sorted[i][
                    'guid'] == \
                        plugins_sorted[j]['guid']:
                    plugins_sorted[j]['guid'] += plugins_sorted[j]['product_name']
                    if plugins_sorted[i]['guid'] in latest:
                        latest[plugins_sorted[j]['guid']] = (
                            latest[plugins_sorted[i]['guid']][0], plugins_sorted[j]['product_name'])
        return latest


class AuUtilHelper:

    @staticmethod
    def accum_auval_reg_utils(batch_accum, required_shells, waves_main_folder):
        if sys.platform == 'darwin':
            for shell in required_shells:
                if required_shells.get(shell) == {''}:
                    continue
                shell_version, shell_enum = shell.split(':')
                old_reg_utility = True
                try:
                    au_reg_utility_new_path = Path(waves_main_folder, f"WaveShells V{shell_version}",
                                                   'Waves AU Reg Utility.app')
                    if au_reg_utility_new_path.exists():
                        au_reg_utility_path = au_reg_utility_new_path
                        exe_name = 'Waves AU Reg Utility'
                        old_reg_utility = False
                    else:
                        au_reg_utility_path = Cleaner.find_resoruces(waves_main_folder / f"WaveShells V{shell_version}",
                                                                     shell_enum.replace('WaveShell',
                                                                                        'Waves AU Reg Utility'),
                                                                     '{} *')[0]
                        exe_name = ' '.join(au_reg_utility_path.name.split(' ')[:-1])
                except IndexError:
                    log.error(f"cannot find au reg utility for {shell}")
                    continue
                if 'StudioRack' not in au_reg_utility_path.name:
                    plugins_folder = Path(waves_main_folder, f'Plug-Ins V{shell_version}')
                    new_path = Path(au_reg_utility_path, 'Contents', 'MacOS', exe_name)
                    cmd_params = (f"'{str(new_path)}' -s -f '{str(plugins_folder)}'")
                    if not old_reg_utility:
                        cmd_params = (f"'{str(new_path)}' -s")
                    batch_accum += ShellCommand(cmd_params)
        return batch_accum


# main class - where the magic happens
class Cleaner:  # should there be inheritance?

    def __init__(self):
        self.script_path = os.path.abspath(__file__)
        self.script_folder = os.path.dirname(self.script_path)
        self.set_main_out_file()  # can probably static method
        self.plugins_folders = Cleaner.get_possible_plugins_folders(Path(config_vars['WAVES_DIR']))
        self.plugins_folders_dict = self.spread_plugins_folder()
        self.waves_shell_paths = list(config_vars['WAVES_SHELL_DIRS'])
        self.artist_dll_paths = [_path for key,_path in self.plugins_folders_dict.items()]
        self.types_be_handled = ['wavesshell', 'artistdlls', 'waveslib']
        self.plugins_info_table = {}
        self.main_actions_table = {}  # all of the relevant actions per folder will be aggregated to this var

    def set_main_out_file(self):
        default_logs_path = Path(config_vars['WAVES_CENTRAL_APP_DATA_DIR'])
        right_now = time.strftime('%Y%m%d%H%M%S')
        log_file_name = f"cleaner_{right_now}.log"
        log_file = default_logs_path / 'Logs' / 'versionManager' / log_file_name
        log_folder = log_file.parent
        os.umask(0)
        main_out_file = log_folder / f'task_list_{right_now}.py'
        config_vars.setdefault('__MAIN_OUT_FILE__', main_out_file)

    @staticmethod
    def get_possible_plugins_folders(waves_main_folder):
        global MAX_PLUGIN_VERSION, MIN_PLUGIN_VERSION
        plugin_folders = {}
        for i in range(MIN_PLUGIN_VERSION, MAX_PLUGIN_VERSION + 1):
            plugin_folders[i] = {'used': waves_main_folder / f'Plug-Ins V{i}',
                                 'unused': waves_main_folder / f'Unused Plug-Ins V{i}'}
        return plugin_folders

    # def __call__(self, *args, **kwargs):
    def run_main_proc(self):

        self.plugins_info_table = Cleaner.sort_plugins_by_guid_version(self.plugins_folders)
        self.update_coex_plugins_actions()
        # generate a table to conclude all

        # there is a dependency between those who are about to be moved to unused and it's relevant shells, etc..
        folders_to_remove = self.get_leftover_folders_to_remove()  # remove leftover operation
        for folder in folders_to_remove:
            if folder not in self.main_actions_table:
                self.main_actions_table[folder] = {}
            self.main_actions_table[folder]['action'] = "REMOVE"  # TODO: can it be the class to be used??
            self.main_actions_table[folder]['dst'] = ''

        Cleaner.pretty(self.main_actions_table)

        required_shells = Cleaner.find_required_shells(self.plugins_info_table)
        accum = Cleaner.accum_actions_table(self.main_actions_table)
        AuUtilHelper.accum_auval_reg_utils(accum, required_shells, Path(config_vars['WAVES_DIR']))
        self.create_and_exec_batch(accum)

    @staticmethod
    def find_resoruces(folder_path, resource, search_format='*/{}'):
        """Return Path object for the relevant path according to the resource"""
        return [Path(file_path) for file_path in Path(folder_path).glob(search_format.format(resource))]

    @staticmethod
    def find_existing_path_by_expr(paths, expr):
        exists_folders = [Cleaner.find_resoruces(_path, expr, '{}*') for _path in paths]
        return list(itertools.chain.from_iterable(exists_folders))

    def spread_plugins_folder(self):
        global INCLUDE_UNUSED
        plugins_paths = {f"used{key}": _path for key, path in self.plugins_folders.items() for is_used, _path in
                         path.items()
                         if is_used == "used"}
        unused_plugins_paths = {f"unused{key}": _path for key, path in self.plugins_folders.items() for is_used, _path
                                in
                                path.items()
                                if is_used == "unused"}
        if INCLUDE_UNUSED:
            plugins_paths.update(unused_plugins_paths)

        return plugins_paths

    def get_waveslib_parent_path(self):  # think of changin the name
        """ return paths of all existing  waveslib in all existing plugins folder"""
        exists_waveslib = [Cleaner.find_resoruces(_path, 'WavesLib', '{}*') for k, _path in
                           self.plugins_folders_dict.items()]
        return list(itertools.chain.from_iterable(exists_waveslib))

    @staticmethod
    def filter_bundles_from_list(plugins_exists, product_to_filter="Insert"):
        bundles_to_filter = [p for p in plugins_exists if p['product_name'] == product_to_filter]
        for to_filter in bundles_to_filter:
            plugins_exists.remove(to_filter)

    @staticmethod
    def get_data_from_xml_by_tag_name(xmldoc, tag_name, tag_idx=0):
        return xmldoc.getElementsByTagName(tag_name)[tag_idx].firstChild.data

    @staticmethod
    def get_relevant_waveslib_index(xmldoc, tag_name, os_type="Mac"):
        tags_list = xmldoc.getElementsByTagName(tag_name)
        for idx, tag in enumerate(tags_list):
            if tag.attributes._attrs['OS'].firstChild.data == os_type:
                return idx

    @staticmethod
    def get_dynamic_plugins_name_idx_by_os(): #weird function I know
    #assuming a constant index suitable per each os
        cur_os = str(config_vars['__CURRENT_OS__'])
        if cur_os == 'Mac':
            idx = 1
        else:
            if '32' in cur_os:
                idx = 2
            else:
                idx = 3
        return idx
    # TODO: this function seems way to long, think of a way to shorten it
    @staticmethod
    def parse_plugin_info_xml(plugin_path):
        '''A function that parses the info xml of a plugin and stores the data in a dictionary for all plugins'''
        info_xml = str(Cleaner.find_resoruces(plugin_path, 'Info.xml')[0])
        try:
            info_xml_dict = utils.get_info_from_plugin(None, in_path=plugin_path)
            info_xml_dict['product_name'] = Path(info_xml_dict['path']).stem
            version = info_xml_dict['PluginExternalVersion']
            info_xml_dict['guid'] = info_xml_dict['LicenseGUID']
            del info_xml_dict['LicenseGUID']
            info_xml_dict['src_path'] = plugin_path
            info_xml_dict['version'] = int(version.split('.')[0])
            major_minor = version.split(".")[0] + "." + version.split(".")[1]
            info_xml_dict['wavesshell_rgx'] = f"{info_xml_dict['WaveShellsBaseName']}-.*{major_minor}"
            info_xml_dict['dst_path'] = '' # for further use
            idx = Cleaner.get_dynamic_plugins_name_idx_by_os()
            info_xml_dict['waveslib'] = info_xml_dict['DynamicPluginLibName'][idx]
            info_xml_dict["waveslib_rgx"] = f"{info_xml_dict['waveslib'].split('/')[0]}.*"
            return info_xml_dict
        except Exception as e:
            log.info(f'Exception in parsing {info_xml} --- {e}')
            raise e

    @staticmethod
    def sort_plugins_by_guid_version(plugin_folders):
        """return a sorted list of dictionary, where each item has the relevant info extracted from the info.xml """
        plugins_list = []
        for p_folders in plugin_folders.values():
            for plugin_folder in p_folders.values():
                if not os.path.exists(plugin_folder):
                    continue
                for plugin_path in list(plugin_folder.glob('*.bundle')):
                    try:
                        plugin_info = Cleaner.parse_plugin_info_xml(plugin_path)
                    except IndexError:
                        log.info(f'cannot find Info.xml file in {plugin_path}')
                        continue
                    except Exception:
                        continue
                    plugins_list.append(plugin_info)
        plugins_sorted = sorted(plugins_list, key=lambda p: (p['guid'], p['version']), reverse=True)
        return plugins_sorted

    @staticmethod
    def find_required_shells(plugins_exists):
        required_shells = {}
        for p in plugins_exists:
            # if 'Unused' in str(p['src_path']):
            #     continue
            shell_key = f"{p['version']}:{p['WaveShellsBaseName']}"
            adding = ''
            if str(p['src_path']) != str(p['dst_path']) and str(p['dst_path']) != '' and 'Unused' not in str(
                    p['dst_path']):
                adding = p['product_name']
            elif str(p['src_path']) != str(p['dst_path']) and str(p['dst_path']) == '' and 'Unused' not in str(
                    p['src_path']):
                adding = p['product_name']
            elif str(p['src_path']) == str(p['dst_path']) and 'Unused' not in str(p['src_path']):
                adding = p['product_name']

            if required_shells.get(shell_key):
                required_shells[shell_key].add(adding)
            else:
                required_shells[shell_key] = {adding}
        for k, v in required_shells.items():
            if len(v) > 10:
                used_by = 'more than 10 products'
            elif v == {''}:
                continue
            else:
                used_by = ', '.join(v)
            # log.info(f"Version{k.replace(':', ' - ')} is used by {used_by}")
        return required_shells

    @staticmethod
    def get_folders_to_remove(folders, plugins_info_table, type_to_remove):
        to_be_left_out = []
        for info in plugins_info_table:
            searched_item = Path(info[type_to_remove])
            searched_item = searched_item.parts[0]
            for folder in folders:
                # TODO: might change this code - waveslib should have a unique condition
                if re.search(searched_item, folder.name) and folder not in to_be_left_out and ("unused" not in str(
                        info['dst_path']).lower() or type_to_remove == 'waveslib_rgx'):
                    to_be_left_out.append(folder)
        to_be_removed = [_folder for _folder in folders if _folder not in to_be_left_out]
        return to_be_removed

    def get_leftover_folders_to_remove(self, spec_type_to_remove=None):
        """one of the two main functions, removing un referenced folders, type_to_remove should be one of four args:'all','wavesshell','artistdlls','waveslib' """
        global INCLUDE_UNUSED
        to_be_removed = []
        if spec_type_to_remove:
            self.types_be_handled.clear()
            self.types_be_handled = [spec_type_to_remove]

        if 'waveslib' in self.types_be_handled:
            waveslib = self.get_waveslib_parent_path()
            to_be_removed.extend(Cleaner.get_folders_to_remove(waveslib, self.plugins_info_table,'waveslib_rgx'))
        if 'wavesshell' in self.types_be_handled:
            existing_shells = Cleaner.find_existing_path_by_expr(self.waves_shell_paths, "WaveShell")
            to_be_removed.extend(Cleaner.get_folders_to_remove(existing_shells, self.plugins_info_table, 'wavesshell_rgx'))
        if 'artistdlls' in self.types_be_handled:
            artist_dlls = Cleaner.find_existing_path_by_expr(self.artist_dll_paths, "ArtistDlls")
            to_be_removed.extend(Cleaner.get_folders_to_remove(artist_dlls, self.plugins_info_table, 'ArtistDlls'))

        return to_be_removed

    # should be executed once all other actions

    def scan_plugins_for_coex(self,plugins_info_table):
        licenses = WleAux.get_licenses(plugins_info_table)  # guid to tuple of version product name
        plugins_to_used = []
        ret_val = []
        if not licenses:
            log.info('No license Found')
        else:
            for guid, (latest_license_version, plugin_name) in licenses.items():
                # go over all found plugins in found license, check for dups
                coex_plugins = [p for p in plugins_info_table if p['guid'] == guid]
                in_unused = [p for p in plugins_info_table if p['guid'] == guid and 'Unused' in str(p['src_path'])]
                if len(coex_plugins) > 1:  # checking for dups
                    try:
                        p_match = [p for p in coex_plugins if p['version'] <= latest_license_version][0]
                    except IndexError:
                        print(
                            f"License for {plugin_name.strip()} in V{latest_license_version}. not coexistence in versions {', '.join(str(p['version']) for p in coex_plugins)}")
                        continue
                    coex_plugins.remove(p_match)
                    #is it already in the correct place?
                    for candi in coex_plugins:
                        if candi['src_path'].parent == self.plugins_folders[candi['version']]['used']:
                            ret_val.append(candi)
                    log.info(
                        f"License for {p_match['product_name'].strip()} in V{p_match['version']} is coexistence with versions {', '.join(str(p['version']) for p in coex_plugins)}")
                elif len(in_unused) == 1 and coex_plugins == in_unused:
                    print(
                        f"Found non coexistence {in_unused[0]['product_name']} in {in_unused[0]['src_path'].parent.name}, return to Plugins V{in_unused[0]['version']} folder")
                    plugins_to_used.extend(in_unused)
                    #should returned to used
                    # batch_accum = accum_return_to_used(batch_accum, in_unused[0], plugin_folders)
            # I think this can probably replaced by simply update the main table?
            ret_val.extend(plugins_to_used)
            return ret_val #TODO: bad name

    def create_and_exec_batch(self, batch_accum, execute=True):
        """Create task_list.py file and optionally run it
        Set log file name to cofix"""
        main_out_file = config_vars['__MAIN_OUT_FILE__']
        out_file_realpath = Path(self.script_folder, main_out_file)
        with utils.utf8_open_for_write(out_file_realpath, 'w') as f:
            f.write(batch_accum.__repr__())

        with utils.utf8_open_for_read(out_file_realpath, 'r') as rfd:
            py_text = rfd.read()
            py_compiled = compile(py_text, os.fspath(out_file_realpath), mode='exec', flags=0, dont_inherit=False,
                                  optimize=2)
            if execute:
                log.info(f"Instl will execute {main_out_file}")
                # try:
                #     exec(py_compiled, globals())
                # except Exception as ex:
                #     log.exception(ex)
                #     pass

    @staticmethod
    def accum_actions_table(actions_table):
        batch_accum = PythonBatchCommandAccum()
        batch_accum.set_current_section('doit')
        for path, item in actions_table.items():
            action = item['action']
            if action == 'MOVE':
                batch_accum += MoveDirToDir(path, item['dst_path'])
            elif action == 'REMOVE':
                batch_accum += RmFileOrDir(path)
        return batch_accum

# ##
#     if os.path.exists(dst_path) and os.path.exists(plugin["src_path"]):
#         log.info(f'Plugin already exist in {dst_path}, will remove the old one and move the new')
    def update_coex_plugins_actions(self):
        coex_plugins = self.scan_plugins_for_coex(self.plugins_info_table)
        for coex in coex_plugins:
            cur_path = coex['src_path']

            if coex['src_path'].parent == self.plugins_folders[coex['version']]['used']:
                coex['dst_path'] = self.plugins_folders[coex['version']]['unused']
            if coex['src_path'].parent == self.plugins_folders[coex['version']]['unused']:
                coex['dst_path'] = self.plugins_folders[coex['version']]['used']
            dst_path = os.path.join(coex["dst_path"], os.path.split(coex["src_path"])[1])  # ??

            for p in self.plugins_info_table:
                if p['product_name'] == coex['product_name'] and p['version'] == coex['version']:
                    p['dst_path'] = dst_path

            if cur_path not in self.main_actions_table:
                self.main_actions_table[cur_path] = {}
            self.main_actions_table[cur_path]['action'] = 'MOVE'
            self.main_actions_table[cur_path]['dst_path'] = dst_path

    @staticmethod
    def pretty(d, indent=0):
        print ("{:<15} {:<15} ".format('Path', 'action'))
        for path, val in d.items():
            action = val['action']
            if 'dst_path' in val:
                action = f"{action} to {val['dst_path']}"
            print ("{:<15}:: {:<15}".format(path.name,action ))

cleaner_obj = Cleaner()
cleaner_obj.run_main_proc()

# since we 2 main functionality here, remove un ref folders and co existent, it will be splitted to 2 main functions
# we can get the instructions from an argument, something like: all,coex,leftover
# issue to consider, cofix get the coex plugins and move them to the unused folder, however it does so
# only "on paper" meaning, the is a dependant calculation between those two operations
#TODO: there can be a situation where unused already exists with a bundle - need to remove it and move the existing one
#