#!/usr/bin/env python3.12


class InstlException(Exception):
    def __init__(self, in_message, in_original_exception=None) -> None:
        super().__init__(in_message)
        self.original_exception = in_original_exception


class InstlFatalException(Exception):
    def __init__(self, *messages) -> None:
        super().__init__()
        self.message = " ".join([str(mess) for mess in messages])

    def __str__(self):
        return self.message
