"""Root pytest conftest.

Force a deterministic import order for two packages that participate in a
circular import.

`pyinstl/curlHelper.py` runs `from pybatch import *` at module top level.
Several `pybatch` submodules in turn import `pyinstl.download*`, which makes
the `pybatch` package the first to start importing along that chain. When
`pybatch` is imported first, `curlHelper`'s star-import executes while
`pybatch` is only partially initialized, so names defined later in
`pybatch/__init__` (e.g. `Progress`) never get bound into the `curlHelper`
namespace. That produced an order-dependent
`NameError: name 'Progress' is not defined` in the download-promotion tests
during a full-suite run (they pass in isolation, where `pyinstl` is imported
first).

Importing `pyinstl.curlHelper` here, before any test module is collected,
makes `curlHelper` the entry point of the chain: `pybatch` then finishes
initializing before the star-import binds, so every name is present. This is
a test-harness-only ordering shim and does not change application behavior.
"""

import pyinstl.curlHelper  # noqa: F401
