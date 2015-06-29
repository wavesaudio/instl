# -*- mode: python -*-
import os
import sys
import fnmatch
import platform
import inspect
import socket
import datetime
import boto

# assuming the instl main is one level above this instl.spec file.
script_folder = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
#print("script_folder", script_folder)
instl_folder = os.path.join(script_folder, '..')
#print("instl_folder", instl_folder)
org_folder = os.getcwd()
os.chdir(instl_folder)

instl_main_path = os.path.join(instl_folder, "instl")
a = Analysis([instl_main_path],
             hiddenimports=[],
             hookspath=None,
             excludes=['PyQt4', 'matplotlib',
                        "PIL", "numpy", "wx", "tornado", "networkx",
                         "pygraphviz", "unittest", "nose",
                         "Tkinter", "scipy", "setuptools", "distutils"])

if False: # print module names
    binary_module_names = [modu[0] for modu in a.binaries]
    pure_module_names =   [modu[0] for modu in a.pure]
    print "=== pure"
    print "\n".join(sorted(pure_module_names))
    print "=== binary"
    print "\n".join(sorted(binary_module_names))
    print "=== END"
    sys.stdout.flush()

instl_defaults_path = os.path.join(instl_folder, "defaults")
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
""".format(str(datetime.datetime.now()), socket.gethostname(), platform.node()))
a.datas += [("defaults/compile-info.yaml", compile_info_path, "DATA")]

instl_help_path = os.path.join(instl_folder, "help")
for help_file in os.listdir(instl_help_path):
    if fnmatch.fnmatch(help_file, '*.yaml'):
        a.datas += [("help/"+help_file, os.path.join(instl_help_path, help_file), "DATA")]

compiled_instl_name = os.path.join('build', 'instl')
if platform.system() == 'Windows':
    compiled_instl_name += ".exe"

pyz = PYZ(a.pure)
exe = EXE(pyz,
          #[('v', None, 'OPTION')],
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name=compiled_instl_name,
          debug=False,
          strip=None,
          upx=False,
          console=True )
