
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with Chmod(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\Chmod_non_recursive\file-to-chmod", mode='a=rwx', recursive=False) as chmod_00011:
    chmod_00011()
# eof

