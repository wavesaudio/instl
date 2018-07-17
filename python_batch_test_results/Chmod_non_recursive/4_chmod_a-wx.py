
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with Chmod(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_non_recursive\file-to-chmod", mode='u-wx', recursive=False) as chmod_00017:
    chmod_00017()
with Chmod(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_non_recursive\file-to-chmod", mode='g-wx', recursive=False) as chmod_00018:
    chmod_00018()
with Chmod(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_non_recursive\file-to-chmod", mode='o-wx', recursive=False) as chmod_00019:
    chmod_00019()
# eof

