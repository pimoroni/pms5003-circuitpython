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

# Test resets of the device and reads in passive and active mode

import time

import board
import digitalio

try:
    from pimoroni_pms5003 import PMS5003
except ImportError:
    from pms5003 import PMS5003

### For benefit of most glorious logic analyzer
a5pin = digitalio.DigitalInOut(board.A5)
a5pin.switch_to_output()

def fmt_data(pdata, info, ident, time_pre, time_post):
    time_since_start = (time_post - start_time_ns) / 1e9
    read_duration = (time_post - time_pre) / 1e9
    return ("{:s} {:3d} at {:f} took {:f} "
            "PM ug/m3 2.5={:d} 10={:d}\n".format(info, ident,
                                                 time_since_start,
                                                 read_duration,
                                                 pdata.pm_ug_per_m3(2.5),
                                                 pdata.pm_ug_per_m3(10)))

def test_run(mode, count, interval):
    """Read some values with a fixed interval but throw in a reset
       half way through.
       This is a common approach in normal active mode but it is
       FLAWED because the device does not generate values at exactly 1Hz.
       """
    global start_time_ns
    print("Instatiating in " + mode + " mode")
    start_time_ns = time.monotonic_ns()
    pms5003 = PMS5003(mode=mode)
    print("Initialisation took", (time.monotonic_ns() - start_time_ns) / 1e9, "seconds")

    for idx in range(1, count + 1):
        a5pin.value = not a5pin.value  # Indicate read via toggling A5
        time_pre_read = time.monotonic_ns()
        data = pms5003.read()
        time_post_read = time.monotonic_ns()
        print(fmt_data(data, mode, idx, time_pre_read, time_post_read), end="")
        if idx == count // 2:
            time_pre_reset = time.monotonic_ns()
            pms5003.reset()
            print("Reset took", (time.monotonic_ns() - time_pre_reset) / 1e9, "seconds")
        else:
            time.sleep(interval)

    pms5003.deinit()

start_time_ns = 0

print("RESET TESTS")
print("Sleeping for a bit")
time.sleep(5.003)
test_run("active", 6, 1.0)
test_run("passive", 6, 1.0)
test_run("active", 6, 0.5)
time.sleep(3.14)
