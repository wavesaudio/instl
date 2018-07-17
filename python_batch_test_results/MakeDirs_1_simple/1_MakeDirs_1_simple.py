
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\MakeDirs_1_simple\MakeDirs_1_simple_1", r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\MakeDirs_1_simple\MakeDirs_1_simple_2", remove_obstacles=True) as make_dirs_00085:
    make_dirs_00085()
with MakeDirs(r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\MakeDirs_1_simple\MakeDirs_1_simple_1", remove_obstacles=False) as make_dirs_00086:
    make_dirs_00086()
# eof

