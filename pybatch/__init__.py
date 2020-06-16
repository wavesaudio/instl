import sys


from .baseClasses import PythonBatchCommandBase
from .batchCommandAccum import PythonBatchCommandAccum

from .conditionalBatchCommands import If
from .conditionalBatchCommands import IsFile
from .conditionalBatchCommands import IsDir
from .conditionalBatchCommands import IsSymlink
from .conditionalBatchCommands import IsEq
from .conditionalBatchCommands import IsNotEq
from .conditionalBatchCommands import IsConfigVarEq
from .conditionalBatchCommands import IsConfigVarNotEq
from .conditionalBatchCommands import IsEnvironVarEq
from .conditionalBatchCommands import IsEnvironVarNotEq
from .conditionalBatchCommands import IsConfigVarDefined

from .copyBatchCommands import CopyDirContentsToDir
from .copyBatchCommands import CopyDirToDir
from .copyBatchCommands import CopyFileToDir
from .copyBatchCommands import CopyFileToFile
from .copyBatchCommands import MoveDirToDir
from .copyBatchCommands import RenameFile
from .copyBatchCommands import CopyBundle
from .copyBatchCommands import CopyGlobToDir

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
from .reportingBatchCommands import ReadConfigVarsFromFile
from .reportingBatchCommands import ReadConfigVarValueFromTextFile
from .reportingBatchCommands import EnvironVarAssign
from .reportingBatchCommands import PatchPyBatchWithTimings
from .reportingBatchCommands import Print

from .removeBatchCommands import RmDir
from .removeBatchCommands import RmFile
from .removeBatchCommands import RmFileOrDir
from .removeBatchCommands import RemoveEmptyFolders
from .removeBatchCommands import RmGlob
from .removeBatchCommands import RmGlobs
from .removeBatchCommands import RmDirContents

from .fileSystemBatchCommands import AppendFileToFile
from .fileSystemBatchCommands import Cd
from .fileSystemBatchCommands import ChFlags
from .fileSystemBatchCommands import Chmod
from .fileSystemBatchCommands import Chown
from .fileSystemBatchCommands import MakeDir
from .fileSystemBatchCommands import MakeRandomDirs
from .fileSystemBatchCommands import MakeRandomDataFile
from .fileSystemBatchCommands import touch
from .fileSystemBatchCommands import Touch
from .fileSystemBatchCommands import Unlock
from .fileSystemBatchCommands import Ls
from .fileSystemBatchCommands import FileSizes
from .fileSystemBatchCommands import SplitFile
from .fileSystemBatchCommands import FixAllPermissions

from .subprocessBatchCommands import ParallelRun
from .subprocessBatchCommands import ShellCommands
from .subprocessBatchCommands import ShellCommand
from .subprocessBatchCommands import CUrl
from .subprocessBatchCommands import ScriptCommand
from .subprocessBatchCommands import Exec
from .subprocessBatchCommands import RunInThread
from .subprocessBatchCommands import Subprocess
from .subprocessBatchCommands import ExternalPythonExec
from .subprocessBatchCommands import SysExit
from .subprocessBatchCommands import Raise
from .subprocessBatchCommands import KillProcess

from .wtarBatchCommands import Wtar, Unwtar, Wzip, Unwzip

from .info_mapBatchCommands import CheckDownloadFolderChecksum
from .info_mapBatchCommands import SetExecPermissionsInSyncFolder
from .info_mapBatchCommands import CreateSyncFolders
from .info_mapBatchCommands import InfoMapFullWriter
from .info_mapBatchCommands import InfoMapSplitWriter
from .info_mapBatchCommands import SetBaseRevision
from .info_mapBatchCommands import IndexYamlReader
from .info_mapBatchCommands import CopySpecificRepoRev
from .info_mapBatchCommands import CreateRepoRevFile
from .info_mapBatchCommands import ShortIndexYamlCreator

from .svnBatchCommands import SVNClient
from .svnBatchCommands import SVNLastRepoRev
from .svnBatchCommands import SVNCheckout
from .svnBatchCommands import SVNInfo
from .svnBatchCommands import SVNPropList
from .svnBatchCommands import SVNAdd
from .svnBatchCommands import SVNRemove
from .svnBatchCommands import SVNInfoReader
from .svnBatchCommands import SVNSetProp
from .svnBatchCommands import SVNDelProp
from .svnBatchCommands import SVNCleanup

from .downloadBatchCommands import DownloadFileAndCheckChecksum

if sys.platform == "win32":
    from .WinOnlyBatchCommands import WinShortcut
    from .WinOnlyBatchCommands import BaseRegistryKey
    from .WinOnlyBatchCommands import ReadRegistryValue
    from .WinOnlyBatchCommands import CreateRegistryKey
    from .WinOnlyBatchCommands import CreateRegistryValues
    from .WinOnlyBatchCommands import DeleteRegistryKey
    from .WinOnlyBatchCommands import DeleteRegistryValues
    from .WinOnlyBatchCommands import ResHackerAddResource
    from .WinOnlyBatchCommands import ResHackerCompileResource
    from .WinOnlyBatchCommands import FullACLForEveryone

if sys.platform == "darwin":
    from .MacOnlyBatchCommands import CreateSymlink
    from .MacOnlyBatchCommands import RmSymlink
    from .MacOnlyBatchCommands import CreateSymlinkFilesInFolder
    from .MacOnlyBatchCommands import MacDock
    from .MacOnlyBatchCommands import ResolveSymlinkFilesInFolder
    from .MacOnlyBatchCommands import SymlinkFileToSymlink
    from .MacOnlyBatchCommands import SymlinkToSymlinkFile

from .new_batchCommands import *


def EvalShellCommand(action_str: str, message: str, python_batch_names=None) -> PythonBatchCommandBase:
    """ shell commands from index can be evaled to a PythonBatchCommand, otherwise a ShellCommand is instantiated
    """
    retVal = Echo(message)
    try:
        retVal = eval(action_str, globals(), locals())
        if not isinstance(retVal, PythonBatchCommandBase):  # if action_str is a quoted string an str object is created
            raise TypeError(f"{retVal} is not PythonBatchCommandBase")
    except (SyntaxError, TypeError, NameError) as ex:
        retVal = ShellCommand(action_str, message)
        # check that it's not a pybatch command
        if python_batch_names:
            assumed_command_name = action_str[:action_str.find('(')]
            if assumed_command_name in python_batch_names:
                log.warning(f"""'{action_str}' was evaled as ShellCommand not as python batch""")

    return retVal
