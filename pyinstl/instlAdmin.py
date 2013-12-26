#!/usr/bin/env python2.7

from __future__ import print_function
import datetime

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
        self.cvl.set_variable("__ALLOWED_COMMANDS__").extend( ('trans', 'createlinks', 'up2s3') )
        self.svnTree = svnTree.SVNTree()

    @func_log_wrapper
    def do_command(self):
        the_command = self.cvl.get_str("__MAIN_COMMAND__")
        if the_command in self.cvl.get_list("__ALLOWED_COMMANDS__"):
            #print("server_commands", the_command)
            if the_command == "trans":
                self.do_trans()
            elif the_command == "createlinks":
                self.do_create_links()
            elif the_command == "up2s3":
                self.do_upload_to_s3()

    def do_trans(self):
        self.read_info_map_file(self.cvl.get_str("__MAIN_INPUT_FILE__"))
        if "__PROPS_FILE__" in self.cvl:
            self.read_info_map_file(self.cvl.get_str("__PROPS_FILE__"))
        self.filter_out_info_map(self.cvl.get_list("__FILTER_OUT_PATHS__"))

        base_rev = int(self.cvl.get_str("__BASE_REPO_REV__"))
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
        self.svnTree.comments.append("      read on "+datetime.datetime.today().isoformat())
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
        match = revision_range_re.match(self.cvl.get_str("__REPO_REV__"))
        if match:
            min_rev += int(match.group('min_rev'))
            if match.group('max_rev'):
                max_rev += int(match.group('max_rev'))
            else:
                max_rev += min_rev
        return min_rev, max_rev

    def do_create_links(self):
        if "COPY_TOOL" not in self.cvl:
            from platformSpecificHelper_Base import DefaultCopyToolName
            self.cvl.set_variable("COPY_TOOL").append(DefaultCopyToolName(self.cvl.get_str("TARGET_OS")))
        if "SVN_CLIENT_PATH" not in self.cvl:
            self.cvl.set_variable("SVN_CLIENT_PATH").append("svn")

        self.batch_accum.set_current_section('links')

        self.platform_helper.use_copy_tool(self.cvl.get_str("COPY_TOOL"))

        self.cvl.set_variable("__CHECKOUT_FOLDER__").append("$(__ROOT_LINKS_FOLDER__)/Base")
        self.batch_accum += self.platform_helper.mkdir("$(__CHECKOUT_FOLDER__)")

        accum = BatchAccumulator(self.cvl)
        accum.set_current_section('links')
        self.create_links_for_revision(accum)

        min_rev, max_rev = self.get_revision_range()
        base_rev = int(self.cvl.get_str("__BASE_REPO_REV__"))
        if base_rev > 0 and base_rev > min_rev:
            raise ValueError("base_rev "+str(base_rev)+" > min_rev "+str(min_rev))
        if min_rev >= max_rev:
            raise ValueError("min_rev "+str(min_rev)+" >= max_rev "+str(max_rev))
        for revision in range(min_rev, max_rev):
            save_dir_var = "REV_"+str(revision)+"_SAVE_DIR"
            self.batch_accum += self.platform_helper.save_dir(save_dir_var)
            self.cvl.set_variable("__CURR_REPO_REV__").append(str(revision))
            revision_lines = accum.finalize_list_of_lines() # will resolve with current  __CURR_REPO_REV__
            self.batch_accum += revision_lines
            self.batch_accum += self.platform_helper.restore_dir(save_dir_var)
            self.batch_accum += self.platform_helper.new_line()

        self.create_variables_assignment()
        self.write_batch_file()
        if "__RUN_BATCH_FILE__" in self.cvl:
            self.run_batch_file()

    def create_links_for_revision(self, accum):
        revision_folder_path = "$(__ROOT_LINKS_FOLDER__)/$(__CURR_REPO_REV__)"
        revision_instl_folder_path = revision_folder_path+"/instl"

        accum += self.platform_helper.echo("Getting version $(__CURR_REPO_REV__) from $(__SVN_URL__)")
        checkout_command_parts = ['"$(SVN_CLIENT_PATH)"', "co", '"'+"$(__SVN_URL__)@$(__CURR_REPO_REV__)"+'"', '"'+"$(__CHECKOUT_FOLDER__)"+'"', "--depth", "infinity"]
        accum += " ".join(checkout_command_parts)

        accum += self.platform_helper.mkdir("$(__ROOT_LINKS_FOLDER__)/$(__CURR_REPO_REV__)")
        accum += self.platform_helper.echo("Copying version $(__CURR_REPO_REV__) to $(__ROOT_LINKS_FOLDER__)/$(__CURR_REPO_REV__)")
        accum += self.platform_helper.copy_tool.copy_dir_contents_to_dir("$(__CHECKOUT_FOLDER__)", revision_folder_path, "$(__CHECKOUT_FOLDER__)")

        accum += self.platform_helper.mkdir(revision_instl_folder_path)
        accum += self.platform_helper.cd("$(__CHECKOUT_FOLDER__)")
        accum += self.platform_helper.echo("Getting info from svn to ../$(__CURR_REPO_REV__)/instl/info_map.info")
        info_command_parts = ['"$(SVN_CLIENT_PATH)"', "info", "--depth infinity", ">", "../$(__CURR_REPO_REV__)/instl/info_map.info"]
        accum += " ".join(info_command_parts)

        accum += self.platform_helper.echo("Getting props from svn to ../$(__CURR_REPO_REV__)/instl/info_map.props")
        props_command_parts = ['"$(SVN_CLIENT_PATH)"', "proplist", "--depth infinity", ">", "../$(__CURR_REPO_REV__)/instl/info_map.props"]
        accum += " ".join(props_command_parts)

        accum += self.platform_helper.echo("Creating $(__ROOT_LINKS_FOLDER__)/$(__CURR_REPO_REV__)/instl/info_map.txt")
        trans_command_parts = ['"$(__INSTL_EXE_PATH__)"', "trans", "--in", "../$(__CURR_REPO_REV__)/instl/info_map.info", "--props ", "../$(__CURR_REPO_REV__)/instl/info_map.props", "--out ", "../$(__CURR_REPO_REV__)/instl/info_map.txt", "--base-rev", "$(__BASE_REPO_REV__)"]
        accum += " ".join(trans_command_parts)

        accum += self.platform_helper.echo("Creating $(__ROOT_LINKS_FOLDER__)/$(__CURR_REPO_REV__)/instl/info_map_upload.txt")
        trans_command_parts = ['"$(__INSTL_EXE_PATH__)"', "trans", "--in", "../$(__CURR_REPO_REV__)/instl/info_map.txt", "--out ", "../$(__CURR_REPO_REV__)/instl/info_map_upload.txt",  "--filter-in", "$(__CURR_REPO_REV__)",  "--filter-out", "instl"]
        accum += " ".join(trans_command_parts)

        accum += self.platform_helper.echo("Creating $(__ROOT_LINKS_FOLDER__)/$(__CURR_REPO_REV__)/instl/info_map_Mac.txt")
        trans_command_parts = ['"$(__INSTL_EXE_PATH__)"', "trans", "--in", "../$(__CURR_REPO_REV__)/instl/info_map.txt", "--out ", "../$(__CURR_REPO_REV__)/instl/info_map_Mac.txt",  "--filter-out", "Win"]
        accum += " ".join(trans_command_parts)

        accum += self.platform_helper.echo("Creating $(__ROOT_LINKS_FOLDER__)/$(__CURR_REPO_REV__)/instl/info_map_Win.txt")
        trans_command_parts = ['"$(__INSTL_EXE_PATH__)"', "trans", "--in", "../$(__CURR_REPO_REV__)/instl/info_map.txt", "--out ", "../$(__CURR_REPO_REV__)/instl/info_map_Win.txt",  "--filter-out", "Mac"]
        accum += " ".join(trans_command_parts)

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

    def do_upload_to_s3(self):
        self.read_yaml_file(self.cvl.get_str("__S3_CONFIG_FILE__"))
        g_map_file_path					= 'instl/info_map_upload.txt'
        #g_upload_done_key				= 'instl/done'
        info_map_path = self.cvl.resolve_string("$(__ROOT_LINKS_FOLDER__)/$(__REPO_REV__)/"+g_map_file_path)
        self.read_info_map_file(info_map_path)

        self.batch_accum.set_current_section('upload') # for symmetry, no instructions are actually produced

        upload_list = list()
        for item in self.svnTree.walk_items(what="file"):
            file_to_upload = self.cvl.resolve_string("$(__ROOT_LINKS_FOLDER__)/$(__REPO_REV__)/"+item.full_path())
            s3_path = self.cvl.resolve_string("$(ROOT_VERSION_NAME)/$(__REPO_REV__)/"+item.full_path())
            if not os.path.islink(file_to_upload):
                upload_list.append( (file_to_upload, s3_path ) )
            else:
                link_value = os.readlink(file_to_upload)
                link_as_text_path = file_to_upload+".readlink"
                open(link_as_text_path, "w").write(link_value)
                upload_list.append( (link_as_text_path, s3_path ) )

        for dirpath, dirnames, filenames in os.walk(self.cvl.resolve_string("$(__ROOT_LINKS_FOLDER__)/$(__REPO_REV__)/instl")):
            for filename in filenames:
                file_to_upload = os.path.join(dirpath, filename)
                s3_path = self.cvl.resolve_string("$(ROOT_VERSION_NAME)/$(__REPO_REV__)/instl/"+filename)
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
                break
        else:
            for upload_pair in upload_list:
                print(upload_pair[0], "-->", upload_pair[1])

def percent_cb(unused_complete, unused_total):
    sys.stdout.write('.')
    sys.stdout.flush()
