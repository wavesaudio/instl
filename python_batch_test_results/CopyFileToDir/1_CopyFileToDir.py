# Creation time: 12-07-18_10-21
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToDir\copy-src", remove_obstacles=True) as make_dirs_00001:
    make_dirs_00001()
with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToDir\copy-target-no-hard-links", remove_obstacles=True) as make_dirs_00002:
    make_dirs_00002()
with Cd(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToDir\copy-src") as cd_00003:
    cd_00003()
    with Touch(path=r"hootenanny") as touch_00004:
        touch_00004()
with CopyFileToDir(src=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToDir\copy-src\hootenanny", trg=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToDir\copy-target-no-hard-links/", link_dest=False, ignore=None, preserve_dest_files=False) as copy_file_to_dir_00005:
    copy_file_to_dir_00005()
# eof

