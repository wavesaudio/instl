from typing import List
import re
import io
from configVar import config_vars
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase


class SVNClient(RunProcessBase):
    def __init__(self, command, **kwargs) -> None:
        super().__init__(**kwargs)
        self.command = command

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_single(self.command))

    def progress_msg_self(self) -> str:
        return f''''''

    def get_run_args(self, run_args) -> None:
        run_args.append(config_vars.get("SVN_CLIENT_PATH", "svn").str())
        run_args.append(self.command)


class SVNLastRepoRev(SVNClient):
    """ get the last repository revision from a url to SVN repository
        the result is placed in a configVar
        :url_param: url to svn repository
        :reply_param: the name of the configVar where the last repository revision is placed
    """
    revision_line_re = re.compile("^Revision:\s+(?P<revision>\d+)$")

    def __init__(self, url_param, reply_param, **kwargs):
        super().__init__("info", **kwargs)
        self.url_param = url_param
        self.reply_param = reply_param

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_single(self.url_param))
        all_args.append(utils.quoteme_single(self.reply_param))

    def get_run_args(self, run_args) -> None:
        super().get_run_args(run_args)
        url = config_vars[self.url_param]
        run_args.append(url)

    def handle_completed_process(self, completed_process):
        info_as_io = io.StringIO(utils.unicodify(completed_process.stdout))
        for line in info_as_io:
            match = self.revision_line_re.match(line)
            if match:
                last_repo_rev = int(match["revision"])
                break
        else:
            raise ValueError(f"Could not find last repo rev for {self.url_param}")
        config_vars["__LAST_REPO_REV__"] = str(last_repo_rev)
