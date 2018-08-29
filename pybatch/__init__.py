import sys

from .batchCommands import PythonBatchCommandBase
from .batchCommandAccum import PythonBatchCommandAccum

from .copyBatchCommands import CopyDirContentsToDir
from .copyBatchCommands import CopyDirToDir
from .copyBatchCommands import CopyFileToDir
from .copyBatchCommands import CopyFileToFile

from .reportingBatchCommands import AnonymousAccum
from .reportingBatchCommands import Echo
from .reportingBatchCommands import Progress
from .reportingBatchCommands import Remark
from .reportingBatchCommands import Section
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

if sys.platform == "win32":
    from .batchCommandsWinOnly import WinShortcut

if sys.platform == "darwin":
    from .batchCommandsMacOnly import CreateSymlink
    from .batchCommandsMacOnly import CreateSymlinkFilesInFolder
    from .batchCommandsMacOnly import MacDock
    from .batchCommandsMacOnly import ResolveSymlinkFilesInFolder
    from .batchCommandsMacOnly import SymlinkFileToSymlink
    from .batchCommandsMacOnly import SymlinkToSymlinkFile

from .new_batchCommands import *
