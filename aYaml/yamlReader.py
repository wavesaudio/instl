#!/usr/bin/env python3.9

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
from contextlib import contextmanager
import urllib.error
import json

from typing import Callable, Dict, List, Tuple
import logging
log = logging.getLogger()

import utils


class YamlNodeStack(object):
    """ keep a stack of currently read yaml nodes
        so in case of error exact location can be reported
    """
    def __init__(self):
        self.node_stack = list()

    def __str__(self):
        return str(self.node_stack)

    @contextmanager
    def __call__(self, *args, **kwargs):
        self.node_stack.append(args[0])
        yield
        self.node_stack.pop()

    @property
    def start_mark(self):
        if len(self.node_stack) > 0:
            return str(self.node_stack[-1].start_mark)
        else:
            return "unknown"


class YamlReader(object):
    def __init__(self, config_vars) -> None:
        self.config_vars = config_vars
        self.path_searcher = None
        self.url_translator = None
        self.specific_doc_readers: Dict[str, Callable] = dict()
        self.file_read_stack: List[str] = list()
        self.exception_printed = False
        self.post_nodes: List[Tuple[yaml.Node, Callable]] = list()
        self.config_vars.setdefault("READ_YAML_FILES", None)

    def progress(self, message: str) -> None:
        pass

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
            kwargs.setdefault('original-path-to-file', file_path)
            allow_reading_of_internal_vars = kwargs.get('allow_reading_of_internal_vars', False)
            with self.allow_reading_of_internal_vars(allow=allow_reading_of_internal_vars):
                self.file_read_stack.append(os.fspath(file_path))
                # utils.add_to_actions_stack(f"""reading yaml file: {file_path}'""")
                buffer, actual_file_path = utils.read_file_or_url_utf8(file_path, config_vars=self.config_vars, path_searcher=self.path_searcher, connection_obj=kwargs.get('connection_obj', None))
                self.config_vars["READ_YAML_FILES"].append(os.fspath(actual_file_path))
                prog_message = f"reading {os.fspath(file_path)}"
                if os.fspath(file_path) != os.fspath(kwargs['original-path-to-file']):
                    prog_message += f" [{kwargs['original-path-to-file']}]"
                if os.fspath(actual_file_path) != os.fspath(file_path) and os.fspath(actual_file_path) != os.fspath(kwargs['original-path-to-file']):
                    prog_message += f" [{actual_file_path}]"
                self.progress(prog_message)
                buffer = io.StringIO(buffer)     # turn text to a stream
                buffer.name = actual_file_path   # so yaml parser knows the name of the file for error report
                kwargs['path-to-file'] = os.fspath(actual_file_path)
                kwargs['allow_reading_of_internal_vars'] = allow_reading_of_internal_vars
                kwargs['node-stack'] = YamlNodeStack()
                if os.fspath(file_path).lower().endswith(".json"):
                    self.read_json_from_stream(buffer, *args, **kwargs)
                else:
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
                log.debug(f"'ignore_if_not_exist' specified, ignoring {ex.__class__.__name__} for {self.file_read_stack[-1]}")
                self.file_read_stack.pop()
            else:
                if not self.exception_printed:  # avoid recursive printing of error message
                    read_file_history = " -> ".join(self.file_read_stack+[os.fspath(file_path)])
                    log.error(f"{ex.__class__.__name__} reading file: {read_file_history}")
                    self.exception_printed = True
                raise
        except Exception as ex: #TODO: oren - change logs?
            if not self.exception_printed:      # avoid recursive printing of error message
                read_file_history = "\n->\n".join(self.file_read_stack)
                log.error(f"""Exception reading file: {read_file_history}""")
                kwargs['exception'] = ex
                self.handle_yaml_read_error(**kwargs)
                self.exception_printed = True
            raise

    def handle_yaml_read_error(self, **kwargs):
        pass

    def read_yaml_from_stream(self, the_stream, *args, **kwargs):
        for a_node in yaml.compose_all(the_stream):
            with kwargs['node-stack'](a_node):
                self.read_yaml_from_node(a_node, *args, **kwargs)

    def read_json_from_stream(self, the_stream, *args, **kwargs):
        json_obj = json.load(the_stream)
        if isinstance(json_obj, dict):
            for identifier, contents in json_obj.items():
                if not isinstance(identifier, str):
                    raise TypeError(f"configVar key {identifier} should be of type str not {type(identifier)}")
                values = list()
                if isinstance(contents, (str, int)):
                    values.append(contents)
                elif isinstance(contents, (list, tuple)):
                    values.extend([item for item in contents if isinstance(item, (str, int))])
                else:
                    raise TypeError(f"configVar values for {identifier} should be of type str, int or list not {type(contents)}")
                self.config_vars[identifier] = values

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
