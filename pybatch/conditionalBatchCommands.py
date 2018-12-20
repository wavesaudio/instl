from typing import List
from .fileSystemBatchCommands import *
from configVar import config_vars


class If(PythonBatchCommandBase, essential=True):
    """ preform an action based on a condition
        if 'condition' is True 'if_true' will be preformed
        if 'condition' is False 'if_false' will be preformed
        either if_true or if_false can be omitted
    """
    def __init__(self, condition, if_true=None, if_false=None, **kwargs) -> None:
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
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_by_type(self.file_path)})'''
        return the_repr

    def __call__(self) -> bool:
        retVal = Path(self.file_path).is_file()
        return retVal

    def __eq__(self, other) -> bool:
        retVal = self.file_path == other.file_path
        return retVal


class IsDir(object):
    """ return True if 'file_path' is a folder
        can be used as 'condition' for If
    """
    def __init__(self, file_path):
        self.file_path = file_path

    def __repr__(self):
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_by_type(self.file_path)})'''
        return the_repr

    def __call__(self) -> bool:
        retVal = Path(self.file_path).is_dir()
        return retVal

    def __eq__(self, other) -> bool:
        retVal = self.file_path == other.file_path
        return retVal


class IsSymlink(object):
    """ return True if 'file_path' is a symbolic link
        can be used as 'condition' for If
    """
    def __init__(self, file_path):
        self.file_path = file_path

    def repr_own_args(self, all_args: List[str]) -> None:
        all_args.append(utils.quoteme_raw_by_type(self.file_path))

    def __call__(self) -> bool:
        retVal = Path(self.file_path).is_symlink()
        return retVal

    def __eq__(self, other) -> bool:
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
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_by_type(self.left_thing)}, {utils.quoteme_raw_if_string(self.right_thing)})'''
        return the_repr

    def __call__(self) -> bool:
        left = self.left_thing
        if isinstance(left, str):
            left = os.path.expandvars(left)

        right = self.right_thing
        if isinstance(right, str):
            right = os.path.expandvars(right)

        retVal = left == right
        return retVal

    def __eq__(self, other) -> bool:
        # is one IsEq equal to another?
        retVal = self.left_thing == other.left_thing and self.right_thing == other.right_thing
        return retVal


class IsNotEq(IsEq):
    """ return True if left_thing is not equals to right_thing
        can be used as 'condition' for If
    """
    def __init__(self, left_thing, right_thing):
        super().__init__(left_thing, right_thing)

    def __call__(self) -> bool:
        retVal = not super().__call__()
        return retVal


class IsConfigVarEq:
    """ return True if value of a configVar equals the expected value, False otherwise.
        if configVar is not defined expected_value is compared to default_value,
        unless default_value is None in which case False is returned
    """
    def __init__(self, var_name, expected_value, default_value=None) -> None:
        self.var_name = var_name
        self.expected_value = expected_value
        self.default_value = default_value

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.var_name)}, {utils.quoteme_raw_string(self.expected_value)}'''
        if self.default_value is not None:
            the_repr += f", {utils.quoteme_raw_string(self.default_value)}"
        the_repr += ")"
        return the_repr

    def __call__(self, *args, **kwargs) -> bool:
        if self.var_name in config_vars:
            retVal = str(config_vars[self.var_name]) == str(self.expected_value)
        elif self.default_value is not None:
            retVal = str(self.default_value) == str(self.expected_value)
        else:
            retVal = True
        return retVal

    def __eq__(self, other) -> bool:
        # is one IsConfigVarEq equal to another?
        retVal = self.var_name == other.var_name and \
                self.expected_value == other.expected_value and \
                self.default_value == other.default_value
        return retVal


class IsConfigVarNotEq(IsConfigVarEq):
    """ return False if value of a configVar equals the expected value, True otherwise.
        if configVar is not defined expected_value is compared to default_value,
        unless default_value is None in which case True is returned
    """
    def __init__(self, var_name, expected_value, default_value=None) -> None:
        super().__init__(var_name, expected_value, default_value)

    def __call__(self) -> bool:
        retVal = not super().__call__()
        return retVal


class IsEnvironVarEq:
    """ return True if value of an environment variable equals the expected value, False otherwise.
        if environment variable is not defined expected_value is compared to default_value,
        unless default_value is None in which case False is returned
    """
    def __init__(self, var_name, expected_value, default_value=None) -> None:
        self.var_name = var_name
        self.expected_value = expected_value
        self.default_value = default_value

    def __repr__(self) -> str:
        the_repr = f'''{self.__class__.__name__}({utils.quoteme_raw_string(self.var_name)}, {utils.quoteme_raw_string(self.expected_value)}'''
        if self.default_value is not None:
            the_repr += f", {utils.quoteme_raw_string(self.default_value)}"
        the_repr += ")"
        return the_repr

    def __call__(self, *args, **kwargs) -> bool:
        if self.var_name in os.environ:
            retVal = str(os.environ[self.var_name]) == str(self.expected_value)
        elif self.default_value is not None:
            retVal = str(self.default_value) == str(self.expected_value)
        else:
            retVal = True
        return retVal

    def __eq__(self, other) -> bool:
        # is one IsEnvironVarEq equal to another?
        retVal = self.var_name == other.var_name and \
                self.expected_value == other.expected_value and \
                self.default_value == other.default_value
        return retVal


class IsEnvironVarNotEq(IsEnvironVarEq):
    """ return False if value of an environment variable equals the expected value, True otherwise.
        if environment variable is not defined expected_value is compared to default_value,
        unless default_value is None in which case True is returned
    """
    def __init__(self, var_name, expected_value, default_value=None) -> None:
        super().__init__(var_name, expected_value, default_value)

    def __call__(self) -> bool:
        retVal = not super().__call__()
        return retVal

