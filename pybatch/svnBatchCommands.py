from typing import List
from configVar import config_vars
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase


class SVNClient(RunProcessBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(**kwargs)
        self.svn_args = args

    def repr_own_args(self, all_args: List[str]) -> None:
        for arg in self.svn_args:
            all_args.append(utils.quoteme_raw_if_string(arg))

    def progress_msg_self(self) -> str:
        return f''''''

    def create_run_args(self):
        svn_client = config_vars.get("SVN_CLIENT_PATH", "svn").str()
        run_args = [svn_client] + list(self.svn_args)
        return run_args
