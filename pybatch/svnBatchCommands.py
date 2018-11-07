from typing import List
import re
import io
from configVar import config_vars
from .baseClasses import *
from .subprocessBatchCommands import RunProcessBase


class SVNClient(RunProcessBase, kwargs_defaults={"url": None, "depth": "infinity", "repo_rev": -1}):
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
        run_args.append(self.url_with_repo_rev())
        run_args.append("--depth")
        run_args.append(self.depth)

    def url_with_repo_rev(self):
        if self.repo_rev == -1:
            retVal = self.url
        else:
            retVal = f"{self.url}@{self.repo_rev}"
        return retVal


class SVNLastRepoRev(SVNClient, kwargs_defaults={"depth": "empty"}):
    """ get the last repository revision from a url to SVN repository
        the result is placed in a configVar
        :url_param: url to svn repository
        :reply_config_var: the name of the configVar where the last repository revision is placed
    """
    revision_line_re = re.compile("^Revision:\s+(?P<revision>\d+)$")

    def __init__(self, **kwargs):
        super().__init__("info", **kwargs)

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def get_run_args(self, run_args) -> None:
        super().get_run_args(run_args)
        run_args.append(self.url)

    def handle_completed_process(self, completed_process):
        info_as_io = io.StringIO(utils.unicodify(completed_process.stdout))
        for line in info_as_io:
            match = self.revision_line_re.match(line)
            if match:
                last_repo_rev = int(match["revision"])
                break
        else:
            raise ValueError(f"Could not find last repo rev for {self.url}")
        if self.reply_config_var:
            config_vars[self.reply_config_var] = str(last_repo_rev)


class SVNCheckout(SVNClient):

    def __init__(self,where, **kwargs):
        super().__init__("checkout", **kwargs)
        self.where = where

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(self.named__init__param("where", os.fspath(self.where)))

    def get_run_args(self, run_args) -> None:
        super().get_run_args(run_args)
        run_args.append(self.url_with_repo_rev())
        run_args.append(self.where)
        run_args.append("--depth")
        run_args.append(self.depth)


class SVNInfo(SVNClient):

    def __init__(self, out_file, **kwargs):
        super().__init__("info", **kwargs)
        self.out_file = out_file

    def repr_own_args(self, all_args: List[str]) -> None:
        pass

    def get_run_args(self, run_args) -> None:
        super().get_run_args(run_args)
        run_args.append(self.url_with_repo_rev())
        run_args.append("--depth")
        run_args.append(self.depth)
