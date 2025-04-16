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
from pathlib import Path
import yaml


a = Analysis(['instl'],
             pathex=['instl'],
             binaries=[],
             datas=[],
             hiddenimports=['packaging',
                            'packaging.version',
                            'packaging.specifiers',
                            'packaging.requirements',
                            'xmltodict'],
             hookspath=[],
             runtime_hooks=[],
             excludes=['PyQt4', 'matplotlib', "PIL", "numpy", "wx", "tornado", "networkx",
                         "pygraphviz", "unittest", "nose", 'PyInstaller',
                        "tkinter", "Tkinter", "scipy", "colorama",
                        "botocore", "boto3", "redis", "rich"],
             win_no_prefer_redirects=False,
             win_private_assemblies=False)


pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='instl',
          debug=False,
          strip=False,
          upx=False, # does not work even if True
          runtime_tmpdir="runtime_tmpdir",
          console=True,
          target_arch='universal2')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=False,
               name='instl')
