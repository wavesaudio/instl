#!/usr/bin/env python3.12
"""ActivateFrameController (the Activate command tab, including the redis-backed
repo-rev table) extracted verbatim from pyinstl/instlGui.py.

Pure structural decomposition: code MOVED verbatim, no logic changes.
"""
from tkinter import *
from tkinter.ttk import *
from tkinter import messagebox
import functools
import logging
from collections import defaultdict
log = logging.getLogger()

import utils
from configVar import config_vars

from ._frame_base import FrameController
from ._tkvars import TkConfigVarStr, TkConfigVarInt


class ActivateFrameController(FrameController):
    def __init__(self, instl_obj):
        super().__init__("Activate", instl_obj)
        self.tk_vars["REDIS_HOST"] = TkConfigVarStr("REDIS_HOST")
        self.tk_vars["REDIS_PORT"] = TkConfigVarInt("REDIS_PORT")
        self.tk_vars["ACTIVATE_CONFIG_FILE"] = TkConfigVarStr("ACTIVATE_CONFIG_FILE")
        self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"] = TkConfigVarStr("DOMAIN_REPO_TO_ACTIVATE")
        #todo oren - ??
        self.tk_vars["DOMAIN_REPO_TO_UPLOAD"] = TkConfigVarStr("DOMAIN_REPO_TO_UPLOAD")
        self.tk_vars["IN_PROGRESS_VALUE"] = TkConfigVarStr("IN_PROGRESS_VALUE")
        self.tk_vars["HEARTBEAT_VALUE"] = TkConfigVarStr("HEARTBEAT_VALUE")

        self.tk_vars["REDIS_KEY_VALUE_1"] = TkConfigVarStr("REDIS_KEY_VALUE_1")
        self.tk_vars["REPO_REV_TO_ACTIVATE"] = TkConfigVarStr("REPO_REV_TO_ACTIVATE")
        # todo oren - ??
        self.tk_vars["REPO_REV_TO_UPLOAD"] = TkConfigVarStr("REPO_REV_TO_UPLOAD")
        self.tk_vars["REDIS_KEY_VALUE_2"] = TkConfigVarStr("REDIS_KEY_VALUE_2")
        self.redis_conn: utils.redisClient.RedisClient = None
        self.update_redis_table_working_id = None
        self.last_heartbeat_value = ""
        self.heartbeat_no_diff_counter = 0

    def read_activate_config_files(self):
        for config_file_var in ("ACTIVATE_CONFIG_FILE", ):
            config_path = config_vars.get(config_file_var, None).Path()
            if config_path:
                if config_path.is_file():
                    config_vars[ "__SEARCH_PATHS__"].clear() # so __include__ file will not be found on old paths
                    self.instl_obj.read_yaml_file(config_path)
                else:
                    log.info(f"""File not found: {config_path}""")

    def update_state(self, *args, **kwargs):
        super().update_state(*args, **kwargs)
        self.read_activate_config_files()

        host = config_vars.get("REDIS_HOST", "").str()
        port = config_vars.get("REDIS_PORT", 0).int()

        if self.redis_conn is not None:
            if self.redis_conn.host != host or self.redis_conn.port != port:
                self.stop_update_redis_table()
                log.info(f"disconnected from redis host: {self.redis_conn.host}, port: {self.redis_conn.port}")
                self.redis_conn.close()
                self.redis_conn = None
        if self.redis_conn is None and host and port:
            self.redis_conn = utils.redisClient.RedisClient(host, port)
            log.info(f"connected to redis host: {self.redis_conn.host}, port: {self.redis_conn.port}")
            self.start_update_redis_table()

    def update_redis_table(self):
        if self.redis_conn is not None:
            unified_dict = defaultdict(dict)

            active_repo_rev_keys = self.redis_conn.keys(str(config_vars["ACTIVATE_REPO_REV_WILDCARD"]))
            for active_repo_rev_key in active_repo_rev_keys:
                active_repo_rev_value = self.redis_conn.get(active_repo_rev_key)
                splited = active_repo_rev_key.split(":")
                domain = splited[1]
                major_version = splited[2]
                if major_version not in unified_dict[domain]:
                    unified_dict[domain][major_version] = dict()
                unified_dict[domain][major_version]['activated'] = active_repo_rev_value

            last_uploaded_repo_rev_keys = self.redis_conn.keys(str(config_vars["UPLOAD_REPO_REV_WILDCARD"]))
            for last_uploaded_repo_rev_key in last_uploaded_repo_rev_keys:
                last_uploaded_repo_rev_value = self.redis_conn.get(last_uploaded_repo_rev_key)
                splited = last_uploaded_repo_rev_key.split(":")
                domain = splited[1]
                major_version = splited[2]
                if major_version not in unified_dict[domain]:
                    unified_dict[domain][major_version] = dict()
                unified_dict[domain][major_version]['uploaded'] = last_uploaded_repo_rev_value

            current_items = list(self.tree.get_children())
            for domain_key, domain_dict in unified_dict.items():
                for major_version_key, major_version_dict in domain_dict.items():
                    activated = major_version_dict.get('activated', "N/A")
                    uploaded = major_version_dict.get('uploaded', "N/A")
                    item_id = f"{domain_key}:{major_version_key}"
                    if item_id in current_items:
                        self.tree.item(item_id, text=domain_key, values=(major_version_key, uploaded, activated))
                        current_items.remove(item_id)
                    else:
                        self.tree.insert('', 'end', item_id, text=domain_key, values=(major_version_key, uploaded, activated))

            # clean leftovers
            for left_over_id in current_items:
                self.tree.delete(left_over_id)

            focused_item = self.tree.focus()
            if focused_item != self.prev_focused_item:
                if focused_item:
                    focused_item_values = self.tree.item(focused_item)
                    new_value = ":".join((focused_item_values['text'], str(focused_item_values['values'][0])))
                    self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"].set(new_value)
                    self.tk_vars["DOMAIN_REPO_TO_UPLOAD"].set(new_value)
                    uploaded_rep_rev = focused_item_values['values'][1]
                    activated_rep_rev = int(focused_item_values['values'][2])
                    self.tk_vars["REPO_REV_TO_ACTIVATE"].set(uploaded_rep_rev)
                    self.tk_vars["REPO_REV_TO_UPLOAD"].set(uploaded_rep_rev)
                self.prev_focused_item = focused_item


            heartbeat_redis_key = config_vars['HEARTBEAT_COUNTER_REDIS_KEY'].str()
            heartbeat_value = config_vars['HEARTBEAT_VALUE'] = self.redis_conn.get(heartbeat_redis_key)
            if heartbeat_value == self.last_heartbeat_value:
                self.heartbeat_no_diff_counter += 1
            else:
                self.last_heartbeat_value = heartbeat_value
                self.heartbeat_no_diff_counter = 0

            if self.heartbeat_no_diff_counter > 10:
                config_vars['IN_PROGRESS_VALUE'] = f"Looks dead"
            else:
                in_progress_redis_key = config_vars['IN_PROGRESS_REDIS_KEY'].str()
                in_progress_value = self.redis_conn.get(in_progress_redis_key)
                config_vars['IN_PROGRESS_VALUE'] = in_progress_value

            self.update_redis_table_working_id = None
            self.start_update_redis_table()
        else:
            log.info(f"update_redis_table: no redis connection")

    def start_update_redis_table(self):
        if not self.update_redis_table_working_id:
            self.update_redis_table_working_id = self.instl_obj.notebook.after(1500, self.update_redis_table)
            #log.info("update_redis_table STARTEd")

    def stop_update_redis_table(self):
        if self.update_redis_table_working_id:
            self.instl_obj.notebook.after_cancel(self.update_redis_table_working_id)
            self.update_redis_table_working_id = None
            #log.info("update_redis_table STOPPEd")

    def activate_repo_rev(self): #oren todo - add something simmilar for upload SI-300
        try:
            if self.redis_conn:
                current_items = self.tree.get_children()
                domain_repo = self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"].get()
                if domain_repo in current_items:
                    host = self.redis_conn.host
                    repo_rev = self.tk_vars["REPO_REV_TO_ACTIVATE"].get()
                    redis_value = config_vars.resolve_str(":".join(('activate', domain_repo, str(repo_rev))))
                    redis_key   = config_vars.resolve_str(":".join(("$(REDIS_KEYS_PREFIX)", host, "waiting_list")))
                    answer = messagebox.askyesno("Activate repo-rev", f"Activate repo-rev {repo_rev} on {domain_repo} ?")
                    if answer:
                        self.redis_conn.lpush(redis_key, redis_value)
        except Exception as ex:
            print(f"activate_repo_rev exception {ex}")

    def upload_repo_rev(self): #oren todo - add something simmilar for upload SI-300
        try:
            if self.redis_conn:
                current_items = self.tree.get_children()
                domain_repo = self.tk_vars["DOMAIN_REPO_TO_UPLOAD"].get()
                if domain_repo in current_items:
                    host = self.redis_conn.host
                    repo_rev = self.tk_vars["REPO_REV_TO_UPLOAD"].get()
                    redis_value = config_vars.resolve_str(":".join(('up2s3', domain_repo, str(repo_rev))))
                    redis_key   = config_vars.resolve_str(":".join(("$(REDIS_KEYS_PREFIX)", host, "waiting_list")))
                    answer = messagebox.askyesno("Upload repo-rev", f"upload repo-rev {repo_rev} on {domain_repo} ?")
                    if answer:
                        self.redis_conn.lpush(redis_key, redis_value)
        except Exception as ex:
            print(f"upload_repo_rev exception {ex}")

    def remove_redis_key(self, key_config_var, value_config_var=None):
        key_to_remove = config_vars[key_config_var].str()
        self.redis_conn.delete(key_to_remove)
        if value_config_var is not None:
            self.tk_vars[value_config_var].set("")

    def lpush_redis_key(self, key_config_var, value_config_var):
        key_to_set = config_vars[key_config_var].str()
        value_to_push = config_vars[value_config_var].str()
        self.redis_conn.lpush(key_to_set, value_to_push)

    def get_redis_key(self, key_config_var, result_config_var):
        key_to_get = config_vars[key_config_var].str()
        value = self.redis_conn.get(key_to_get)
        if value is None:
            value = "UNKNOWN KEY"
        config_vars[result_config_var] = value

    def set_redis_key(self, key_config_var, value_config_var):
        key_to_set = config_vars[key_config_var].str()
        value_to_set = config_vars[value_config_var].str()
        self.redis_conn.set(key_to_set, value_to_set)

    def create_frame(self, master):  # ActivateFrameController
        super().create_frame(master)

        self.frame = Frame(master)

        curr_row = 0
        self.tk_vars["ACTIVATE_CONFIG_FILE"].set_trace_write_callback(functools.partial(self.update_state, who="ACTIVATE_CONFIG_FILE"))
        self.create_line_for_file(curr_row=curr_row, curr_column=0, label="Server config:", var_name="ACTIVATE_CONFIG_FILE", locate=True, edit=True, check=True, columnspan=3, label_stick=W)

        curr_row += 1
        Label(self.frame, text="Host:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["REDIS_HOST"]).grid(row=curr_row, column=1, sticky=W)

        curr_row += 1
        Label(self.frame, text="Port:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["REDIS_PORT"]).grid(row=curr_row, column=1, sticky=W)

        curr_row += 1
        Label(self.frame, text="Doing:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["IN_PROGRESS_VALUE"]).grid(row=curr_row, column=1, columnspan=1, sticky=W)
        Label(self.frame, text="Heartbeat:").grid(row=curr_row, column=2)
        Label(self.frame, textvariable=self.tk_vars["HEARTBEAT_VALUE"]).grid(row=curr_row, column=3, columnspan=1, sticky=E)

        curr_row += 1
        self.tree = Treeview(self.frame, columns=('major version', 'uploaded', 'activated'))
        self.tree.column('major version', width=100, anchor='center')
        self.tree.heading('major version', text='Major Version')
        self.tree.column('uploaded', width=100, anchor='center')
        self.tree.heading('uploaded', text='Uploaded')
        self.tree.column('activated', width=100, anchor='center')
        self.tree.heading('activated', text='Activated')
        self.tree.grid(row=curr_row, column=0, columnspan=4, sticky=W)

        curr_row += 1
        Label(self.frame, text="Repository:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["DOMAIN_REPO_TO_ACTIVATE"]).grid(row=curr_row, column=1, columnspan=1, sticky=W)

        Label(self.frame, text="rep-rev:").grid(row=curr_row, column=2, sticky=E)
        Entry(self.frame, textvariable=self.tk_vars["REPO_REV_TO_ACTIVATE"]).grid(row=curr_row, column=3, columnspan=1, sticky=W + E)
        Button(self.frame, width=7, text="Activate", command=self.activate_repo_rev).grid(row=curr_row, column=4, columnspan=1, sticky="E")

        curr_row += 1
        Label(self.frame, text="Repository:").grid(row=curr_row, column=0, sticky=W)
        Label(self.frame, textvariable=self.tk_vars["DOMAIN_REPO_TO_UPLOAD"]).grid(row=curr_row, column=1,
                                                                                     columnspan=1, sticky=W)

        Label(self.frame, text="rep-rev:").grid(row=curr_row, column=2, sticky=E)
        Entry(self.frame, textvariable=self.tk_vars["REPO_REV_TO_UPLOAD"]).grid(row=curr_row, column=3, columnspan=1,
                                                                                  sticky=W + E)
        Button(self.frame, width=7, text="Upload", command=self.upload_repo_rev).grid(row=curr_row, column=4,
                                                                                          columnspan=1, sticky="E")

        self.prev_focused_item = None

        return self.frame
