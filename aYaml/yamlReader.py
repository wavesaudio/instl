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

import os
import io
import yaml
import urllib.error

from typing import Callable, Dict, List, Tuple

import utils


class YamlReader(object):
    def __init__(self) -> None:
        self.path_searcher = None
        self.url_translator = None
        self.specific_doc_readers: Dict[str, Callable] = dict()
        self.file_read_stack: List[os.PathLike] = list()
        self.exception_printed = False
        self.post_nodes: List[Tuple[yaml.Node, Callable]] = list()

    def init_specific_doc_readers(self): # this function must be overridden
        self.specific_doc_readers["__no_tag__"] = self.do_nothing_node_reader
        self.specific_doc_readers["__unknown_tag__"] = self.do_nothing_node_reader

    def get_read_function_for_doc(self, a_node):
        is_post_tag = False  # post tags should be read only after all documents where read
        if not a_node.tag:
            retVal = self.specific_doc_readers.get("__no_tag__", None)
        else:
            effective_tag = a_node.tag
            if a_node.tag.endswith("_post"):
                effective_tag = a_node.tag[:-len("_post")]
                is_post_tag = True
            if effective_tag in self.specific_doc_readers:
                retVal = self.specific_doc_readers[effective_tag]
            else:
                retVal = self.specific_doc_readers.get("__unknown_tag__", None)
        return retVal, is_post_tag

    def do_nothing_node_reader(self, a_node, *args, **kwargs):
        pass

    def read_yaml_file(self, file_path, *args, **kwargs):
        try:
            #self.progress("reading ", file_path)
            allow_reading_of_internal_vars = kwargs.get('allow_reading_of_internal_vars', False)
            with self.allow_reading_of_internal_vars(allow=allow_reading_of_internal_vars):
                self.file_read_stack.append(file_path)
                buffer = utils.read_file_or_url(file_path, path_searcher=self.path_searcher)
                buffer = io.StringIO(buffer)     # turn text to a stream
                kwargs['path-to-file'] = file_path
                kwargs['allow_reading_of_internal_vars'] = allow_reading_of_internal_vars
                self.read_yaml_from_stream(buffer, *args, **kwargs)
                self.file_read_stack.pop()
                # now read the __post tags if any
                if len(self.file_read_stack) == 0:  # first file done reading
                    while self.post_nodes:
                        a_post_node, a_post_read_func = self.post_nodes.pop()
                        a_post_read_func(a_post_node, *args, **kwargs)

        except (FileNotFoundError, urllib.error.URLError, yaml.YAMLError) as ex:
            if isinstance(ex, yaml.YAMLError):
                kwargs['exception'] = ex
                kwargs['buffer'] = buffer
                self.handle_yaml_read_error(**kwargs)
            ignore = kwargs.get('ignore_if_not_exist', False)
            if ignore:
                self.progress(f"'ignore_if_not_exist' specified, ignoring {ex.__class__.__name__} for {self.file_read_stack[-1]}")
                self.file_read_stack.pop()
            else:
                if not self.exception_printed:  # avoid recursive printing of error message
                    read_file_history = " -> ".join(self.file_read_stack+[file_path])
                    print(f"{ex.__class__.__name__} reading file:\n", read_file_history)
                    self.exception_printed = True
                raise
        except Exception as ex:
            if not self.exception_printed:      # avoid recursive printing of error message
                read_file_history = "\n->\n".join([os.fspath(file_path) for file_path in  self.file_read_stack])
                print("Exception reading file:", read_file_history)
                self.exception_printed = True
            raise

    def read_yaml_from_stream(self, the_stream, *args, **kwargs):
        for a_node in yaml.compose_all(the_stream):
            self.read_yaml_from_node(a_node, *args, **kwargs)

    def read_yaml_from_node(self, the_node, *args, **kwargs):
        YamlReader.convert_standard_tags(the_node)
        self.init_specific_doc_readers()  # in case previous reading changed the assigned readers (ACCEPTABLE_YAML_DOC_TAGS)
        read_func, is_post_tag = self.get_read_function_for_doc(the_node)
        if read_func is not None:
            if is_post_tag:
                self.post_nodes.append((the_node, read_func))
            else:
                read_func(the_node, *args, **kwargs)

    @staticmethod
    def convert_standard_tags(a_node):
        if a_node.tag in ("tag:yaml.org,2002:null", "tag:yaml.org,2002:python/none"):
            a_node.value = None
        elif a_node.isSequence():
             for item in a_node.value:
                YamlReader.convert_standard_tags(item)
        elif a_node.isMapping():
            for (_key, _val) in a_node.value:
                YamlReader.convert_standard_tags(_val)

    def handle_yaml_parse_error(self, **kwargs):
        """
            override if something needs to be done when parsing a yaml file fails
            this function will be called for yaml.reader.ReaderError and like
            minded errors, NOT for FileNotFoundError or URLError
        """
        pass
