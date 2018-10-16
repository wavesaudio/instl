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
        condition_obj = self.condition
        if isinstance(condition_obj, str):
            condition = eval(condition_obj)
        else:
            condition = condition_obj

        if callable(condition):
            condition_result = condition()
        else:
            condition_result = bool(condition)

        if condition_result:
            to_do_obj = self.if_true
        else:
            to_do_obj = self.if_false

        if callable(to_do_obj):
            self.doing = f"""condition is {condition_result} calling '{repr(to_do_obj)}'"""
            if isinstance(to_do_obj, PythonBatchCommandBase) and to_do_obj.is_context_manager:
                to_do_obj.own_progress_count = 0
                with to_do_obj as it:
                    it()
            else:
                to_do_obj()


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
        left = self.left_thing
        if isinstance(left, str):
            left = os.path.expandvars(left)

        right = self.right_thing
        if isinstance(right, str):
            right = os.path.expandvars(right)

        retVal = left == right
        return retVal


class IsNotEq(IsEq):
    """ return True if left_thing is not equals to right_thing
        can be used as 'condition' for If
    """
    def __init__(self, left_thing, right_thing):
        super().__init__(left_thing, right_thing)

    def __call__(self):
        retVal = not super().__call__()
        return retVal
