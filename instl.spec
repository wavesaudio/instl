# -*- mode: python -*-
# -*- coding: utf-8 -*-

import os
import sys
import fnmatch
import platform
import socket
import datetime
import re
from subprocess import check_output

block_cipher = None

a = Analysis(['instl'],
             pathex=['instl'],
             binaries=None,
             datas=None,
             hiddenimports=['distutils', 'six','packaging', 'packaging.version', 'packaging.specifiers', 'packaging.requirements', 'xmltodict'],
             hookspath=None,
             runtime_hooks=None,
             excludes=['PyQt4', 'matplotlib', "PIL", "numpy", "wx", "tornado", "networkx",
                         "pygraphviz", "unittest", "nose", 'PyInstaller',
                        "tkinter", "Tkinter", "scipy", "setuptools", "colorama"],
             win_no_prefer_redirects=None,
             win_private_assemblies=None,
             cipher=block_cipher)

instl_defaults_path = os.path.join("defaults")
for defaults_file in os.listdir(instl_defaults_path):
    if fnmatch.fnmatch(defaults_file, '*.yaml') or fnmatch.fnmatch(defaults_file, '*.ddl'):
        a.datas += [("defaults/"+defaults_file, os.path.join(instl_defaults_path, defaults_file), "DATA")]


git_branch = check_output(["git", "rev-parse", "--symbolic-full-name", "--abbrev-ref", "HEAD"]).decode('utf-8')

PyInstallerVersion =  re.split(r'[~\\/]+', HOMEPATH)[-1]

compile_info_path = os.path.join("build", "compile-info.yaml")
with open(compile_info_path, "w", encoding='utf-8') as wfd:
    wfd.write(
"""
--- !define_const
__COMPILATION_TIME__: {}
__SOCKET_HOSTNAME__: {}
__PLATFORM_NODE__: {}
__PYTHON_COMPILER__: {}
__GITHUB_BRANCH__: {}
""".format(str(datetime.datetime.now()), socket.gethostname(), platform.node(), PyInstallerVersion, git_branch))
a.datas += [("defaults/compile-info.yaml", compile_info_path, "DATA")]

instl_help_path = os.path.join("help")
for help_file in os.listdir(instl_help_path):
    if fnmatch.fnmatch(help_file, '*.yaml'):
        a.datas += [("help/"+help_file, os.path.join(instl_help_path, help_file), "DATA")]



pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='instl',
          debug=False,
          strip=None,
          upx=False, # does not work even if True
          runtime_tmpdir="runtime_tmpdir",
          console=True )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
                strip=None,
               upx=False,
               name='instl')

app = BUNDLE(coll,
         name='instl.bundle',
         icon=None,
         bundle_identifier=None)