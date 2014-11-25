#!/usr/bin/env python2.7

from __future__ import print_function

import filecmp
import cStringIO as StringIO
from collections import defaultdict
import stat
import fnmatch

from instlException import *
from pyinstl.utils import *
from aYaml.augmentedYaml import writeAsYaml, YamlDumpDocWrap

from instlInstanceBase import InstlInstanceBase
from pyinstl import svnTree
from installItem import InstallItem
from batchAccumulator import BatchAccumulator
from configVarStack import var_stack as var_list

# noinspection PyPep8,PyPep8,PyPep8
class InstlAdmin(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlAdmin, self).__init__(initial_vars)
        self.svnTree = svnTree.SVNTree()

    def set_default_variables(self):
        if "__CONFIG_FILE__" in var_list:
            config_file_resolved = self.path_searcher.find_file(var_list.resolve("$(__CONFIG_FILE__)"), return_original_if_not_found=True)
            var_list.set_var("__CONFIG_FILE_PATH__").append(config_file_resolved)
            self.read_yaml_file(config_file_resolved)
            self.resolve_defined_paths()
        if "PUBLIC_KEY" not in var_list:
            if "PUBLIC_KEY_FILE" in var_list:
                try:
                    public_key_file = var_list.resove("$(PUBLIC_KEY_FILE)")
                    public_key_text = open(public_key_file, "rb").read()
                    var_list.set_var("PUBLIC_KEY", "from "+public_key_file).append(public_key_text)
                except:
                    pass  # lo nora
        if "PRIVATE_KEY" not in var_list:
            if "PRIVATE_KEY_FILE" in var_list:
                try:
                    private_key_file = var_list.resove("$(PRIVATE_KEY_FILE)")
                    private_key_text = open(private_key_file, "rb").read()
                    var_list.set_var("PUBLIC_KEY", "from "+private_key_file).append(private_key_text)
                except:
                    pass  # lo nora

    def do_command(self):
        the_command = var_list.resolve("$(__MAIN_COMMAND__)")
        self.set_default_variables()
        self.platform_helper.num_items_for_progress_report = int(var_list.resolve("$(LAST_PROGRESS)"))
        self.platform_helper.init_copy_tool()
        fixed_command_name = the_command.replace('-', '_')
        do_command_func = getattr(self, "do_"+fixed_command_name)
        do_command_func()

    def do_trans(self):
        self.read_info_map_file(var_list.resolve("$(__MAIN_INPUT_FILE__)"))
        if "__PROPS_FILE__" in var_list:
            self.read_info_map_file(var_list.resolve("$(__PROPS_FILE__)"))
        self.filter_out_info_map(var_list.resolve_to_list("$(__FILTER_OUT_PATHS__)"))

        base_rev = int(var_list.resolve("$(BASE_REPO_REV)"))
        if base_rev > 0:
            for item in self.svnTree.walk_items():
                item.set_last_rev(max(item.last_rev(), base_rev))

        if "__FILTER_IN_VERSION__" in var_list:
            self.filter_in_specific_version(var_list.resolve("$(__FILTER_IN_VERSION__)"))
        self.write_info_map_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def filter_out_info_map(self, paths_to_filter_out):
        for path in paths_to_filter_out:
            self.svnTree.remove_item_at_path(path)

    def filter_in_specific_version(self, ver):
        remove_predicate = InstlAdmin.RemoveIfNotSpecificVersion(int(ver))
        self.svnTree.recursive_remove_depth_first(remove_predicate)

    def get_revision_range(self):
        revision_range_re = re.compile("""
                                (?P<min_rev>\d+)
                                (:
                                (?P<max_rev>\d+)
                                )?
                                """, re.VERBOSE)
        min_rev = 0
        max_rev = 1
        match = revision_range_re.match(var_list.resolve("$(REPO_REV)"))
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
        current_base_repo_rev = int(var_list.resolve("$(BASE_REPO_REV)"))
        retVal = True
        revision_links_folder = var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/"+str(revision))
        create_links_done_stamp_file = var_list.resolve(revision_links_folder+"/$(CREATE_LINKS_STAMP_FILE_NAME)")
        if os.path.isfile(create_links_done_stamp_file):
            if revision == current_base_repo_rev:  # revision is the new base_repo_rev
                try:
                    previous_base_repo_rev = int(open(create_links_done_stamp_file, "r").read())  # try to read the previous
                    if previous_base_repo_rev == current_base_repo_rev:
                        retVal = False
                    else:
                        msg = " ".join( ("new base revision", str(current_base_repo_rev), "(was", str(previous_base_repo_rev),") need to refresh links") )
                        self.batch_accum += self.platform_helper.echo(msg)
                        print(msg)
                        # if we need to create links, remove the upload stems in order to force upload
                        try: os.remove(var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/"+str(revision)+"/$(UP_2_S3_STAMP_FILE_NAME)"))
                        except: pass
                except:
                    pass  # no previous base repo rev indication was found so return True to re-create the links
            else:
                retVal = False
        return retVal

    def get_last_repo_rev(self):
        retVal = 0
        revision_line_re = re.compile("^Revision:\s+(?P<last_rev>\d+)$")
        repo_url = var_list.resolve("$(SVN_REPO_URL)")
        if os.path.isdir(repo_url):
            svn_info_command = [var_list.resolve("$(SVN_CLIENT_PATH)"), "info", "."]
        else:
            svn_info_command = [var_list.resolve("$(SVN_CLIENT_PATH)"), "info", repo_url]
        with ChangeDirIfExists(repo_url):
            proc = subprocess.Popen(svn_info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            my_stdout, my_stderr = proc.communicate()
            if proc.returncode != 0 or my_stderr != "":
                raise ValueError("Could not read info from svn: "+my_stderr)
            info_as_io = StringIO.StringIO(my_stdout)
            for line in info_as_io:
                match = revision_line_re.match(line)
                if match:
                    retVal = int(match.group("last_rev"))
                    break
        if retVal <= 0:
            raise ValueError("Could not find last repo rev for "+repo_url)
        var_list.set_var("__LAST_REPO_REV__").append(str(retVal))
        return retVal

    def do_create_links(self):
        self.check_prerequisite_var_existence(("REPO_NAME", "SVN_REPO_URL", "ROOT_LINKS_FOLDER_REPO"))

        self.batch_accum.set_current_section('links')

        info_as_io = None
        # call svn info and to find out the last repo revision
        last_repo_rev = self.get_last_repo_rev()

        self.batch_accum += self.platform_helper.mkdir("$(ROOT_LINKS_FOLDER_REPO)/Base")

        accum = BatchAccumulator()  # sub-accumulator serves as a template for each version
        accum.set_current_section('links')
        self.create_links_for_revision(accum)

        no_need_link_nums = list()
        yes_need_link_nums = list()
        base_rev = int(var_list.resolve("$(BASE_REPO_REV)"))
        if base_rev > last_repo_rev:
            raise ValueError("base_rev "+str(base_rev)+" > last_repo_rev "+str(last_repo_rev))
        for revision in range(base_rev, last_repo_rev+1):
            if self.needToCreatelinksForRevision(revision):
                yes_need_link_nums.append(str(revision))
                save_dir_var = "REV_"+str(revision)+"_SAVE_DIR"
                self.batch_accum += self.platform_helper.save_dir(save_dir_var)
                var_list.set_var("__CURR_REPO_REV__").append(str(revision))
                revision_lines = accum.finalize_list_of_lines()  # will resolve with current  __CURR_REPO_REV__
                self.batch_accum += revision_lines
                self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
                self.batch_accum += self.platform_helper.new_line()
            else:
                no_need_link_nums.append(str(revision))

        if yes_need_link_nums:
            if no_need_link_nums:
                no_need_links_str = find_sequences(no_need_link_nums)
                msg = " ".join( ("Links already created for revisions:", no_need_links_str) )
                print(msg)
            yes_need_links_str = find_sequences(yes_need_link_nums)
            msg = " ".join( ("Need to create links for revisions:", yes_need_links_str) )
            print(msg)
        else:
            msg = " ".join( ("Links already created for all revisions:", str(base_rev), "...", str(last_repo_rev)) )
            print(msg)

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def create_links_for_revision(self, accum):
        revision_folder_path = "$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)"
        revision_instl_folder_path = revision_folder_path+"/instl"

        # sync revision from SVN to Base folder
        accum += self.platform_helper.echo("Getting revision $(__CURR_REPO_REV__) from $(SVN_REPO_URL)")
        checkout_command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"'+"$(SVN_REPO_URL)@$(__CURR_REPO_REV__)"+'"', '"'+"$(ROOT_LINKS_FOLDER_REPO)/Base"+'"', "--depth", "infinity"]
        accum += " ".join(checkout_command_parts)
        accum += self.platform_helper.progress("Create links for revision $(__CURR_REPO_REV__)")

        # copy Base folder to revision folder
        accum += self.platform_helper.mkdir("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)")
        accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir("$(ROOT_LINKS_FOLDER_REPO)/Base", revision_folder_path, link_dest=True, ignore=".svn", preserve_dest_files=False)
        accum += self.platform_helper.progress("Copy revision $(__CURR_REPO_REV__) to $(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)")

        # get info from SVN for all files in revision
        accum += self.platform_helper.mkdir(revision_instl_folder_path)
        accum += self.platform_helper.cd("$(ROOT_LINKS_FOLDER_REPO)/Base")
        accum += self.platform_helper.echo("Getting info from svn to ../$(__CURR_REPO_REV__)/instl/info_map.info")
        info_command_parts = ['"$(SVN_CLIENT_PATH)"', "info", "--depth infinity", ">", "../$(__CURR_REPO_REV__)/instl/info_map.info"]
        accum += " ".join(info_command_parts)
        accum += self.platform_helper.progress("Get info from svn to ../$(__CURR_REPO_REV__)/instl/info_map.info")

        # get properties from SVN for all files in revision
        props_command_parts = ['"$(SVN_CLIENT_PATH)"', "proplist", "--depth infinity", ">", "../$(__CURR_REPO_REV__)/instl/info_map.props"]
        accum += " ".join(props_command_parts)
        accum += self.platform_helper.progress("Get props from svn to ../$(__CURR_REPO_REV__)/instl/info_map.props")

        accum += self.platform_helper.cd("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)")
        # translate SVN info and properties to info_map text format
        accum += self.platform_helper.progress("Create $(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)/instl/info_map.txt")
        trans_command_parts = [self.platform_helper.run_instl(), "trans",
                               "--in", "instl/info_map.info",
                               "--props ", "instl/info_map.props",
                               "--base-repo-rev", "$(BASE_REPO_REV)",
                               "--out ", "instl/info_map.txt"]
        accum += " ".join(trans_command_parts)

        # create Mac only info_map
        trans_command_parts = [self.platform_helper.run_instl(), "trans", "--in", "instl/info_map.txt", "--out ", "instl/info_map_Mac.txt",  "--filter-out", "Win"]
        accum += " ".join(trans_command_parts)
        accum += self.platform_helper.progress("Create $(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)/instl/info_map_Mac.txt")

        # create Win only info_map
        trans_command_parts = [self.platform_helper.run_instl(), "trans", "--in", "instl/info_map.txt", "--out ", "instl/info_map_Win.txt",  "--filter-out", "Mac"]
        accum += " ".join(trans_command_parts)
        accum += self.platform_helper.progress("Create $(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)/instl/info_map_Win.txt")

        create_repo_rev_file_command_parts = [self.platform_helper.run_instl(), "create-repo-rev-file", "--config-file", '"$(__CONFIG_FILE_PATH__)"', "--rev", "$(__CURR_REPO_REV__)"]
        accum += " ".join(create_repo_rev_file_command_parts)
        accum += self.platform_helper.progress("Create repo-rev file")

        # create text versions of info and yaml files, so they can be displayed in browser
        accum +=  " ".join( ("find", "instl", "-type", "f", "-regextype", "posix-extended", "-regex", "'.*(yaml|info|props)'", "-print0", "|", "xargs", "-0", "-I{}", "cp", "-f", '"{}"', '"{}.txt"') )

        accum += self.platform_helper.rmfile("$(UP_2_S3_STAMP_FILE_NAME)")
        accum += self.platform_helper.progress("Remove $(UP_2_S3_STAMP_FILE_NAME)")
        accum += " ".join(["echo", "-n", "$(BASE_REPO_REV)", ">", "$(CREATE_LINKS_STAMP_FILE_NAME)"])
        accum += self.platform_helper.progress("Create $(CREATE_LINKS_STAMP_FILE_NAME)")

        accum += self.platform_helper.echo("done create-links version $(__CURR_REPO_REV__)")

    class RemoveIfNotSpecificVersion:
        def __init__(self, version_not_to_remove):
            self.version_not_to_remove = version_not_to_remove

        def __call__(self, svn_item):
            retVal = None
            if svn_item.isFile():
                retVal = svn_item.last_rev() != self.version_not_to_remove
            elif svn_item.isDir():
                retVal = len(svn_item.subs()) == 0
            return retVal

    def do_up2s3(self):
        # call svn info and to find out the last repo revision
        base_repo_rev = int(var_list.resolve("$(BASE_REPO_REV)"))
        last_repo_rev = self.get_last_repo_rev()
        revision_list = range(base_repo_rev, last_repo_rev+1)
        dirs_to_upload = list()
        no_need_upload_nums = list()
        yes_need_upload_nums = list()
        for dir_as_int in revision_list:
            dir_name = str(dir_as_int)
            if not os.path.isdir(var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/"+dir_name)):
                print("revision dir", dir_name, "is missing, run create-links to create this folder")
            else:
                create_links_done_stamp_file = var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/"+dir_name+"/$(CREATE_LINKS_STAMP_FILE_NAME)")
                if not os.path.isfile(create_links_done_stamp_file):
                    print("revision dir", dir_name, "does not have create-links stamp file:", create_links_done_stamp_file)
                else:
                    up_2_s3_done_stamp_file = var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/"+dir_name+"/$(UP_2_S3_STAMP_FILE_NAME)")
                    if os.path.isfile(up_2_s3_done_stamp_file):
                        no_need_upload_nums.append(dir_name)
                    else:
                        yes_need_upload_nums.append(dir_name)
                        dirs_to_upload.append(dir_name)

        if yes_need_upload_nums:
            if no_need_upload_nums:
                no_need_upload__str = find_sequences(no_need_upload_nums)
                msg = " ".join( ("Revisions already uploaded to S3:", no_need_upload__str) )
                print(msg)
            yes_need_upload_str = find_sequences(yes_need_upload_nums)
            msg = " ".join( ("Revisions will be uploaded to S3:", yes_need_upload_str) )
            print(msg)
        else:
            msg = " ".join( ("All revisions already uploaded to S3:", str(base_repo_rev), "...", str(last_repo_rev)) )
            print(msg)

        self.batch_accum.set_current_section('upload')
        for dir_name in dirs_to_upload:
            accum = BatchAccumulator()  # sub-accumulator serves as a template for each version
            accum.set_current_section('upload')
            save_dir_var = "REV_"+dir_name+"_SAVE_DIR"
            self.batch_accum += self.platform_helper.save_dir(save_dir_var)
            var_list.set_var("__CURR_REPO_REV__").append(dir_name)
            self.do_upload_to_s3_aws_for_revision(accum)
            revision_lines = accum.finalize_list_of_lines()  # will resolve with current  __CURR_REPO_REV__
            self.batch_accum += revision_lines
            self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
            self.batch_accum += self.platform_helper.new_line()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def do_upload_to_s3_aws_for_revision(self, accum):
        map_file_path = 'instl/info_map.txt'
        info_map_path = var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)/"+map_file_path)
        repo_rev = int(var_list.resolve("$(__CURR_REPO_REV__)"))
        self.svnTree.clear_subs()
        self.read_info_map_file(info_map_path)

        accum += self.platform_helper.cd("$(ROOT_LINKS_FOLDER_REPO)/$(__CURR_REPO_REV__)")

        if 'Mac' in var_list.resolve_to_list("$(__CURRENT_OS_NAMES__)"):
            accum += "find . -name .DS_Store -delete"

        # Files a folders that do not belong to __CURR_REPO_REV__ should not be uploaded.
        # Since aws sync command uploads the whole folder, we delete from disk all files
        # and folders that should not be uploaded.
        # To save delete instructions for every file we rely on the fact that each folder
        # has last_rev which is the maximum last_rev of it's sub-items.
        self.svnTree.remove_item_at_path('instl')  # never remove the instl folder
        from collections import deque
        dir_queue = deque()
        dir_queue.append(self.svnTree)
        while len(dir_queue) > 0:
            curr_item = dir_queue.popleft()
            files, dirs = curr_item.unsorted_sub_items()
            for file_item in files:
                if file_item.last_rev() > repo_rev:
                    raise ValueError(str(file_item)+" last_rev > repo_rev "+str(repo_rev))
                elif file_item.last_rev() < repo_rev:
                    accum += self.platform_helper.rmfile(file_item.full_path())
                    accum += self.platform_helper.progress("rmfile "+file_item.full_path())
            for dir_item in dirs:
                if dir_item.last_rev() > repo_rev:
                    raise ValueError(str(dir_item)+" last_rev > repo_rev "+str(repo_rev))
                elif dir_item.last_rev() < repo_rev:  # whole folder should be removed
                    accum += self.platform_helper.rmdir(dir_item.full_path(), recursive=True)
                    accum += self.platform_helper.progress("rmdir "+dir_item.full_path())
                else:
                    dir_queue.append(dir_item)  # need to check inside the folder

        # remove broken links, aws cannot handle them
        accum += " ".join( ("find", ".", "-type", "l", "!", "-exec", "test", "-e", "{}", "\;", "-exec", "rm", "-f", "{}", "\;") )

        accum += " ".join(["aws", "s3", "sync",
                           ".", "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_REV__)",
                           "--acl", "public-read",
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
        accum += self.platform_helper.echo("done up2s3 revision $(__CURR_REPO_REV__)")

    def create_sig_for_file(self, file_to_sig):
        retVal = None
        config_dir, _ = os.path.split(var_list.resolve("$(__CONFIG_FILE_PATH__)"))
        private_key_file = os.path.join(config_dir, var_list.resolve("$(REPO_NAME)")+".private_key")
        with open(private_key_file, "rb") as private_key_fd:
            retVal = create_file_signatures(file_to_sig, private_key_fd.read())
        return retVal

    def do_create_repo_rev_file(self):
        if "REPO_REV_FILE_VARS" not in var_list:
            raise ValueError("REPO_REV_FILE_VARS must be defined")
        repo_rev_vars = var_list.resolve_to_list("$(REPO_REV_FILE_VARS)")
        var_list.set_var("REPO_REV").append("$(TARGET_REPO_REV)") # override the repo rev from the config file
        dangerous_intersection = set(repo_rev_vars).intersection(
            {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "PRIVATE_KEY", "PRIVATE_KEY_FILE"})
        if dangerous_intersection:
            print("found", str(dangerous_intersection), "in REPO_REV_FILE_VARS, aborting")
            raise ValueError("file REPO_REV_FILE_VARS "+str(dangerous_intersection)+" and so is forbidden to upload")

        info_map_file = var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/$(TARGET_REPO_REV)/instl/info_map.txt")
        info_map_sigs = self.create_sig_for_file(info_map_file)
        var_list.set_var("INFO_MAP_SIG").append(info_map_sigs["SHA-512_rsa_sig"])
        var_list.set_var("INFO_MAP_CHECKSUM").append(info_map_sigs["sha1_checksum"])

        var_list.set_var("INDEX_URL").append("$(SYNC_BASE_URL)/$(REPO_REV)/instl/index.yaml")
        index_file = var_list.resolve("$(ROOT_LINKS_FOLDER_REPO)/$(TARGET_REPO_REV)/instl/index.yaml")
        index_file_sigs = self.create_sig_for_file(index_file)
        var_list.set_var("INDEX_SIG").append(index_file_sigs["SHA-512_rsa_sig"])
        var_list.set_var("INDEX_CHECKSUM").append(index_file_sigs["sha1_checksum"])

        for var in repo_rev_vars:
            if var not in var_list:
                raise ValueError(var+" is missing cannot write repo rev file")

        repo_rev_yaml = YamlDumpDocWrap(var_list.repr_for_yaml(repo_rev_vars, include_comments=False),
                                                    '!define', "", explicit_start=True, sort_mappings=True)
        safe_makedirs(var_list.resolve("$(ROOT_LINKS_FOLDER)/admin"))
        local_file = var_list.resolve("$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(TARGET_REPO_REV)")
        with open(local_file, "w") as wfd:
            writeAsYaml(repo_rev_yaml, out_stream=wfd, indentor=None, sort=True)
            print("created", local_file)

    def do_up_repo_rev(self):
        self.batch_accum.set_current_section('admin')

        just_with_number = int(var_list.resolve("$(__JUST_WITH_NUMBER__)"))
        if just_with_number > 0:
            var_list.set_var("REPO_REV").append("$(__JUST_WITH_NUMBER__)")

        if just_with_number == 0:
            self.batch_accum += " ".join( ["aws", "s3", "cp",
                                "\"$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                               "\"s3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME)\"",
                               "--acl", "public-read",
                               "--content-type", 'text/plain'
                                ] )
            self.batch_accum += self.platform_helper.progress("Uploaded '$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)' to 's3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)'")

        self.batch_accum += " ".join( ["aws", "s3", "cp",
                           "\"$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                           "\"s3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)\"",
                           "--acl", "public-read",
                           "--content-type", 'text/plain'
                            ] )
        self.batch_accum += self.platform_helper.progress("Uploaded '$(ROOT_LINKS_FOLDER)/admin/$(REPO_REV_FILE_NAME).$(REPO_REV)' to 's3://$(S3_BUCKET_NAME)/admin/$(REPO_REV_FILE_NAME)'")

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def do_fix_props(self):
        self.batch_accum.set_current_section('admin')
        repo_folder = var_list.resolve("$(SVN_CHECKOUT_FOLDER)")
        save_dir = os.getcwd()
        os.chdir(repo_folder)

        # read svn info
        svn_info_command = [var_list.resolve("$(SVN_CLIENT_PATH)"), "info", "--depth", "infinity"]
        proc = subprocess.Popen(svn_info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        my_stdout, my_stderr = proc.communicate()
        if proc.returncode != 0 or my_stderr != "":
            raise ValueError("Could not read info from svn: "+my_stderr)
        # write svn info to file for debugging and reference. But go one folder up so not to be in the svn repo.
        with open("../svn-info-for-fix-props.txt", "w") as wfd:
            wfd.write(my_stdout)
        with open("../svn-info-for-fix-props.txt", "r") as rfd:
            self.svnTree.read_from_svn_info(rfd)

        # read svn props
        svn_props_command = [var_list.resolve("$(SVN_CLIENT_PATH)"), "proplist", "--depth", "infinity"]
        proc = subprocess.Popen(svn_props_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        my_stdout, my_stderr = proc.communicate()
        with open("../svn-proplist-for-fix-props.txt", "w") as wfd:
            wfd.write(my_stdout)
        with open("../svn-proplist-for-fix-props.txt", "r") as rfd:
            self.svnTree.read_props(rfd)

        self.batch_accum += self.platform_helper.cd(repo_folder)

        for item in self.svnTree.walk_items():
            shouldBeExec = self.should_be_exec(item)
            if item.props:
                for extra_prop in item.props:
                    #print("remove prop", extra_prop, "from", item.full_path())
                    self.batch_accum += " ".join( (var_list.resolve("$(SVN_CLIENT_PATH)"), "propdel", "svn:"+extra_prop, '"'+item.full_path()+'"') )
                    self.batch_accum += self.platform_helper.progress(" ".join(("remove prop", extra_prop, "from", item.full_path())) )
            if item.isExecutable() and not shouldBeExec:
                #print("remove prop", "executable", "from", item.full_path())
                self.batch_accum += " ".join( (var_list.resolve("$(SVN_CLIENT_PATH)"), "propdel", 'svn:executable', '"'+item.full_path()+'"') )
                self.batch_accum += self.platform_helper.progress(" ".join(("remove prop", "executable", "from", item.full_path())) )
            elif not item.isExecutable() and shouldBeExec:
                #print("add prop", "executable", "to", item.full_path())
                self.batch_accum += " ".join( (var_list.resolve("$(SVN_CLIENT_PATH)"), "propset", 'svn:executable', 'yes', '"'+item.full_path()+'"') )
                self.batch_accum += self.platform_helper.progress(" ".join(("add prop", "executable", "from", item.full_path())) )
        self.create_variables_assignment()
        os.chdir(save_dir)
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def is_file_exec(self, file_path):
        file_mode = stat.S_IMODE(os.stat(file_path).st_mode)
        exec_mode = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        retVal = (file_mode & exec_mode) != 0
        return retVal

    def should_file_be_exec(self, file_path):
        retVal = False
        try:
            regex_list = var_list.resolve_to_list("$(EXEC_PROP_REGEX)")
            for regex in regex_list:
                if re.search(regex, file_path):
                    retVal = True
                    raise Exception
        except:
            pass
        return retVal

    def should_be_exec(self, item):
        retVal = item.isFile() and self.should_file_be_exec(item.full_path())
        return retVal

    # to do: prevent create-links and up2s3 if there are files marked as symlinks
    def do_fix_symlinks(self):
        self.batch_accum.set_current_section('admin')
        folder_to_check = var_list.resolve("$(STAGING_FOLDER)")
        valid_symlinks = list()
        broken_symlinks = list()
        for root, dirs, files in os.walk(folder_to_check, followlinks=False):
            for item in files + dirs:
                item_path = os.path.join(root, item)
                if os.path.islink(item_path):
                    target_path = os.path.realpath(item_path)
                    link_value = os.readlink(item_path)
                    if os.path.isdir(target_path) or os.path.isfile(target_path):
                        valid_symlinks.append( (item_path, link_value) )
                    else:
                        broken_symlinks.append((item_path, link_value))
        if len(broken_symlinks) > 0:
            print("Found broken symlinks, please fix and run fix-symlinks again")
            for symlink_file, link_value in broken_symlinks:
                print(symlink_file, "-?>", link_value)
        else:
            for symlink_file, link_value in valid_symlinks:
                symlink_text_path = symlink_file+".symlink"
                self.batch_accum += " ".join( ("echo", "-n", "'"+link_value+"'", ">", "'"+symlink_text_path+"'") )
                self.batch_accum += self.platform_helper.rmfile(symlink_file)
                self.batch_accum += self.platform_helper.progress(symlink_text_path)
                self.batch_accum += self.platform_helper.new_line()
        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def do_stage2svn(self):
        self.batch_accum.set_current_section('admin')
        if var_list.defined("__LIMIT_COMMAND_TO__"):
            print("stage2svn limited to ", "; ".join(var_list.resolve_to_list("$(__LIMIT_COMMAND_TO__)")))
        else:
            print ("stage2svn for the whole repository")
        stage_folder = var_list.resolve("$(STAGING_FOLDER)")
        svn_folder = var_list.resolve("$(SVN_CHECKOUT_FOLDER)")
        self.batch_accum += self.platform_helper.unlock(stage_folder, recursive=True)
        self.batch_accum += self.platform_helper.progress("chflags -R nouchg "+stage_folder)
        self.batch_accum += self.platform_helper.new_line()
        self.batch_accum += self.platform_helper.cd(svn_folder)
        stage_folder_svn_folder_pairs = []
        if var_list.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_list.resolve_to_list("$(__LIMIT_COMMAND_TO__)")
            for limit in limit_list:
                limit = unquoteme(limit)
                stage_folder_svn_folder_pairs.append( (os.path.join(stage_folder,limit) , os.path.join(svn_folder, limit) ) )
        else:
                stage_folder_svn_folder_pairs.append( (stage_folder , svn_folder) )
        for pair in stage_folder_svn_folder_pairs:
            comparer = filecmp.dircmp(pair[0], pair[1], ignore=[".svn", ".DS_Store", "Icon\015"])
            self.stage2svn_for_folder(comparer)
        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def stage2svn_for_folder(self, comparer):
        # copy new and changed items:
        for item in comparer.left_only + comparer.diff_files:
            item_path = os.path.join(comparer.left, item)
            if os.path.islink(item_path):
                raise InstlException(item_path+" is a symlink which should not be committed to svn, run instl fix-symlinks and try again")
            elif os.path.isfile(item_path):
                self.batch_accum += self.platform_helper.copy_tool.copy_file_to_dir(item_path, comparer.right, link_dest=False, ignore=".svn")
            elif os.path.isdir(item_path):
                self.batch_accum += self.platform_helper.copy_tool.copy_dir_to_dir(item_path, comparer.right, link_dest=False, ignore=".svn")
            else:
                raise InstlException(item_path+" not a file, dir or symlink, an abomination!")
            self.batch_accum += self.platform_helper.progress(item_path)

        # tell svn about new items, svn will not accept 'add' for changed items
        for item in comparer.left_only:
            self.batch_accum += self.platform_helper.svn_add_item(os.path.join(comparer.right, item))
            self.batch_accum += self.platform_helper.progress(os.path.join(comparer.right, item))

        # removed items:
        for item in comparer.right_only:
            item_path = os.path.join(comparer.left, item)
            self.batch_accum += self.platform_helper.svn_remove_item(os.path.join(comparer.right, item))
            self.batch_accum += self.platform_helper.progress(os.path.join(comparer.right, item))

        # recurse to sub folders
        for sub_comparer in comparer.subdirs.values():
            self.stage2svn_for_folder(sub_comparer)

    def should_wtar(self, dir_item, regexes, max_file_size):
        retVal = False
        try:
            for regex in regexes:
                if re.search(regex, dir_item):
                    retVal = True
                    raise Exception
            if os.path.isfile(dir_item):
                if os.path.getsize(dir_item) > max_file_size:
                    retVal = True
        except:
            pass
        return retVal

    def prepare_permissions_for_wtar(self, item_path):
        if os.path.isfile(item_path):
            file_is_exec = self.is_file_exec(item_path)
            if self.should_file_be_exec(item_path) and not file_is_exec:
                self.batch_accum += self.platform_helper.chmod("a+x", item_path)
                self.batch_accum += self.platform_helper.progress("chmod a+x "+item_path)
            elif not self.should_file_be_exec(item_path) and file_is_exec:
                self.batch_accum += self.platform_helper.chmod("a-x", item_path)
                self.batch_accum += self.platform_helper.progress("chmod a-x "+item_path)
            self.batch_accum += self.platform_helper.chmod("a+rw", item_path)
            self.batch_accum += self.platform_helper.progress("chmod a+rw "+item_path)
        elif os.path.isdir(item_path):
            self.batch_accum += self.platform_helper.chmod("a+rwx", item_path)
            self.batch_accum += self.platform_helper.progress("chmod a+rwx "+item_path)
            dir_items = os.listdir(item_path)
            for dir_item in dir_items:
                dir_item_full_path = os.path.join(item_path, dir_item)
                self.prepare_permissions_for_wtar(dir_item_full_path)

    def do_wtar(self):
        self.batch_accum.set_current_section('admin')
        regex_list = var_list.resolve_to_list("$(WTAR_REGEX)")

        compiled_regex_list = list()
        for regex in regex_list:
            compiled_regex_list.append(re.compile(regex))

        self.batch_accum += self.platform_helper.split_func()

        max_file_size = int(var_list.resolve(("$(MAX_FILE_SIZE)")))
        stage_folder = var_list.resolve("$(STAGING_FOLDER)")
        self.batch_accum += self.platform_helper.unlock(stage_folder, recursive=True)
        self.batch_accum += self.platform_helper.progress("chflags -R nouchg "+stage_folder)
        self.batch_accum += self.platform_helper.new_line()
        folders_to_check = [stage_folder]
        while len(folders_to_check) > 0:
            folder_to_check = folders_to_check.pop()
            dir_items = os.listdir(folder_to_check)
            items_to_tar = list()
            for dir_item in dir_items:
                dir_item_full_path = os.path.join(folder_to_check, dir_item)
                if not os.path.islink(dir_item_full_path):
                    to_tar = self.should_wtar(dir_item_full_path, compiled_regex_list, max_file_size)
                    if to_tar:
                        items_to_tar.append(dir_item)
                    else:
                        if os.path.isdir(dir_item_full_path):
                            folders_to_check.append(dir_item_full_path)
            if items_to_tar:
                self.batch_accum += self.platform_helper.cd(folder_to_check)
                for item_to_tar in items_to_tar:
                    item_to_tar_full_path = os.path.join(folder_to_check, item_to_tar)
                    if item_to_tar.endswith(".wtar"):
                        for delete_file in dir_items:
                            if fnmatch.fnmatch(delete_file, item_to_tar+'.??'):
                                self.batch_accum += self.platform_helper.rmfile(delete_file)
                        self.batch_accum += self.platform_helper.split(item_to_tar)
                    else:
                        for delete_file in dir_items:
                            if fnmatch.fnmatch(delete_file, item_to_tar+'.wtar*'):
                                self.batch_accum += self.platform_helper.rmfile(delete_file)
                        self.prepare_permissions_for_wtar(item_to_tar_full_path)
                        self.batch_accum += self.platform_helper.tar(item_to_tar)
                        self.batch_accum += self.platform_helper.split(item_to_tar+".wtar")
                    if os.path.isdir(item_to_tar_full_path):
                        self.batch_accum += self.platform_helper.rmdir(item_to_tar, recursive=True)
                    elif os.path.isfile(item_to_tar_full_path):
                        self.batch_accum += self.platform_helper.rmfile(item_to_tar)
                    self.batch_accum += self.platform_helper.progress(item_to_tar_full_path)
                    self.batch_accum += self.platform_helper.new_line()
        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()


    def do_svn2stage(self):
        self.batch_accum.set_current_section('admin')
        stage_folder = var_list.resolve(("$(STAGING_FOLDER)"))
        svn_folder = var_list.resolve("$(SVN_CHECKOUT_FOLDER)")

        # --limit command line option might have been specified
        if var_list.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_list.resolve_to_list("$(__LIMIT_COMMAND_TO__)")
            joined_limit_list = "; ".join(limit_list)
            print("svn2stage limited to ", joined_limit_list)
        else:
            print ("svn2stage for the whole repository")

        limit_info_list = []
        if var_list.defined("__LIMIT_COMMAND_TO__"):
            limit_list = var_list.resolve_to_list("$(__LIMIT_COMMAND_TO__)")
            for limit in limit_list:
                limit = unquoteme(limit)
                limit_info_list.append( (limit, os.path.join(svn_folder, limit), os.path.join(stage_folder,limit) ) )
        else:
                limit_info_list.append(("", svn_folder, stage_folder))
        for limit_info in limit_info_list:
            checkout_url = var_list.resolve("$(SVN_REPO_URL)")
            if limit_info[0] != "":
                checkout_url += "/"+limit_info[0]
            checkout_url = quoteme_double(checkout_url)
            svn_command_parts = ['"$(SVN_CLIENT_PATH)"', "checkout", checkout_url, '"'+limit_info[1]+'"', "--depth", "infinity"]
            self.batch_accum += " ".join(svn_command_parts)
            self.batch_accum += self.platform_helper.progress("Checkout {} to {}".format(checkout_url, limit_info[1]))
            self.batch_accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir(limit_info[1], limit_info[2], link_dest=False, ignore=(".svn", ".DS_Store"), preserve_dest_files=False)
            self.batch_accum += self.platform_helper.progress("rsync {} to {}".format(limit_info[1], limit_info[2]))
        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in var_list:
            self.run_batch_file()

    def do_create_rsa_keys(self):
        public_key_file = var_list.resolve("$(PUBLIC_KEY_FILE)")
        private_key_file = var_list.resolve("$(PRIVATE_KEY_FILE)")
        pubkey, privkey = rsa.newkeys(4096, poolsize=8)
        with open(public_key_file, "wb") as wfd:
            wfd.write(pubkey.save_pkcs1(format='PEM'))
            print("public key created:", public_key_file)
        with open(private_key_file, "wb") as wfd:
            wfd.write(privkey.save_pkcs1(format='PEM'))
            print("private key created:", private_key_file)

    def do_make_sig(self):
        private_key = None
        if "PRIVATE_KEY_FILE" in var_list:
            private_key_file = self.path_searcher.find_file(var_list.resolve("$(PRIVATE_KEY_FILE)"),
                                                    return_original_if_not_found=True)
            private_key = open(private_key_file, "rb").read()
        file_to_sign = self.path_searcher.find_file(var_list.resolve("$(__MAIN_INPUT_FILE__)"),
                                                    return_original_if_not_found=True)
        file_sigs = create_file_signatures(file_to_sign, private_key_text=private_key)
        print("sha1:\n", file_sigs["sha1_checksum"])
        print("SHA-512_rsa_sig:\n", file_sigs.get("SHA-512_rsa_sig", "no private key"))

    def do_check_sig(self):
        file_to_check = self.path_searcher.find_file(var_list.resolve("$(__MAIN_INPUT_FILE__)"),
                                                    return_original_if_not_found=True)
        file_contents = open(file_to_check, "rb").read()

        sha1_checksum = var_list.resolve("$(__SHA1_CHECKSUM__)")
        if sha1_checksum:
            checksumOk = check_buffer_checksum(file_contents, sha1_checksum)
            if checksumOk:
                print("Checksum OK")
            else:
                print("Bad checksum, should be:", get_buffer_checksum(file_contents))

        rsa_signature = var_list.resolve("$(__RSA_SIGNATURE__)")
        if rsa_signature:
            if "PUBLIC_KEY_FILE" in var_list:
                public_key_file = self.path_searcher.find_file(var_list.resolve("$(PUBLIC_KEY_FILE)"),
                                                        return_original_if_not_found=True)
                public_key_text = open(public_key_file, "rb").read()

                signatureOk = check_buffer_signature(file_contents, rsa_signature, public_key_text)
                if signatureOk:
                    print("Signature OK")
                else:
                    print("Bad Signature")

    def do_verify_index(self):
        self.read_yaml_file(var_list.resolve("$(__MAIN_INPUT_FILE__)"))
        info_map = svnTree.SVNTree()
        with open_for_read_file_or_url(var_list.resolve("$(INFO_MAP_FILE_URL)")) as rfd:
            info_map.read_from_text(rfd)

        # for each iid get full paths to it's sources
        iid_to_sources = defaultdict(list)
        InstallItem.begin_get_for_all_oses()
        for iid in sorted(self.install_definitions_index):
            with self.install_definitions_index[iid]:
                for source_var in var_list.get_configVar_obj("iid_source_var_list"):
                    source = var_list.resolve_var_to_list(source_var)
                    if source[2] in ("common", "Mac"):
                        iid_to_sources[iid].append( ("/".join( ("Mac", source[0])), source[1]))
                    if source[2] in ("common", "Win", "Win32", "Win64"):
                        iid_to_sources[iid].append( ("/".join( ("Win", source[0])), source[1]))

        for iid in sorted(iid_to_sources):
            with self.install_definitions_index[iid]:
                iid_problem_messages = list()
                # check inherits
                for inheritee in var_list.resolve_var_to_list("iid_inherit"):
                    if inheritee not in self.install_definitions_index:
                        iid_problem_messages.append(" ".join( ("inherits from non existing", inheritee ) ))
                # check depends
                for dependee in var_list.resolve_var_to_list("iid_depend_list"):
                    if dependee not in self.install_definitions_index:
                        iid_problem_messages.append(" ".join( ("depends on non existing", dependee ) ))
                # check sources
                for source in iid_to_sources[iid]:
                    map_item = info_map.get_item_at_path(source[0])
                    if map_item is None:
                        iid_problem_messages.append(" ".join( ("source", quoteme_single(source[0]), "does not exist") ))
                    else:
                        if source[1] in ("!dir", "!dir_cont", "!files"):
                            if map_item.isFile():
                                iid_problem_messages.append(" ".join( ("source", quoteme_single(source[0]), "is a file but type is", source[1]) ))
                            else:
                                file_list, dir_list = map_item.unsorted_sub_items()
                                if source[1] == "!files" and len(file_list) == 0:
                                    iid_problem_messages.append(" ".join( ("source", quoteme_single(source[0]), "has no files but type is", source[1]) ))
                                if source[1] in ("!dir", "!dir_cont") and len(file_list)+len(dir_list) == 0:
                                    iid_problem_messages.append(" ".join( ("source", quoteme_single(source[0]), "has no files or dirs but type is", source[1]) ))
                        if source[1] == "!file"  and not map_item.isFile():
                            iid_problem_messages.append(" ".join( ("source", quoteme_single(source[0]), "is a dir but type is", source[1]) ))
                if iid_problem_messages:
                    print(iid+":")
                    for problem_message in sorted(iid_problem_messages):
                        print("   ", problem_message)
        self.find_cycles()
        print("index:", len(self.install_definitions_index), "iids")
        num_files = info_map.num_subs_in_tree(what="file")
        num_dirs = info_map.num_subs_in_tree(what="dir")
        print("info map:", num_files, "files in", num_dirs, "folders")


def percent_cb(unused_complete, unused_total):
    sys.stdout.write('.')
    sys.stdout.flush()
