from .batchCommands import *


class If(PythonBatchCommandBase, essential=True):
    def __init__(self, condition, if_true=None, if_false=None,**kwargs) -> None:
        super().__init__(**kwargs)
        self.condition = condition
        self.if_true = if_true
        self.if_false = if_false

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}('''
        params = []
        params.append(repr(self.condition))
        if self.if_true is not None:
            params.append(f"if_true={repr(self.if_true)}")
        if self.if_false is not None:
            params.append(f"if_false={repr(self.if_false)}")
        params_text = ", ".join(filter(None, params))
        if params_text:
            the_repr += params_text
        the_repr += ")"
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        condition = self.condition
        if callable(condition):
            condition = condition()
        if condition:
            if callable(self.if_true):
                self.if_true()
        else:
            if callable(self.if_false):
                self.if_false()


class IsFile(object):
    def __init__(self, file_path):
        self.file_path = file_path

    def __repr__(self):
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.file_path)})'''
        return the_repr

    def __call__(self):
        retVal = Path(self.file_path).is_file()
        return retVal

    def __eq__(self, other):
        retVal = self.file_path == other.file_path
        return retVal


class IsDir(object):
    def __init__(self, file_path):
        self.file_path = file_path

    def __repr__(self):
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.file_path)})'''
        return the_repr

    def __call__(self):
        retVal = Path(self.file_path).is_dir()
        return retVal

    def __eq__(self, other):
        retVal = self.file_path == other.file_path
        return retVal


class IsSymlink(object):
    def __init__(self, file_path):
        self.file_path = file_path

    def __repr__(self):
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.file_path)})'''
        return the_repr

    def __call__(self):
        retVal = Path(self.file_path).is_symlink()
        return retVal

    def __eq__(self, other):
        retVal = self.file_path == other.file_path
        return retVal
