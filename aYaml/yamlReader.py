#!/usr/bin/env python3

""" YamlReader is a base class for writing specific classes that read yaml.
    when reading a yaml file, one or more documents can be found, each optionally
    tagged, e.g.: --- !define. yamlReader will identify these documents and call the
    appropriate function to parse the document. Classes inheriting from yamlReader
    should supply these document type specific read functions by overriding
    YamlReader.init_specific_doc_readers.
    Two meta tags are provided: "__no_tag__" for documents that have no tag,
    "__unknown_tag__" for document tags that were not assigned specific read
    functions.
    For readers that do not support either "__no_tag__", "__unknown_tag__" or both,
    delete these tags from self.specific_doc_readers when overriding init_specific_doc_readers.
"""

import io
import yaml
import urllib.error

import utils


class YamlReader(object):
    def __init__(self):
        self.path_searcher = None
        self.url_translator = None
        self.specific_doc_readers = dict()
        self.file_read_stack = list()
        self.exception_printed = False

    def init_specific_doc_readers(self): # this function must be overridden
        self.specific_doc_readers["__no_tag__"] = self.do_nothing_node_reader
        self.specific_doc_readers["__unknown_tag__"] = self.do_nothing_node_reader

    def get_read_function_for_doc(self, a_node):
        if not a_node.tag:
            retVal = self.specific_doc_readers.get("__no_tag__", None)
        elif a_node.tag in self.specific_doc_readers:
            retVal = self.specific_doc_readers[a_node.tag]
        else:
            retVal = self.specific_doc_readers.get("__unknown_tag__", None)
        return retVal

    def do_nothing_node_reader(self, a_node, *args, **kwargs):
        pass

    def read_yaml_file(self, file_path, *args, **kwargs):
        try:
            self.file_read_stack.append(file_path)
            with utils.open_for_read_file_or_url(file_path, self.url_translator, self.path_searcher) as open_file:
                self.file_read_stack[-1] = open_file.actual_path
                buffer = open_file.fd.read()
                buffer = utils.unicodify(buffer) # make sure text is unicode
                buffer = io.StringIO(buffer)     # turn text to a stream
                buffer.name = open_file.actual_path          # this will help identify the file for debugging and messages
                kwargs['path-to-file'] = open_file.actual_path
                self.read_yaml_from_stream(buffer, *args, **kwargs)
            self.file_read_stack.pop()
        except (FileNotFoundError, urllib.error.URLError) as ex:
            ignore = kwargs.get('ignore_if_not_exist', False)
            if ignore:
                print("'ignore_if_not_exist' specified, ignoring FileNotFoundError for", self.file_read_stack[-1])
                self.file_read_stack.pop()
            else:
                if not self.exception_printed:  # avoid recursive printing of error message
                    read_file_history = "\n->\n".join(self.file_read_stack+[file_path])
                    print("FileNotFoundError/URLError reading file:\n", read_file_history)
                    self.exception_printed = True
                raise
        except Exception as ex:
            if not self.exception_printed:      # avoid recursive printing of error message
                read_file_history = "\n->\n".join(self.file_read_stack)
                print("Exception reading file:", read_file_history)
                self.exception_printed = True
            raise

    def read_yaml_from_stream(self, the_stream, *args, **kwargs):
        for a_node in yaml.compose_all(the_stream):
            self.init_specific_doc_readers()  # in case previous reading changed the assigned readers (ACCEPTABLE_YAML_DOC_TAGS)
            read_func = self.get_read_function_for_doc(a_node)
            if read_func is not None:
                read_func(a_node, *args, **kwargs)

