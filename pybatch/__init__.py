import sys

from .batchCommands import PythonBatchCommandBase, RunProcessBase
from .batchCommandAccum import PythonBatchCommandAccum

from .conditionalBatchCommands import If
from .conditionalBatchCommands import IsFile
from .conditionalBatchCommands import IsDir
from .conditionalBatchCommands import IsSymlink

from .copyBatchCommands import CopyDirContentsToDir
from .copyBatchCommands import CopyDirToDir
from .copyBatchCommands import CopyFileToDir
from .copyBatchCommands import CopyFileToFile
from .copyBatchCommands import MoveDirToDir

from .reportingBatchCommands import AnonymousAccum
from .reportingBatchCommands import Echo
from .reportingBatchCommands import Progress
from .reportingBatchCommands import Remark
from .reportingBatchCommands import Stage
from .reportingBatchCommands import ConfigVarAssign
from .reportingBatchCommands import PythonVarAssign
from .reportingBatchCommands import PythonBatchRuntime
from .reportingBatchCommands import RaiseException

from .batchCommands import AppendFileToFile
from .batchCommands import Cd
from .batchCommands import ChFlags
from .batchCommands import Chmod
from .batchCommands import Chown
from .batchCommands import MakeDirs
from .batchCommands import MakeRandomDirs
from .batchCommands import RmDir
from .batchCommands import RmFile
from .batchCommands import RmFileOrDir
from .batchCommands import RunProcessBase
from .batchCommands import touch
from .batchCommands import Touch
from .batchCommands import Unlock

from .subprocessBatchCommands import ParallelRun
from .subprocessBatchCommands import ShellCommands
from .subprocessBatchCommands import ShellCommand

from .wtarBatchCommands import Wtar, Unwtar, Wzip, Unwzip

from .info_mapBatchCommands import CheckDownloadFolderChecksum
from .info_mapBatchCommands import SetExecPermissionsInSyncFolder
from .info_mapBatchCommands import CreateSyncFolders

from .svnBatchCommands import SVNClient

if sys.platform == "win32":
    from .batchCommandsWinOnly import WinShortcut
    from .batchCommandsWinOnly import BaseRegistryKey
    from .batchCommandsWinOnly import ReadRegistryValue
    from .batchCommandsWinOnly import CreateRegistryKey
    from .batchCommandsWinOnly import CreateRegistryValues
    from .batchCommandsWinOnly import DeleteRegistryKey
    from .batchCommandsWinOnly import DeleteRegistryValues

if sys.platform == "darwin":
    from .batchCommandsMacOnly import CreateSymlink
    from .batchCommandsMacOnly import CreateSymlinkFilesInFolder
    from .batchCommandsMacOnly import MacDock
    from .batchCommandsMacOnly import ResolveSymlinkFilesInFolder
    from .batchCommandsMacOnly import SymlinkFileToSymlink
    from .batchCommandsMacOnly import SymlinkToSymlinkFile

from .new_batchCommands import *


def EvalShellCommand(action_str, message):
    """ shell commands from index can be evaled to a PythonBatchCommand, otherwise a ShellCommand is instantiated
    """
    retVal = Echo(message)
    try:
        retVal = eval(action_str, globals(), locals())
        if not isinstance(retVal, PythonBatchCommandBase):  # if action_str is a quoted string an str object is created
            raise TypeError(f"{retVal} is not PythonBatchCommandBase")
        retVal.remark = f"""eval'ed {message}"""
    except (SyntaxError, TypeError, NameError) as ex:
        retVal = ShellCommand(action_str, message)
    return retVal
