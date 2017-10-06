#!/usr/bin/env python3


import os
import filecmp
import io
import re
import shutil
import subprocess
from collections import defaultdict
import stat

import utils
import aYaml
from .instlInstanceBase import InstlInstanceBase
from .batchAccumulator import BatchAccumulator
from configVar import var_stack
from svnTree import SVNTable


# noinspection PyPep8,PyPep8,PyPep8
class InstlAdmin(InstlInstanceBase):

    def __init__(self, initial_vars):
        super().__init__(initial_vars)
        self.init_items_table()
        var_stack.add_const_config_variable("__DATABASE_URL__", "", self.items_table.get_db_url())
        self.info_map_table = SVNTable()
        self.read_name_specific_defaults_file(super().__thisclass__.__name__)
        self.fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')

    def get_default_out_file(self):
        retVal = None
        if "__MAIN_INPUT_FILE__" in var_stack:
            retVal = "$(__CONFIG_FILE__)-$(__MAIN_COMMAND__).$(BATCH_EXT)"
        return retVal

    def set_default_variables(self):
        if "__CONFIG_FILE__" in var_stack:
            config_file_resolved = self.path_searcher.find_file(var_stack.ResolveVarToStr("__CONFIG_FILE__"), return_original_if_not_found=True)
            var_stack.set_var("__CONFIG_FILE_PATH__").append(config_file_resolved)

            self.read_yaml_file(config_file_resolved)
            self.resolve_defined_paths()
        if "PUBLIC_KEY" not in var_stack:
            if "PUBLIC_KEY_FILE" in var_stack:
                try:
                    public_key_file = var_stack.ResolveVarToStr("PUBLIC_KEY_FILE")
                    public_key_text = open(public_key_file, "rb").read()
                    var_stack.set_var("PUBLIC_KEY", "from " + public_key_file).append(public_key_text)
                except Exception:
                    pass  # lo nora
        if "PRIVATE_KEY" not in var_stack:
            if "PRIVATE_KEY_FILE" in var_stack:
                try:
                    private_key_file = var_stack.ResolveVarToStr("PRIVATE_KEY_FILE")
                    private_key_text = open(private_key_file, "rb").read()
                    var_stack.set_var("PUBLIC_KEY", "from " + private_key_file).append(private_key_text)
                except Exception:
                    pass  # lo nora

    def do_command(self):
        self.set_default_variables()
        self.platform_helper.num_items_for_progress_report = int(var_stack.ResolveVarToStr("LAST_PROGRESS"))
        self.platform_helper.init_copy_tool()
        do_command_func = getattr(self, "do_" + self.fixed_command)
        do_command_func()

    def do_trans(self):
        self.info_map_table.read_from_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"), a_format="info")
        if "__PROPS_FILE__" in var_stack:
            self.info_map_table.read_from_file(var_stack.ResolveVarToStr("__PROPS_FILE__"), a_format="props")
        if "__FILE_SIZES_FILE__" in var_stack:
            self.info_map_table.read_from_file(var_stack.ResolveVarToStr("__FILE_SIZES_FILE__"), a_format="file-sizes")

        base_rev = int(var_stack.ResolveVarToStr("BASE_REPO_REV"))
        if base_rev > 0:
            self.info_map_table.set_base_revision(base_rev)

        if "__BASE_URL__" in var_stack:
            self.add_urls_to_info_map()
        self.info_map_table.write_to_file(var_stack.ResolveVarToStr("__MAIN_OUT_FILE__"), field_to_write=self.fields_relevant_to_info_map)

    def add_urls_to_info_map(self):
        base_url = var_stack.ResolveVarToStr("__BASE_URL__")
        for file_item in self.info_map_table.get_items(what="file"):
            file_item.url = os.path.join(base_url, str(file_item.revision), file_item.path)
            print(file_item)

    def get_revision_range(self):
        revision_range_re = re.compile("""
                                (?P<min_rev>\d+)
                                (:
                                (?P<max_rev>\d+)
                                )?
                                """, re.VERBOSE)
        min_rev = 0
        max_rev = 1
        match = revision_range_re.match(var_stack.ResolveVarToStr("REPO_REV"))
        if match:
            min_rev += int(match.group('min_rev'))
            if match.group('max_rev'):
                max_rev += int(match.group('max_rev'))
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
        current_base_repo_rev = int(var_stack.ResolveVarToStr("BASE_REPO_REV"))
        retVal = True
        revision_links_folder = var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/" + str(revision))
        create_links_done_stamp_file = var_stack.ResolveStrToStr(revision_links_folder + "/$(CREATE_LINKS_STAMP_FILE_NAME)")
        if os.path.isfile(create_links_done_stamp_file):
            if revision == current_base_repo_rev:  # revision is the new base_repo_rev
                try:
                    previous_base_repo_rev = int(utils.utf8_open(create_links_done_stamp_file, "r").read())  # try to read the previous
                    if previous_base_repo_rev == current_base_repo_rev:
                        retVal = False
                    else:
                        msg = " ".join( ("new base revision", str(current_base_repo_rev), "(was", str(previous_base_repo_rev),") need to refresh links") )
                        self.batch_accum += self.platform_helper.echo(msg)
                        print(msg)
                        # if we need to create links, remove the upload stems in order to force upload
                        try: os.remove(var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/"+str(revision)+"/$(UP_2_S3_STAMP_FILE_NAME)"))
                        except Exception: pass
                except Exception:
                    pass  # no previous base repo rev indication was found so return True to re-create the links
            else:
                retVal = False
        return retVal

    def get_last_repo_rev(self):
        retVal = 0
        revision_line_re = re.compile("^Revision:\s+(?P<revision>\d+)$")
        repo_url = var_stack.ResolveVarToStr("SVN_REPO_URL")
        if os.path.isdir(repo_url):
            svn_info_command = [var_stack.ResolveVarToStr("SVN_CLIENT_PATH"), "info", "."]
        else:
            svn_info_command = [var_stack.ResolveVarToStr("SVN_CLIENT_PATH"), "info", repo_url]
        with utils.ChangeDirIfExists(repo_url):
            proc = subprocess.Popen(svn_info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            my_stdout, my_stderr = proc.communicate()
            my_stdout, my_stderr = utils.unicodify(my_stdout), utils.unicodify(my_stderr)
            if proc.returncode != 0 or my_stderr != "":
                raise ValueError("Could not read info from svn: ", my_stderr, proc.returncode)
            info_as_io = io.StringIO(my_stdout)
            for line in info_as_io:
                match = revision_line_re.match(line)
                if match:
                    retVal = int(match.group("revision"))
                    break
        if retVal <= 0:
            raise ValueError("Could not find last repo rev for " + repo_url)
        var_stack.set_var("__LAST_REPO_REV__").append(str(retVal))
        return retVal

    def do_create_links(self):
        self.check_prerequisite_var_existence(("REPO_NAME", "SVN_REPO_URL", "ROOT_LINKS_FOLDER_REPO"))

        self.batch_accum.set_current_section('links')

        # call svn info to find out the last repo revision
        last_repo_rev = self.get_last_repo_rev()
        base_repo_rev = int(var_stack.ResolveVarToStr("BASE_REPO_REV"))
        curr_repo_rev = int(var_stack.ResolveVarToStr("REPO_REV"))
        if base_repo_rev > curr_repo_rev:
            raise ValueError("base_repo_rev "+str(base_repo_rev)+" > curr_repo_rev "+str(curr_repo_rev))
        if curr_repo_rev > last_repo_rev:
            raise ValueError("base_repo_rev "+str(base_repo_rev)+" > last_repo_rev "+str(last_repo_rev))

        self.batch_accum += self.platform_helper.mkdir("$(ROOT_LINKS_FOLDER_REPO)/Base")

        accum = BatchAccumulator()  # sub-accumulator serves as a template for each version
        accum.set_current_section('links')
        self.create_links_for_revision(accum)

        self.batch_accum += self.platform_helper.cd("$(ROOT_LINKS_FOLDER_REPO)")
        no_need_link_nums = list()
        yes_need_link_nums = list()
        max_repo_rev_to_work_on = curr_repo_rev
        if "__ALL_REVISIONS__" in var_stack:
            max_repo_rev_to_work_on = last_repo_rev
        for revision in range(base_repo_rev, max_repo_rev_to_work_on+1):
            if self.needToCreatelinksForRevision(revision):
                yes_need_link_nums.append(str(revision))
                save_dir_var = "REV_" + str(revision) + "_SAVE_DIR"
                self.batch_accum += self.platform_helper.save_dir(save_dir_var)
                var_stack.set_var("__CURR_REPO_REV__").append(str(revision))
                revision_lines = accum.finalize_list_of_lines()  # will resolve with current  __CURR_REPO_REV__
                self.batch_accum += revision_lines
                self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
                self.batch_accum += self.platform_helper.new_line()
            else:
                no_need_link_nums.append(str(revision))

        if yes_need_link_nums:
            if no_need_link_nums:
                no_need_links_str = utils.find_sequences(no_need_link_nums)
                msg = " ".join(("Links already created for revisions:", no_need_links_str))
                print(msg)
            yes_need_links_str = utils.find_sequences(yes_need_link_nums)
            var_stack.set_var("__NEED_UPLOAD_REPO_REV_LIST__").extend(yes_need_link_nums)
            msg = " ".join(("Need to create links for revisions:", yes_need_links_str))
            print(msg)
        else:
            msg = " ".join( ("Links already created for all revisions:", str(base_repo_rev), "...", str(max_repo_rev_to_work_on)) )
            print(msg)

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def create_links_for_revision(self, accum):
        base_folder_path = "$(ROOT_LINKS_FOLDER_REPO)/Base"
        revision_folder_path = "$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)"
        revision_instl_folder_path = revision_folder_path + "/instl"

        # sync revision __CURR_REPO_REV__ from SVN to Base folder
        accum += self.platform_helper.echo("Getting revision $(__CURR_REPO_REV__) from $(SVN_REPO_URL)")
        checkout_command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"' + "$(SVN_REPO_URL)@$(__CURR_REPO_REV__)" + '"',
                                  '"' + base_folder_path + '"', "--depth", "infinity"]
        accum += " ".join(checkout_command_parts)
        accum += self.platform_helper.progress("Create links for revision $(__CURR_REPO_REV__)")

        # copy Base folder to revision folder
        accum += self.platform_helper.mkdir(revision_folder_path)
        accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(base_folder_path, revision_folder_path,
                                                                         link_dest=True, ignore=".svn", preserve_dest_files=False)
        accum += self.platform_helper.progress("Copy revision $(__CURR_REPO_REV__) to "+revision_folder_path)

        # get info from SVN for all files in revision
        self.create_info_map(base_folder_path, revision_instl_folder_path, accum)

        accum += self.platform_helper.pushd(revision_folder_path)
        # create depend file
        create_depend_file_command_parts = [self.platform_helper.run_instl(), "depend", "--in", "instl/index.yaml",
                                            "--out", "instl/index-dependencies.yaml"]
        accum += " ".join(create_depend_file_command_parts)
        accum += self.platform_helper.progress("Create dependencies file")

        # create repo-rev file
        accum += self.platform_helper.progress("Create repo-rev file ...")
        create_repo_rev_file_command_parts = [self.platform_helper.run_instl(), "create-repo-rev-file",
                                              "--config-file", '"$(__CONFIG_FILE_PATH__)"', "--rev", "$(__CURR_REPO_REV__)"]
        accum += " ".join(create_repo_rev_file_command_parts)
        accum += self.platform_helper.progress("Create repo-rev file done")

        # create text versions of info and yaml files, so they can be displayed in browser
        if var_stack.ResolveVarToStr("__CURRENT_OS__") == "Linux":
            accum += " ".join(("find", "instl", "-type", "f", "-regextype", "posix-extended",
                               "-regex", "'.*(yaml|info|props)'", "-print0", "|",
                               "xargs", "-0", "-I{}", "cp", "-f", '"{}"', '"{}.txt"'))
        elif var_stack.ResolveVarToStr("__CURRENT_OS__") == "Mac":
            accum += " ".join(("find", "-E", "instl", "-type", "f",
                               "-regex", "'.*(yaml|info|props)'", "-print0", "|",
                               "xargs", "-0", "-I{}", "cp", "-f", '"{}"', '"{}.txt"'))
        else:
            raise EnvironmentError("instl admin commands can only run under Mac or Linux")

        accum += self.platform_helper.rmfile("$(UP_2_S3_STAMP_FILE_NAME)")
        accum += self.platform_helper.progress("Remove $(UP_2_S3_STAMP_FILE_NAME)")
        accum += " ".join(["echo", "-n", "$(BASE_REPO_REV)", ">", "$(CREATE_LINKS_STAMP_FILE_NAME)"])
        accum += self.platform_helper.progress("Create $(CREATE_LINKS_STAMP_FILE_NAME)")

        accum += self.platform_helper.popd()
        accum += self.platform_helper.echo("done create-links version $(__CURR_REPO_REV__)")

    class RemoveIfNotSpecificVersion(object):
        def __init__(self, version_not_to_remove):
            self.version_not_to_remove = version_not_to_remove

        def __call__(self, svn_item):
            retVal = None
            if svn_item.isFile():
                retVal = svn_item.revision != self.version_not_to_remove
            elif svn_item.isDir():
                retVal = len(svn_item.subs) == 0
            return retVal

    def do_up2s3(self):
        base_repo_rev = int(var_stack.ResolveVarToStr("BASE_REPO_REV"))
        curr_repo_rev = int(var_stack.ResolveVarToStr("REPO_REV"))
        # call svn info to find out the last repo revision
        last_repo_rev = self.get_last_repo_rev()
        if base_repo_rev > curr_repo_rev:
            raise ValueError("base_repo_rev "+str(base_repo_rev)+" > curr_repo_rev "+str(curr_repo_rev))
        if curr_repo_rev > last_repo_rev:
            raise ValueError("base_repo_rev "+str(base_repo_rev)+" > last_repo_rev "+str(last_repo_rev))

        max_repo_rev_to_work_on = curr_repo_rev
        if "__ALL_REVISIONS__" in var_stack:
            max_repo_rev_to_work_on = last_repo_rev
        revision_list = list(range(base_repo_rev, max_repo_rev_to_work_on+1))
        dirs_that_dont_need_upload = list()
        dirs_that_need_upload = list()
        dirs_missing = list()
        for dir_as_int in revision_list:
            dir_name = str(dir_as_int)
            if not os.path.isdir(var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/" + dir_name)):
                print("revision dir", dir_name, "is missing, run create-links to create this folder")
                dirs_missing.append(dir_name)
            else:
                create_links_done_stamp_file = var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/"+dir_name+"/$(CREATE_LINKS_STAMP_FILE_NAME)")
                if not os.path.isfile(create_links_done_stamp_file):
                    print("revision dir", dir_name, "does not have create-links stamp file:", create_links_done_stamp_file)
                else:
                    up_2_s3_done_stamp_file = var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/"+dir_name+"/$(UP_2_S3_STAMP_FILE_NAME)")
                    if os.path.isfile(up_2_s3_done_stamp_file):
                        dirs_that_dont_need_upload.append(dir_name)
                    else:
                        dirs_that_need_upload.append(dir_name)
        if dirs_missing:
            sequences_of_dirs_missing = utils.find_sequences(dirs_missing)
            msg = " ".join( ("Revisions cannot be uploaded to S3:", sequences_of_dirs_missing) )
            print(msg)
            dirs_that_need_upload = []
        elif dirs_that_need_upload:
            if dirs_that_dont_need_upload:
                sequences_of_dirs_that_dont_need_upload = utils.find_sequences(dirs_that_dont_need_upload)
                msg = " ".join(("Revisions already uploaded to S3:", sequences_of_dirs_that_dont_need_upload))
                print(msg)
            sequences_of_dirs_that_need_upload = utils.find_sequences(dirs_that_need_upload)
            msg = " ".join(("Revisions will be uploaded to S3:", sequences_of_dirs_that_need_upload))
            print(msg)
        else:
            msg = " ".join( ("All revisions already uploaded to S3:", str(base_repo_rev), "...", str(max_repo_rev_to_work_on)) )
            print(msg)

        self.batch_accum.set_current_section('upload')
        for dir_name in dirs_that_need_upload:
            accum = BatchAccumulator()  # sub-accumulator serves as a template for each version
            accum.set_current_section('upload')
            save_dir_var = "REV_" + dir_name + "_SAVE_DIR"
            self.batch_accum += self.platform_helper.save_dir(save_dir_var)
            var_stack.set_var("__CURR_REPO_REV__").append(dir_name)
            self.upload_to_s3_aws_for_revision(accum)
            revision_lines = accum.finalize_list_of_lines()  # will resolve with current  __CURR_REPO_REV__
            self.batch_accum += revision_lines
            self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
            self.batch_accum += self.platform_helper.new_line()

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def upload_to_s3_aws_for_revision(self, accum):
        map_file_path = 'instl/info_map.txt'
        info_map_path = var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)/" + map_file_path)
        repo_rev = int(var_stack.ResolveVarToStr("__CURR_REPO_REV__"))
        self.info_map_table.clear_all()
        self.info_map_table.read_from_file(info_map_path)

        accum += self.platform_helper.cd("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)")

        if 'Mac' in var_stack.ResolveVarToList("__CURRENT_OS_NAMES__"):
            accum += "find . -name .DS_Store -delete"

        # Files a folders that do not belong to __CURR_REPO_REV__ should not be uploaded.
        # Since aws sync command uploads the whole folder, we delete from disk all files
        # and folders that should not be uploaded.
        # To save delete instructions for every file, we first delete those folders where
        # all files are not __CURR_REPO_REV__. Then the remaining files  are removed
        self.info_map_table.mark_required_for_dir('instl') # never remove the instl folder
        self.info_map_table.mark_required_for_revision(repo_rev)

        unrequired_dirs = self.info_map_table.get_unrequired_paths_where_parent_required(what="dir")
        for unrequired_dir in unrequired_dirs:
            accum += self.platform_helper.rmdir(unrequired_dir, recursive=True)
            accum += self.platform_helper.progress("rmdir " + unrequired_dir)

        unrequired_files = self.info_map_table.get_unrequired_paths_where_parent_required(what="file")
        for unrequired_file in unrequired_files:
            accum += self.platform_helper.rmfile(unrequired_file)
            accum += self.platform_helper.progress("rmfile " + unrequired_file)

        # remove broken links, aws cannot handle them
        accum += " ".join( ("find", ".", "-type", "l", "!", "-exec", "test", "-e", "{}", "\;", "-exec", "rm", "-f", "{}", "\;") )

        accum += " ".join(["aws", "s3", "sync",
                           ".", "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_REV__)",
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
        accum += self.platform_helper.progress("up-repo-rev file - just with number")

        accum += " ".join(["echo", "-n", "$(BASE_REPO_REV)", ">", "$(UP_2_S3_STAMP_FILE_NAME)"])
        accum += self.platform_helper.progress("Uploaded $(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)")
        accum += " ".join(("echo", "find", ".", "-mindepth",  "1", "-maxdepth", "1", "-type", "d", "-not", "-name", "instl"))  #, "-print0", "|", "xargs", "-0", "rm", "-fr"
        accum += self.platform_helper.echo("done up2s3 revision $(__CURR_REPO_REV__)")

    def create_sig_for_file(self, file_to_sig):
        config_dir, _ = os.path.split(var_stack.ResolveVarToStr("__CONFIG_FILE_PATH__"))
        private_key_file = os.path.join(config_dir, var_stack.ResolveVarToStr("REPO_NAME") + ".private_key")
        with open(private_key_file, "rb") as private_key_fd:
            retVal = utils.create_file_signatures(file_to_sig, private_key_fd.read())
        return retVal

    def do_create_repo_rev_file(self):
        if "REPO_REV_FILE_VARS" not in var_stack:
            raise ValueError("REPO_REV_FILE_VARS must be defined")
        repo_rev_vars = var_stack.ResolveVarToList("REPO_REV_FILE_VARS")
        var_stack.set_var("REPO_REV").append("$(TARGET_REPO_REV)")  # override the repo rev from the config file
        dangerous_intersection = set(repo_rev_vars).intersection(
            {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "PRIVATE_KEY", "PRIVATE_KEY_FILE"})
        if dangerous_intersection:
            print("found", str(dangerous_intersection), "in REPO_REV_FILE_VARS, aborting")
            raise ValueError("file REPO_REV_FILE_VARS "+str(dangerous_intersection)+" and so is forbidden to upload")

        info_map_file = var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/$(TARGET_REPO_REV)/instl/info_map.txt")
        info_map_sigs = self.create_sig_for_file(info_map_file)
        var_stack.set_var("INFO_MAP_SIG").append(info_map_sigs["SHA-512_rsa_sig"])
        var_stack.set_var("INFO_MAP_CHECKSUM").append(info_map_sigs["sha1_checksum"])

        var_stack.set_var("INDEX_URL_RELATIVE_PATH").append("$(REPO_NAME)/$(REPO_REV)/instl/index.yaml")
        var_stack.set_var("INDEX_URL").append("$(S3_BUCKET_BASE_URL)/$(INDEX_URL_RELATIVE_PATH)")
        index_file = var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER_REPO)/$(TARGET_REPO_REV)/instl/index.yaml")
        index_file_sigs = self.create_sig_for_file(index_file)
        var_stack.set_var("INDEX_SIG").append(index_file_sigs["SHA-512_rsa_sig"])
        var_stack.set_var("INDEX_CHECKSUM").append(index_file_sigs["sha1_checksum"])

        for var in repo_rev_vars:
            if var not in var_stack:
                raise ValueError(var + " is missing cannot write repo rev file")

        repo_rev_yaml = aYaml.YamlDumpDocWrap(var_stack.repr_for_yaml(repo_rev_vars, include_comments=False),
                                              '!define', "", explicit_start=True, sort_mappings=True)
        os.makedirs(var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER)/admin"), exist_ok=True)
        local_file = var_stack.ResolveStrToStr("$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(TARGET_REPO_REV)")
        with utils.utf8_open(local_file, "w") as wfd:
            aYaml.writeAsYaml(repo_rev_yaml, out_stream=wfd, indentor=None, sort=True)
            print("created", local_file)

    def do_up_repo_rev(self):
        self.batch_accum.set_current_section('admin')

        just_with_number = int(var_stack.ResolveVarToStr("__JUST_WITH_NUMBER__"))
        if just_with_number > 0:
            var_stack.set_var("REPO_REV").append("$(__JUST_WITH_NUMBER__)")

        if just_with_number == 0:
            self.batch_accum += " ".join(["aws", "s3", "cp",
                                "\"$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                               "\"s3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME)\"",
                               "--content-type", 'text/plain'
                                ])
            self.batch_accum += self.platform_helper.progress("Uploaded '$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)' to 's3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME)'")

        self.batch_accum += " ".join( ["aws", "s3", "cp",
                           "\"$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                           "\"s3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                           "--content-type", 'text/plain'
                            ] )
        self.batch_accum += self.platform_helper.progress("Uploaded '$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)' to 's3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)'")

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def do_fix_props(self):
        self.batch_accum.set_current_section('admin')
        repo_folder = var_stack.ResolveVarToStr("SVN_CHECKOUT_FOLDER")
        save_dir = os.getcwd()
        os.chdir(repo_folder)

        # read svn info
        svn_info_command = [var_stack.ResolveVarToStr("SVN_CLIENT_PATH"), "info", "--depth", "infinity"]
        proc = subprocess.Popen(svn_info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        my_stdout, my_stderr = proc.communicate()
        my_stdout, my_stderr = utils.unicodify(my_stdout), utils.unicodify(my_stderr)
        if proc.returncode != 0 or my_stderr != "":
            raise ValueError("Could not read info from svn: " + my_stderr)
        # write svn info to file for debugging and reference. But go one folder up so not to be in the svn repo.
        with utils.utf8_open("../svn-info-for-fix-props.txt", "w") as wfd:
            wfd.write(my_stdout)
        self.info_map_table.read_from_file("../svn-info-for-fix-props.txt", a_format="info")

        # read svn props
        svn_props_command = [var_stack.ResolveVarToStr("SVN_CLIENT_PATH"), "proplist", "--depth", "infinity"]
        proc = subprocess.Popen(svn_props_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        my_stdout, my_stderr = proc.communicate()
        with utils.utf8_open("../svn-proplist-for-fix-props.txt", "w") as wfd:
            wfd.write(my_stdout)
        self.info_map_table.read_from_file(var_stack.ResolveStrToStr("../svn-proplist-for-fix-props.txt"), a_format="props")

        self.batch_accum += self.platform_helper.cd(repo_folder)

        should_be_exec_regex_list = var_stack.ResolveVarToList("EXEC_PROP_REGEX")
        self.compiled_should_be_exec_regex = utils.compile_regex_list_ORed(should_be_exec_regex_list)

        for item in self.info_map_table.get_items(what="any"):
            shouldBeExec = self.should_be_exec(item)
            for extra_prop in item.extra_props_list():
                # print("remove prop", extra_prop, "from", item.path)
                self.batch_accum += " ".join( (var_stack.ResolveVarToStr("SVN_CLIENT_PATH"), "propdel", "svn:"+extra_prop, '"'+item.path+'"') )
                self.batch_accum += self.platform_helper.progress(" ".join(("remove prop", extra_prop, "from", item.path)) )
            if item.isExecutable() and not shouldBeExec:
                # print("remove prop", "executable", "from", item.path)
                self.batch_accum += " ".join( (var_stack.ResolveVarToStr("SVN_CLIENT_PATH"), "propdel", 'svn:executable', '"'+item.path+'"') )
                self.batch_accum += self.platform_helper.progress(" ".join(("remove prop", "executable", "from", item.path)) )
            elif not item.isExecutable() and shouldBeExec:
                # print("add prop", "executable", "to", item.path)
                self.batch_accum += " ".join( (var_stack.ResolveVarToStr("SVN_CLIENT_PATH"), "propset", 'svn:executable', 'yes', '"'+item.path+'"') )
                self.batch_accum += self.platform_helper.progress(" ".join(("add prop", "executable", "from", item.path)) )

        os.chdir(save_dir)
        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def is_file_exec(self, file_path):
        file_mode = stat.S_IMODE(os.stat(file_path).st_mode)
        exec_mode = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        retVal = (file_mode & exec_mode) != 0
        return retVal

    # to do: prevent create-links and up2s3 if there are files marked as symlinks
    def do_fix_symlinks(self):
        self.batch_accum.set_current_section('admin')

        stage_folder = var_stack.ResolveVarToStr("STAGING_FOLDER")
        folders_to_check = self.prepare_list_of_dirs_to_work_on(stage_folder)
        if tuple(folders_to_check) == (stage_folder,):
            print("fix-symlink for the whole repository")
        else:
            print("fix-symlink limited to ", "; ".join(folders_to_check))

        valid_symlinks = list()
        broken_symlinks = list()
        for folder_to_check in folders_to_check:
            for root, dirs, files in os.walk(folder_to_check, followlinks=False):
                for item in files + dirs:
                    item_path = os.path.join(root, item)
                    if os.path.islink(item_path):
                        target_path = os.path.realpath(item_path)
                        link_value = os.readlink(item_path)
                        if os.path.isdir(target_path) or os.path.isfile(target_path):
                            valid_symlinks.append((item_path, link_value))
                        else:
                            valid_symlinks.append((item_path, link_value))  # fix even the broken symlinks
                            broken_symlinks.append((item_path, link_value))
        if len(broken_symlinks) > 0:
            print("Found broken symlinks")
            for symlink_file, link_value in broken_symlinks:
                print(symlink_file, "-?>", link_value)
        if len(valid_symlinks) > 0:
            for symlink_file, link_value in valid_symlinks:
                symlink_text_path = symlink_file + ".symlink"
                self.batch_accum += " ".join(("echo", "-n", "'" + link_value + "'", ">", "'" + symlink_text_path + "'"))
                self.batch_accum += self.platform_helper.rmfile(symlink_file)
                self.batch_accum += self.platform_helper.progress(symlink_text_path)
                self.batch_accum += self.platform_helper.new_line()

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def compile_exclude_regexi(self):
        forbidden_folder_regex_list = var_stack.ResolveVarToList("FOLDER_EXCLUDE_REGEX")
        self.compiled_forbidden_folder_regex = utils.compile_regex_list_ORed(forbidden_folder_regex_list)
        forbidden_file_regex_list = var_stack.ResolveVarToList("FILE_EXCLUDE_REGEX")
        self.compiled_forbidden_file_regex = utils.compile_regex_list_ORed(forbidden_file_regex_list)

    def do_stage2svn(self):
        self.batch_accum.set_current_section('admin')
        stage_folder = var_stack.ResolveVarToStr("STAGING_FOLDER")
        svn_folder = var_stack.ResolveVarToStr("SVN_CHECKOUT_FOLDER")

        self.compile_exclude_regexi()

        self.batch_accum += self.platform_helper.unlock(stage_folder, recursive=True)
        self.batch_accum += self.platform_helper.progress("chflags -R nouchg " + stage_folder)
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.cd(svn_folder)
        stage_folder_svn_folder_pairs = []
        if var_stack.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_stack.ResolveVarToList("__LIMIT_COMMAND_TO__")
            print("stage2svn limited to ", limit_list)
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                stage_path = os.path.join(stage_folder,limit)
                svn_path = os.path.join(svn_folder, limit)
                stage_folder_svn_folder_pairs.append((stage_path, svn_path))
        else:
            print("stage2svn for the whole repository")
            stage_folder_svn_folder_pairs.append((stage_folder, svn_folder))
        for pair in stage_folder_svn_folder_pairs:
            if self.compiled_forbidden_folder_regex.search(pair[0]):
                raise utils.InstlException(pair[0] + " has forbidden characters should not be committed to svn")
            comparator = filecmp.dircmp(pair[0], pair[1], ignore=[".svn", ".DS_Store", "Icon\015"])
            self.stage2svn_for_folder(comparator)

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
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
                    self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(left_item_path, comparator.right, link_dest=False, ignore=".svn")
                    self.batch_accum += self.platform_helper.progress("copy file {}".format(left_item_path))
                    # tell svn about new items, svn will not accept 'add' for changed items
                    self.batch_accum += self.platform_helper.svn_add_item(right_item_path)
                    self.batch_accum += self.platform_helper.progress("add to svn {}".format(right_item_path))
                else:
                    self.batch_accum += self.platform_helper.progress("not adding {} because {} exists and is identical".format(left_item_path, right_item_path_without_aa))

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

                self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(left_item_path, comparator.right, link_dest=False, ignore=".svn", preserve_dest_files=False)
                self.batch_accum += self.platform_helper.progress("copy dir {}".format(left_item_path))
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
                    self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(left_item_path, comparator.right, link_dest=False, ignore=".svn")
                    self.batch_accum += self.platform_helper.progress("copy {}".format(left_item_path))
                else:
                    self.batch_accum += self.platform_helper.progress("identical {}".format(left_item_path))
            else:
                raise utils.InstlException(left_item_path+" not a different file or symlink, an abomination!")

        # removed items:
        for right_only_item in sorted(comparator.right_only):
            if right_only_item not in do_not_remove_items:
                item_to_remove = os.path.join(comparator.right, right_only_item)
                self.batch_accum += self.platform_helper.svn_remove_item(item_to_remove)
                self.batch_accum += self.platform_helper.progress("remove from svn {}".format(item_to_remove))

        # recurse to sub folders
        for sub_comparator in list(comparator.subdirs.values()):
            self.stage2svn_for_folder(sub_comparator)

    def prepare_conditions_for_wtar(self):
        folder_wtar_regex_list = var_stack.ResolveVarToList("FOLDER_WTAR_REGEX")
        self.compiled_folder_wtar_regex = utils.compile_regex_list_ORed(folder_wtar_regex_list)
        file_wtar_regex_list = var_stack.ResolveVarToList("FILE_WTAR_REGEX")
        self.compiled_file_wtar_regex = utils.compile_regex_list_ORed(file_wtar_regex_list)

        self.min_file_size_to_wtar = int(var_stack.ResolveVarToStr("MIN_FILE_SIZE_TO_WTAR"))

        if "WTAR_BY_FILE_SIZE_EXCLUDE_REGEX" in var_stack:
            wtar_by_file_size_exclude_regex = var_stack.ResolveVarToStr("WTAR_BY_FILE_SIZE_EXCLUDE_REGEX")
            self.compiled_wtar_by_file_size_exclude_regex = re.compile(wtar_by_file_size_exclude_regex)
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

        stage_folder = var_stack.ResolveVarToStr("STAGING_FOLDER")
        folders_to_check = self.prepare_list_of_dirs_to_work_on(stage_folder)
        if tuple(folders_to_check) == (stage_folder,):
            print("wtar for the whole repository")
        else:
            print("wtar limited to ", "; ".join(folders_to_check))

        for a_folder in folders_to_check:
            self.batch_accum += self.platform_helper.unlock(a_folder, recursive=True)
            self.batch_accum += self.platform_helper.progress("chflags -R nouchg " + a_folder)
            self.batch_accum += """find "{}" -name ".DS_Store" -delete""".format(a_folder)
            self.batch_accum += self.platform_helper.progress("delete ignored files")
            self.batch_accum += self.platform_helper.new_line()

        total_items_to_tar = 0
        total_redundant_wtar_files = 0
        while len(folders_to_check) > 0:
            folder_to_check = folders_to_check.pop()
            dir_items = os.listdir(folder_to_check)
            items_to_tar = list()
            items_to_delete = list()  # these are .wtar files for items that no linger need wtarring
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
                self.batch_accum += self.platform_helper.progress("begin folder {}".format(folder_to_check))
                self.batch_accum += self.platform_helper.cd(folder_to_check)

                for item_to_delete in items_to_delete:
                    self.batch_accum += self.platform_helper.rmfile(item_to_delete)
                    self.batch_accum += self.platform_helper.progress("removed file {}".format(item_to_delete))

                for item_to_tar in items_to_tar:
                    item_to_tar_full_path = os.path.join(folder_to_check, item_to_tar)

                    self.batch_accum += self.platform_helper.tar_with_instl(item_to_tar)
                    self.batch_accum += self.platform_helper.progress("tar file {}".format(item_to_tar))
                    self.batch_accum += self.platform_helper.split(item_to_tar + ".wtar")
                    self.batch_accum += self.platform_helper.progress("split file {}".format(item_to_tar + ".wtar"))
                    if os.path.isdir(item_to_tar_full_path):
                        self.batch_accum += self.platform_helper.rmdir(item_to_tar, recursive=True)
                        self.batch_accum += self.platform_helper.progress("removed dir {}".format(item_to_tar))
                    elif os.path.isfile(item_to_tar_full_path):
                        self.batch_accum += self.platform_helper.rmfile(item_to_tar)
                        self.batch_accum += self.platform_helper.progress("removed file {}".format(item_to_tar))
                    self.batch_accum += self.platform_helper.progress(item_to_tar_full_path)
                    self.batch_accum += self.platform_helper.new_line()
                self.batch_accum += self.platform_helper.progress("end folder {}".format(folder_to_check))
                self.batch_accum += self.platform_helper.new_line()

        print("found", total_items_to_tar, "to wtar")
        if total_redundant_wtar_files:
            print(total_redundant_wtar_files, "redundant wtar files will be removed")

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def do_svn2stage(self):
        self.batch_accum.set_current_section('admin')
        stage_folder = var_stack.ResolveVarToStr("STAGING_FOLDER")
        svn_folder = var_stack.ResolveVarToStr("SVN_CHECKOUT_FOLDER")

        # --limit command line option might have been specified
        limit_info_list = []
        if var_stack.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_stack.ResolveVarToList("__LIMIT_COMMAND_TO__")
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                limit_info_list.append((limit, os.path.join(svn_folder, limit), os.path.join(stage_folder, limit) ))
        else:
            limit_info_list.append(("", svn_folder, stage_folder))

        for limit_info in limit_info_list:
            checkout_url = var_stack.ResolveVarToStr("SVN_REPO_URL")
            if limit_info[0] != "":
                checkout_url += "/" + limit_info[0]
            checkout_url_quoted = utils.quoteme_double(checkout_url)
            limit_info_quoted = utils.quoteme_double(limit_info[1])
            svn_command_parts = ['"$(SVN_CLIENT_PATH)"', "checkout", checkout_url_quoted, limit_info_quoted, "--depth", "infinity"]
            svn_checkout_command = " ".join(svn_command_parts)
            self.batch_accum += svn_checkout_command
            self.batch_accum += self.platform_helper.progress("Checkout {} to {}".format(checkout_url, limit_info[1]))
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(limit_info[1], limit_info[2], link_dest=False, ignore=(".svn", ".DS_Store"), preserve_dest_files=False)
            self.batch_accum += self.platform_helper.progress("rsync {} to {}".format(limit_info[1], limit_info[2]))

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def do_create_rsa_keys(self):
        public_key_file = var_stack.ResolveVarToStr("PUBLIC_KEY_FILE")
        private_key_file = var_stack.ResolveVarToStr("PRIVATE_KEY_FILE")
        pubkey, privkey = rsa.newkeys(4096, poolsize=8)
        with open(public_key_file, "wb") as wfd:
            wfd.write(pubkey.save_pkcs1(format='PEM'))
            print("public key created:", public_key_file)
        with open(private_key_file, "wb") as wfd:
            wfd.write(privkey.save_pkcs1(format='PEM'))
            print("private key created:", private_key_file)

    def do_make_sig(self):
        private_key = None
        if "PRIVATE_KEY_FILE" in var_stack:
            private_key_file = self.path_searcher.find_file(var_stack.ResolveVarToStr("PRIVATE_KEY_FILE"),
                                                            return_original_if_not_found=True)
            private_key = open(private_key_file, "rb").read()
        file_to_sign = self.path_searcher.find_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"),
                                                    return_original_if_not_found=True)
        file_sigs = utils.create_file_signatures(file_to_sign, private_key_text=private_key)
        print("sha1:\n", file_sigs["sha1_checksum"])
        print("SHA-512_rsa_sig:\n", file_sigs.get("SHA-512_rsa_sig", "no private key"))

    def do_check_sig(self):
        file_to_check = self.path_searcher.find_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"),
                                                     return_original_if_not_found=True)
        file_contents = open(file_to_check, "rb").read()

        sha1_checksum = var_stack.ResolveVarToStr("__SHA1_CHECKSUM__")
        if sha1_checksum:
            checksumOk = utils.check_buffer_checksum(file_contents, sha1_checksum)
            if checksumOk:
                print("Checksum OK")
            else:
                print("Bad checksum, should be:", utils.get_buffer_checksum(file_contents))

        rsa_signature = var_stack.ResolveVarToStr("__RSA_SIGNATURE__")
        if rsa_signature:
            if "PUBLIC_KEY_FILE" in var_stack:
                public_key_file = self.path_searcher.find_file(var_stack.ResolveVarToStr("PUBLIC_KEY_FILE"),
                                                               return_original_if_not_found=True)
                public_key_text = open(public_key_file, "rb").read()

                signatureOk = utils.check_buffer_signature(file_contents, rsa_signature, public_key_text)
                if signatureOk:
                    print("Signature OK")
                else:
                    print("Bad Signature")

    def do_verify_index(self):
        self.read_yaml_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"))
        self.info_map_table.read_from_file(var_stack.ResolveVarToStr("FULL_INFO_MAP_FILE_PATH"))

        self.verify_index_to_repo()

    def do_read_yaml(self):
        self.read_yaml_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"))

    def do_depend(self):
        self.read_yaml_file(var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__"))
        self.items_table.activate_all_oses()
        self.items_table.resolve_inheritance()
        depend_result = defaultdict(dict)
        for IID in self.items_table.get_all_iids():
            needs_list = utils.unique_list()
            self.needs(IID, needs_list)
            if not needs_list:
                depend_result[IID]['depends'] = None
            else:
                depend_result[IID]['depends'] = sorted(needs_list)
            needed_by_list = self.needed_by(IID)
            if not needed_by_list:
                depend_result[IID]['needed_by'] = None
            else:
                depend_result[IID]['needed_by'] = sorted(needed_by_list)

        out_file_path = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            aYaml.writeAsYaml(aYaml.YamlDumpWrap(depend_result, sort_mappings=True), out_file)
        print("dependencies written to", out_file_path)

    def do_verify_repo(self):
        self.read_yaml_file(var_stack.ResolveVarToStr("__CONFIG_FILE__"))
        self.read_yaml_file(var_stack.ResolveVarToStr("STAGING_FOLDER_INDEX"))

        the_folder = var_stack.ResolveVarToStr("STAGING_FOLDER")
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
        self.items_table.change_status_of_all_iids(1)

        problem_messages_by_iid = defaultdict(list)

        # check inherit
        missing_inheritees = self.items_table.get_missing_iids_from_details("inherit")
        for missing_inheritee in missing_inheritees:
            err_message = " ".join(("inherits from non existing", utils.quoteme_single(missing_inheritee[1])))
            problem_messages_by_iid[missing_inheritee[0]].append(err_message)

        # check depends
        missing_dependees = self.items_table.get_missing_iids_from_details("depends")
        for missing_dependee in missing_dependees:
            err_message = " ".join(("depends from non existing", utils.quoteme_single(missing_dependee[1])))
            problem_messages_by_iid[missing_dependee[0]].append(err_message)

        for iid in all_iids:

            # check sources
            source_and_tag_list = self.items_table.get_details_and_tag_for_active_iids("install_sources", unique_values=True, limit_to_iids=(iid,))

            for source in source_and_tag_list:
                num_files_for_source = self.info_map_table.mark_required_for_source(source)
                if num_files_for_source == 0:
                    err_message = " ".join(("source", utils.quoteme_single(str(source)),"required by", iid, "does not have files"))
                    problem_messages_by_iid[iid].append(err_message)

            # check targets
            if len(source_and_tag_list) > 0:
                target_folders = set(self.items_table.get_resolved_details_value_for_active_iid(iid, "install_folders", unique_values=True))
                if len(target_folders) == 0:
                    err_message = " ".join(("iid", iid, "does not have target folder"))
                    problem_messages_by_iid[iid].append(err_message)

        for iid in sorted(problem_messages_by_iid):
            print(iid+":")
            for problem_message in sorted(problem_messages_by_iid[iid]):
                print("   ", problem_message)

        self.info_map_table.mark_required_completion()
        self.find_cycles()
        print("index:", len(all_iids), "iids")
        num_files = self.info_map_table.num_items("all-files")
        num_dirs = self.info_map_table.num_items("all-dirs")
        num_required_files = self.info_map_table.num_items("required-files")
        num_required_dirs = self.info_map_table.num_items("required-dirs")
        print("info map:", num_files, "files in", num_dirs, "folders")
        print("info map:", num_required_files, "required files, ", num_required_dirs, "required folders")

        unrequired_files = self.info_map_table.get_required_items(what="file", get_unrequired=True)
        print("unrequired files:")
        [print("    ", f.path) for f in unrequired_files]
        unrequired_dirs = self.info_map_table.get_required_items(what="dir",  get_unrequired=True)
        print("unrequired dirs:")
        [print("    ", d.path) for d in unrequired_dirs]

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
        if var_stack.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_stack.ResolveVarToList("__LIMIT_COMMAND_TO__")
            for limit in limit_list:
                limit = utils.unquoteme(limit)
                retVal.append(os.path.join(top_folder, limit))
        else:
            retVal.append(top_folder)
        return retVal

    def do_fix_perm(self):
        self.batch_accum.set_current_section('admin')
        self.read_yaml_file(var_stack.ResolveVarToStr("__CONFIG_FILE__"))
        should_be_exec_regex_list = var_stack.ResolveVarToList("EXEC_PROP_REGEX")
        self.compiled_should_be_exec_regex = utils.compile_regex_list_ORed(should_be_exec_regex_list)

        files_that_should_not_be_exec = list()
        files_that_must_be_exec = list()

        folders_to_check = self.prepare_list_of_dirs_to_work_on(var_stack.ResolveVarToStr("STAGING_FOLDER"))
        for folder_to_check in folders_to_check:
            self.batch_accum += self.platform_helper.unlock(folder_to_check, recursive=True)
            self.batch_accum += self.platform_helper.progress("chflags -R nouchg " + folder_to_check)
            for root, dirs, files in os.walk(folder_to_check, followlinks=False):
                for a_file in files:
                    item_path = os.path.join(root, a_file)
                    file_is_exec = self.is_file_exec(item_path)
                    file_should_be_exec = self.should_file_be_exec(item_path)
                    if file_is_exec != file_should_be_exec:
                        if file_should_be_exec:
                            self.batch_accum += self.platform_helper.chmod("a+x", item_path)
                            self.batch_accum += self.platform_helper.progress("chmod a+x " + item_path)
                            files_that_must_be_exec.append(item_path)
                        else:
                            self.batch_accum += self.platform_helper.chmod("a-x", item_path)
                            self.batch_accum += self.platform_helper.progress("chmod a-x " + item_path)
                            files_that_should_not_be_exec.append(item_path)

            self.batch_accum += self.platform_helper.chmod("-R a+rw,+X", folder_to_check)
            self.batch_accum += self.platform_helper.progress("chmod -R a+rw,+X " + folder_to_check)

        if len(files_that_should_not_be_exec) > 0:
            print("Exec bit will be removed from the {} following files".format(len(files_that_should_not_be_exec)))
            for a_file in files_that_should_not_be_exec:
                print("   ", a_file)
            print()

        if len(files_that_must_be_exec) > 0:
            print("Exec bit will be added to the {} following files".format(len(files_that_must_be_exec)))
            for a_file in files_that_must_be_exec:
                print("   ", a_file)
            print()

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def do_file_sizes(self):
        self.compile_exclude_regexi()
        out_file_path = var_stack.ResolveVarToStr("__MAIN_OUT_FILE__")
        with utils.write_to_file_or_stdout(out_file_path) as out_file:
            what_to_scan = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
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
        full_info_map_file_path = var_stack.ResolveStrToStr(os.path.join(results_folder, "$(FULL_INFO_MAP_FILE_NAME)"))

        accum += self.platform_helper.pushd(svn_folder)

        info_command_parts = ['"$(SVN_CLIENT_PATH)"', "info", "--depth infinity", ">", info_map_info_path]
        accum += " ".join(info_command_parts)
        accum += self.platform_helper.progress("Get info from svn to" +os.path.join(results_folder, "info_map.info" ))

        # get properties from SVN for all files in revision
        props_command_parts = ['"$(SVN_CLIENT_PATH)"', "proplist", "--depth infinity", ">", info_map_props_path]
        accum += " ".join(props_command_parts)
        accum += self.platform_helper.progress("Get props from svn to"+os.path.join(results_folder, "info_map.props"))

        # get sizes of all files
        file_sizes_command_parts = [self.platform_helper.run_instl(), "file-sizes",
                                    "--in", svn_folder,
                                    "--out", info_map_file_sizes_path]
        accum += " ".join(file_sizes_command_parts)
        accum += self.platform_helper.progress("Get file-sizes from disk to "+os.path.join(results_folder, "info_map.file-sizes"))

        accum += self.platform_helper.progress("Create {} ...".format(full_info_map_file_path))
        trans_command_parts = [self.platform_helper.run_instl(), "trans",
                                   "--in", info_map_info_path,
                                   "--props ", info_map_props_path,
                                   "--file-sizes", info_map_file_sizes_path,
                                   "--base-repo-rev", "$(BASE_REPO_REV)",
                                   "--out ", full_info_map_file_path]
        accum += " ".join(trans_command_parts)
        accum += self.platform_helper.progress("Create {} done".format(full_info_map_file_path))

        # split info_map.txt according to info_map fields in index.yaml
        accum += self.platform_helper.progress("Split {} ...".format(full_info_map_file_path))
        split_info_map_command_parts = [self.platform_helper.run_instl(), "filter-infomap",
                                        "--in", results_folder, "--define", var_stack.ResolveStrToStr("REPO_REV=$(__CURR_REPO_REV__)")]
        accum += " ".join(split_info_map_command_parts)
        accum += self.platform_helper.progress("Split {} done".format(full_info_map_file_path))

        accum += self.platform_helper.popd()

    def do_create_infomap(self):
        svn_folder = "$(WORKING_SVN_CHECKOUT_FOLDER)"
        results_folder = "$(INFO_MAP_OUTPUT_FOLDER)"
        accum = BatchAccumulator()  # sub-accumulator

        accum.set_current_section('admin')
        self.create_info_map(svn_folder, results_folder, accum)
        self.batch_accum.merge_with(accum)

        self.write_batch_file(self.batch_accum)
        if "__RUN_BATCH__" in var_stack:
            self.run_batch_file()

    def do_filter_infomap(self):
        """ filter the full infomap file according to info_map fields in the index """
        # __MAIN_INPUT_FILE__ is the folder where to find index.yaml, full_info_map.txt and where to create info_map files
        instl_folder = var_stack.ResolveVarToStr("__MAIN_INPUT_FILE__")
        full_info_map_file_path = var_stack.ResolveStrToStr(os.path.join(instl_folder, "$(FULL_INFO_MAP_FILE_NAME)"))
        index_yaml_path = os.path.join(instl_folder, "index.yaml")

        # read the index
        self.read_yaml_file(index_yaml_path)
        # read the full info map
        self.info_map_table.read_from_file(full_info_map_file_path, a_format="text")
        # fill the IIDToSVNItem table
        self.info_map_table.populate_IIDToSVNItem()

        # get the list of info map file names
        all_info_maps = self.items_table.get_unique_detail_values('info_map')

        lines_for_main_info_map = list()  # each additional info map is written into the main info map
        # write each info map to file
        for infomap_file_name in all_info_maps:
            info_map_items = self.info_map_table.get_items_by_infomap(infomap_file_name)
            if info_map_items:  # could be that no items are linked to the info map file
                info_map_file_path = os.path.join(instl_folder, infomap_file_name)
                self.info_map_table.write_to_file(in_file=info_map_file_path, items_list=info_map_items, field_to_write=self.fields_relevant_to_info_map)
                info_map_checksum = utils.get_file_checksum(info_map_file_path)
                info_map_size = os.path.getsize(info_map_file_path)
                line_for_main_info_map = "instl/{infomap_file_name}, f, $(REPO_REV), {info_map_checksum}, {info_map_size}".format(**locals())
                lines_for_main_info_map.append(var_stack.ResolveStrToStr(line_for_main_info_map))

        # write default info map to file
        default_info_map_file_path = var_stack.ResolveStrToStr(os.path.join(instl_folder, "$(MAIN_INFO_MAP_FILE_NAME)"))
        items_for_default_info_map = self.info_map_table.get_items_for_default_infomap()
        self.info_map_table.write_to_file(in_file=default_info_map_file_path, items_list=items_for_default_info_map, field_to_write=self.fields_relevant_to_info_map)

        with open(default_info_map_file_path, "a") as wfd:
            wfd.write("\n".join(lines_for_main_info_map))

    def do_read_info_map(self):
        files_to_read = var_stack.ResolveVarToList("__MAIN_INPUT_FILE__")
        for f2r in files_to_read:
            self.info_map_table.read_from_file(f2r)
