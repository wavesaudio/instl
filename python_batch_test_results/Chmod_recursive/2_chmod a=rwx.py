
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with Chmod(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_recursive\folder-to-chmod", mode='a=rwx', recursive=True) as chmod_00033:
    chmod_00033()
# eof

