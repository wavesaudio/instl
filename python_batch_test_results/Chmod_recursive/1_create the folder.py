
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_recursive\folder-to-chmod", remove_obstacles=True) as make_dirs_00023:
    make_dirs_00023()
with Cd(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_recursive\folder-to-chmod") as cd_00024:
    cd_00024()
    with Touch(path="hootenanny") as touch_00025:
        touch_00025()
    with MakeRandomDirs(num_levels=1, num_dirs_per_level=2, num_files_per_dir=3, file_size=41) as make_random_dirs_00026:
        make_random_dirs_00026()
    with Chmod(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_recursive\folder-to-chmod", mode='a+rw', recursive=True) as chmod_00027:
        chmod_00027()
# eof

