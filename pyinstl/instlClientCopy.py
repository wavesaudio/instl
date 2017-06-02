#!/usr/bin/env python3



import os
import pathlib
import utils
import functools

from configVar import var_stack
from .instlClient import InstlClient


class InstlClientCopy(InstlClient):
    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)

    def do_copy(self):
        self.init_copy_vars()

        # unwtar will take place directly so no need to copy those files
        self.ignore_additions = ['.wtar']
        for ignore_item in self.ignore_additions:
            ignore_item_wildcards = '*{}*'.format(ignore_item)
            if ignore_item_wildcards not in self.patterns_copy_should_ignore:
                self.patterns_copy_should_ignore.append(ignore_item_wildcards)

        self.create_copy_instructions()

    def init_copy_vars(self):
        self.action_type_to_progress_message = {'pre_copy': "pre-install step",
                                                'post_copy': "post-install step",
                                                'pre_copy_to_folder': "pre-copy step",
                                                'post_copy_to_folder': "post-copy step"}
        self.bytes_to_copy = 0
        self.wtar_ratio = 1.3 # ratio between wtar file and it's uncompressed contents
        if "WTAR_RATIO" in var_stack:
            self.wtar_ratio = float(var_stack.ResolveVarToStr("WTAR_RATIO"))
        self.calc_user_cache_dir_var() # this will set USER_CACHE_DIR if it was not explicitly defined
        self.patterns_copy_should_ignore = var_stack.ResolveVarToList("COPY_IGNORE_PATTERNS")

    def write_copy_debug_info(self):
        try:
            if var_stack.defined('ECHO_LOG_FILE'):
                log_file_path = var_stack.ResolveVarToStr("ECHO_LOG_FILE")
                log_folder, log_file = os.path.split(log_file_path)
                with open(os.path.join(log_folder, "sync-folder-manifest.txt"), "w", encoding='utf-8', errors='namereplace') as wfd:
                    repo_sync_dir = var_stack.ResolveVarToStr("COPY_SOURCES_ROOT_DIR")
                    wfd.write(utils.disk_item_listing(repo_sync_dir))
        except Exception:
            pass # if it did not work - forget it

    def write_copy_to_folder_debug_info(self, folder_path):
        try:
            if var_stack.defined('ECHO_LOG_FILE'):
                log_file_path = var_stack.ResolveVarToStr("ECHO_LOG_FILE")
                log_folder, log_file = os.path.split(log_file_path)
                manifests_log_folder = os.path.join(log_folder, "manifests")
                os.makedirs(manifests_log_folder, exist_ok=True)
                folder_path_parent, folder_name = os.path.split(var_stack.ResolveStrToStr(folder_path))
                ls_output_file = os.path.join(manifests_log_folder, folder_name+"-folder-manifest.txt")
                create_folder_ls_command_parts = [self.platform_helper.run_instl(), "ls",
                                              "--in", '"."',
                                              "--out", utils.quoteme_double(ls_output_file)]
                self.batch_accum += " ".join(create_folder_ls_command_parts)
        except Exception:
            pass # if it did not work - forget it

    def create_create_folders_instructions(self, folder_list):
        if len(folder_list) > 0:
            self.batch_accum += self.platform_helper.progress("Create folders ...")
            for target_folder_path in folder_list:
                self.batch_accum += self.platform_helper.progress("Create folder {0} ...".format(target_folder_path))
                if os.path.isfile(var_stack.ResolveStrToStr(target_folder_path)):
                    # weird as it maybe, some users have files where a folder should be.
                    # test for isfile is done here rather than in the batch file, because
                    # Windows does not have proper way to check "is file" in a batch.
                    self.batch_accum += self.platform_helper.rmfile(target_folder_path)
                    self.batch_accum += self.platform_helper.progress("Removed file that should be a folder {0}".format(target_folder_path))
                self.batch_accum += self.platform_helper.mkdir_with_owner(target_folder_path)
                self.batch_accum += self.platform_helper.progress("Create folder {0} done".format(target_folder_path))
            self.batch_accum += self.platform_helper.progress("Create folders done")

    def create_copy_instructions(self):
        self.create_sync_folder_manifest_command("before-copy")
        # If we got here while in synccopy command, there is no need to read the info map again.
        # If we got here while in copy command, read HAVE_INFO_MAP_FOR_COPY which defaults to HAVE_INFO_MAP_PATH.
        # Copy might be called after the sync batch file was created
        # but before it was executed in which case HAVE_INFO_MAP_FOR_COPY will be defined to NEW_HAVE_INFO_MAP_PATH.
        if len(self.info_map_table.files_read_list) == 0:
            have_info_path = var_stack.ResolveVarToStr("HAVE_INFO_MAP_FOR_COPY")
            self.read_info_map_from_file(have_info_path)

        # copy and actions instructions for sources
        self.batch_accum.set_current_section('copy')
        self.batch_accum += self.platform_helper.progress("Starting copy from $(COPY_SOURCES_ROOT_DIR)")

        self.accumulate_unique_actions_for_active_iids('pre_copy')
        self.batch_accum += self.platform_helper.new_line()

        sorted_target_folder_list = sorted(self.all_iids_by_target_folder,
                                           key=lambda fold: var_stack.ResolveStrToStr(fold))

        # first create all target folders so to avoid dependency order problems such as creating links between folders
        self.create_create_folders_instructions(sorted_target_folder_list)

        if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__") and 'Mac' in var_stack.ResolveVarToList("TARGET_OS"):
            self.pre_copy_mac_handling()

        remove_previous_sources = var_stack.ResolveVarToBool("REMOVE_PREVIOUS_SOURCES", default=True)
        for target_folder_path in sorted_target_folder_list:
            if remove_previous_sources:
                self.create_remove_previous_sources_instructions_for_target_folder(target_folder_path)
            self.create_copy_instructions_for_target_folder(target_folder_path)

        # actions instructions for sources that do not need copying, here folder_name is the sync folder
        for sync_folder_name in sorted(self.no_copy_iids_by_sync_folder.keys()):
            self.create_copy_instructions_for_no_copy_folder(sync_folder_name)

        print(self.bytes_to_copy, "bytes to copy")

        self.accumulate_unique_actions_for_active_iids('post_copy')

        self.batch_accum.set_current_section('post-copy')
        # Copy have_info file to "site" (e.g. /Library/Application support/... or c:\ProgramData\...)
        # for reference. But when preparing offline installers the site location is the same as the sync location
        # so copy should be avoided.
        if var_stack.ResolveVarToStr("HAVE_INFO_MAP_PATH") != var_stack.ResolveVarToStr("SITE_HAVE_INFO_MAP_PATH"):
            self.batch_accum += self.platform_helper.mkdir_with_owner("$(SITE_REPO_BOOKKEEPING_DIR)")
            self.batch_accum += self.platform_helper.progress("Created folder $(SITE_REPO_BOOKKEEPING_DIR)")
            self.batch_accum += self.platform_helper.copy_file_to_file("$(HAVE_INFO_MAP_PATH)", "$(SITE_HAVE_INFO_MAP_PATH)")
            self.batch_accum += self.platform_helper.progress("Copied $(HAVE_INFO_MAP_PATH) to $(SITE_HAVE_INFO_MAP_PATH)")

        self.platform_helper.copy_tool.finalize()

        self.create_require_file_instructions()

        # messages about orphan iids
        for iid in sorted(var_stack.ResolveVarToList("__ORPHAN_INSTALL_TARGETS__")):
            self.batch_accum += self.platform_helper.echo("Don't know how to install " + iid)
        self.batch_accum += self.platform_helper.progress("Done copy")

    def calc_size_of_file_item(self, a_file_item):
        """ for use with builtin function reduce to calculate the unwtarred size of a file """
        if a_file_item.is_wtar_file():
            item_size = int(float(a_file_item.size) * self.wtar_ratio)
        else:
            item_size = a_file_item.size
        return item_size

    def create_copy_instructions_for_file(self, source_path, name_for_progress_message):
        source_files = self.info_map_table.get_required_for_file(source_path)
        num_wtars = functools.reduce(lambda total, item: total + item.wtarFlag, source_files, 0)
        assert (len(source_files) == 1 and num_wtars == 0) or num_wtars == len(source_files)

        if num_wtars == 0:
            source_file = source_files[0]
            source_file_full_path = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_file.path)

            # patterns_copy_should_ignore is passed for the sake of completeness but is not being used further down the road in copy_file_to_dir
            self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(source_file_full_path, ".",
                                                                                link_dest=True,
                                                                                ignore=self.patterns_copy_should_ignore)

            self.batch_accum += self.platform_helper.echo("copy {source_file_full_path}".format(**locals()))

            if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__") and 'Mac' in var_stack.ResolveVarToList("TARGET_OS"):
                if not source_file.path.endswith(".symlink"):
                    self.batch_accum += self.platform_helper.chmod(source_file.chmod_spec(), source_file.name())
                    self.batch_accum += self.platform_helper.echo("chmod {} {}".format(source_file.chmod_spec(), source_file.name()))

            self.bytes_to_copy += self.calc_size_of_file_item(source_file)
        else:  # one or more wtar files
            first_wtar_item = None
            for source_wtar in source_files:
                self.bytes_to_copy += self.calc_size_of_file_item(source_wtar)
                if source_wtar.is_first_wtar_file():
                    first_wtar_item = source_wtar
            assert first_wtar_item is not None
            first_wtar_full_path = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + first_wtar_item.path)
            #self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message} ...".format(**locals()))
            self.unwtar_instructions.append((first_wtar_full_path, '.'))

            #self.batch_accum += self.platform_helper.unwtar_something(first_wtar_full_path, no_artifacts=False, where_to_unwtar='.')
            #self.batch_accum += self.platform_helper.unlock(first_wtar_item.name_without_wtar_extension())
            self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message} done".format(**locals()))

    def create_copy_instructions_for_dir_cont(self, source_path, name_for_progress_message):
        source_path_abs = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_path)
        self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(
                                                    source_path_abs,
                                                    ".",
                                                    link_dest=True,
                                                    ignore=self.patterns_copy_should_ignore,
                                                    preserve_dest_files=True)  # preserve files already in destination

        source_items = self.info_map_table.get_items_in_dir(dir_path=source_path, what="any")
        self.bytes_to_copy += functools.reduce(lambda total, item: total + self.calc_size_of_file_item(item), source_items, 0)

        if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__") and 'Mac' in var_stack.ResolveVarToList("TARGET_OS"):
            for source_item in source_items:
                if source_item.wtarFlag == 0:
                    source_path_relative_to_current_dir = source_item.path_starting_from_dir(source_path)
                    self.batch_accum += self.platform_helper.chmod("-R -f a+rw", source_path_relative_to_current_dir)  # all copied files and folders should be rw
                    if source_item.isExecutable():
                        self.batch_accum += self.platform_helper.chmod(source_item.chmod_spec(), source_path_relative_to_current_dir)


        num_wtars = functools.reduce(lambda total, item: total + item.wtarFlag, source_items, 0)
        if num_wtars > 0:
            #self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message} ...".format(**locals()))
            self.unwtar_instructions.append((source_path_abs, '.'))
            #self.batch_accum += self.platform_helper.unwtar_something(source_path_abs, no_artifacts=False, where_to_unwtar='.')
            #self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message} done".format(**locals()))
            self.batch_accum += self.platform_helper.unlock('.', recursive=True)

            # fix permissions for any items that were unwtarred
            if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__"):
                self.batch_accum += self.platform_helper.chmod("-R -f a+rwX", ".")

    def create_copy_instructions_for_dir(self, source_path, name_for_progress_message):
        dir_item = self.info_map_table.get_item(source_path, what="dir")
        if dir_item is not None:
            source_path_abs = os.path.normpath("$(COPY_SOURCES_ROOT_DIR)/" + source_path)
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(source_path_abs, ".",
                                                                               link_dest=True,
                                                                               ignore=self.patterns_copy_should_ignore)
            source_items = self.info_map_table.get_items_in_dir(dir_path=source_path, what="any")
            self.bytes_to_copy += functools.reduce(lambda total, item: total + self.calc_size_of_file_item(item), source_items, 0)

            source_path_dir, source_path_name = os.path.split(source_path)

            if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__") and 'Mac' in var_stack.ResolveVarToList("TARGET_OS"):
                self.batch_accum += self.platform_helper.chmod("-R -f a+rw", source_path_name)  # all copied files should be rw
                for source_item in source_items:
                    if source_item.wtarFlag == 0 and source_item.isExecutable():
                        source_path_relative_to_current_dir = source_item.path_starting_from_dir(source_path_dir)
                        # executable files should also get exec bit
                        self.batch_accum += self.platform_helper.chmod(source_item.chmod_spec(), source_path_relative_to_current_dir)


            num_wtars = functools.reduce(lambda total, item: total + item.wtarFlag, source_items, 0)
            if num_wtars > 0:
                #self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message} ...".format(**locals()))
                self.unwtar_instructions.append((source_path_abs, source_path_name))
                #self.batch_accum += self.platform_helper.unwtar_something(source_path_abs, no_artifacts=False, where_to_unwtar=source_path_name)
                #self.batch_accum += self.platform_helper.progress("Expand {name_for_progress_message} done".format(**locals()))
                self.batch_accum += self.platform_helper.unlock(".", recursive=True)

                # fix permissions for any items that were unwtarred
                if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__"):
                    self.batch_accum += self.platform_helper.chmod("-R -f a+rwX", source_path_name)
        else:
            # it might be a dir that was wtarred
            self.create_copy_instructions_for_file(source_path, name_for_progress_message)

    def create_copy_instructions_for_source(self, source, name_for_progress_message):
        """ source is a tuple (source_path, tag), where tag is either !file or !dir or !dir_cont'
        """
        self.batch_accum += self.platform_helper.progress("Copy {0} ...".format(name_for_progress_message))
        if source[1] == '!file':  # get a single file
            self.create_copy_instructions_for_file(source[0], name_for_progress_message)
        elif source[1] == '!dir_cont':  # get all files and folders from a folder
            self.create_copy_instructions_for_dir_cont(source[0], name_for_progress_message)
        elif source[1] == '!dir':  # !dir
            self.create_copy_instructions_for_dir(source[0], name_for_progress_message)
        else:
            raise ValueError("unknown source type "+source[1]+" for "+source[0])
        self.batch_accum += self.platform_helper.progress("Copy {0} done".format(name_for_progress_message))

    # special handling when running on Mac OS
    def pre_copy_mac_handling(self):
        required_and_exec = self.info_map_table.get_required_exec_items(what="file")
        num_files_to_set_exec = len(required_and_exec)
        if num_files_to_set_exec > 0:
            self.batch_accum += self.platform_helper.pushd("$(COPY_SOURCES_ROOT_DIR)")
            have_info_path = var_stack.ResolveVarToStr("REQUIRED_INFO_MAP_PATH")
            self.batch_accum += self.platform_helper.set_exec_for_folder(have_info_path)
            self.platform_helper.num_items_for_progress_report += num_files_to_set_exec
            self.batch_accum += self.platform_helper.progress("Set exec done")
            self.batch_accum += self.platform_helper.new_line()
            self.batch_accum += self.platform_helper.popd()

    def get_max_repo_rev_for_source(self, source):
        retVal = self.info_map_table.get_max_repo_rev_for_source(source)
        return retVal

    # Todo: move function to a better location
    def pre_resolve_path(self, path_to_resolve):
        """ for some paths we cannot wait for resolution in the batch file"""
        resolved_path = var_stack.ResolveStrToStr(path_to_resolve)
        try:
            resolved_path = str(pathlib.Path(resolved_path).resolve())
        except:
            pass
        return resolved_path

    def create_create_folders_instructions(self, folder_list):
        if len(folder_list) > 0:
            self.batch_accum += self.platform_helper.progress("Create folders ...")
            for target_folder_path in folder_list:
                resolved_target_folder_path = self.pre_resolve_path(target_folder_path)
                self.batch_accum += self.platform_helper.progress("Create folder {0} ...".format(resolved_target_folder_path))
                if os.path.isfile(resolved_target_folder_path):
                    # weird as it maybe, some users have files where a folder should be.
                    # test for isfile is done here rather than in the batch file, because
                    # Windows does not have proper way to check "is file" in a batch.
                    self.batch_accum += self.platform_helper.rmfile(resolved_target_folder_path)
                    self.batch_accum += self.platform_helper.progress("Removed file that should be a folder {0}".format(target_folder_path))
                self.batch_accum += self.platform_helper.mkdir_with_owner(resolved_target_folder_path)
                self.batch_accum += self.platform_helper.progress("Create folder {0} done".format(resolved_target_folder_path))
            self.batch_accum += self.platform_helper.progress("Create folders done")

    def create_copy_instructions_for_target_folder(self, target_folder_path):
        self.unwtar_instructions = list()
        num_items_copied_to_folder = 0
        items_in_folder = sorted(self.all_iids_by_target_folder[target_folder_path])
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.remark("- Begin folder {0}".format(target_folder_path))
        self.batch_accum += self.platform_helper.cd(target_folder_path)
        self.batch_accum += self.platform_helper.progress("copy to {0} ...".format(target_folder_path))

        # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions_for_active_iids('pre_copy_to_folder', items_in_folder)

        batch_accum_len_before = len(self.batch_accum)
        self.batch_accum += self.platform_helper.copy_tool.begin_copy_folder()
        for IID in items_in_folder:
            self.batch_accum += self.platform_helper.remark("-- Begin iid {0}".format(IID))
            adjusted_sources_for_iid = self.items_table.get_adjusted_sources_for_iid(IID)
            adjusted_resolved_sources_for_iid = [(var_stack.ResolveStrToStr(s[0]), s[1]) for s in adjusted_sources_for_iid]
            for source in adjusted_resolved_sources_for_iid:
                self.batch_accum += self.platform_helper.remark("--- Begin source {0}".format(source[0]))
                num_items_copied_to_folder += 1
                self.batch_accum += var_stack.ResolveVarToList("iid_action_list_pre_copy_item", default=[])
                self.create_copy_instructions_for_source(source, self.iid_to_name_and_version[IID].name_and_version)
                self.batch_accum += var_stack.ResolveVarToList("iid_action_list_post_copy_item", default=[])
                self.batch_accum += self.platform_helper.remark("--- End source {0}".format(source[0]))
            self.batch_accum += self.platform_helper.remark("-- End iid {0}".format(IID))

        target_folder_path_parent, target_folder_name = os.path.split(var_stack.ResolveStrToStr(target_folder_path))
        self.create_unwtar_batch_file(self.unwtar_instructions, target_folder_name)
        self.unwtar_instructions = None
        self.batch_accum += self.platform_helper.copy_tool.end_copy_folder()

        # only if items were actually copied there's need to (Mac only) resolve symlinks
        if num_items_copied_to_folder > 0:
            if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__") and 'Mac' in var_stack.ResolveVarToList("TARGET_OS"):
                self.batch_accum += self.platform_helper.progress("Resolve symlinks ...")
                self.batch_accum += self.platform_helper.resolve_symlink_files()
                self.batch_accum += self.platform_helper.progress("Resolve symlinks done")

        # accumulate post_copy_to_folder actions from all items, eliminating duplicates
        self.accumulate_unique_actions_for_active_iids('post_copy_to_folder', items_in_folder)
        self.batch_accum += self.platform_helper.progress("Copy to {0} done".format(target_folder_path))
        self.batch_accum += self.platform_helper.remark("- End folder {0}".format(target_folder_path))

    # Todo: move function to a better location
    def pre_resolve_path(self, path_to_resolve):
        """ for some paths we cannot wait for resolution in the batch file"""
        resolved_path = var_stack.ResolveStrToStr(path_to_resolve)
        try:
            resolved_path = str(pathlib.Path(resolved_path).resolve())
        except:
            pass
        return resolved_path

    def create_copy_instructions_for_no_copy_folder(self, sync_folder_name):
        """ Instructions for sources that do not need copying
            These are sources that do not have 'install_folder' section OR those with active
            'direct_sync' section.
        """
        self.batch_accum.begin_transaction()

        actual_instructions = 0  # num "real" instruction not including cd, newline, progress, echo etc...

        items_in_folder = self.no_copy_iids_by_sync_folder[sync_folder_name]
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.cd(sync_folder_name)
        self.batch_accum += self.platform_helper.progress("Actions in {0} ...".format(sync_folder_name))

        # accumulate pre_copy_to_folder actions from all items, eliminating duplicates
        actual_instructions += self.accumulate_unique_actions_for_active_iids('pre_copy_to_folder', items_in_folder)

        num_wtars = 0
        for IID in sorted(items_in_folder):
            with self.install_definitions_index[IID].push_var_stack_scope():
                for source_var in sorted(var_stack.ResolveVarToList("iid_source_var_list", default=[])):
                    source = var_stack.ResolveVarToList(source_var)
                    num_wtars = self.info_map_table.count_wtar_items_of_dir(source[0]);
                self.batch_accum.begin_transaction()
                self.batch_accum += var_stack.ResolveVarToList("iid_action_list_pre_copy_item", default=[])
                self.batch_accum += var_stack.ResolveVarToList("iid_action_list_post_copy_item", default=[])
                actual_instructions += self.batch_accum.end_transaction()

        if num_wtars > 0:
            source_folder, source_name = os.path.split(source[0])
            # to_unwtar = os.path.join(sync_folder_name, source_name)
            self.batch_accum += self.platform_helper.unwtar_something(sync_folder_name, no_artifacts=False, where_to_unwtar='.')
            actual_instructions += 1

        # accumulate post_copy_to_folder actions from all items, eliminating duplicates
        actual_instructions += self.accumulate_unique_actions_for_active_iids('post_copy_to_folder', items_in_folder)

        self.batch_accum += self.platform_helper.progress("{sync_folder_name}".format(**locals()))
        self.batch_accum += self.platform_helper.progress("Actions in {0} done".format(sync_folder_name))

        if actual_instructions > 0:
            self.batch_accum.end_transaction()
        else:
            self.batch_accum.cancel_transaction()

    def create_unwtar_batch_file(self, wtar_instructions, name_for_progress):
        if wtar_instructions:
            main_out_file_dir, main_out_file_leaf = os.path.split(var_stack.ResolveVarToStr("__MAIN_OUT_FILE__"))
            unwtar_batch_files_dir = os.path.join(main_out_file_dir, "unwtar")
            os.makedirs(unwtar_batch_files_dir, exist_ok=True)
            batch_file_path = os.path.join(unwtar_batch_files_dir, name_for_progress+".unwtar")
            batch_file_path = var_stack.ResolveStrToStr(batch_file_path)
            with open(batch_file_path, "w") as wfd:
                for wtar_inst in self.unwtar_instructions:
                    unwtar_line = var_stack.ResolveStrToStr("""unwtar --in "{}" --out "{}" --no-numbers-progress\n""".format(*wtar_inst))
                    progress = self.platform_helper.increment_progress()
                    wfd.write(unwtar_line)
            self.batch_accum += self.platform_helper.run_instl_command_list(batch_file_path, parallel=True)
            self.batch_accum += self.platform_helper.progress("Expand files in {} done".format(name_for_progress))
