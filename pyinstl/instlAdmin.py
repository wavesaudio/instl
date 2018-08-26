#!/usr/bin/env python3


import os
import sys
import filecmp
import io
import re
import shutil
import subprocess
from collections import defaultdict
import stat
import zlib

import utils
import aYaml
from .instlInstanceBase import InstlInstanceBase
from .batchAccumulator import BatchAccumulator
from configVar import config_vars
from svnTree import SVNTable
from pybatch import *


# noinspection PyPep8,PyPep8,PyPep8
class InstlAdmin(InstlInstanceBase):

    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.total_self_progress = 1000
        self.read_defaults_file(super().__thisclass__.__name__)
        self.fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')

    def get_default_out_file(self):
        retVal = None
        if "__MAIN_INPUT_FILE__" in config_vars:
            retVal = "$(__CONFIG_FILE__)-$(__MAIN_COMMAND__).$(BATCH_EXT)"
        return retVal

    def set_default_variables(self):
        if "__CONFIG_FILE__" in config_vars:
            config_file_resolved = self.path_searcher.find_file(config_vars["__CONFIG_FILE__"].str(), return_original_if_not_found=True)
            config_vars["__CONFIG_FILE_PATH__"] = config_file_resolved

            self.read_yaml_file(config_file_resolved)
            self.resolve_defined_paths()

    def do_command(self):
        self.set_default_variables()
        self.platform_helper.num_items_for_progress_report = int(config_vars["LAST_PROGRESS"])
        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()

    def do_trans(self):
        self.info_map_table.read_from_file(config_vars["__MAIN_INPUT_FILE__"].str(), a_format="info", disable_indexes_during_read=True)

        if "__PROPS_FILE__" in config_vars:
            self.info_map_table.read_from_file(config_vars["__PROPS_FILE__"].str(), a_format="props")
        if "__FILE_SIZES_FILE__" in config_vars:
            self.info_map_table.read_from_file(config_vars["__FILE_SIZES_FILE__"].str(), a_format="file-sizes")

        base_rev = int(config_vars["BASE_REPO_REV"])
        if base_rev > 0:
            self.info_map_table.set_base_revision(base_rev)

        if "__BASE_URL__" in config_vars:
            self.add_urls_to_info_map()
        self.info_map_table.write_to_file(config_vars["__MAIN_OUT_FILE__"].str(), field_to_write=self.fields_relevant_to_info_map)

    def add_urls_to_info_map(self):
        base_url = config_vars["__BASE_URL__"].str()
        for file_item in self.info_map_table.get_items(what="file"):
            file_item.url = os.path.join(base_url, str(file_item.revision), file_item.path)
            self.progress(file_item)

    def get_revision_range(self):
        revision_range_re = re.compile("""
                                (?P<min_rev>\d+)
                                (:
                                (?P<max_rev>\d+)
                                )?
                                """, re.VERBOSE)
        min_rev = 0
        max_rev = 1
        match = revision_range_re.match(config_vars["REPO_REV"].str())
        if match:
            min_rev += int(match['min_rev'])
            if match['max_rev']:
                max_rev += int(match['max_rev'])
            else:
                max_rev += min_rev
        return min_rev, max_rev

    def needToCreatelinksForRevision(self, revision):
        """ Need to create links if the create_links_done_stamp_file was not found.

            If the file was found there is still one situation where we would like
            to re-create the links: If the links are for a revision that was not the
            base revision and now this revision is the base revision. In which case
            the whole revision will need to be uploaded.
        """
        current_base_repo_rev = int(config_vars["BASE_REPO_REV"])
        retVal = True
        revision_folder_hierarchy = self.repo_rev_to_folder_hierarchy(revision)
        revision_links_folder = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/" + revision_folder_hierarchy)
        create_links_done_stamp_file = config_vars.resolve_str(revision_links_folder + "/$(CREATE_LINKS_STAMP_FILE_NAME)")
        if os.path.isfile(create_links_done_stamp_file):
            if revision == current_base_repo_rev:  # revision is the new base_repo_rev
                try:
                    previous_base_repo_rev = int(utils.utf8_open(create_links_done_stamp_file, "r").read())  # try to read the previous
                    if previous_base_repo_rev == current_base_repo_rev:
                        retVal = False
                    else:
                        msg = " ".join( ("new base revision", str(current_base_repo_rev), "(was", str(previous_base_repo_rev),") need to refresh links") )
                        self.batch_accum += Echo(msg)
                        self.progress(msg)
                        # if we need to create links, remove the upload stems in order to force upload
                        try: os.remove(config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/"+revision_folder_hierarchy+"/$(UP_2_S3_STAMP_FILE_NAME)"))
                        except Exception: pass
                except Exception:
                    pass  # no previous base repo rev indication was found so return True to re-create the links
            else:
                retVal = False
        return retVal

    def get_last_repo_rev(self):
        retVal = 0
        revision_line_re = re.compile("^Revision:\s+(?P<revision>\d+)$")
        repo_url = config_vars["SVN_REPO_URL"].str()
        if os.path.isdir(repo_url):
            svn_info_command = [config_vars["SVN_CLIENT_PATH"].str(), "info", os.curdir]
        else:
            svn_info_command = [config_vars["SVN_CLIENT_PATH"].str(), "info", repo_url]
        with utils.ChangeDirIfExists(repo_url):
            proc = subprocess.Popen(svn_info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            my_stdout, my_stderr = proc.communicate()
            my_stdout, my_stderr = utils.unicodify(my_stdout), utils.unicodify(my_stderr)
            if proc.returncode != 0 or my_stderr != "":
                raise ValueError(f"Could not read info from svn: {my_stderr} {proc.returncode}")
            info_as_io = io.StringIO(my_stdout)
            for line in info_as_io:
                match = revision_line_re.match(line)
                if match:
                    retVal = int(match["revision"])
                    break
        if retVal <= 0:
            raise ValueError(f"Could not find last repo rev for {repo_url}")
        config_vars["__LAST_REPO_REV__"] = str(retVal)
        return retVal

    def do_create_links(self):
        self.check_prerequisite_var_existence(("REPO_NAME", "SVN_REPO_URL", "ROOT_LINKS_FOLDER_REPO"))

        self.batch_accum.set_current_section('links')

        # call svn info to find out the last repo revision
        last_repo_rev = self.get_last_repo_rev()
        min_repo_rev_to_work_on = int(config_vars.get("IGNORE_BELOW_REPO_REV", "1"))
        base_repo_rev = int(config_vars["BASE_REPO_REV"])
        curr_repo_rev = int(config_vars["REPO_REV"])
        if base_repo_rev > curr_repo_rev:
            raise ValueError(f"base_repo_rev {base_repo_rev} > curr_repo_rev {curr_repo_rev}")
        if curr_repo_rev > last_repo_rev:
            raise ValueError(f"base_repo_rev {base_repo_rev} > last_repo_rev {last_repo_rev}")

        self.batch_accum += self.platform_helper.mkdir("$(ROOT_LINKS_FOLDER_REPO)/Base")

        self.batch_accum += Cd("$(ROOT_LINKS_FOLDER_REPO)")
        ignore_nums = list()
        no_need_link_nums = list()
        yes_need_link_nums = list()
        max_repo_rev_to_work_on = curr_repo_rev
        if "__WHICH_REVISION__" in config_vars:
            which_revision = config_vars["__WHICH_REVISION__"].str()
            if which_revision == "all":
                max_repo_rev_to_work_on = last_repo_rev
            else:  # force one specific revision
                base_repo_rev = int(which_revision)
                max_repo_rev_to_work_on = base_repo_rev

        for revision in range(base_repo_rev, max_repo_rev_to_work_on+1):
            if revision < min_repo_rev_to_work_on:
                ignore_nums.append(revision)
                continue
            if self.needToCreatelinksForRevision(revision):
                yes_need_link_nums.append(str(revision))
                save_dir_var = "REV_" + str(revision) + "_SAVE_DIR"
                self.batch_accum += self.platform_helper.save_dir(save_dir_var)
                config_vars["__CURR_REPO_REV__"] = str(revision)
                config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.repo_rev_to_folder_hierarchy(revision)
                accum = BatchAccumulator()
                accum.set_current_section('links')
                self.create_links_for_revision(accum)
                revision_lines = accum.finalize_list_of_lines()  # will resolve with current  __CURR_REPO_REV__
                self.batch_accum += revision_lines
                self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
            else:
                no_need_link_nums.append(str(revision))

        if yes_need_link_nums:
            if no_need_link_nums:
                no_need_links_str = utils.find_sequences(no_need_link_nums)
                self.progress("Links already created for revisions:", no_need_links_str)
            if ignore_nums:
                ignore_nums_str = utils.find_sequences(ignore_nums)
                self.progress("Ignoring revisions below:", min_repo_rev_to_work_on, ignore_nums_str)
            yes_need_links_str = utils.find_sequences(yes_need_link_nums)
            config_vars["__NEED_UPLOAD_REPO_REV_LIST__"] = yes_need_link_nums
            self.progress("Need to create links for revisions:", yes_need_links_str)
        else:
            self.progress("Links already created for all revisions:", str(base_repo_rev), "...", str(max_repo_rev_to_work_on))

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def create_links_for_revision(self, accum):
        assert config_vars["__CURR_REPO_REV__"].str() == "".join(config_vars["__CURR_REPO_FOLDER_HIERARCHY__"].str().split("/")).lstrip("0")
        base_folder_path = "$(ROOT_LINKS_FOLDER_REPO)/Base"
        revision_folder_path = "$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)"
        revision_instl_folder_path = revision_folder_path + "/instl"

        # sync revision __CURR_REPO_REV__ from SVN to Base folder
        accum += Echo("Getting revision $(__CURR_REPO_REV__) from $(SVN_REPO_URL)")
        checkout_command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"' + "$(SVN_REPO_URL)@$(__CURR_REPO_REV__)" + '"',
                                  '"' + base_folder_path + '"', "--depth", "infinity"]
        accum += " ".join(checkout_command_parts)
        accum += Progress("Create links for revision $(__CURR_REPO_REV__)")

        # copy Base folder to revision folder
        accum += self.platform_helper.mkdir(revision_folder_path)
        accum += CopyDirContentsToDir(config_vars.resolve_str(base_folder_path),
                                                                         config_vars.resolve_str(revision_folder_path),
                                                                         link_dest=True, ignore_patterns=".svn", preserve_dest_files=False)
        accum += Progress("Copy revision $(__CURR_REPO_REV__) to "+revision_folder_path)

        # get info from SVN for all files in revision
        self.create_info_map(base_folder_path, revision_instl_folder_path, accum)

        accum += self.platform_helper.pushd(revision_folder_path)
        # create depend file
        accum += Progress("Create dependencies file ...")
        create_depend_file_command_parts = [self.platform_helper.run_instl(), "depend", "--in", "instl/index.yaml",
                                            "--out", "instl/index-dependencies.yaml"]
        accum += " ".join(create_depend_file_command_parts)
        accum += Progress("Create dependencies file done")

        # create repo-rev file
        accum += Progress("Create repo-rev file ...")
        create_repo_rev_file_command_parts = [self.platform_helper.run_instl(), "create-repo-rev-file",
                                              "--config-file", '"$(__CONFIG_FILE_PATH__)"', "--rev", "$(__CURR_REPO_REV__)"]
        accum += " ".join(create_repo_rev_file_command_parts)
        accum += Progress("Create repo-rev file done")

        if False:  # disabled creating and uploading the .txt version of the files, was not that useful and took long time to upload
            # create text versions of info and yaml files, so they can be displayed in browser
            if config_vars["__CURRENT_OS__"].str() == "Linux":
                accum += " ".join(("find", "instl", "-type", "f", "-regextype", "posix-extended",
                                   "-regex", "'.*(yaml|info|props)'", "-print0", "|",
                                   "xargs", "-0", "-I{}", "cp", "-f", '"{}"', '"{}.txt"'))
            elif config_vars["__CURRENT_OS__"].str() == "Mac":
                accum += " ".join(("find", "-E", "instl", "-type", "f",
                                   "-regex", "'.*(yaml|info|props)'", "-print0", "|",
                                   "xargs", "-0", "-I{}", "cp", "-f", '"{}"', '"{}.txt"'))
            else:
                raise EnvironmentError("instl admin commands can only run under Mac or Linux")

        accum += self.platform_helper.rmfile("$(UP_2_S3_STAMP_FILE_NAME)")
        accum += Progress("Remove $(UP_2_S3_STAMP_FILE_NAME)")
        accum += " ".join(["echo", "-n", "$(BASE_REPO_REV)", ">", "$(CREATE_LINKS_STAMP_FILE_NAME)"])
        accum += Progress("Create $(CREATE_LINKS_STAMP_FILE_NAME)")

        accum += self.platform_helper.popd()
        accum += Echo("done create-links version $(__CURR_REPO_REV__)")

    def do_up2s3(self):
        min_repo_rev_to_work_on = int(config_vars.get("IGNORE_BELOW_REPO_REV", "1"))
        base_repo_rev = int(config_vars["BASE_REPO_REV"])
        curr_repo_rev = int(config_vars["REPO_REV"])
        # call svn info to find out the last repo revision
        last_repo_rev = self.get_last_repo_rev()
        if base_repo_rev > curr_repo_rev:
            raise ValueError(f"base_repo_rev {base_repo_rev} > curr_repo_rev {curr_repo_rev}")
        if curr_repo_rev > last_repo_rev:
            raise ValueError(f"base_repo_rev {base_repo_rev} > last_repo_rev {last_repo_rev}")

        max_repo_rev_to_work_on = curr_repo_rev
        if "__WHICH_REVISION__" in config_vars:
            which_revision = config_vars["__WHICH_REVISION__"].str()
            if which_revision == "all":
                max_repo_rev_to_work_on = last_repo_rev
            else:  # force one specific revision
                base_repo_rev = int(which_revision)
                max_repo_rev_to_work_on = base_repo_rev

        revision_list = list(range(base_repo_rev, max_repo_rev_to_work_on+1))
        dirs_that_dont_need_upload = list()
        dirs_that_need_upload = list()
        dirs_missing = list()
        for dir_as_int in revision_list:
            if dir_as_int < min_repo_rev_to_work_on:
                continue
            dir_as_int_folder_hierarchy = self.repo_rev_to_folder_hierarchy(dir_as_int)
            dir_name = str(dir_as_int)
            if not os.path.isdir(config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/" + dir_as_int_folder_hierarchy)):
                self.progress("revision dir", dir_as_int_folder_hierarchy, "is missing, run create-links to create this folder")
                dirs_missing.append(dir_name)
            else:
                create_links_done_stamp_file = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/"+dir_as_int_folder_hierarchy+"/$(CREATE_LINKS_STAMP_FILE_NAME)")
                if not os.path.isfile(create_links_done_stamp_file):
                    self.progress("revision dir", dir_as_int_folder_hierarchy, "does not have create-links stamp file:", create_links_done_stamp_file)
                else:
                    up_2_s3_done_stamp_file = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/"+dir_as_int_folder_hierarchy+"/$(UP_2_S3_STAMP_FILE_NAME)")
                    if os.path.isfile(up_2_s3_done_stamp_file):
                        dirs_that_dont_need_upload.append(dir_name)
                    else:
                        dirs_that_need_upload.append(dir_name)
        if dirs_missing:
            sequences_of_dirs_missing = utils.find_sequences(dirs_missing)
            self.progress("Revisions cannot be uploaded to S3:", sequences_of_dirs_missing)
            dirs_that_need_upload = []
        elif dirs_that_need_upload:
            if dirs_that_dont_need_upload:
                sequences_of_dirs_that_dont_need_upload = utils.find_sequences(dirs_that_dont_need_upload)
                self.progress("Revisions already uploaded to S3:", sequences_of_dirs_that_dont_need_upload)
            sequences_of_dirs_that_need_upload = utils.find_sequences(dirs_that_need_upload)
            self.progress("Revisions will be uploaded to S3:", sequences_of_dirs_that_need_upload)
        else:
            self.progress("All revisions already uploaded to S3:", str(base_repo_rev), "...", str(max_repo_rev_to_work_on))

        self.batch_accum.set_current_section('upload')
        for dir_name in dirs_that_need_upload:
            accum = BatchAccumulator()  # sub-accumulator serves as a template for each version
            accum.set_current_section('upload')
            save_dir_var = "REV_" + dir_name + "_SAVE_DIR"
            self.batch_accum += self.platform_helper.save_dir(save_dir_var)
            config_vars["__CURR_REPO_REV__"] = dir_name
            config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.repo_rev_to_folder_hierarchy(dir_name)
            self.upload_to_s3_aws_for_revision(accum)
            revision_lines = accum.finalize_list_of_lines()  # will resolve with current  __CURR_REPO_REV__
            self.batch_accum += revision_lines
            self.batch_accum += self.platform_helper.restore_dir(save_dir_var)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def upload_to_s3_aws_for_revision(self, accum):
        assert config_vars["__CURR_REPO_REV__"].str() == "".join(config_vars["__CURR_REPO_FOLDER_HIERARCHY__"].str().split("/")).lstrip("0")
        map_file_path = 'instl/full_info_map.txt'
        info_map_path = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)/" + map_file_path)
        repo_rev = int(config_vars["__CURR_REPO_REV__"])
        self.info_map_table.clear_all()
        self.info_map_table.read_from_file(info_map_path, disable_indexes_during_read=True)

        accum += Cd("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)")

        if 'Mac' in list(config_vars["__CURRENT_OS_NAMES__"]):
            accum += "find . -name .DS_Store -delete"

        # Files a folders that do not belong to __CURR_REPO_REV__ should not be uploaded.
        # Since aws sync command uploads the whole folder, we delete from disk all files
        # and folders that should not be uploaded.
        self.info_map_table.mark_required_for_dir('instl') # never remove the instl folder
        self.info_map_table.mark_required_for_revision(repo_rev)

        # remove all unrequired files
        self.info_map_table.ignore_unrequired_where_parent_unrequired()
        unrequired_items = self.info_map_table.get_unrequired_not_ignored_paths()
        for i, unrequired_item in enumerate(unrequired_items):
            accum += self.platform_helper.rm_file_or_dir(unrequired_item)
            #if i % 1000 == 0:  # only report every 1000'th file
            #    accum += Progress("rmfile " + unrequired_item +" & 999 more")

        # now remove all empty folders, the files that are left should be uploaded
        remove_empty_folders_command_parts = [self.platform_helper.run_instl(), "remove-empty-folders", "--in", os.curdir]
        accum += Progress("remove-empty-folders ...")
        accum += " ".join(remove_empty_folders_command_parts)
        accum += Progress("remove-empty-folders done")

        # remove broken links, aws cannot handle them
        accum += " ".join( ("find", os.curdir, "-type", "l", "!", "-exec", "test", "-e", "{}", "\;", "-exec", "rm", "-f", "{}", "\;") )

        accum += " ".join(["aws", "s3", "sync",
                           os.curdir, "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)",
                           "--exclude", '"*.DS_Store"',
                           "--exclude", '"$(UP_2_S3_STAMP_FILE_NAME)"',
                           "--exclude", '"$(CREATE_LINKS_STAMP_FILE_NAME)"'
        ])

        up_repo_rev_file_command_parts = [self.platform_helper.run_instl(), "up-repo-rev",
                                          "--config-file", '"$(__CONFIG_FILE_PATH__)"',
                                          "--out", "up_repo_rev.$(__CURR_REPO_REV__)",
                                          "--just-with-number", "$(__CURR_REPO_REV__)",
                                          "--run"]
        accum += " ".join(up_repo_rev_file_command_parts)
        accum += Progress("up-repo-rev file - just with number")

        accum += " ".join(["echo", "-n", "$(BASE_REPO_REV)", ">", "$(UP_2_S3_STAMP_FILE_NAME)"])
        accum += Progress("Uploaded $(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)")
        accum += " ".join(("echo", "find", os.curdir, "-mindepth",  "1", "-maxdepth", "1", "-type", "d", "-not", "-name", "instl"))  #, "-print0", "|", "xargs", "-0", "rm", "-fr"
        accum += Echo("done up2s3 revision $(__CURR_REPO_REV__)")

    def do_create_repo_rev_file(self):
        if "REPO_REV_FILE_VARS" not in config_vars:
            # must have a list of variable names to write to the repo-rev file
            raise ValueError("REPO_REV_FILE_VARS must be defined")
        repo_rev_vars = list(config_vars["REPO_REV_FILE_VARS"])
        config_vars["REPO_REV"] = "$(TARGET_REPO_REV)"  # override the repo rev from the config file

        use_zlib = bool(config_vars.get("USE_ZLIB", "False"))

        # check that the variable names from REPO_REV_FILE_VARS do not contain
        # names that must not be made public
        config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.repo_rev_to_folder_hierarchy(config_vars["TARGET_REPO_REV"].str())
        config_vars["REPO_REV_FOLDER_HIERARCHY"] = "$(__CURR_REPO_FOLDER_HIERARCHY__)"

        config_vars["INSTL_FOLDER_BASE_URL"] = "$(BASE_LINKS_URL)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl"

        dangerous_intersection = set(repo_rev_vars).intersection(
            {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "PRIVATE_KEY", "PRIVATE_KEY_FILE"})
        if dangerous_intersection:
            self.progress("found", str(dangerous_intersection), "in REPO_REV_FILE_VARS, aborting")
            raise ValueError(f"file REPO_REV_FILE_VARS {dangerous_intersection} and so is forbidden to upload")

        # create checksum for the main info_map file
        info_map_file = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/info_map.txt")
        zip_info_map_file = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/info_map.txt$(WZLIB_EXTENSION)")
        if use_zlib:
            config_vars["RELATIVE_INFO_MAP_URL"] = "$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/info_map.txt$(WZLIB_EXTENSION)"
            info_map_checksum = utils.get_file_checksum(zip_info_map_file)
        else:
            config_vars["RELATIVE_INFO_MAP_URL"] = "$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/info_map.txt"
            info_map_checksum = utils.get_file_checksum(info_map_file)
        config_vars["INFO_MAP_FILE_URL"] = "$(BASE_LINKS_URL)/$(RELATIVE_INFO_MAP_URL)"
        config_vars["INFO_MAP_CHECKSUM"] = info_map_checksum

        # create checksum for the main index.yaml file
        # zip the index file
        local_index_file = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/index.yaml")
        zip_local_index_file = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/index.yaml$(WZLIB_EXTENSION)")
        zlib_compression_level = int(config_vars["ZLIB_COMPRESSION_LEVEL"])
        with open(zip_local_index_file, "wb") as wfd:
            wfd.write(zlib.compress(open(local_index_file, "r").read().encode(), zlib_compression_level))

        if use_zlib:
            config_vars["RELATIVE_INDEX_URL"] = "$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/index.yaml$(WZLIB_EXTENSION)"
            index_file_checksum = utils.get_file_checksum(zip_local_index_file)
        else:
            config_vars["RELATIVE_INDEX_URL"] = "$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/index.yaml"
            index_file_checksum = utils.get_file_checksum(local_index_file)
        config_vars["INDEX_URL"] = "$(BASE_LINKS_URL)/$(RELATIVE_INDEX_URL)"
        config_vars["INDEX_CHECKSUM"] = index_file_checksum

        # check that all variables are present
        for var in repo_rev_vars:
            if var not in config_vars:
                raise ValueError(f"{var} is missing cannot write repo rev file")

        # create yaml out of the variables
        variables_as_yaml = config_vars.repr_for_yaml(repo_rev_vars, include_comments=False)
        repo_rev_yaml_doc = aYaml.YamlDumpDocWrap(variables_as_yaml, '!define', "",
                                              explicit_start=True, sort_mappings=True)

        # repo rev file is written to the admin folder and to the repo-rev folder
        os.makedirs(config_vars.resolve_str("$(ROOT_LINKS_FOLDER)/admin"), exist_ok=True)
        admin_folder_path = config_vars.resolve_str("$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(TARGET_REPO_REV)")
        with utils.utf8_open(admin_folder_path, "w") as wfd:
            aYaml.writeAsYaml(repo_rev_yaml_doc, out_stream=wfd, indentor=None, sort=True)
            self.progress("created", admin_folder_path)
        repo_rev_folder_path = config_vars.resolve_str("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/$(REPO_REV_FILE_NAME).$(TARGET_REPO_REV)")

        with utils.utf8_open(repo_rev_folder_path, "w") as wfd:
            aYaml.writeAsYaml(repo_rev_yaml_doc, out_stream=wfd, indentor=None, sort=True)
            self.progress("created", repo_rev_folder_path)

    def do_up_repo_rev(self):
        self.batch_accum.set_current_section('admin')

        just_with_number = int(config_vars["__JUST_WITH_NUMBER__"])
        if just_with_number > 0:
            config_vars["REPO_REV"] = "$(__JUST_WITH_NUMBER__)"

        if just_with_number == 0:
            self.batch_accum += " ".join(["aws", "s3", "cp",
                                "\"$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                               "\"s3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME)\"",
                               "--content-type", 'text/plain'
                                ])
            self.batch_accum += Progress("Uploaded '$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)' to 's3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME)'")

        self.batch_accum += " ".join( ["aws", "s3", "cp",
                           "\"$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                           "\"s3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                           "--content-type", 'text/plain'
                            ] )
        self.batch_accum += Progress("Uploaded '$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)' to 's3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)'")

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def do_fix_props(self):
        self.batch_accum.set_current_section('admin')
        repo_folder = config_vars["SVN_CHECKOUT_FOLDER"].str()
        save_dir = os.getcwd()
        os.chdir(repo_folder)

        # read svn info
        svn_info_command = [config_vars["SVN_CLIENT_PATH"].str(), "info", "--depth", "infinity"]
        proc = subprocess.Popen(svn_info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        my_stdout, my_stderr = proc.communicate()
        my_stdout, my_stderr = utils.unicodify(my_stdout), utils.unicodify(my_stderr)
        if proc.returncode != 0 or my_stderr != "":
            raise ValueError(f"Could not read info from svn: {my_stderr}")
        # write svn info to file for debugging and reference. But go one folder up so not to be in the svn repo.
        with utils.utf8_open("../svn-info-for-fix-props.txt", "w") as wfd:
            wfd.write(my_stdout)
        self.info_map_table.read_from_file("../svn-info-for-fix-props.txt", a_format="info")

        # read svn props
        svn_props_command = [config_vars["SVN_CLIENT_PATH"].str(), "proplist", "--depth", "infinity"]
        proc = subprocess.Popen(svn_props_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        my_stdout, my_stderr = proc.communicate()
        with utils.utf8_open("../svn-proplist-for-fix-props.txt", "w") as wfd:
            wfd.write(utils.unicodify(my_stdout))
        self.info_map_table.read_from_file(config_vars.resolve_str("../svn-proplist-for-fix-props.txt"), a_format="props")

        self.batch_accum += Cd(repo_folder)

        should_be_exec_regex_list = list(config_vars["EXEC_PROP_REGEX"])
        self.compiled_should_be_exec_regex = utils.compile_regex_list_ORed(should_be_exec_regex_list)

        for item in self.info_map_table.get_items(what="any"):
            shouldBeExec = self.should_be_exec(item)
            for extra_prop in item.extra_props_list():
                # print("remove prop", extra_prop, "from", item.path)
                self.batch_accum += " ".join( (config_vars["SVN_CLIENT_PATH"].str(), "propdel", "svn:"+extra_prop, '"'+item.path+'"') )
                self.batch_accum += Progress(" ".join(("remove prop", extra_prop, "from", item.path)) )
            if item.isExecutable() and not shouldBeExec:
                # print("remove prop", "executable", "from", item.path)
                self.batch_accum += " ".join( (config_vars["SVN_CLIENT_PATH"].str(), "propdel", 'svn:executable', '"'+item.path+'"') )
                self.batch_accum += Progress(" ".join(("remove prop", "executable", "from", item.path)) )
            elif not item.isExecutable() and shouldBeExec:
                # print("add prop", "executable", "to", item.path)
                self.batch_accum += " ".join( (config_vars["SVN_CLIENT_PATH"].str(), "propset", 'svn:executable', 'yes', '"'+item.path+'"') )
                self.batch_accum += Progress(" ".join(("add prop", "executable", "from", item.path)) )

        os.chdir(save_dir)
        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def is_file_exec(self, file_path):
        file_mode = stat.S_IMODE(os.stat(file_path).st_mode)
        exec_mode = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        retVal = (file_mode & exec_mode) != 0
        return retVal

    # to do: prevent create-links and up2s3 if there are files marked as symlinks
    def do_fix_symlinks(self):
        self.batch_accum.set_current_section('admin')

        stage_folder = config_vars["STAGING_FOLDER"].str()
        folders_to_check = self.prepare_list_of_dirs_to_work_on(stage_folder)
        if tuple(folders_to_check) == (stage_folder,):
            self.progress("fix-symlink for the whole repository")
        else:
            self.progress("fix-symlink limited to ", "; ".join(folders_to_check))

        for folder_to_check in folders_to_check:
            self.batch_accum += CreateSymlinkFilesInFolder(folder_to_check)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def compile_exclude_regexi(self):
        forbidden_folder_regex_list = list(config_vars["FOLDER_EXCLUDE_REGEX"])
        self.compiled_forbidden_folder_regex = utils.compile_regex_list_ORed(forbidden_folder_regex_list)
        forbidden_file_regex_list = list(config_vars["FILE_EXCLUDE_REGEX"])
        self.compiled_forbidden_file_regex = utils.compile_regex_list_ORed(forbidden_file_regex_list)

    def do_stage2svn(self):
        self.batch_accum.set_current_section('admin')
        stage_folder = config_vars["STAGING_FOLDER"].str()
        svn_folder = config_vars["SVN_CHECKOUT_FOLDER"].str()

        self.compile_exclude_regexi()

        self.batch_accum += Unlock(stage_folder, recursive=True)
        self.batch_accum += Progress("chflags -R nouchg " + stage_folder)
        self.batch_accum += Cd(svn_folder)
        stage_folder_svn_folder_pairs = []
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            self.progress("stage2svn limited to ", limit_list)
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                stage_path = os.path.join(stage_folder,limit)
                svn_path = os.path.join(svn_folder, limit)
                stage_folder_svn_folder_pairs.append((stage_path, svn_path))
        else:
            self.progress("stage2svn for the whole repository")
            stage_folder_svn_folder_pairs.append((stage_folder, svn_folder))
        for pair in stage_folder_svn_folder_pairs:
            if self.compiled_forbidden_folder_regex.search(pair[0]):
                raise utils.InstlException(pair[0] + " has forbidden characters should not be committed to svn")
            comparator = filecmp.dircmp(pair[0], pair[1], ignore=[".svn", ".DS_Store", "Icon\015"])
            self.stage2svn_for_folder(comparator)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def stage2svn_for_folder(self, comparator):
        # copy new items:
        do_not_remove_items = list()
        for left_only_item in sorted(comparator.left_only):
            left_item_path = os.path.join(comparator.left, left_only_item)
            right_item_path = os.path.join(comparator.right, left_only_item)
            if os.path.islink(left_item_path):
                raise utils.InstlException(left_item_path+" is a symlink which should not be committed to svn, run instl fix-symlinks and try again")
            elif os.path.isfile(left_item_path):
                if self.compiled_forbidden_file_regex.search(left_item_path):
                    raise utils.InstlException(left_item_path + " has forbidden characters should not be committed to svn")

                # if left is .wtar.aa file but there is an identical .wtar on the right - do no add.
                # this is done to help transitioning to single wtar files to be .wtar.aa without forcing the users
                # to download again just because extension changed.
                copy_and_add_file = True
                if left_item_path.endswith(".wtar.aa"):
                    right_item_path_without_aa = right_item_path[:-3]
                    if os.path.isfile(right_item_path_without_aa):
                        left_checksum = utils.get_wtar_total_checksum(left_item_path)
                        right_checksum = utils.get_wtar_total_checksum(right_item_path_without_aa)
                        if left_checksum == right_checksum:
                            copy_and_add_file = False
                            do_not_remove_items.append(os.path.basename(right_item_path_without_aa))

                if copy_and_add_file:
                    self.batch_accum += CopyFileToDir(left_item_path, comparator.right, link_dest=False, ignore_patterns=".svn")
                    self.batch_accum += Progress(f"copy file {left_item_path}")
                    # tell svn about new items, svn will not accept 'add' for changed items
                    self.batch_accum += self.platform_helper.svn_add_item(right_item_path)
                    self.batch_accum += Progress(f"add to svn {right_item_path}")
                else:
                    self.batch_accum += Progress(f"not adding {left_item_path} because {right_item_path_without_aa} exists and is identical")

            elif os.path.isdir(left_item_path):
                if self.compiled_forbidden_folder_regex.search(left_item_path):
                    raise utils.InstlException(left_item_path + " has forbidden characters should not be committed to svn")
                # check that all items under a new folder pass the forbidden file/folder rule
                for root, dirs, files in os.walk(left_item_path, followlinks=False):
                    for item in sorted(files):
                        if self.compiled_forbidden_file_regex.search(item):
                            raise utils.InstlException(os.path.join(root, item)+" has forbidden characters should not be committed to svn")
                    for item in sorted(dirs):
                        if self.compiled_forbidden_folder_regex.search(item):
                            raise utils.InstlException(os.path.join(root, item)+" has forbidden characters should not be committed to svn")

                self.batch_accum += CopyDirToDir(left_item_path, comparator.right, link_dest=False, ignore_patterns=".svn", preserve_dest_files=False)
                self.batch_accum += Progress(f"copy dir {left_item_path}")
            else:
                raise utils.InstlException(left_item_path+" not a file, dir or symlink, an abomination!")

        # copy changed items:

        do_not_copy_items = list()  # items that should not be copied even if different, there are items that are part of .wtar where
                                    # each part might be different but the contents are not. E.g. whe re-wtaring files where only
                                    # modification date has changed.
        for diff_item in sorted(comparator.diff_files):
            copy_file = diff_item not in do_not_copy_items
            left_item_path = os.path.join(comparator.left, diff_item)
            right_item_path = os.path.join(comparator.right, diff_item)
            if os.path.islink(left_item_path):
                raise utils.InstlException(left_item_path+" is a symlink which should not be committed to svn, run instl fix-symlinks and try again")
            elif os.path.isfile(left_item_path):
                if self.compiled_forbidden_file_regex.search(left_item_path):
                    raise utils.InstlException(left_item_path+" has forbidden characters should not be committed to svn")

                if utils.is_first_wtar_file(diff_item):
                    left_checksum = utils.get_wtar_total_checksum(left_item_path)
                    right_checksum = utils.get_wtar_total_checksum(right_item_path)
                    if left_checksum == right_checksum:
                        copy_file = False
                        split_wtar_files = utils.find_split_files(left_item_path)
                        do_not_copy_items.extend([os.path.basename(split_wtar_file) for split_wtar_file in split_wtar_files])

                if copy_file:
                    self.batch_accum += CopyFileToDir(left_item_path, comparator.right, link_dest=False, ignore_patterns=".svn")
                    self.batch_accum += Progress(f"copy {left_item_path}")
                else:
                    self.batch_accum += Progress(f"identical {left_item_path}")
            else:
                raise utils.InstlException(left_item_path+" not a different file or symlink, an abomination!")

        # removed items:
        for right_only_item in sorted(comparator.right_only):
            if right_only_item not in do_not_remove_items:
                item_to_remove = os.path.join(comparator.right, right_only_item)
                self.batch_accum += self.platform_helper.svn_remove_item(item_to_remove)
                self.batch_accum += Progress(f"remove from svn {item_to_remove}")

        # recurse to sub folders
        for sub_comparator in list(comparator.subdirs.values()):
            self.stage2svn_for_folder(sub_comparator)

    def prepare_conditions_for_wtar(self):
        folder_wtar_regex_list = list(config_vars["FOLDER_WTAR_REGEX"])
        self.compiled_folder_wtar_regex = utils.compile_regex_list_ORed(folder_wtar_regex_list)
        file_wtar_regex_list = list(config_vars["FILE_WTAR_REGEX"])
        self.compiled_file_wtar_regex = utils.compile_regex_list_ORed(file_wtar_regex_list)

        self.min_file_size_to_wtar = int(config_vars["MIN_FILE_SIZE_TO_WTAR"])

        if "WTAR_BY_FILE_SIZE_EXCLUDE_REGEX" in config_vars:
            wtar_by_file_size_exclude_regex = list(config_vars["WTAR_BY_FILE_SIZE_EXCLUDE_REGEX"])
            self.compiled_wtar_by_file_size_exclude_regex = utils.compile_regex_list_ORed(wtar_by_file_size_exclude_regex)
        else:
            self.compiled_wtar_by_file_size_exclude_regex = None

        self.already_wtarred_regex = re.compile("wtar(\.\w\w)?$")

    def should_wtar(self, dir_item):
        retVal = False
        already_tarred = False
        try:
            if self.already_wtarred_regex.search(dir_item):
                already_tarred = True
                raise Exception
            if os.path.isdir(dir_item):
                if self.compiled_folder_wtar_regex.search(dir_item):
                    retVal = True
                    raise Exception
            elif os.path.isfile(dir_item):
                if self.compiled_file_wtar_regex.search(dir_item):
                    retVal = True
                    raise Exception
                if os.path.getsize(dir_item) > self.min_file_size_to_wtar:
                    if self.compiled_wtar_by_file_size_exclude_regex is not None:
                        if not re.match(self.compiled_wtar_by_file_size_exclude_regex, dir_item):
                            retVal = True
                    else:
                        retVal = True
        except Exception:
            pass
        return retVal, already_tarred

    def do_wtar_staging_folder(self):
        self.batch_accum.set_current_section('admin')
        self.prepare_conditions_for_wtar()
        self.batch_accum += self.platform_helper.split_func()

        stage_folder = config_vars["STAGING_FOLDER"].str()
        folders_to_check = self.prepare_list_of_dirs_to_work_on(stage_folder)
        if tuple(folders_to_check) == (stage_folder,):
            self.progress("wtar for the whole repository")
        else:
            self.progress("wtar limited to ", "; ".join(folders_to_check))

        for a_folder in folders_to_check:
            self.batch_accum += Unlock(a_folder, recursive=True)
            self.batch_accum += Progress(f"chflags -R nouchg {a_folder}")
            self.batch_accum += f"""find "{a_folder}" -name ".DS_Store" -delete"""
            self.batch_accum += Progress("delete ignored files")

        total_items_to_tar = 0
        total_redundant_wtar_files = 0
        while len(folders_to_check) > 0:
            folder_to_check = folders_to_check.pop()
            items_to_tar = list()
            items_to_delete = list()  # these are .wtar files for items that no longer need wtarring

            # check if the folder it self is candidate for wtarring
            to_tar, already_tarred = self.should_wtar(folder_to_check)
            if to_tar:
                items_to_tar.append(folder_to_check)
            else:
                dir_items = os.listdir(folder_to_check)
                for dir_item in sorted(dir_items):
                    dir_item_full_path = os.path.join(folder_to_check, dir_item)
                    if not os.path.islink(dir_item_full_path):
                        to_tar, already_tarred = self.should_wtar(dir_item_full_path)
                        if to_tar:
                            items_to_tar.append(dir_item)
                        else:
                            redundant_wtar_files = utils.find_split_files_from_base_file(dir_item_full_path)
                            total_redundant_wtar_files += len(redundant_wtar_files)
                            items_to_delete.extend(redundant_wtar_files)
                            if os.path.isdir(dir_item_full_path):
                                folders_to_check.append(dir_item_full_path)

            if items_to_tar or items_to_delete:
                total_items_to_tar += len(items_to_tar)
                self.batch_accum += Progress(f"begin folder {folder_to_check}")
                self.batch_accum += Cd(folder_to_check)

                for item_to_delete in items_to_delete:
                    self.batch_accum += self.platform_helper.rmfile(item_to_delete)
                    self.batch_accum += Progress(f"removed file {item_to_delete}")

                for item_to_tar in items_to_tar:
                    item_to_tar_full_path = os.path.join(folder_to_check, item_to_tar)

                    self.batch_accum += self.platform_helper.tar_with_instl(item_to_tar)
                    self.batch_accum += Progress(f"tar file {item_to_tar}")
                    self.batch_accum += self.platform_helper.split(item_to_tar + ".wtar")
                    self.batch_accum += Progress(f"split file {item_to_tar}.wtar")
                    if os.path.isdir(item_to_tar_full_path):
                        self.batch_accum += RmDir(item_to_tar)
                        self.batch_accum += Progress(f"removed dir {item_to_tar}")
                    elif os.path.isfile(item_to_tar_full_path):
                        self.batch_accum += self.platform_helper.rmfile(item_to_tar)
                        self.batch_accum += Progress(f"removed file {item_to_tar}")
                    self.batch_accum += Progress(item_to_tar_full_path)
                self.batch_accum += Progress(f"end folder {folder_to_check}")

        self.progress("found", total_items_to_tar, "to wtar")
        if total_redundant_wtar_files:
            self.progress(total_redundant_wtar_files, "redundant wtar files will be removed")

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def do_svn2stage(self):
        self.batch_accum.set_current_section('admin')
        stage_folder = config_vars["STAGING_FOLDER"].str()
        svn_folder = config_vars["SVN_CHECKOUT_FOLDER"].str()

        # --limit command line option might have been specified
        limit_info_list = []
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                limit_info_list.append((limit, os.path.join(svn_folder, limit), os.path.join(stage_folder, limit) ))
        else:
            limit_info_list.append(("", svn_folder, stage_folder))

        for limit_info in limit_info_list:
            checkout_url = config_vars["SVN_REPO_URL"].str()
            if limit_info[0] != "":
                checkout_url += "/" + limit_info[0]
            checkout_url_quoted = utils.quoteme_double(checkout_url)
            limit_info_quoted = utils.quoteme_double(limit_info[1])
            svn_command_parts = ['"$(SVN_CLIENT_PATH)"', "checkout", checkout_url_quoted, limit_info_quoted, "--depth", "infinity"]
            svn_checkout_command = " ".join(svn_command_parts)
            self.batch_accum += SingleShellCommand(svn_checkout_command, "svn checkout")
            self.batch_accum += Progress(f"Checkout {checkout_url} to {limit_info[1]}")
            self.batch_accum += CopyDirContentsToDir(limit_info[1], limit_info[2], link_dest=False, ignore_patterns=(".svn", ".DS_Store"), preserve_dest_files=False)
            self.batch_accum += Progress(f"rsync {limit_info[1]} to {limit_info[2]}")

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def do_create_rsa_keys(self):
        public_key_file = config_vars["PUBLIC_KEY_FILE"].str()
        private_key_file = config_vars["PRIVATE_KEY_FILE"].str()
        pubkey, privkey = rsa.newkeys(4096, poolsize=8)
        with open(public_key_file, "wb") as wfd:
            wfd.write(pubkey.save_pkcs1(format='PEM'))
            self.progress("public key created:", public_key_file)
        with open(private_key_file, "wb") as wfd:
            wfd.write(privkey.save_pkcs1(format='PEM'))
            self.progress("private key created:", private_key_file)

    def do_make_sig(self):
        private_key = None
        if "PRIVATE_KEY_FILE" in config_vars:
            private_key_file = self.path_searcher.find_file(config_vars["PRIVATE_KEY_FILE"].str(),
                                                            return_original_if_not_found=True)
            private_key = open(private_key_file, "rb").read()
        file_to_sign = self.path_searcher.find_file(config_vars["__MAIN_INPUT_FILE__"].str(),
                                                    return_original_if_not_found=True)
        file_sigs = utils.create_file_signatures(file_to_sign, private_key_text=private_key)
        self.progress("sha1:\n", file_sigs["sha1_checksum"])
        self.progress("SHA-512_rsa_sig:\n", file_sigs.get("SHA-512_rsa_sig", "no private key"))

    def do_check_sig(self):
        file_to_check = self.path_searcher.find_file(config_vars["__MAIN_INPUT_FILE__"].str(),
                                                     return_original_if_not_found=True)
        file_contents = open(file_to_check, "rb").read()

        sha1_checksum = config_vars["__SHA1_CHECKSUM__"].str()
        if sha1_checksum:
            checksumOk = utils.check_buffer_checksum(file_contents, sha1_checksum)
            if checksumOk:
                self.progress("Checksum OK")
            else:
                self.progress("Bad checksum, should be:", utils.get_buffer_checksum(file_contents))

        rsa_signature = config_vars["__RSA_SIGNATURE__"].str()
        if rsa_signature:
            if "PUBLIC_KEY_FILE" in config_vars:
                public_key_file = self.path_searcher.find_file(config_vars["PUBLIC_KEY_FILE"].str(),
                                                               return_original_if_not_found=True)
                public_key_text = open(public_key_file, "rb").read()

                signatureOk = utils.check_buffer_signature(file_contents, rsa_signature, public_key_text)
                if signatureOk:
                    self.progress("Signature OK")
                else:
                    self.progress("Bad Signature")

    def do_verify_index(self):
        self.read_yaml_file(config_vars["__MAIN_INPUT_FILE__"].str())
        self.info_map_table.read_from_file(config_vars["FULL_INFO_MAP_FILE_PATH"].str(), disable_indexes_during_read=True)

        self.verify_index_to_repo()

    def do_read_yaml(self):
        self.read_yaml_file(config_vars["__MAIN_INPUT_FILE__"].str())
        if "__MAIN_OUT_FILE__" in config_vars:
            define_yaml = aYaml.YamlDumpDocWrap(config_vars, '!define', "Definitions", explicit_start=True, sort_mappings=True, include_comments=False)
            index_yaml = aYaml.YamlDumpDocWrap(self.items_table.repr_for_yaml(), '!index', "Installation index", explicit_start=True, sort_mappings=True, include_comments=False)
            out_file_path = config_vars["__MAIN_OUT_FILE__"].str()
            with open(out_file_path, "w") as wfd:
                aYaml.writeAsYaml(define_yaml, wfd)
                aYaml.writeAsYaml(index_yaml, wfd)

    def do_depend(self):
        from . import installItemGraph

        self.read_yaml_file(config_vars["__MAIN_INPUT_FILE__"].str())
        self.items_table.activate_all_oses()
        self.items_table.resolve_inheritance()
        depend_result = defaultdict(dict)
        graph = installItemGraph.create_dependencies_graph(self.items_table)
        all_iids = self.items_table.get_all_iids()
        cache_for_needs = dict()
        for IID in all_iids:
            depend_result[IID]['depends'] = self.needs(IID, set(all_iids), cache_for_needs)
            if not depend_result[IID]['depends']:
                depend_result[IID]['depends'] = None   # so '~' is displayed instead of []

            depend_result[IID]['needed_by'] = self.needed_by(IID, graph)
            if not depend_result[IID]['needed_by']:
                depend_result[IID]['needed_by'] = None # so '~' is displayed instead of []

        out_file_path = config_vars["__MAIN_OUT_FILE__"].str()
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            aYaml.writeAsYaml(aYaml.YamlDumpWrap(depend_result, sort_mappings=True), out_file)
        self.progress("dependencies written to", out_file_path)

    def do_verify_repo(self):
        self.read_yaml_file(config_vars["STAGING_FOLDER_INDEX"].str())

        the_folder = config_vars["STAGING_FOLDER"].str()
        self.info_map_table.initialize_from_folder(the_folder)
        self.items_table.activate_all_oses()
        self.items_table.resolve_inheritance()

        self.verify_index_to_repo()

    def verify_index_to_repo(self):
        """ helper function for verify-repo and verify-index commands
            Assuming the index and info-map have already been read
            check the expect files from the index appear in the info-map
        """
        all_iids = sorted(self.items_table.get_all_iids())
        self.total_self_progress += len(all_iids)
        self.items_table.change_status_of_all_iids(1)

        problem_messages_by_iid = defaultdict(list)

        # check inherit
        self.progress("checking inheritance")
        missing_inheritees = self.items_table.get_missing_iids_from_details("inherit")
        for missing_inheritee in missing_inheritees:
            err_message = " ".join(("inherits from non existing", utils.quoteme_single(missing_inheritee[1])))
            problem_messages_by_iid[missing_inheritee[0]].append(err_message)

        # check depends
        self.progress("checking dependencies")
        missing_dependees = self.items_table.get_missing_iids_from_details("depends")
        for missing_dependee in missing_dependees:
            err_message = " ".join(("depends from non existing", utils.quoteme_single(missing_dependee[1])))
            problem_messages_by_iid[missing_dependee[0]].append(err_message)

        for iid in all_iids:
            self.progress("checking sources for", iid)

            # check sources
            source_and_tag_list = self.items_table.get_details_and_tag_for_active_iids("install_sources", unique_values=True, limit_to_iids=(iid,))

            for source in source_and_tag_list:
                source_path, source_type = source[0], source[1]
                num_files_for_source = self.info_map_table.mark_required_for_source(source_path, source_type)
                if num_files_for_source == 0:
                    err_message = " ".join(("source", utils.quoteme_single(source_path),"required by", iid, "does not have files"))
                    problem_messages_by_iid[iid].append(err_message)

            # check targets
            if len(source_and_tag_list) > 0:
                target_folders = set(self.items_table.get_resolved_details_value_for_active_iid(iid, "install_folders", unique_values=True))
                if len(target_folders) == 0:
                    err_message = " ".join(("iid", iid, "does not have target folder"))
                    problem_messages_by_iid[iid].append(err_message)

        self.progress("checking for cyclic dependencies")
        self.info_map_table.mark_required_completion()
        self.find_cycles()

        for iid in sorted(problem_messages_by_iid):
            self.progress(iid+":")
            for problem_message in sorted(problem_messages_by_iid[iid]):
                self.progress("   ", problem_message)

        self.progress("index:", len(all_iids), "iids")
        num_files = self.info_map_table.num_items("all-files")
        num_dirs = self.info_map_table.num_items("all-dirs")
        num_required_files = self.info_map_table.num_items("required-files")
        num_required_dirs = self.info_map_table.num_items("required-dirs")
        self.progress("info map:", num_files, "files in", num_dirs, "folders")
        self.progress("info map:", num_required_files, "required files, ", num_required_dirs, "required folders")

        unrequired_files = self.info_map_table.get_unrequired_items(what="file")
        self.progress("unrequired files:")
        [self.progress("    ", f.path) for f in unrequired_files]
        unrequired_dirs = self.info_map_table.get_unrequired_items(what="dir")
        self.progress("unrequired dirs:")
        [self.progress("    ", d.path) for d in unrequired_dirs]

    def should_file_be_exec(self, file_path):
        retVal = self.compiled_should_be_exec_regex.search(file_path)
        return retVal is not None

    def should_be_exec(self, item):
        retVal = item.isFile() and self.should_file_be_exec(item.path)
        return retVal

    def prepare_list_of_dirs_to_work_on(self, top_folder):
        """ Some command can operate on a subset of folders inside the main folder.
            If __LIMIT_COMMAND_TO__ is defined join top_folder to each item in __LIMIT_COMMAND_TO__.
            otherwise return top_folder.
        """
        retVal = list()
        if config_vars.defined("__LIMIT_COMMAND_TO__"):
            limit_list = list(config_vars["__LIMIT_COMMAND_TO__"])
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                retVal.append(os.path.join(top_folder, limit))
        else:
            retVal.append(top_folder)
        return retVal

    def do_fix_perm(self):
        self.batch_accum.set_current_section('admin')
        should_be_exec_regex_list = list(config_vars["EXEC_PROP_REGEX"])
        self.compiled_should_be_exec_regex = utils.compile_regex_list_ORed(should_be_exec_regex_list)

        files_that_should_not_be_exec = list()
        files_that_must_be_exec = list()

        folders_to_check = self.prepare_list_of_dirs_to_work_on(config_vars["STAGING_FOLDER"].str())
        for folder_to_check in folders_to_check:
            self.batch_accum += Unlock(folder_to_check, recursive=True)
            self.batch_accum += Progress("chflags -R nouchg " + folder_to_check)
            for root, dirs, files in os.walk(folder_to_check, followlinks=False):
                for a_file in files:
                    item_path = os.path.join(root, a_file)
                    file_is_exec = self.is_file_exec(item_path)
                    file_should_be_exec = self.should_file_be_exec(item_path)
                    if file_is_exec != file_should_be_exec:
                        if file_should_be_exec:
                            self.batch_accum += Chmod(item_path, "a+x")
                            self.batch_accum += Progress("chmod a+x " + item_path)
                            files_that_must_be_exec.append(item_path)
                        else:
                            self.batch_accum += Chmod(item_path, "a-x")
                            self.batch_accum += Progress("chmod a-x " + item_path)
                            files_that_should_not_be_exec.append(item_path)

            self.batch_accum += Chmod(folder_to_check, mode="a+rw,+X", recursive=True)  # "-R a+rw,+X"
            self.batch_accum += Progress("chmod -R a+rw,+X " + folder_to_check)

        if len(files_that_should_not_be_exec) > 0:
            self.progress(f"Exec bit will be removed from the {len(files_that_should_not_be_exec)} following files")
            for a_file in files_that_should_not_be_exec:
                self.progress("   ", a_file)

        if len(files_that_must_be_exec) > 0:
            self.progress(f"Exec bit will be added to the {len(files_that_must_be_exec)} following files")
            for a_file in files_that_must_be_exec:
                self.progress("   ", a_file)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def do_file_sizes(self):
        self.compile_exclude_regexi()
        out_file_path = config_vars["__MAIN_OUT_FILE__"].str()
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            what_to_scan = config_vars["__MAIN_INPUT_FILE__"].str()
            if os.path.isfile(what_to_scan):
                file_size = os.path.getsize(what_to_scan)
                print(what_to_scan+",", file_size, file=out_file)
            else:
                folder_to_scan_name_len = len(what_to_scan)+1 # +1 for the last '\'
                if not self.compiled_forbidden_folder_regex.search(what_to_scan):
                    for root, dirs, files in utils.excluded_walk(what_to_scan, file_exclude_regex=self.compiled_forbidden_file_regex, dir_exclude_regex=self.compiled_forbidden_folder_regex, followlinks=False):
                        for a_file in files:
                            full_path = os.path.join(root, a_file)
                            file_size = os.path.getsize(full_path)
                            partial_path = full_path[folder_to_scan_name_len:]
                            print(partial_path+",", file_size, file=out_file)

    def create_info_map(self, svn_folder, results_folder, accum):

        accum += self.platform_helper.mkdir(results_folder)
        info_map_info_path = os.path.join(results_folder, "info_map.info")
        info_map_props_path = os.path.join(results_folder, "info_map.props")
        info_map_file_sizes_path = os.path.join(results_folder, "info_map.file-sizes")
        full_info_map_file_path = config_vars.resolve_str(os.path.join(results_folder, "$(FULL_INFO_MAP_FILE_NAME)"))

        accum += self.platform_helper.pushd(svn_folder)

        info_command_parts = ['"$(SVN_CLIENT_PATH)"', "info", "--depth infinity", ">", info_map_info_path]
        accum += " ".join(info_command_parts)
        accum += Progress("Get info from svn to" +os.path.join(results_folder, "info_map.info" ))

        # get properties from SVN for all files in revision
        props_command_parts = ['"$(SVN_CLIENT_PATH)"', "proplist", "--depth infinity", ">", info_map_props_path]
        accum += " ".join(props_command_parts)
        accum += Progress("Get props from svn to"+os.path.join(results_folder, "info_map.props"))

        # get sizes of all files
        file_sizes_command_parts = [self.platform_helper.run_instl(), "file-sizes",
                                    "--in", svn_folder,
                                    "--out", info_map_file_sizes_path]
        accum += " ".join(file_sizes_command_parts)
        accum += Progress("Get file-sizes from disk to "+os.path.join(results_folder, "info_map.file-sizes"))

        accum += Progress(f"Create {full_info_map_file_path} ...")
        trans_command_parts = [self.platform_helper.run_instl(), "trans",
                                   "--in", info_map_info_path,
                                   "--props ", info_map_props_path,
                                   "--file-sizes", info_map_file_sizes_path,
                                   "--base-repo-rev", "$(BASE_REPO_REV)",
                                   "--out ", full_info_map_file_path]
        accum += " ".join(trans_command_parts)
        accum += Progress(f"Create {full_info_map_file_path} done")

        # split info_map.txt according to info_map fields in index.yaml
        accum += Progress(f"Split {full_info_map_file_path} ...")
        split_info_map_command_parts = [self.platform_helper.run_instl(), "filter-infomap",
                                        "--in", results_folder, "--define", config_vars.resolve_str("REPO_REV=$(__CURR_REPO_REV__)")]
        accum += " ".join(split_info_map_command_parts)
        accum += Progress(f"Split {full_info_map_file_path} done")

        accum += self.platform_helper.popd()

    def do_create_infomap(self):
        svn_folder = "$(WORKING_SVN_CHECKOUT_FOLDER)"
        results_folder = "$(INFO_MAP_OUTPUT_FOLDER)"
        accum = BatchAccumulator()  # sub-accumulator

        accum.set_current_section('admin')
        self.create_info_map(svn_folder, results_folder, accum)
        self.batch_accum.merge_with(accum)

        self.write_batch_file(self.batch_accum)
        if bool(config_vars["__RUN_BATCH__"]):
            self.run_batch_file()

    def do_filter_infomap(self):
        """ filter the full infomap file according to info_map fields in the index """
        # __MAIN_INPUT_FILE__ is the folder where to find index.yaml, full_info_map.txt and where to create info_map files
        instl_folder = config_vars["__MAIN_INPUT_FILE__"].str()
        full_info_map_file_path = config_vars.resolve_str(os.path.join(instl_folder, "$(FULL_INFO_MAP_FILE_NAME)"))
        index_yaml_path = os.path.join(instl_folder, "index.yaml")
        zlib_compression_level = int(config_vars["ZLIB_COMPRESSION_LEVEL"])

        # read the index
        self.read_yaml_file(index_yaml_path)
        # read the full info map
        self.info_map_table.read_from_file(full_info_map_file_path, a_format="text", disable_indexes_during_read=True)
        # fill the iid_to_svn_item_t table
        self.info_map_table.populate_IIDToSVNItem()

        # get the list of info map file names
        all_info_maps = self.items_table.get_unique_detail_values('info_map')

        lines_for_main_info_map = list()  # each additional info map is written into the main info map
        # write each info map to file
        for infomap_file_name in all_info_maps:
            self.info_map_table.mark_items_required_by_infomap(infomap_file_name)
            info_map_items = self.info_map_table.get_required_items()
            if info_map_items:  # could be that no items are linked to the info map file
                info_map_file_path = os.path.join(instl_folder, infomap_file_name)
                self.info_map_table.write_to_file(in_file=info_map_file_path, items_list=info_map_items, field_to_write=self.fields_relevant_to_info_map)

                info_map_checksum = utils.get_file_checksum(info_map_file_path)
                info_map_size = os.path.getsize(info_map_file_path)
                line_for_main_info_map = f"instl/{infomap_file_name}, f, $(REPO_REV), {info_map_checksum}, {info_map_size}"
                lines_for_main_info_map.append(config_vars.resolve_str(line_for_main_info_map))

                zip_infomap_file_name = config_vars.resolve_str(infomap_file_name+"$(WZLIB_EXTENSION)")
                zip_info_map_file_path = os.path.join(instl_folder, zip_infomap_file_name)
                with Wzip(info_map_file_path, instl_folder) as wzipper:
                    wzipper()

                zip_info_map_checksum = utils.get_file_checksum(zip_info_map_file_path)
                zip_info_map_size = os.path.getsize(zip_info_map_file_path)
                line_for_main_info_map = f"instl/{zip_infomap_file_name}, f, $(REPO_REV), {zip_info_map_checksum}, {zip_info_map_size}"
                lines_for_main_info_map.append(config_vars.resolve_str(line_for_main_info_map))

        # write default info map to file
        default_info_map_file_path = config_vars.resolve_str(os.path.join(instl_folder, "$(MAIN_INFO_MAP_FILE_NAME)"))
        items_for_default_info_map = self.info_map_table.get_items_for_default_infomap()
        self.info_map_table.write_to_file(in_file=default_info_map_file_path, items_list=items_for_default_info_map, field_to_write=self.fields_relevant_to_info_map)

        with open(default_info_map_file_path, "a") as wfd:
            wfd.write("\n".join(lines_for_main_info_map))

        zip_default_info_map_file_path = config_vars.resolve_str(default_info_map_file_path+"$(WZLIB_EXTENSION)")
        with Wzip(default_info_map_file_path, instl_folder) as wzipper:
            wzipper()

    def do_read_info_map(self):
        files_to_read = list(config_vars["__MAIN_INPUT_FILE__"])
        with self.info_map_table.reading_files_context():
            for f2r in files_to_read:
                self.info_map_table.read_from_file(f2r)

    def do_check_instl_folder_integrity(self):
        instl_folder_path = config_vars["__MAIN_INPUT_FILE__"].str()
        index_path = os.path.join(instl_folder_path, "index.yaml")
        self.read_yaml_file(index_path)
        main_info_map_path = os.path.join(instl_folder_path, "info_map.txt")
        self.info_map_table.read_from_file(main_info_map_path)
        instl_folder_path_parts = os.path.normpath(instl_folder_path).split(os.path.sep)
        revision_folder_name = instl_folder_path_parts[-2]
        revision_file_path = os.path.join(instl_folder_path, "V9_repo_rev.yaml."+revision_folder_name)
        if not os.path.isfile(revision_file_path):
            self.progress("file not found", revision_file_path)
        self.read_yaml_file(revision_file_path)
        index_checksum = utils.get_file_checksum(index_path)
        if config_vars["INDEX_CHECKSUM"].str() != index_checksum:
            self.progress(f"""bad index checksum expected: {config_vars["INDEX_CHECKSUM"]}, actual: {index_checksum}""")

        main_info_map_checksum = utils.get_file_checksum(main_info_map_path)
        if config_vars["INFO_MAP_CHECKSUM"].str() != main_info_map_checksum:
            self.progress(f"""bad info_map.txt checksum expected: {config_vars["INFO_MAP_CHECKSUM"]}, actual: {main_info_map_checksum}""")

        self.items_table.activate_all_oses()
        all_info_maps = self.items_table.get_detail_values_by_name_for_all_iids("info_map")
        all_instl_folder_items = self.info_map_table.get_file_items_of_dir('instl')
        for item in all_instl_folder_items:
            if item.leaf in all_info_maps:
                info_map_full_path = os.path.join(instl_folder_path, item.leaf)
                info_map_checksum = utils.get_file_checksum(info_map_full_path)
                if item.checksum != info_map_checksum:
                    self.progress("""bad {item.leaf} checksum expected: {item.checksum}, actual: {info_map_checksum}""")
