#!/usr/bin/env python3.6

import sys
import re
import datetime
from collections import defaultdict

progress_line_re = re.compile("""
    .*?
    Progress:\s+
    ((?P<curr_prog_num>\d+)|(?P<curr_prog_anon>\.\.\.))
    \s+of\s+
    ((?P<total_prog_num>\d+)|(?P<total_prog_anon>\.\.\.))
    ;\s*
    (?P<prog_message>.+?)
    \s*$
""", re.VERBOSE)

if __name__ == "__main__":
    last_progress_num = 0
    last_total_progress = 0
    last_time = datetime.datetime.now()
    time_to_step = defaultdict(list)
    begin_time = datetime.datetime.now()

    for line in sys.stdin:
        now_time = datetime.datetime.now()
        match = progress_line_re.match(line)
        if match:
            if match["total_prog_num"]:
                last_total_progress = int(match["total_prog_num"])
            if match["curr_prog_num"]:
                now_progress_num = int(match["curr_prog_num"])
            elif match["curr_prog_anon"]:
                now_progress_num = last_progress_num + 1
            progress_time = now_time-last_time
            time_to_step[str(progress_time)].append((now_progress_num, match["prog_message"]))
            print(f"""{now_progress_num}/{last_total_progress}, {progress_time}, {match["prog_message"]}""", flush=True)

            last_time = now_time
            last_progress_num = now_progress_num

    end_time = datetime.datetime.now()
    print("===", last_progress_num, "progress items", end_time-begin_time, flush=True)

    num_timing_items = len(time_to_step)
    for timing in sorted(time_to_step):
        for item in time_to_step[timing]:
            print(num_timing_items, timing, item[0], item[1])
        num_timing_items -= 1
