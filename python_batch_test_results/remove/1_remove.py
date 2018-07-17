
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\remove\remove-me", remove_obstacles=True) as make_dirs_00095:
    make_dirs_00095()
with Cd(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\remove\remove-me") as cd_00096:
    cd_00096()
    with MakeRandomDirs(num_levels=3, num_dirs_per_level=5, num_files_per_dir=7, file_size=41) as make_random_dirs_00097:
        make_random_dirs_00097()
with RmFile(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\remove\remove-me") as rm_file_00098:
    rm_file_00098()
# eof

