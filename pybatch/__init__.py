import sys

from .batchCommands import PythonBatchCommandBase
from .batchCommandAccum import PythonBatchCommandAccum
from .batchCommandAccum import batch_repr

from .copyBatchCommands import CopyDirContentsToDir
from .copyBatchCommands import CopyDirToDir
from .copyBatchCommands import CopyFileToDir
from .copyBatchCommands import CopyFileToFile

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
from .batchCommands import Section
from .batchCommands import SingleShellCommand
from .batchCommands import ShellCommands
from .batchCommands import touch
from .batchCommands import Touch
from .batchCommands import Unlock
from .batchCommands import VarAssign

from .wtarBatchCommands import Wtar, Unwtar, Wzip, Unwzip

from .info_mapBatchCommands import CheckDownloadFolderChecksum

if sys.platform == "win32":
    from .batchCommandsWinOnly import WinShortcut

if sys.platform == "darwin":
    from .batchCommandsMacOnly import MacDock
    from .batchCommandsMacOnly import CreateSymlink
    from .batchCommandsMacOnly import SymlinkToSymlinkFile
    from .batchCommandsMacOnly import SymlinkFileToSymlink
    from .batchCommandsMacOnly import CreateSymlinkFilesInFolder
    from .batchCommandsMacOnly import ResolveSymlinkFilesInFolder

from .new_batchCommands import *
