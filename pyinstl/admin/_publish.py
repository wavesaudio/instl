#!/usr/bin/env python3.12
"""Publishing / S3 / redis / manifests commands extracted verbatim from
pyinstl/instlAdmin.py (up2s3, up-short-index, wait-on-action-trigger,
activate-repo-rev, collect-manifests and their helpers).

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
import json
import logging
log = logging.getLogger()

import os
import sys
import traceback
import multiprocessing as mp
import time
import datetime
import re
import redis
import boto3

from dataclasses import dataclass
import dictdiffer

import utils
import aYaml
from pybatch import *
from configVar import ConfigVarYamlReader
from configVar import current_os
from configVar import run_batch

from ._helpers import start_redis_heartbeat_thread, smart_merge_dicts, dict_in_canonical_order


class _PublishAdminMixin:

    def do_up2s3(self):
        repo_rev = int(config_vars['TARGET_REPO_REV'])
        self.up2s3_repo_rev(repo_rev, self.batch_accum)

    def do_up_short_index(self):
        repo_rev = int(config_vars['TARGET_REPO_REV'])
        self.up_short_index_repo_rev(repo_rev, self.batch_accum)

    def up_short_index_repo_rev(self, repo_rev, batch_accum):
        assert repo_rev >= int(config_vars['BASE_REPO_REV']), f"repo-rev({repo_rev}) < BASE_REPO_REV({int(config_vars['BASE_REPO_REV'])})"
        assert repo_rev >= int(config_vars['IGNORE_BELOW_REPO_REV']), f"repo-rev({repo_rev}) < IGNORE_BELOW_REPO_REV({int(config_vars['IGNORE_BELOW_REPO_REV'])})"
        assert repo_rev not in list(map(int, list(config_vars.get('IGNORE_SPECIFIC_REPO_REV', [])))), f"repo-rev({repo_rev}) is in IGNORE_SPECIFIC_REPO_REV"

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        try:

            config_vars['UP_SHORT_INDEX_STATUS'] = "FAILED"
            config_vars['UP_SHORT_INDEX_EXCEPTION'] = ""
            config_vars["REPO_REV"] = str(repo_rev)
            config_vars["__CURR_REPO_REV__"] = str(repo_rev)
            config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.info_map_table.repo_rev_to_folder_hierarchy(repo_rev)  # e.g. 345 -> 03/45

            revision_folder_path = Path(config_vars["UPLOAD_REVISION_FOLDER"])
            if not revision_folder_path.is_dir():
                raise FileNotFoundError(f"revision folder does not exist {revision_folder_path}")

            revision_instl_index_path = Path(config_vars["UPLOAD_REVISION_INDEX_FILE"])
            checkout_folder_short_index_path = Path(config_vars["UPLOAD_REVISION_SHORT_INDEX_FILE"])

            batch_accum.set_current_section('admin')
            # checkout specific repo-rev to base folder
            # full checkout might take a long time so checking out to base folder, if done in repo-rev order
            # will only get the files of that repo-rev instead of the whole repository

            skip_some_actions = False  # to save time during debugging

            batch_accum += IndexYamlReader(revision_instl_index_path)
            batch_accum += ShortIndexYamlCreator(checkout_folder_short_index_path)
            base_rev = int(config_vars["BASE_REPO_REV"])
            if base_rev > 0:
                batch_accum += SetBaseRevision(base_rev)
            batch_accum += CreateRepoRevFile()

            if not skip_some_actions:
                with batch_accum.sub_accum(Cd(revision_folder_path)) as sub_accum:
                    sub_accum += Subprocess("aws", "s3", "cp", os.fspath(checkout_folder_short_index_path), "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/"+checkout_folder_short_index_path.name, "--content-type", 'text/plain')
                    repo_rev_file_path = config_vars["UPLOAD_REVISION_REPO_REV_FILE"].Path()
                    sub_accum += Subprocess("aws", "s3", "cp", os.fspath(repo_rev_file_path), "s3://$(S3_BUCKET_NAME)/admin/"+repo_rev_file_path.name, "--content-type", 'text/plain')
                    sub_accum += Subprocess("aws", "s3", "cp", os.fspath(repo_rev_file_path), "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)/instl/"+repo_rev_file_path.name, "--content-type", 'text/plain')

            self.write_batch_file(batch_accum)
            if run_batch():
                self.run_batch_file()

            r.hset(config_vars["UPLOAD_SHORT_INDEX_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["UPLOAD_SHORT_INDEX_LAST_UPLOADED_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            config_vars['UP_SHORT_INDEX_STATUS'] = "Completed"
        except Exception as ex:
            config_vars['UP_SHORT_INDEX_EXCEPTION'] = f"{ex}"
            print(f"up_short_index_repo_rev exception {ex}")
            raise
        finally:
            self.send_email_from_template_file(config_vars["SHORT_INDEX_EMAIL_TEMPLATE_PATH"].Path())

    def up2s3_repo_rev(self, repo_rev, batch_accum):
        assert repo_rev >= int(config_vars['BASE_REPO_REV']), f"repo-rev({repo_rev}) < BASE_REPO_REV({int(config_vars['BASE_REPO_REV'])})"
        assert repo_rev >= int(config_vars['IGNORE_BELOW_REPO_REV']), f"repo-rev({repo_rev}) < IGNORE_BELOW_REPO_REV({int(config_vars['IGNORE_BELOW_REPO_REV'])})"
        assert repo_rev not in list(map(int, list(config_vars.get('IGNORE_SPECIFIC_REPO_REV', [])))), f"repo-rev({repo_rev}) is in IGNORE_SPECIFIC_REPO_REV"

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        try:

            config_vars['UP2S3_STATUS'] = "FAILED"
            config_vars['UP2S3_EXCEPTION'] = ""
            config_vars["REPO_REV"] = str(repo_rev)
            config_vars["__CURR_REPO_REV__"] = str(repo_rev)
            config_vars["__CURR_REPO_FOLDER_HIERARCHY__"] = self.info_map_table.repo_rev_to_folder_hierarchy(repo_rev)  # e.g. 345 -> 03/45

            checkout_url = str(config_vars['SVN_REPO_URL'])
            checkout_base_folder = Path(config_vars['UPLOAD_BASE_CHECKOUT_FOLDER'])
            checkout_folder_instl_folder_path = checkout_base_folder.joinpath("instl")
            checkout_folder_index_path = checkout_folder_instl_folder_path.joinpath("index.yaml")

            revision_folder_path = Path(config_vars["UPLOAD_REVISION_FOLDER"])
            revision_instl_folder_path = Path(config_vars["UPLOAD_REVISION_INSTL_FOLDER"])
            revision_instl_index_path = Path(config_vars["UPLOAD_REVISION_INDEX_FILE"])

            checkout_folder_short_index_path = revision_instl_folder_path.joinpath("short-index.yaml")
            info_map_info_path = revision_instl_folder_path.joinpath("info_map.info")
            info_map_props_path = revision_instl_folder_path.joinpath("info_map.props")
            info_map_file_sizes_path = revision_instl_folder_path.joinpath("info_map.file-sizes")
            full_info_map_file_path = revision_instl_folder_path.joinpath(str(config_vars['FULL_INFO_MAP_FILE_NAME']))

            batch_accum.set_current_section('admin')
            # checkout specific repo-rev to base folder
            # full checkout might take a long time so checking out to base folder, if done in repo-rev order
            # will only get the files of that repo-rev instead of the whole repository

            skip_some_actions = False  # to save time during debugging

            if checkout_base_folder.is_dir():   # check if folder is indeed svn checkout folder
                if checkout_base_folder.joinpath(".svn").is_dir():
                    batch_accum += SVNCleanup(working_copy_path=checkout_base_folder, skip_action=skip_some_actions, stderr_means_err=False)
                else:
                    shutil.rmtree(checkout_base_folder)

            batch_accum += SVNCheckout(url=checkout_url, working_copy_path=checkout_base_folder, repo_rev=repo_rev, skip_action=skip_some_actions, stderr_means_err=False)

            batch_accum += MakeDir(revision_folder_path)  # create specific repo-rev folder
            batch_accum += MakeDir(revision_instl_folder_path)  # create specific repo-rev instl folder
            with batch_accum.sub_accum(Cd(checkout_base_folder)) as sub_accum:
                sub_accum += SVNInfo(url=".", out_file=info_map_info_path, skip_action=skip_some_actions, stderr_means_err=False)
                sub_accum += SVNPropList(url=".", out_file=info_map_props_path, skip_action=skip_some_actions, stderr_means_err=False)
                sub_accum += FileSizes(folder_to_scan=checkout_base_folder, out_file=info_map_file_sizes_path, skip_action=skip_some_actions)

            batch_accum += IndexYamlReader(checkout_folder_index_path)
            batch_accum += SVNInfoReader(info_map_info_path, format='info', disable_indexes_during_read=True)
            batch_accum += SVNInfoReader(info_map_props_path, format='props')
            batch_accum += SVNInfoReader(info_map_file_sizes_path, format='file-sizes')
            base_rev = int(config_vars["BASE_REPO_REV"])
            if base_rev > 0:
                batch_accum += SetBaseRevision(base_rev)

            # copy all (and only) the files from repo-rev
            batch_accum += CopySpecificRepoRev(checkout_base_folder, revision_folder_path, repo_rev, skip_action=skip_some_actions)
            # also copy the whole instl folder
            batch_accum += CopyDirToDir(checkout_folder_instl_folder_path, revision_folder_path, delete_extraneous_files=False)

            batch_accum += InfoMapFullWriter(full_info_map_file_path, in_format='text')
            batch_accum += InfoMapSplitWriter(revision_instl_folder_path, in_format='text')
            batch_accum += Wzip(revision_instl_index_path)
            batch_accum += ShortIndexYamlCreator(checkout_folder_short_index_path)
            batch_accum += CreateRepoRevFile()

            with batch_accum.sub_accum(Cd(revision_folder_path)) as sub_accum:
                sub_accum += Subprocess("aws", "s3", "sync", os.curdir, "s3://$(S3_BUCKET_NAME)/$(REPO_NAME)/$(__CURR_REPO_FOLDER_HIERARCHY__)", "--exclude", "*.DS_Store")
                repo_rev_file_path = config_vars["UPLOAD_REVISION_REPO_REV_FILE"].Path()
                sub_accum += Subprocess("aws", "s3", "cp", os.fspath(repo_rev_file_path), "s3://$(S3_BUCKET_NAME)/admin/"+repo_rev_file_path.name, "--content-type", 'text/plain')
            batch_accum += RmDirContents(revision_folder_path, exclude=['instl'])

            self.write_batch_file(batch_accum)
            if run_batch():
                self.run_batch_file()

            r.hset(config_vars["UPLOAD_REPO_REV_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["UPLOAD_REPO_REV_LAST_UPLOADED_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            r.hset(config_vars["UPLOAD_SHORT_INDEX_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["UPLOAD_SHORT_INDEX_LAST_UPLOADED_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            config_vars['UP2S3_STATUS'] = "Completed"
        except Exception as ex:
            config_vars['UP2S3_EXCEPTION'] = f"{ex}"
            print(f"up2s3_repo_rev exception {ex}")
            raise
        finally:
            self.send_email_from_template_file(config_vars["UP2S3_EMAIL_TEMPLATE_PATH"].Path())

    def report_instl_info_to_redis(self, redis_instance):
        instl_info_redis_key = config_vars.get("INSTL_INFO_REDIS_KEY", None).str()
        if instl_info_redis_key:
            instl_info_dict = dict()
            instl_info_dict["version"] = self.get_version_str(short=True)
            instl_info_dict["version string"] = self.get_version_str(short=False)
            instl_info_dict["path"] = config_vars["__INSTL_EXE_PATH__"].str()
            instl_info_dict["python version"] = config_vars["__PYTHON_VERSION__"].str()
            instl_info_dict["current os"] = current_os()
            redis_instance.hmset(instl_info_redis_key, instl_info_dict)

    def print_wait_on_action_trigger_info(self, _redis_host, _redis_port, _waiting_list_redis_key):
        if self.wait_info_counter == 0:
            log.info(f"{self.get_version_str(short=False)}")
            log.info(f"wait on redis list: {_redis_host}:{_redis_port} {_waiting_list_redis_key}")
            log.info(f"to upload: lpush {_waiting_list_redis_key} upload:domain:version:repo-rev (e.g. upload:test:V10:333)")
            log.info(f"to create and upload only short index: lpush {_waiting_list_redis_key} short-index:domain:version:repo-rev (e.g. short-index:test:V12:17)")
            log.info(f"to activate: lpush {_waiting_list_redis_key} activate:domain:version:repo-rev (e.g. activate:test:V10:333)")

            log.info(f"special values: lpush {_waiting_list_redis_key} stop|ping|reload-config-files")

        self.wait_info_counter += 1
        self.wait_info_counter = self.wait_info_counter % 30

    def do_wait_on_action_trigger(self):

        sys.path.append(os.pardir)
        sys.path.append(f"{os.pardir}/{os.pardir}")
        from ..instl_main import instl_own_main

        # config yaml such as stout-config.yaml with definitions needed for this function to work
        main_input_file = Path(config_vars["__CONFIG_FILE__"][0]).resolve()
        # other config files are assumed to exist below the folder where main_input_file is found
        main_config_folder = main_input_file.parent

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port

        waiting_list_redis_key = config_vars['WAITING_LIST_REDIS_KEY'].str()

        # heartbeat_redis_key: regular time stamps will be send to this key
        heartbeat_redis_key = config_vars.get("HEARTBEAT_COUNTER_REDIS_KEY", None).str()
        if heartbeat_redis_key:
            start_redis_heartbeat_thread(redis_host, redis_port, heartbeat_redis_key, 2.0)

        r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.report_instl_info_to_redis(r)
        trigger_keys_to_wait_on = (waiting_list_redis_key,)
        while True:
            self.print_wait_on_action_trigger_info(redis_host, redis_port, waiting_list_redis_key)
            r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), "waiting...")
            poped = r.brpop(trigger_keys_to_wait_on, timeout=30)
            if poped is not None:
                key = str(poped[0])
                value = str(poped[1])
                r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), value)

                log.info(f"popped key: {key}, value: {value}")

                match value:
                    case "stop":
                        log.info(f"received stop")
                        break
                    case "ping":
                        ping_redis_key = f"{key}:ping"
                        r.incr(ping_redis_key, 1)
                        log.info(f"ping incremented {ping_redis_key}")
                    case "reload-config-files":
                        log.info(f"reloading config files {config_vars['__CONFIG_FILE__'].list()}")
                        self.read_config_files(reset_previous=True)
                    case _:
                        with config_vars.push_scope_context(use_cache=True):
                            try:
                                what_to_do, domain, major_version, repo_rev = value.split(":")
                                instl_command_name = {'upload': "up2s3", 'up2s3': "up2s3", 'activate': "activate-repo-rev", "short-index": "up-short-index" }[what_to_do.lower()]
                                config_vars["TARGET_DOMAIN"] = domain
                                config_vars["TARGET_MAJOR_VERSION"] = major_version
                                config_vars["TARGET_REPO_REV"] = repo_rev
                                log.info(f"{key} triggered domain: {domain} major_version: {major_version} repo-rev {repo_rev}")
                                config_vars["TARGET_WORK_FOLDER"] = self.get_work_folder()

                                domain_major_version_config_folder = main_config_folder.joinpath(domain, major_version)
                                domain_major_version_config_file = domain_major_version_config_folder.joinpath("config.yaml")
                                up2s3_yaml_dict = {
                                    "__include__": [os.fspath(domain_major_version_config_file),
                                                    os.fspath(main_input_file)],
                                    'TARGET_DOMAIN': domain,
                                    'TARGET_MAJOR_VERSION': major_version,
                                    'TARGET_REPO_REV': repo_rev,
                                    'TARGET_WORK_FOLDER': config_vars["TARGET_WORK_FOLDER"].str(),
                                }
                                define_dict = aYaml.YamlDumpDocWrap(up2s3_yaml_dict,
                                                                    '!define', "definitions",
                                                                    explicit_start=True, sort_mappings=False)

                                work_config_file = config_vars["TARGET_WORK_FOLDER"].Path().joinpath(f"{instl_command_name}_{domain}_{major_version}_{repo_rev}.yaml")
                                with utils.utf8_open_for_write(work_config_file, "w") as wfd:
                                    aYaml.writeAsYaml(define_dict, wfd)

                                work_log_file = config_vars["TARGET_WORK_FOLDER"].Path().joinpath(f"{instl_command_name}_{domain}_{major_version}_{repo_rev}.log")
                                log_files = config_vars.get("OPEN_LOG_FILES", []).list()
                                log_files.append(work_log_file)
                                log_files = [os.fspath(log_file) for log_file in log_files]
                                mp_context = mp.get_context("spawn")
                                up2s3_process = mp_context.Process (target=instl_own_main,
                                                            name=f"{instl_command_name}_{domain}_{major_version}_{repo_rev}",
                                                            args=([str(config_vars["__INSTL_EXE_PATH__"]),
                                                                  instl_command_name,
                                                                   "--config-file", os.fspath(work_config_file),
                                                                   "--log", *log_files,
                                                                   "--db", ":file:",    # let instl will decide where the db file is placed
                                                                   "--run"],))

                                up2s3_process.start()
                                up2s3_process.join()

                            except Exception as ex:
                                log.info(f"Exception {ex} while handling {key} {value}")

            r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), "waiting...")
            time.sleep(2)
        log.info(f"stopped waiting on {trigger_keys_to_wait_on}")
        r.set(config_vars["IN_PROGRESS_REDIS_KEY"].str(), "stopped")

    def do_activate_repo_rev(self):

        redis_host = config_vars['REDIS_HOST'].str()  # redis-server ip
        redis_port = config_vars['REDIS_PORT'].int()  # redis-server port
        r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)

        try:

            config_vars['ACTIVATE_STATUS'] = "FAILED"
            config_vars['ACTIVATE_EXCEPTION'] = ""

            s3_resource = boto3.resource('s3')
            bucket_name = str(config_vars["S3_BUCKET_NAME"])
            repo_rev_file_specific_name = str(config_vars["REPO_REV_FILE_SPECIFIC_NAME"])  # file name for a specific repo-rev file e.g. V9_repo_rev.yaml.236
            repo_rev_file_specific_key = f"admin/{repo_rev_file_specific_name}"

            repo_rev_file_activated_name = str(config_vars["REPO_REV_FILE_BASE_NAME"])  # file name for activated repo-rev file e.g. V9_repo_rev.yaml
            repo_rev_file_activated_key = f"admin/{repo_rev_file_activated_name}"

            # find if the specific file exists in the admin folder of the bucket
            def is_file_in_s3(_s3_resource, _bucket_name, path_in_bucket):
                retVal = False
                try:
                    ls_response = _s3_resource.meta.client.list_objects_v2(Bucket=_bucket_name, Prefix=path_in_bucket)
                    list_of_files = ls_response['Contents']
                    for file in list_of_files:
                        if file["Key"] == path_in_bucket:
                            retVal = True
                            break
                except Exception:
                    pass
                return retVal

            if not is_file_in_s3(s3_resource, bucket_name, repo_rev_file_specific_key):
                raise FileNotFoundError(f"{repo_rev_file_specific_key} was not found in bucket {bucket_name}")

            # now copy the specific file to be the activated file, this is done directly on s3
            s3_resource.meta.client.copy({'Bucket': bucket_name, 'Key': repo_rev_file_specific_key},
                                         Bucket=bucket_name, Key=repo_rev_file_activated_key)
            log.info(f"activated repo-rev {config_vars['TARGET_REPO_REV']} for {config_vars['TARGET_MAJOR_VERSION']} on {config_vars['TARGET_DOMAIN']}")

            if not is_file_in_s3(s3_resource, bucket_name, repo_rev_file_activated_key):
                raise FileNotFoundError(f"{repo_rev_file_activated_key} was not found in bucket {bucket_name}")

            target_domain = config_vars["TARGET_DOMAIN"].str()
            major_version = config_vars["TARGET_MAJOR_VERSION"].str()
            target_repo_rev = config_vars["TARGET_REPO_REV"].int()
            work_folder = config_vars["TARGET_WORK_FOLDER"].Path()

            # download the activated file to the work folder for reference
            copy_of_activated_repo_rev_file_path = config_vars.resolve_str(f"{work_folder}/$(REPO_REV_FILE_BASE_NAME)")
            s3_resource.meta.client.download_file(Bucket=bucket_name, Key=repo_rev_file_activated_key, Filename=copy_of_activated_repo_rev_file_path)
            log.info(f"downloaded activated repo-rev file to {copy_of_activated_repo_rev_file_path}")
            with utils.utf8_open_for_read(copy_of_activated_repo_rev_file_path, "r") as rfd:
                repo_rev_file_text = rfd.read()
                match = re.search(r"^REPO_REV:\s+(?P<target_repo_rev>\d+)", repo_rev_file_text, flags=re.MULTILINE)
                if match:
                    actual_activated_repo_rev_from_s3 = int(match.group('target_repo_rev'))
                    if actual_activated_repo_rev_from_s3 == target_repo_rev:
                        log.info(f"verified activated repo-rev for {target_domain} {major_version} is {actual_activated_repo_rev_from_s3}")
                    else:
                        raise ValueError(f"activated repo-rev for {target_domain} {major_version} is {actual_activated_repo_rev_from_s3} not {target_repo_rev}")
                else:
                    raise ValueError(f"regex could find 'REPO_REV:' in {copy_of_activated_repo_rev_file_path}")

            r.hset(config_vars["ACTIVATE_REPO_REV_DONE_LIST_REDIS_KEY"].str(), config_vars["TARGET_REFERENCE"].str(), str(datetime.datetime.now()))
            r.set(config_vars["ACTIVATE_REPO_REV_CURRENT_REDIS_KEY"].str(), config_vars["TARGET_REPO_REV"].str())
            config_vars['ACTIVATE_STATUS'] = "Completed"

        except Exception as ex:
            config_vars['ACTIVATE_EXCEPTION'] = f"{ex}"
            print(f"do_activate_repo_rev exception {ex}")
            raise
        finally:
            self.send_email_from_template_file(config_vars["ACTIVATE_REPO_REV_EMAIL_TEMPLATE_PATH"].Path())

    def get_work_folder(self):
        """ calculate the path of the work folder for specific repo_rev/major_version/domain
            create the folder
            assign the path to configVar
        """

        repo_rev_work_folder = self.info_map_table.repo_rev_to_folder_hierarchy(config_vars["TARGET_REPO_REV"])
        work_folder: Path = config_vars["UPLOAD_WORK_AREA"].Path().joinpath(config_vars["TARGET_DOMAIN"].str(), config_vars["TARGET_MAJOR_VERSION"].str(), repo_rev_work_folder)
        with MakeDir(work_folder, report_own_progress=False) as md:
            md()
        return work_folder

    def send_email_from_template_file(self, path_to_template):
        work_folder = config_vars["TARGET_WORK_FOLDER"].Path()
        path_to_resolved = work_folder.joinpath(path_to_template.name)
        try:
            ResolveConfigVarsInFile(path_to_template, path_to_resolved)()
            utils.send_email_from_template_file(path_to_resolved)
        except Exception as ex:
            with open(path_to_resolved, "a") as wfd:
                wfd.write(f"\nFailed to send email\n{traceback.format_exc()}")

    def do_collect_manifests(self):
        @dataclass
        class ManifestItem:
            """ holds one IID collected from manifest.yaml files"""
            iid: str
            manifest_node: dict
            origin_path: Path
            top_level_tag: str = None  # Mac/Win/Common

        yaml_keys_order = config_vars["INDEX_YAML_CANONICAL_KEY_ORDER"].list()
        yaml_single_value_keys = config_vars["INDEX_YAML_SINGLE_VALUE_KEYS"].list()

        class ManifestYamlReader(ConfigVarYamlReader):
            """ overrides ConfigVarYamlReader to read manifest.yaml files
            """
            def __init__(self, config_vars):
                super().__init__(config_vars)
                self.manifest_nodes = defaultdict(list)

            def init_specific_doc_readers(self):
                ConfigVarYamlReader.init_specific_doc_readers(self)
                self.specific_doc_readers["__no_tag__"] = self.manifest_node_reader
                self.specific_doc_readers['tag:yaml.org,2002:map'] = self.manifest_node_reader # standalone manifest files will be identified by this tag
                self.specific_doc_readers["!index"] = self.manifest_node_reader

            def manifest_node_reader(self, the_node, *args, **kwargs):
                for a_node_name, a_node_value in the_node.items():
                    if a_node_name.startswith("template"):
                        continue
                    yaml_node_as_dict = aYaml.nodeToPy(a_node_value, order=yaml_keys_order, single_value=yaml_single_value_keys, preserve_tags=True)
                    top_level_tag = kwargs.get("top_level_tag", None)
                    item = ManifestItem(a_node_name, yaml_node_as_dict, self.file_read_stack[-1], top_level_tag)
                    self.manifest_nodes[a_node_name].append(item)

        folders_to_search_for_manifests = [Path(f) for f in config_vars["COLLECT_MANIFESTS_DIR"].list()]
        reader = ManifestYamlReader(config_vars)
        num_files = 0
        for manifests_folder in folders_to_search_for_manifests:
            for top_level_dir in sorted(manifests_folder.glob("*")):
                if top_level_dir.is_dir() and not top_level_dir.name.startswith('.'):
                    top_level_tag = top_level_dir.name
                    for root, dirs, files in os.walk(top_level_dir, followlinks=False):
                        dirs.sort()  # to be idempotent, so folders will always be scanned in the same order
                        for a_file in sorted(files):
                            a_file_path = Path(root, a_file)
                            if a_file_path.name.endswith("manifest.yaml") and not a_file_path.name.startswith("."):
                                print(a_file_path)
                                reader.read_yaml_file(a_file_path, top_level_tag=top_level_tag)
                                num_files += 1
                # add manifest.yaml's if they are on the top level too
                # not sure is top_level_tag will be appropriate
                elif top_level_dir.is_file() and top_level_dir.name.endswith("manifest.yaml") and not top_level_dir.name.startswith("."):
                    top_level_tag = manifests_folder.name
                    print(top_level_dir)
                    reader.read_yaml_file(top_level_dir, top_level_tag=top_level_tag)
                    num_files += 1

        manifest_nodes = reader.manifest_nodes
        num_singles = 0
        num_duplicates = 0
        num_different = 0
        diffs_dict = dict()
        filtered_manifest_nodes = {key: value for key, value in manifest_nodes.items() if key.endswith("_IID")}

        for iid, content_list in filtered_manifest_nodes.items():
            match len(content_list):
                case 1:
                    num_singles += 1
                    content_list[0].top_level_tag = "Common"
                case 2:
                    num_duplicates += 1
                    the_diff = list(dictdiffer.diff(content_list[0].manifest_node, content_list[1].manifest_node, ignore=['top_level_tag']))
                    if the_diff:
                        num_different += 1
                        # they are different so merge them
                        merged = smart_merge_dicts({content_list[0].top_level_tag: content_list[0].manifest_node,
                                           content_list[1].top_level_tag: content_list[1].manifest_node})
                        merged = dict_in_canonical_order(merged, order=yaml_keys_order, single_value=yaml_single_value_keys)

                        content_list[0].manifest_node = merged
                        content_list[0].top_level_tag = "Common"
                        print(f"unified {iid}")
                    else:
                        # they are the same so take the first one
                        content_list[0].top_level_tag = "Common"
                    del content_list[1]
                case _:
                    print(f"IID {iid} found in more than 2 files")
                    for item in content_list:
                        print(f"    {item.origin_path}")
                    filtered_manifest_nodes[iid].clear()

        print(f"scanned {num_files}, found {len(filtered_manifest_nodes)} distinct IIDs")
        print(f"{num_singles} singles, {num_duplicates} duplicates, {num_different} dup and different")

        all_manifests = {"Common": dict(), "Mac": dict(), "Win": dict()}
        for iid, content_list in filtered_manifest_nodes.items():
            for contents in content_list:
                all_manifests[contents.top_level_tag][iid] = contents.manifest_node

        collect_manifests_results_path = config_vars["COLLECT_MANIFESTS_RESULTS_PATH"].Path()

        if "__OUTPUT_FORMAT__" in config_vars:
            config_vars["COLLECT_MANIFESTS_FORMAT"] = "$(__OUTPUT_FORMAT__)"
        output_format = config_vars.get("COLLECT_MANIFESTS_FORMAT", "yaml").str()
        match output_format:
            case "yaml":
                self.write_collected_manifests_yaml(collect_manifests_results_path, all_manifests)
            case "json":
                self.write_collected_manifests_json(collect_manifests_results_path, all_manifests)

    def write_collected_manifests_yaml(self, out_manifests_file, all_manifests):
        with open(out_manifests_file, "w") as wfd:
            try:
                base_index_path = config_vars["COLLECT_MANIFESTS_BASE_INDEX"].Path()
                wfd.write(base_index_path.read_text())  # copy the index_base.yaml verbatim
            except:
                pass
            wfd.write("\n# below are IIDs collected from manifest.yaml files\n\n")
            if all_manifests["Common"]:
                aYaml.writeAsYaml(aYaml.YamlDumpDocWrap(all_manifests["Common"], tag="!index", sort_mappings=True),
                                  wfd, top_level_blank_line=True)
            if all_manifests["Mac"]:
                aYaml.writeAsYaml(aYaml.YamlDumpDocWrap(all_manifests["Mac"], tag="!index_Mac", sort_mappings=True),
                                  wfd,
                                  top_level_blank_line=True)
            if all_manifests["Win"]:
                aYaml.writeAsYaml(aYaml.YamlDumpDocWrap(all_manifests["Win"], tag="!index_Win", sort_mappings=True),
                                  wfd,
                                  top_level_blank_line=True)
        print(f"collected manifests written to: {out_manifests_file}")

    def write_collected_manifests_json(self, out_manifests_file, all_manifests):
        item_list = list()
        for section, mani_list in all_manifests.items():
            for iid, a_node in mani_list.items():
                item = {"IID": iid}
                if not a_node:
                    print(f"no node for iid {iid}")
                    continue
                if 'name' in a_node:
                    item['name'] = a_node['name']
                if 'version' in a_node:
                    item['version'] = a_node['version']
                if 'guid' in a_node:
                    item['guid'] = a_node['guid']
                item_list.append(item)
                if 'depends' in a_node:
                    depends = [{'IID': iid} for iid in a_node['depends']]
                    item['_children'] = depends

        with open(out_manifests_file, "w") as wfd:
            wfd.write(json.dumps(item_list, indent=1, default=utils.extra_json_serializer))
