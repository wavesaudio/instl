from typing import List
from .batchCommands import *


class If(PythonBatchCommandBase, essential=True):
    """ preform an action based on a condition
        if 'condition' is True 'if_true' will be preformed
        if 'condition' is False 'if_false' will be preformed
        either if_true or if_false can be omitted
    """
    def __init__(self, condition, if_true=None, if_false=None,**kwargs) -> None:
        super().__init__(**kwargs)
        self.condition = condition
        self.if_true = if_true
        self.if_false = if_false
        # Ignoring if_true/if_false - In case there's an error with one of the functions, the json will issue a serialization error
        self.non_representative__dict__keys.extend(('if_true', 'if_false'))

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(repr(self.condition))
        if self.if_true is not None:
            all_args.append(f"if_true={repr(self.if_true)}")
        if self.if_false is not None:
            all_args.append(f"if_false={repr(self.if_false)}")

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        condition = self.condition
        if isinstance(condition, str):
            condition = eval(condition)

        if callable(condition):
            condition = condition()
        else:
            condition = bool(condition)

        if condition:
            if callable(self.if_true):
                self.doing = f"""condition is True calling '{repr(self.if_true)}'"""
                self.if_true()
        else:
            if callable(self.if_false):
                self.doing = f"""condition is False calling '{repr(self.if_false)}'"""
                self.if_false()


class IsFile(object):
    """ return True if 'file_path' is a file
        can be used as 'condition' for If
    """
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
    """ return True if 'file_path' is a folder
        can be used as 'condition' for If
    """
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
    """ return True if 'file_path' is a symbolic link
        can be used as 'condition' for If
    """
    def __init__(self, file_path):
        self.file_path = file_path

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_string(self.file_path))

    def __call__(self):
        retVal = Path(self.file_path).is_symlink()
        return retVal

    def __eq__(self, other):
        retVal = self.file_path == other.file_path
        return retVal


class IsEq(object):
    """ return True if left_thing equals right_thing
        can be used as 'condition' for If
    """
    def __init__(self, left_thing, right_thing):
        self.left_thing = left_thing
        self.right_thing = right_thing

    def __repr__(self):
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_if_string(self.left_thing)}, {utils.quoteme_raw_if_string(self.right_thing)})'''
        return the_repr

    def __call__(self):
        retVal = self.left_thing == self.right_thing
        return retVal
