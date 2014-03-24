#!/usr/bin/env python2.7

from __future__ import print_function
import os
import sys
import subprocess
import shutil

script_folder = os.path.dirname(os.path.join(os.getcwd(), __file__))
print("script_folder", script_folder)
org_folder = os.getcwd()
os.chdir(script_folder)

if sys.platform == 'win32':
    current_os = 'Win'
    spec_file = os.path.join(script_folder, 'instl_win.spec')
    instl_bin_file = 'instl.exe'
elif sys.platform == 'darwin':
    current_os = 'Mac'
    spec_file = os.path.join(script_folder, 'instl_mac.spec')
    instl_bin_file = 'instl'
elif sys.platform == 'linux2':
    current_os = 'Linux'
    spec_file = os.path.join(script_folder, 'instl_linux.spec')
    instl_bin_file = 'instl'


py_installer_path = os.path.join(script_folder, '..', '..', 'SDKs', 'python', 'PyInstaller-2.1', 'pyinstaller.py')
p4_instl_bin = os.path.join('..', 'bin', current_os, instl_bin_file)
compiled_instl_bin = os.path.join(script_folder, 'dist', instl_bin_file)

cmd = ['python2.7', os.path.abspath(py_installer_path), spec_file]
print('... Running command - %s' % ' '.join(cmd))
if current_os == 'Win':
    subprocess.check_call(cmd, shell=True)
elif current_os in ('Mac', 'Linux'):
    subprocess.check_call(cmd)


print('... Copying executable - %s %s' % (compiled_instl_bin, os.path.abspath(p4_instl_bin)))
shutil.copy(compiled_instl_bin, p4_instl_bin)

os.chdir(org_folder)

if __name__ == "__main__":