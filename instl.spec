# -*- mode: python -*-

import os
import sys
import fnmatch
import platform
import socket
import datetime

block_cipher = None


a = Analysis(['instl'],
             pathex=['instl'],
             binaries=None,
             datas=None,
             hiddenimports=[],
             hookspath=None,
             runtime_hooks=None,
             excludes=['PyQt4', 'matplotlib',
                        "PIL", "numpy", "wx", "tornado", "networkx",
                         "pygraphviz", "unittest", "nose",
                         "Tkinter", "scipy", "setuptools", "distutils"],
             win_no_prefer_redirects=None,
             win_private_assemblies=None,
             cipher=block_cipher)

instl_defaults_path = os.path.join("defaults")
for defaults_file in os.listdir(instl_defaults_path):
    if fnmatch.fnmatch(defaults_file, '*.yaml'):
        a.datas += [("defaults/"+defaults_file, os.path.join(instl_defaults_path, defaults_file), "DATA")]

compile_info_path = os.path.join("build", "compile-info.yaml")
with open(compile_info_path, "w") as wfd:
    wfd.write(
"""
--- !define_const
__COMPILATION_TIME__: {}
__SOCKET_HOSTNAME__: {}
__PLATFORM_NODE__: {}
__PYTHON_COMPILER__: PyInstaller-3.0
""".format(str(datetime.datetime.now()), socket.gethostname(), platform.node()))
a.datas += [("defaults/compile-info.yaml", compile_info_path, "DATA")]

instl_help_path = os.path.join("help")
for help_file in os.listdir(instl_help_path):
    if fnmatch.fnmatch(help_file, '*.yaml'):
        a.datas += [("help/"+help_file, os.path.join(instl_help_path, help_file), "DATA")]



pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='instl',
          debug=False,
          strip=None,
          upx=True,
          console=True )
