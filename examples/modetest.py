# MIT License

# Copyright (c) 2020 Kevin J. Walters

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Test reads in passive and active mode

import time

try:
    from pimoroni_pms5003 import PMS5003
except ImportError:
    from pms5003 import PMS5003


def fmt_data(pdata, info, ident, time_pre, time_post):
    time_since_start = (time_post - start_time_ns) / 1e9
    read_duration = (time_post - time_pre) / 1e9
    return ("{:s} {:3d} at {:f} took {:f} "
            "PM ug/m3 2.5={:d} 10={:d}\n".format(info, ident,
                                                 time_since_start,
                                                 read_duration,
                                                 pdata.pm_ug_per_m3(2.5),
                                                 pdata.pm_ug_per_m3(10)))


# This is for testing where the device breaks
# for high frequency polling reads in passive mode
test_to_destruction = False

print("MODE TESTS")
print("Instatiating in the non-default passive mode...")
start_time_ns = time.monotonic_ns()
pms5003 = PMS5003(mode="passive")

idx = 1

disp_mode = "passive"
t1 = t2 = 0.0
for interval in (1.0, 1.35, 1.7, 0.85, 0.5, 0.3, 0.100, 0.090, 0.080):
    time.sleep(interval)
    time_pre_read = time.monotonic_ns()
    data = pms5003.read()
    time_post_read = time.monotonic_ns()
    t1 = time.monotonic_ns()
    print(fmt_data(data, disp_mode, idx, time_pre_read, time_post_read), end="")
    t2 = time.monotonic_ns()
    idx += 1

if test_to_destruction:
    # dies with 30ms interval
    # Output is put in a string to remove print to console slowing things down
    output = ""
    #kaboom = False
    for interval in (0.050, 0.050, 0.048, 0.045, 0.043, 0.040, 0.030, 0.020):
        time.sleep(interval)
        try:
            time_pre_read = time.monotonic_ns()
            data = pms5003.read()
            time_post_read = time.monotonic_ns()
        except:
            print(output, end="")
            raise
        output += fmt_data(data, disp_mode, idx, time_pre_read, time_post_read)
        idx += 1
    print(output)


# The library now includes delays
# 0.100 worked 3 of 3
# 0.010 errored 3 of 3
# 0.030 errored 3 of 3
# 0.040 errored 3 of 3
# 0.045 errored 3 of 3
# 0.050 worked 9 of 9
#intercommanddelay = 0.050
intercommanddelay = 0.0

time.sleep(intercommanddelay)
pms5003.cmd_mode_active()
time.sleep(intercommanddelay)
pms5003.cmd_mode_passive()
time.sleep(intercommanddelay)
pms5003.cmd_mode_active()
time.sleep(intercommanddelay)
disp_mode = "active "

for _ in range(5):
    time_pre_read = time.monotonic_ns()
    data = pms5003.read()
    time_post_read = time.monotonic_ns()
    print(fmt_data(data, disp_mode, idx, time_pre_read, time_post_read), end="")
    idx += 1

pms5003.cmd_mode_passive()
disp_mode = "passive"
for interval in (1.6, 0.8, 0.4, 0.2, 0.2, 0.2):
    time.sleep(interval)
    time_pre_read = time.monotonic_ns()
    data = pms5003.read()
    time_post_read = time.monotonic_ns()
    print(fmt_data(data, disp_mode, idx, time_pre_read, time_post_read), end="")
    idx += 1

time.sleep(3.14)
