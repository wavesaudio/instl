import keyword

import utils
from .baseClasses import *


class Section(PythonBatchCommandBase, essential=False, empty__call__=True):
    def __init__(self, *titles):
        super().__init__()
        self.titles = titles

    def __repr__(self):
        if len(self.titles) == 1:
            quoted_titles = utils.quoteme_double(self.titles[0])
        else:
            quoted_titles = ", ".join((utils.quoteme_double(title) for title in self.titles))
        the_repr = f"""{self.__class__.__name__}({quoted_titles})"""
        return the_repr

    def repr_batch_win(self):
        retVal = list()
        retVal.append(f"""echo section: {self.self.titles}""")
        return retVal

    def repr_batch_mac(self):
        retVal = list()
        retVal.append(f"""echo section: {self.self.titles}""")
        return retVal

    def progress_msg_self(self):
        the_progress_msg = f'''{", ".join((utils.quoteme_double(title) for title in self.titles))} ...'''
        return the_progress_msg

    def __call__(self, *args, **kwargs):
        pass


class Progress(PythonBatchCommandBase, essential=False, empty__call__=True):
    """
        just issue a progress message
    """
    def __init__(self, message, **kwargs) -> None:
        kwargs['is_context_manager'] = False
        super().__init__(**kwargs)
        self.message = message

    def __repr__(self) -> str:
        the_repr = f'''print(r"progress: x of y: {self.message}")'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class Echo(PythonBatchCommandBase, essential=False, empty__call__=True):
    """
        just issue a (non progress) message
    """
    def __init__(self, message, **kwargs) -> None:
        kwargs['is_context_manager'] = False
        super().__init__(**kwargs)
        self.message = message

    def __repr__(self) -> str:
        the_repr = f'''print("{self.message}")'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class Remark(PythonBatchCommandBase, essential=False, empty__call__=True):
    """
        write a remark in code
    """
    def __init__(self, remark, **kwargs) -> None:
        kwargs['is_context_manager'] = False
        super().__init__(**kwargs)
        self.remark = remark

    def __repr__(self) -> str:
        the_repr = f'''# {self.remark}'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass


class VarAssign(PythonBatchCommandBase, essential=False, empty__call__=True):
    """
        configVar assignment as python variable
    """
    def __init__(self, var_name, *var_values, **kwargs) -> None:
        kwargs['is_context_manager'] = False
        super().__init__(**kwargs)
        assert var_name.isidentifier(), f"{var_name} is not a valid identifier"
        assert not keyword.iskeyword(var_name), f"{var_name} is not a python key word"
        self.var_name = var_name
        self.var_values = var_values

    def __repr__(self) -> str:
        the_repr = ""
        if any(self.var_values):
            adjusted_values = list()
            for val in self.var_values:
                try:
                    adjusted_values.append(int(val))
                except:
                    adjusted_values.append(utils.quoteme_raw_string(val))
            if len(adjusted_values) == 1:
                the_repr = f'''{self.var_name} = {adjusted_values[0]}'''
            else:
                values = "".join(('(', ", ".join(str(adj) for adj in adjusted_values), ')'))
                the_repr = f'''{self.var_name} = {values}'''
        else:
            the_repr = f'''{self.var_name} = ""'''
        return the_repr

    def repr_batch_win(self) -> str:
        the_repr = f''''''
        return the_repr

    def repr_batch_mac(self) -> str:
        the_repr = f''''''
        return the_repr

    def progress_msg_self(self) -> str:
        return f''''''

    def __call__(self, *args, **kwargs) -> None:
        pass
