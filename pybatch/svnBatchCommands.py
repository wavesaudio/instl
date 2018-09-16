from configVar import config_vars
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase


class SVNClient(RunProcessBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(**kwargs)
        self.svn_args = args

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}(*{utils.quoteme_raw_if_list(self.svn_args)})'''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def create_run_args(self):
        svn_client = config_vars.get("SVN_CLIENT_PATH", "svn").str()
        run_args = [svn_client] + list(self.svn_args)
        return run_args
