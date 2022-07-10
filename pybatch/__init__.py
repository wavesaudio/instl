import sys

from .baseClasses import PythonBatchCommandBase
from .batchCommandAccum import PythonBatchCommandAccum
from .conditionalBatchCommands import If, IsFile, IsDir, IsSymlink, IsEq, IsNotEq, IsConfigVarEq, IsConfigVarNotEq, \
    IsEnvironVarEq, IsEnvironVarNotEq, IsConfigVarDefined, ForInConfigVar
from .copyBatchCommands import CopyDirContentsToDir, CopyDirToDir, CopyFileToDir, CopyFileToFile, MoveDirToDir, \
    RenameFile, CopyBundle, CopyGlobToDir
from .downloadBatchCommands import DownloadFileAndCheckChecksum, DownloadManager
from .fileSystemBatchCommands import AppendFileToFile, Cd, ChFlags, Chmod, Chown, MakeDir, MakeRandomDirs, \
    MakeRandomDataFile, touch, Touch, Unlock, Ls, FileSizes, SplitFile, FixAllPermissions, Glober
from .info_mapBatchCommands import CheckDownloadFolderChecksum, SetExecPermissionsInSyncFolder, CreateSyncFolders, \
    InfoMapFullWriter, InfoMapSplitWriter, SetBaseRevision, IndexYamlReader, CopySpecificRepoRev, CreateRepoRevFile, \
    ShortIndexYamlCreator
from .removeBatchCommands import RmDir, RmFile, RmFileOrDir, RemoveEmptyFolders, RmGlob, RmGlobs, RmDirContents
from .reportingBatchCommands import AnonymousAccum, Echo, Progress, Remark, Stage, ConfigVarAssign, ConfigVarPrint, \
    PythonVarAssign, PythonBatchRuntime, RaiseException, PythonDoSomething, ResolveConfigVarsInFile, ResolveConfigVarsInYamlFile, \
    ReadConfigVarsFromFile, ReadConfigVarValueFromTextFile, EnvironVarAssign, PatchPyBatchWithTimings, Print
from .subprocessBatchCommands import ParallelRun, ShellCommands, ShellCommand, CUrl, ScriptCommand, Exec, RunInThread, \
    Subprocess, ExternalPythonExec, SysExit, Raise, KillProcess
from .svnBatchCommands import SVNClient, SVNLastRepoRev, SVNCheckout, SVNInfo, SVNPropList, SVNAdd, SVNRemove, \
    SVNInfoReader, SVNSetProp, SVNDelProp, SVNCleanup
from .wtarBatchCommands import Wtar, Unwtar, Wzip, Unwzip
from .shutdownBatchCommands import Shutdown
# from .fileSystemBatchCommands import AdvisoryFileLock

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

    #Added for test purposes, without those classes verify_actions gives false positives/negatives
    class PythonBatchCommandDummy(PythonBatchCommandBase):
        def __init__(self, *args, **kwargs) -> None:
            pass
        def __call__(self, *args, **kwargs) -> None:
            pass
        def progress_msg_self(self, *args, **kwargs):
            pass

    class WinShortcut(PythonBatchCommandDummy):
        pass

    class CreateRegistryValues(PythonBatchCommandDummy):
        pass

    class ReadRegistryValue(PythonBatchCommandDummy):
        pass

    class CreateRegistryKey(PythonBatchCommandDummy):
        pass

    class DeleteRegistryKey(PythonBatchCommandDummy):
        pass

    class DeleteRegistryValues(PythonBatchCommandDummy):
        pass

    class ResHackerCompileResource(PythonBatchCommandDummy):#??
        pass


from .new_batchCommands import *


def EvalShellCommand(action_str: str, message: str, python_batch_names=None, raise_on_error=False) -> PythonBatchCommandBase:
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
                if raise_on_error:
                    raise ValueError()
                else:
                    log.warning(f"""'{action_str}' was evaled as ShellCommand not as python batch""")

    return retVal
