#!/usr/bin/env python3.12
"""pyinstl.admin package.

This package is the result of a pure structural decomposition (extract-module
refactor) of the former god-object pyinstl/instlAdmin.py. The InstlAdmin class
implementation is split across focused mixin submodules and composed here. No
behavior was changed: method names, signatures and emitted output are identical.

The original module pyinstl/instlAdmin.py is kept as a thin shim that re-exports
the same public surface from this package.
"""
from ..instlInstanceBase import InstlInstanceBase

from ._helpers import (
    start_redis_heartbeat_thread,
    smart_merge_dicts,
    dict_in_canonical_order,
)
from ._core import _CoreAdminMixin
from ._repo import _RepoAdminMixin
from ._wtar import _WtarAdminMixin
from ._verify import _VerifyAdminMixin
from ._info import _InfoAdminMixin
from ._publish import _PublishAdminMixin


# noinspection PyPep8,PyPep8,PyPep8
class InstlAdmin(_CoreAdminMixin,
                 _RepoAdminMixin,
                 _WtarAdminMixin,
                 _VerifyAdminMixin,
                 _InfoAdminMixin,
                 _PublishAdminMixin,
                 InstlInstanceBase):

    def __init__(self, initial_vars) -> None:
        super().__init__(initial_vars)
        self.total_self_progress = 1000
        self.read_defaults_file(super().__thisclass__.__name__)
        self.fields_relevant_to_info_map = ('path', 'flags', 'revision', 'checksum', 'size')
        self.config_vars_stack_size_before_reading_config_files = None
        self.wait_info_counter = 0  # incremented when printing wait info
        self.compile_exclude_regexi()
