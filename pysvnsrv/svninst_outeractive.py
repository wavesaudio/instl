#!/usr/bin/env python2.7
from __future__ import print_function

import os
import sys
import argparse
import svnTree

extension_to_format = {"txt" : "text", "text" : "text",
                        "inf" : "info", "info" : "info",
                        "yml" : "yaml", "yaml" : "yaml",
                        "pick" : "pickle", "pickl" : "pickle", "pickle" : "pickle",
                        }
def go_outeractive():
    name_space_obj = read_command_line_options(sys.argv[1:])
    elif name_space_obj.command == "diff":
        _, extension = os.path.splitext(name_space_obj.have_info_map_file[0])
        have_format = extension_to_format[extension[1:]]
        print("have:", name_space_obj.have_info_map_file[0], input_format)
        
        _, extension = os.path.splitext(name_space_obj.need_info_map_file[0])
        need_format = extension_to_format[extension[1:]]
        print("need:", name_space_obj.need_info_map_file[0], input_format)
        
        svnTreeObjHave = svnTree.SVNTree()
        svnTreeObj.read_from_file(name_space_obj.have_info_map_file[0], format=have_format, report_level=1)
        
        svnTreeObjNeed = svnTree.SVNTree()
        svnTreeObj.read_from_file(name_space_obj.need_info_map_file[0], format=need_format, report_level=1)
        
        svnTreeObjDiff = diff_info_maps(svnTreeObjHave, svnTreeObjNeed)
    
    else:
        ValueError("Unknown command "+name_space_obj.command)

def read_command_line_options(arglist):
    """ parse command line options """
    name_space_obj = None
    if arglist and len(arglist) > 0:
        parser = prepare_args_parser()
        name_space_obj = cmd_line_options()
        parser.parse_args(arglist, namespace=name_space_obj)
    return name_space_obj

class cmd_line_options(object):
    """ namespace object to give to parse_args
        holds command line options
    """
    def __init__(self):
        self.command = None
        self.input_file = None
        self.output_file = None
        self.props_file = None
        self.popu_folder = None
        self.have_info_map_file = None
        self.need_info_map_file = None

    def __str__(self):
        return "\n".join([''.join((n, ": ", str(v))) for n,v in sorted(vars(self).iteritems())])


def prepare_args_parser():
    def decent_convert_arg_line_to_args(self, arg_line):
        """ parse a file with options so that we do not have to write one sub-option
            per line.  Remove empty lines, comment lines, and end of line comments.
            ToDo: handle quotes
        """
        line_no_whitespce = arg_line.strip()
        if line_no_whitespce and line_no_whitespce[0] != '#':
            for arg in line_no_whitespce.split():
                if not arg:
                    continue
                elif  arg[0] == '#':
                    break
                yield arg

    parser = argparse.ArgumentParser(description='svninstl: prepare svn for instl usage',
                    prefix_chars='-',
                    fromfile_prefix_chars='@',
                    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    argparse.ArgumentParser.convert_arg_line_to_args = decent_convert_arg_line_to_args

    subparsers = parser.add_subparsers(dest='command', help='sub-command help')
    parser_diff = subparsers.add_parser('diff',
                                        help='diff two info maps')
    parser_create_info = subparsers.add_parser('createinfo',
                                        help='create info from local SVN repository')
#    parser_synccopy = subparsers.add_parser('synccopy',
#                                        help='sync files to be installed from server to temp folder and copy files from temp folder to target paths')

    for subparser in (parser_diff, ):
        popu_options = subparser.add_argument_group(description='diff arguments:')
        popu_options.add_argument('--have',
                                    required=True,
                                    nargs=1,
                                    metavar='have-info-map-file',
                                    dest='have_info_map_file',
                                    help="info map of currently synced files")
        popu_options.add_argument('--need',
                                    required=True,
                                    nargs=1,
                                    metavar='need-info-map-file',
                                    dest='need_info_map_file',
                                    help="info map of needed to sync files")

    for subparser in (parser_create_info, ):
        popu_options = subparser.add_argument_group(description='createinfo arguments:')
        popu_options.add_argument('--in','-i',
                                    required=True,
                                    nargs=1,
                                    metavar='svn_repo_folder',
                                    dest='input_file',
                                    help="folder containing local SVN repository")

    parser_version = subparsers.add_parser('version', help='display instl version')
    return parser
