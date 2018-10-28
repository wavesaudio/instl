from typing import List
from configVar import config_vars
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase


class SVNClient(RunProcessBase):
    def __init__(self, command, *args, **kwargs) -> None:
        super().__init__(**kwargs)
        self.command = command

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.command)

    def progress_msg_self(self) -> str:
        return f''''''

    def create_run_args(self):
        svn_client = config_vars.get("SVN_CLIENT_PATH", "svn").str()
        run_args = [svn_client] + list(self.svn_args)
        return run_args


class SVNLastRepoRev(SVNClient):
    def __init__(self, url_param, reply_param, *args, **kwargs):
        self.url_param = url_param
        self.reply_param = reply_param

    def create_run_args(self):
        svn_client = config_vars.get("SVN_CLIENT_PATH", "svn").str()
        command = "info"
        url = config_vars[self.url_param]
        run_args = list()
        run_args.append(svn_client)
        run_args.append(command)
        run_args.append(url)
        return run_args
