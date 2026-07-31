import sys

from .baseClasses import PythonBatchCommandBase
from .batchCommandAccum import PythonBatchCommandAccum
from .conditionalBatchCommands import If, IsFile, IsDir, IsSymlink, IsEq, IsNotEq, IsConfigVarEq, IsConfigVarNotEq, \
    IsEnvironVarEq, IsEnvironVarNotEq, IsConfigVarDefined, ForInConfigVar
from .copyBatchCommands import CopyDirContentsToDir, CopyDirToDir, CopyFileToDir, CopyFileToFile, MoveDirToDir, \
    RenameFile, CopyBundle, CopyGlobToDir, MoveFileToDir
from .downloadBatchCommands import DownloadFileAndCheckChecksum, DownloadManager
from .fileSystemBatchCommands import AppendFileToFile, Cd, ChFlags, Chmod, Chown, MakeDir, MakeRandomDirs, \
    MakeRandomDataFile, touch, Touch, Unlock, Ls, FileSizes, SplitFile, FixAllPermissions, Glober
from .info_mapBatchCommands import CheckDownloadFolderChecksum, PrepareDownloadTempFiles, ReportDownloadStarted, ReportDownloadState, SetExecPermissionsInSyncFolder, CreateSyncFolders, \
    InfoMapFullWriter, InfoMapSplitWriter, SetBaseRevision, IndexYamlReader, CopySpecificRepoRev, CreateRepoRevFile, \
    ShortIndexYamlCreator
from .removeBatchCommands import RmDir, RmFile, RmFileOrDir, RemoveEmptyFolders, RmGlob, RmGlobs, RmDirContents
from .reportingBatchCommands import AnonymousAccum, Echo, Progress, Remark, Stage, ConfigVarAssign, ConfigVarPrint, \
    PythonVarAssign, PythonBatchRuntime, RaiseException, PythonDoSomething, ResolveConfigVarsInFile, \
    ResolveConfigVarsInYamlFile, \
    ReadConfigVarsFromFile, ReadConfigVarValueFromTextFile, EnvironVarAssign, PatchPyBatchWithTimings, Print, FailIfFileNotFound
from .subprocessBatchCommands import ParallelRun, ShellCommands, ShellCommand, CUrl, ScriptCommand, Exec, RunInThread, \
    Subprocess, ExternalPythonExec, SysExit, Raise, KillProcess, CurlWithInternalParallel
from .svnBatchCommands import SVNClient, SVNLastRepoRev, SVNCheckout, SVNInfo, SVNPropList, SVNAdd, SVNRemove, \
    SVNInfoReader, SVNSetProp, SVNDelProp, SVNCleanup
from .wtarBatchCommands import Wtar, Unwtar, Wzip, Unwzip, ZipFlat, UnZip

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

if sys.platform in ("darwin", "linux"):
    from .POSIXBatchCommands import CreateSymlink
    from .POSIXBatchCommands import RmSymlink
    from .POSIXBatchCommands import CreateSymlinkFilesInFolder
    from .POSIXBatchCommands import ResolveSymlinkFilesInFolder
    from .POSIXBatchCommands import SymlinkFileToSymlink
    from .POSIXBatchCommands import SymlinkToSymlinkFile

    #Added for test purposes, without those classes verify_actions gives false positives/negatives
    # also to avoid syntax error messages when running on linux
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

if sys.platform == "darwin":
    from .MacOnlyBatchCommands import MacDock

from .new_batchCommands import *


def EvalShellCommand(action_str: str, message: str, python_batch_names=None, raise_on_error=False) -> PythonBatchCommandBase:
    """ Turn an *action string* from the index into a PythonBatchCommand object.

        This is the deserialization counterpart of the ``repr()`` serializer: an
        ``action`` declared in a Central-authored index (e.g. ``MakeDir(r"x")``)
        is ``eval()``-ed here against the ``pybatch`` package namespace to
        re-materialize the typed command object. If the string is NOT a valid
        pybatch constructor call (SyntaxError / TypeError / NameError) it is
        treated as a raw shell command and wrapped in ``ShellCommand`` instead.

        ATTACK SURFACE / TRUST MODEL (documented):
          * ``action_str`` is trusted input: it originates from the index that
            Central generates, not from end users. ``eval`` here is the same
            trust boundary as ``exec``-ing the emitted batch file.
          * ``eval`` is given ``globals()`` (the pybatch command namespace) and
            ``locals()`` (this function's frame). The ``locals()`` exposure is
            historical and slightly wider than necessary; tightening it could
            change which strings evaluate successfully, so it is deliberately
            left unchanged: narrowing it needs a golden-verified change, not an
            edit here.
          * A bare quoted string ``"foo"`` evals to a ``str`` (not a command);
            the ``isinstance`` check below converts that case to a ShellCommand.
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
