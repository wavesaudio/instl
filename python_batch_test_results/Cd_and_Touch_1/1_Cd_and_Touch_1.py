
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Cd_and_Touch_1\cd-here", remove_obstacles=False) as make_dirs_00002:
    make_dirs_00002()
with Cd(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Cd_and_Touch_1\cd-here") as cd_00003:
    cd_00003()
    with Touch(path="touch-me") as touch_00004:
        touch_00004()
# eof

