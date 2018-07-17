# Creation time: 17-07-18_11-42
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\copy-src", remove_obstacles=True) as make_dirs_00001:
    make_dirs_00001()
with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\target_dir_no_hard_links", remove_obstacles=True) as make_dirs_00002:
    make_dirs_00002()
with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\target_dir_with_hard_links", remove_obstacles=True) as make_dirs_00003:
    make_dirs_00003()
with Cd(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\copy-src") as cd_00004:
    cd_00004()
    with Touch(path=r"hootenanny") as touch_00005:
        touch_00005()
with CopyFileToFile(src=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\copy-src\hootenanny", trg=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\target_dir_no_hard_links\hootenanny", link_dest=False, ignore=None, preserve_dest_files=False) as copy_file_to_file_00006:
    copy_file_to_file_00006()
with CopyFileToFile(src=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\copy-src\hootenanny", trg=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\CopyFileToFile\target_dir_with_hard_links\hootenanny", link_dest=True, ignore=None, preserve_dest_files=False) as copy_file_to_file_00007:
    copy_file_to_file_00007()
# eof

