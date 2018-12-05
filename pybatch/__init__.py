import sys

from .baseClasses import PythonBatchCommandBase
from .subprocessBatchCommands import RunProcessBase
from .batchCommandAccum import PythonBatchCommandAccum

from .conditionalBatchCommands import If
from .conditionalBatchCommands import IsFile
from .conditionalBatchCommands import IsDir
from .conditionalBatchCommands import IsSymlink
from .conditionalBatchCommands import IsEq
from .conditionalBatchCommands import IsNotEq

from .copyBatchCommands import CopyDirContentsToDir
from .copyBatchCommands import CopyDirToDir
from .copyBatchCommands import CopyFileToDir
from .copyBatchCommands import CopyFileToFile
from .copyBatchCommands import MoveDirToDir
from .copyBatchCommands import RenameFile

from .reportingBatchCommands import AnonymousAccum
from .reportingBatchCommands import Echo
from .reportingBatchCommands import Progress
from .reportingBatchCommands import Remark
from .reportingBatchCommands import Stage
from .reportingBatchCommands import ConfigVarAssign
from .reportingBatchCommands import ConfigVarPrint
from .reportingBatchCommands import PythonVarAssign
from .reportingBatchCommands import PythonBatchRuntime
from .reportingBatchCommands import RaiseException
from .reportingBatchCommands import PythonDoSomething
from .reportingBatchCommands import ResolveConfigVarsInFile

from .removeBatchCommands import RmDir
from .removeBatchCommands import RmFile
from .removeBatchCommands import RmFileOrDir
from .removeBatchCommands import RemoveEmptyFolders
from .removeBatchCommands import RmGlob
from .removeBatchCommands import RmGlobs

from .fileSystemBatchCommands import AppendFileToFile
from .fileSystemBatchCommands import Cd
from .fileSystemBatchCommands import ChFlags
from .fileSystemBatchCommands import Chmod
from .fileSystemBatchCommands import Chown
from .fileSystemBatchCommands import MakeDirs
from .fileSystemBatchCommands import MakeRandomDirs
from .fileSystemBatchCommands import MakeRandomDataFile
from .fileSystemBatchCommands import touch
from .fileSystemBatchCommands import Touch
from .fileSystemBatchCommands import Unlock
from .fileSystemBatchCommands import Ls
from .fileSystemBatchCommands import FileSizes

from .subprocessBatchCommands import ParallelRun
from .subprocessBatchCommands import ShellCommands
from .subprocessBatchCommands import ShellCommand
from .subprocessBatchCommands import CUrl
from .subprocessBatchCommands import ScriptCommand
from .subprocessBatchCommands import Exec

from .wtarBatchCommands import Wtar, Unwtar, Wzip, Unwzip

from .info_mapBatchCommands import CheckDownloadFolderChecksum
from .info_mapBatchCommands import SetExecPermissionsInSyncFolder
from .info_mapBatchCommands import CreateSyncFolders

from .svnBatchCommands import SVNClient
from .svnBatchCommands import SVNLastRepoRev
from .svnBatchCommands import SVNCheckout
from .svnBatchCommands import SVNInfo
from .svnBatchCommands import SVNPropList

if sys.platform == "win32":
    from .WinOnlyBatchCommands import WinShortcut
    from .WinOnlyBatchCommands import BaseRegistryKey
    from .WinOnlyBatchCommands import ReadRegistryValue
    from .WinOnlyBatchCommands import CreateRegistryKey
    from .WinOnlyBatchCommands import CreateRegistryValues
    from .WinOnlyBatchCommands import DeleteRegistryKey
    from .WinOnlyBatchCommands import DeleteRegistryValues
    from .WinOnlyBatchCommands import ResHacker

if sys.platform == "darwin":
    from .MacOnlyBatchCommands import CreateSymlink
    from .MacOnlyBatchCommands import RmSymlink
    from .MacOnlyBatchCommands import CreateSymlinkFilesInFolder
    from .MacOnlyBatchCommands import MacDock
    from .MacOnlyBatchCommands import ResolveSymlinkFilesInFolder
    from .MacOnlyBatchCommands import SymlinkFileToSymlink
    from .MacOnlyBatchCommands import SymlinkToSymlinkFile

from .new_batchCommands import *


def EvalShellCommand(action_str: str, message: str) -> PythonBatchCommandBase:
    """ shell commands from index can be evaled to a PythonBatchCommand, otherwise a ShellCommand is instantiated
    """
    retVal = Echo(message)
    try:
        retVal = eval(action_str, globals(), locals())
        if not isinstance(retVal, PythonBatchCommandBase):  # if action_str is a quoted string an str object is created
            raise TypeError(f"{retVal} is not PythonBatchCommandBase")
        #retVal.remark = f"""evaled {message}"""
    except (SyntaxError, TypeError, NameError) as ex:
        retVal = ShellCommand(action_str, message)
    return retVal
