#!/usr/bin/env python2.7

from __future__ import print_function

import subprocess
import StringIO

from pyinstl.log_utils import func_log_wrapper
from pyinstl.utils import *

from instlInstanceBase import InstlInstanceBase
from pyinstl import svnTree

from batchAccumulator import BatchAccumulator

map_info_extension_to_format = {"txt" : "text", "text" : "text",
                "inf" : "info", "info" : "info",
                "yml" : "yaml", "yaml" : "yaml",
                "pick" : "pickle", "pickl" : "pickle", "pickle" : "pickle",
                "props" : "props", "prop" : "props"
                }


class InstlAdmin(InstlInstanceBase):

    def __init__(self, initial_vars):
        super(InstlAdmin, self).__init__(initial_vars)
        self.cvl.set_variable("__ALLOWED_COMMANDS__").extend( ('trans', 'createlinks', 'up2s3', 'up_repo_rev') )
        self.svnTree = svnTree.SVNTree()

    def set_default_variables(self):
        if "CREATE_LINKS_STAMP_FILE_NAME" not in self.cvl:
            self.cvl.set_variable("CREATE_LINKS_STAMP_FILE_NAME").append("create_links_done.stamp")
        if "UP_2_S3_STAMP_FILE_NAME" not in self.cvl:
            self.cvl.set_variable("UP_2_S3_STAMP_FILE_NAME").append("up2s3.stamp")
        if "__CONFIG_FILE__" in self.cvl:
            config_file_resolved = self.search_paths_helper.find_file_with_search_paths(self.cvl.resolve_string("$(__CONFIG_FILE__)"), return_original_if_not_found=True)
            self.cvl.set_variable("__CONFIG_FILE_PATH__").append(config_file_resolved)
            self.read_yaml_file(config_file_resolved)

    @func_log_wrapper
    def do_command(self):
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        if the_command in self.cvl.get_list("__ALLOWED_COMMANDS__"):
            self.set_default_variables()
            if the_command == "trans":
                self.do_trans()
            elif the_command == "createlinks":
                self.do_create_links()
            elif the_command == "up2s3":
                self.do_upload_to_s3_aws()
            elif the_command == "up_repo_rev":
                self.do_up_repo_rev()

    def do_trans(self):
        self.read_info_map_file(self.cvl.get_str("__MAIN_INPUT_FILE__"))
        if "__PROPS_FILE__" in self.cvl:
            self.read_info_map_file(self.cvl.get_str("__PROPS_FILE__"))
        self.filter_out_info_map(self.cvl.get_list("__FILTER_OUT_PATHS__"))

        base_rev = int(self.cvl.get_str("BASE_REPO_REV"))
        if base_rev > 0:
            for item in self.svnTree.walk_items():
                item.set_last_rev(max(item.last_rev(), base_rev))

        if "__FILTER_IN_VERSION__" in self.cvl:
            self.filter_in_specific_version(self.cvl.get_str("__FILTER_IN_VERSION__"))
        self.write_info_map_file()
        if "__RUN_BATCH_FILE__" in self.cvl:
            self.run_batch_file()

    def read_info_map_file(self, in_file_path):
        _, extension = os.path.splitext(in_file_path)
        input_format = map_info_extension_to_format[extension[1:]]
        self.svnTree.comments.append("Original file "+in_file_path)
        self.svnTree.read_info_map_from_file(in_file_path, format=input_format)

    def write_info_map_file(self):
        _, extension = os.path.splitext(self.cvl.get_str("__MAIN_OUT_FILE__"))
        output_format = map_info_extension_to_format[extension[1:]]
        self.svnTree.write_to_file(self.cvl.get_str("__MAIN_OUT_FILE__"), in_format=output_format)

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
        match = revision_range_re.match(self.cvl.get_str("REPO_REV"))
        if match:
            min_rev += int(match.group('min_rev'))
            if match.group('max_rev'):
                max_rev += int(match.group('max_rev'))
            else:
                max_rev += min_rev
        return min_rev, max_rev

    def do_create_links(self):
        if "REPO_NAME" not in self.cvl:
            raise ValueError("'REPO_NAME' was not defined")
        if "SVN_REPO_URL" not in self.cvl:
            raise ValueError("'SVN_REPO_URL' was not defined")
        if "ROOT_LINKS_FOLDER" not in self.cvl:
            raise ValueError("'ROOT_LINKS_FOLDER' was not defined")
        if "COPY_TOOL" not in self.cvl:
            from platformSpecificHelper_Base import DefaultCopyToolName
            self.cvl.set_variable("COPY_TOOL").append(DefaultCopyToolName(self.cvl.get_str("TARGET_OS")))
        if "SVN_CLIENT_PATH" not in self.cvl:
            self.cvl.set_variable("SVN_CLIENT_PATH").append("svn")

        self.batch_accum.set_current_section('links')

        self.platform_helper.use_copy_tool(self.cvl.resolve_string("$(COPY_TOOL)"))

        # call svn info and to find out the last repo revision
        svn_info_command = ["svn", "info", self.cvl.resolve_string("$(SVN_REPO_URL)")]
        proc = subprocess.Popen(svn_info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        my_stdout, my_stderr = proc.communicate()
        if proc.returncode != 0 or my_stderr != "":
            raise ValueError("Could not read info from svn: "+my_stderr)

        info_as_io = StringIO.StringIO(my_stdout)
        self.svnTree.read_from_svn_info(info_as_io)
        _, last_repo_rev = self.svnTree.min_max_rev()
        self.cvl.set_variable("__LAST_REPO_REV__").append(str(last_repo_rev))

        self.cvl.set_variable("__CHECKOUT_FOLDER__").append("$(ROOT_LINKS_FOLDER)/Base")
        self.batch_accum += self.platform_helper.mkdir("$(__CHECKOUT_FOLDER__)")

        accum = BatchAccumulator(self.cvl) # sub-accumulator serves as a template for each version
        accum.set_current_section('links')
        self.create_links_for_revision(accum)

        base_rev = int(self.cvl.get_str("BASE_REPO_REV"))
        if base_rev > last_repo_rev:
            raise ValueError("base_rev "+str(base_rev)+" > last_repo_rev "+str(last_repo_rev))
        for revision in range(base_rev, last_repo_rev+1):
            create_links_done_stamp_file = self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/"+str(revision)+"/$(CREATE_LINKS_STAMP_FILE_NAME)")
            if not os.path.isfile(create_links_done_stamp_file):
                save_dir_var = "REV_"+str(revision)+"_SAVE_DIR"
                self.batch_accum += self.platform_helper.save_dir(save_dir_var)
                self.cvl.set_variable("__CURR_REPO_REV__").append(str(revision))
                revision_lines = accum.finalize_list_of_lines() # will resolve with current  __CURR_REPO_REV__
                self.batch_accum += revision_lines
                self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
                self.batch_accum += self.platform_helper.new_line()
            else:
                msg = " ".join( ("links for revision", str(revision), "are already created") )
                self.batch_accum += self.platform_helper.echo(msg)
                print(msg)
        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in self.cvl:
            self.run_batch_file()

    def create_links_for_revision(self, accum):
        revision_folder_path = "$(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)"
        revision_instl_folder_path = revision_folder_path+"/instl"

        accum += self.platform_helper.echo("Creating links for revision $(__CURR_REPO_REV__)")
        # sync revision from SVN to Base folder
        accum += self.platform_helper.echo("Getting revision $(__CURR_REPO_REV__) from $(SVN_REPO_URL)")
        checkout_command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"'+"$(SVN_REPO_URL)@$(__CURR_REPO_REV__)"+'"', '"'+"$(__CHECKOUT_FOLDER__)"+'"', "--depth", "infinity"]
        accum += " ".join(checkout_command_parts)

        # copy Base folder to revision folder
        accum += self.platform_helper.mkdir("$(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)")
        accum += self.platform_helper.echo("Copying revision $(__CURR_REPO_REV__) to $(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)")
        accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir("$(__CHECKOUT_FOLDER__)", revision_folder_path, "$(ROOT_LINKS_FOLDER)/Base")

        # get info from SVN for all files in revision
        accum += self.platform_helper.mkdir(revision_instl_folder_path)
        accum += self.platform_helper.cd("$(__CHECKOUT_FOLDER__)")
        accum += self.platform_helper.echo("Getting info from svn to ../$(__CURR_REPO_REV__)/instl/info_map.info")
        info_command_parts = ['"$(SVN_CLIENT_PATH)"', "info", "--depth infinity", ">", "../$(__CURR_REPO_REV__)/instl/info_map.info"]
        accum += " ".join(info_command_parts)

        # get properties from SVN for all files in revision
        accum += self.platform_helper.echo("Getting props from svn to ../$(__CURR_REPO_REV__)/instl/info_map.props")
        props_command_parts = ['"$(SVN_CLIENT_PATH)"', "proplist", "--depth infinity", ">", "../$(__CURR_REPO_REV__)/instl/info_map.props"]
        accum += " ".join(props_command_parts)

        accum += self.platform_helper.cd("$(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)")
        # translate SVN info and properties to info_map text format
        accum += self.platform_helper.echo("Creating $(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)/instl/info_map.txt")
        trans_command_parts = ['"$(__INSTL_EXE_PATH__)"', "trans",
                               "--in", "instl/info_map.info",
                               "--props ", "instl/info_map.props",
                               "--out ", "instl/info_map.txt",
                               "--config", "$(__CONFIG_FILE_PATH__)"]
        accum += " ".join(trans_command_parts)

        # create Mac only info_map
        accum += self.platform_helper.echo("Creating $(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)/instl/info_map_Mac.txt")
        trans_command_parts = ['"$(__INSTL_EXE_PATH__)"', "trans", "--in", "instl/info_map.txt", "--out ", "instl/info_map_Mac.txt",  "--filter-out", "Win"]
        accum += " ".join(trans_command_parts)

        # create Win only info_map
        accum += self.platform_helper.echo("Creating $(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)/instl/info_map_Win.txt")
        trans_command_parts = ['"$(__INSTL_EXE_PATH__)"', "trans", "--in", "instl/info_map.txt", "--out ", "instl/info_map_Win.txt",  "--filter-out", "Mac"]
        accum += " ".join(trans_command_parts)

        accum += " ".join(["touch", "$(CREATE_LINKS_STAMP_FILE_NAME)"])

        accum += self.platform_helper.echo("done version $(__CURR_REPO_REV__)")

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

    def do_upload_to_s3_aws(self):
        root_links_folder = self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)")
        sub_dirs = os.listdir(root_links_folder)
        dirs_to_upload = list()
        for rev_dir in sub_dirs:
            try:
                dir_as_int = int(rev_dir) # revision dirs should be integers
                if not os.path.isdir(self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/"+str(rev_dir))):
                    print(rev_dir, "is not a directory")
                    continue
                if dir_as_int < int(self.cvl.get_str("BASE_REPO_REV")):
                    print(rev_dir, "is below BASE_REPO_REV", self.cvl.get_str("BASE_REPO_REV"))
                    continue
                create_links_done_stamp_file = self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/"+str(rev_dir)+"/$(CREATE_LINKS_STAMP_FILE_NAME)")
                if not os.path.isfile(create_links_done_stamp_file):
                    print("Ignoring folder", str(rev_dir), "Could not find ", create_links_done_stamp_file)
                    continue
                up_2_s3_done_stamp_file = self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/"+str(rev_dir)+"/$(UP_2_S3_STAMP_FILE_NAME)")
                if os.path.isfile(up_2_s3_done_stamp_file):
                    print("Ignoring folder", str(rev_dir), "already uploaded to S3")
                    continue
                dirs_to_upload.append(rev_dir)
            except:
                pass
        dirs_to_upload.sort(key=int)
        for work_dir in dirs_to_upload:
            print("Will upload to", self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/"+work_dir))

        self.batch_accum.set_current_section('upload')
        for revision in dirs_to_upload:
            accum = BatchAccumulator(self.cvl) # sub-accumulator serves as a template for each version
            accum.set_current_section('upload')
            save_dir_var = "REV_"+revision+"_SAVE_DIR"
            self.batch_accum += self.platform_helper.save_dir(save_dir_var)
            self.cvl.set_variable("__CURR_REPO_REV__").append(str(revision))
            self.do_upload_to_s3_aws_for_revision(accum)
            revision_lines = accum.finalize_list_of_lines() # will resolve with current  __CURR_REPO_REV__
            self.batch_accum += revision_lines
            self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
            self.batch_accum += self.platform_helper.new_line()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in self.cvl:
            self.run_batch_file()

    def do_upload_to_s3_aws_for_revision(self, accum):
        map_file_path = 'instl/info_map.txt'
        info_map_path = self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)/"+map_file_path)
        repo_rev = int(self.cvl.resolve_string("$(__CURR_REPO_REV__)"))
        self.svnTree.clear_subs()
        self.read_info_map_file(info_map_path)

        accum += self.platform_helper.cd("$(ROOT_LINKS_FOLDER)/$(__CURR_REPO_REV__)")

        if 'Mac' in self.cvl.get_list("CURRENT_OS_NAMES"):
            accum += "find . -name .DS_Store -delete"

        # Files a folders that do not be long to __CURR_REPO_REV__ should not be uploaded.
        # Since aws sync command uploads the whole folder, we delete from disk all files
        # and folders that should not be uploaded.
        # To save delete instructions for every file we rely on the fact that each folder
        # has last_rev which is the maximum last_rev of it's sub-items.
        self.svnTree.remove_item_at_path('instl') # never remove the instl folder
        from collections import deque
        dir_queue = deque()
        dir_queue.append(self.svnTree)
        while len(dir_queue) > 0:
            curr_item = dir_queue.popleft()
            files, dirs = curr_item.sorted_sub_items()
            for file_item in files:
                if file_item.last_rev() > repo_rev:
                    raise ValueError(str(file_item)+" last_rev > repo_rev "+str(repo_rev))
                elif file_item.last_rev() < repo_rev:
                    accum += self.platform_helper.rmfile(file_item.full_path())
            for dir_item in dirs:
                if dir_item.last_rev() > repo_rev:
                    raise ValueError(str(dir_item)+" last_rev > repo_rev "+str(repo_rev))
                elif dir_item.last_rev() < repo_rev: # whole folder should be removed
                    accum += self.platform_helper.rmdir(dir_item.full_path(), recursive=True)
                else:
                    dir_queue.append(dir_item) # need to check inside the folder
        
        # remove broken links, aws cannot handle them
        accum += " ".join( ("find", ".", "-type", "l", "!", "-exec", "test", "-e", "{}", "\;", "-exec", "rm", "{}", "\;") )

        accum += " ".join( ["aws", "s3", "sync",
                           ".","s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_REV__)",
                           "--acl", "public-read",
                           "--exclude", '"*.DS_Store"',
                           "--exclude", '"$(UP_2_S3_STAMP_FILE_NAME)"',
                           "--exclude", '"$(CREATE_LINKS_STAMP_FILE_NAME)"'
                        ] )
        accum += " ".join(["touch", "$(UP_2_S3_STAMP_FILE_NAME)"])

    def do_up_repo_rev(self):
        file_to_upload = self.cvl.get_str("__MAIN_INPUT_FILE__")
        _, file_to_upload_name = os.path.split(file_to_upload)
        s3_path = "admin/"+file_to_upload_name
        print("uploading:", file_to_upload, "to", s3_path)

        import boto
        s3 		= boto.connect_s3(self.cvl.get_str("AWS_ACCESS_KEY_ID"), self.cvl.get_str("AWS_SECRET_ACCESS_KEY"))
        bucket 	= s3.get_bucket(self.cvl.get_str("S3_BUCKET_NAME"))
        key_obj = boto.s3.key.Key(bucket)
        key_obj.key = s3_path
        key_obj.metadata={'Content-Type': 'text/plain'}
        key_obj.set_contents_from_filename(file_to_upload, cb=percent_cb, num_cb=4)
        key_obj.set_acl('public-read') # must be done after the upload

    def do_upload_to_s3(self):
        g_map_file_path					= 'instl/info_map_upload.txt'
        #g_upload_done_key				= 'instl/done'
        info_map_path = self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/$(REPO_REV)/"+g_map_file_path)
        self.read_info_map_file(info_map_path)

        self.batch_accum.set_current_section('upload') # for symmetry, no instructions are actually produced

        upload_list = list()
        for item in self.svnTree.walk_items(what="file"):
            file_to_upload = self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/$(REPO_REV)/"+item.full_path())
            s3_path = self.cvl.resolve_string("$(REPO_NAME)/$(REPO_REV)/"+item.full_path())
            if not os.path.islink(file_to_upload):
                upload_list.append( (file_to_upload, s3_path ) )
            else:
                link_value = os.readlink(file_to_upload)
                link_as_text_path = file_to_upload+".readlink"
                open(link_as_text_path, "w").write(link_value)
                upload_list.append( (link_as_text_path, s3_path ) )

        for dirpath, dirnames, filenames in os.walk(self.cvl.resolve_string("$(ROOT_LINKS_FOLDER)/$(REPO_REV)/instl")):
            for filename in filenames:
                file_to_upload = os.path.join(dirpath, filename)
                s3_path = self.cvl.resolve_string("$(REPO_NAME)/$(REPO_REV)/instl/"+filename)
                upload_list.append( (file_to_upload, s3_path) )

        import boto
        s3 		= boto.connect_s3(self.cvl.get_str("AWS_ACCESS_KEY_ID"), self.cvl.get_str("AWS_SECRET_ACCESS_KEY"))
        bucket 	= s3.get_bucket(self.cvl.get_str("S3_BUCKET_NAME"))
        key_obj = boto.s3.key.Key(bucket)
        if "__RUN_BATCH_FILE__" in self.cvl:
            for upload_pair in upload_list:
                print("uploading:", upload_pair[0], "to", upload_pair[1])
                key_obj.key = upload_pair[1]
                key_obj.set_contents_from_filename(upload_pair[0], cb=percent_cb, num_cb=4)
                key_obj.set_acl('public-read') # must be done after the upload
                print()
        else:
            for upload_pair in upload_list:
                print(upload_pair[0], "-->", upload_pair[1])

def percent_cb(unused_complete, unused_total):
    sys.stdout.write('.')
    sys.stdout.flush()
