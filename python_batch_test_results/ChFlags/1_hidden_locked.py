# Creation time: 17-07-18_10-40
import sys
sys.path.append(r'C:\Users\nira\Documents\GitHub\instl')
from pybatch import *

with Touch(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\ChFlags\chflags-me") as touch_00001:
    touch_00001()
with ChFlags(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\ChFlags\chflags-me", flag="locked", recursive=False, ignore_errors=True) as ch_flags_00002:
    ch_flags_00002()
with ChFlags(path=r"C:\Users\nira\Documents\GitHub\instl\python_batch_test_results\ChFlags\chflags-me", flag="hidden", recursive=False, ignore_errors=True) as ch_flags_00003:
    ch_flags_00003()
# eof

