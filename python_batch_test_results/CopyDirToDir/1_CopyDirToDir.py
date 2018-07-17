# Creation time: 17-07-18_15-43
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyDirToDir\copy-src", remove_obstacles=True) as make_dirs_00001:
    make_dirs_00001()
with Cd(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyDirToDir\copy-src") as cd_00002:
    cd_00002()
    with Touch(path=r"hootenanny") as touch_00003:
        touch_00003()
    with MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41) as make_random_dirs_00004:
        make_random_dirs_00004()
with CopyDirToDir(src=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyDirToDir\copy-src", trg=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyDirToDir\copy-target-no-hard-links", link_dest=False, ignore=None, preserve_dest_files=False) as copy_dir_to_dir_00005:
    copy_dir_to_dir_00005()
with CopyDirToDir(src=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyDirToDir\copy-src", trg=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyDirToDir\copy-target-with-ignore", link_dest=False, ignore=['hootenanny'], preserve_dest_files=False) as copy_dir_to_dir_00006:
    copy_dir_to_dir_00006()
# eof

