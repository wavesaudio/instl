#!/usr/bin/env python3

""" YamlReader is a base class for writing specific classes that read yaml
    when reading a yaml file, one or more documents can be found, each optionally
    tagged: --- !define. yamlReader will identify these documents and call the
    appropriate function to parse the document. Classes inheriting from yamlReader
    should supply these read functions by overriding init_specific_doc_readers.
    Two meta tags are provided: "__no_tag__" for documents that have not tag,
    "__unknown_tag__" for tags that were not assigned specific read functions.
    For readers that do not support either "__no_tag__", "__unknown_tag__" or both,
    delete these tags from self.specific_doc_readers when overriding init_specific_doc_readers.
"""

import io
import yaml

import utils


class YamlReader(object):
    def __init__(self):
        self.path_searcher = None
        self.url_translator = None
        self.specific_doc_readers = dict()
        self.init_specific_doc_readers()

    def init_specific_doc_readers(self): # this function must be overridden
        self.specific_doc_readers["__no_tag__"] = self.do_nothing_node_reader
        self.specific_doc_readers["__unknown_tag__"] = self.do_nothing_node_reader

    def get_read_function_for_doc(self, a_node):
        retVal = None
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
            with utils.open_for_read_file_or_url(file_path, self.url_translator, self.path_searcher) as file_fd:
                buffer = file_fd.read()
                buffer = utils.unicodify(buffer) # make sure text is unicode
                buffer = io.StringIO(buffer)     # turn text to a stream
                buffer.name = file_path          # this will help identify the file for debugging and messages
                self.read_yaml_from_stream(buffer, *args, **kwargs)
                self.init_specific_doc_readers()  # call again in case the reading changed the readers (ACCEPTABLE_YAML_DOC_TAGS)
        except Exception as ex:
            print("Exception reading file:", file_path, ex)
            raise

    def read_yaml_from_stream(self, the_stream, *args, **kwargs):
        for a_node in yaml.compose_all(the_stream):
            read_func = self.get_read_function_for_doc(a_node)
            if read_func is not None:
                read_func(a_node, *args, **kwargs)

