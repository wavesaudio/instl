import sys

from .batchCommands import PythonBatchCommandBase
from .batchCommandAccum import batch_repr
from .batchCommandAccum import PythonBatchCommandAccum

from .rsyncClone import CopyDirContentsToDir
from .rsyncClone import CopyDirToDir
from .rsyncClone import CopyFileToDir
from .rsyncClone import CopyFileToFile

from .reportingBatchCommands import Echo
from .reportingBatchCommands import Progress
from .reportingBatchCommands import Remark
from .reportingBatchCommands import Section
from .reportingBatchCommands import VarAssign

from .batchCommands import AppendFileToFile
from .batchCommands import Cd
from .batchCommands import ChFlags
from .batchCommands import Chmod
from .batchCommands import Chown
from .batchCommands import MakeDirs
from .batchCommands import MakeRandomDirs
from .batchCommands import ParallelRun
from .batchCommands import RmDir
from .batchCommands import RmFile
from .batchCommands import RmFileOrDir
from .batchCommands import RunProcessBase
from .batchCommands import ShellCommands
from .batchCommands import SingleShellCommand
from .batchCommands import touch
from .batchCommands import Touch
from .batchCommands import Unlock

from .wtarBatchCommands import Wtar, Unwtar, Wzip, Unwzip

from .info_mapBatchCommands import CheckDownloadFolderChecksum
from .info_mapBatchCommands import SetDownloadFolderExec
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

from .rsyncClone import RsyncClone
from .new_batchCommands import *
