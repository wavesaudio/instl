from .pythonBatchCommands import *


class AppendFileToFile(PythonBatchCommandBase):
    def __init__(self, source_file, target_file):

        append_command = " ".join(("cat", utils.quoteme_double(source_file), ">>", utils.quoteme_double(target_file)))
