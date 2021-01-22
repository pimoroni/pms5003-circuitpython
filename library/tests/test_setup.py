import sys
import time
from unittest import mock
import pytest
import struct


# PMS5003 as seen from logic analayser
GOODFRAME1 = (b'\x42\x4d'
              b'\x00\x1c'
              b'\x00\x02\x00\x04\x00\x04\x00\x02\x00\x04\x00\x04\x02\xe8\x00\xd4\x00\x20\x00\x00\x00\x00\x00\x00\x97\x00'
              b'\x03\x34')

CORRUPTION_POS = len(GOODFRAME1) // 2
# Make a bad frame by inverting bits in one byte
BADFRAME1 = (GOODFRAME1[0:CORRUPTION_POS]
             + bytes([~GOODFRAME1[CORRUPTION_POS] & 0xff])
             + GOODFRAME1[CORRUPTION_POS+1:])

# PMS5003 from REPL on Feather nRF52840 Express
GOODFRAME2 = b'BM\x00\x1c\x00\x07\x00\t\x00\t\x00\x07\x00\t\x00\t\x05.\x01\x8a\x004\x00\x00\x00\x00\x00\x00\x97\x00\x02f'

READ_REQ = b'\x42\x4d\xe2\x00\x00\x01\x71'

PASSIVE_REQ = b'\x42\x4d\xe1\x00\x00\x01\x70'
PASSIVE_RESP = b'\x42\x4d\x00\x04\xe1\x00\x01\x74'

ACTIVE_REQ = b'\x42\x4d\xe1\x00\x01\x01\x71'
ACTIVE_RESP = b'\x42\x4d\x00\x04\xe1\x01\x01\x75'


class MockSerialFail():
    def __init__(self):
        pass

    def read(self, length):
        return b'\x00' * length

    def reset_input_buffer(self):
        pass

    def deinit(self):
        pass

    @property
    def in_waiting(self):
        return 32


class MockSerial():
    def __init__(self):
        self.ptr = 0
        self.sof = b'\x42\x4d'
        self.data = self.sof
        self.data += struct.pack('>H', 28)
        self.data += b'\x00' * 26
        checksum = struct.pack('>H', sum(bytearray(self.data)))
        self.data += checksum

    def read(self, length):
        result = self.data[self.ptr:self.ptr + length]
        self.ptr += length
        if self.ptr >= len(self.data):
            self.ptr = 0
        return result

    def reset_input_buffer(self):
        pass

    def deinit(self):
        pass

    @property
    def in_waiting(self):
        return len(self.data) - self.ptr


class MockSerialArbitrary():
    """A simulator for serial with the ability to feed the internal,
       fixed-size receieve buffer with data."""

    def __init__(self, rx_buf_size=64):
        self.rx_buf_size = rx_buf_size
        self.buffer = bytearray(self.rx_buf_size)
        self.buflen = 0
        self.written_data = bytearray()

    def simulate_rx(self, data):
        """Add data to the buffer, discarding anything which
           does not fit to simulate overruns."""
        buffer_add_size = min(len(data), self.rx_buf_size - self.buflen)
        if buffer_add_size > 0:
            self.buffer[self.buflen:self.buflen + buffer_add_size] = data[0:buffer_add_size]
            self.buflen += buffer_add_size
        return buffer_add_size

    def read(self, length):
        read_size = min(length, self.rx_buf_size, self.buflen)
        result = bytes(self.buffer[0:read_size])
        self.buflen -= read_size
        if self.buflen > 0:
            self.buffer[0:self.buflen] = self.buffer[read_size:read_size+self.buflen]
        return result

    def write(self, data):
        self.written_data.extend(data)

    def reset_input_buffer(self):
        """This intentionally does not discard data in the buffer to
           allow tests to add data beforehand."""
        pass

    def deinit(self):
        pass

    @property
    def in_waiting(self):
        return self.buflen


class PMS5003Simulator():
    """A partial simulator for serial connected to a PMS5003
       with fixed-size receive buffer.
       This uses real time so could be flaky if starved of CPU.
       """
    RESPONSES = {PASSIVE_REQ: PASSIVE_RESP,
                 ACTIVE_REQ: ACTIVE_RESP}
    INIT_DURATION = 2.6
    ACTIVE_INTERVAL = 0.910

    def __init__(self,
                 rx_buf_size=64,
                 timeout=4.0,
                 time_func=time.time,
                 init_duration=INIT_DURATION,
                 active_interval=ACTIVE_INTERVAL):
        self.rx_buf_size = rx_buf_size
        self.buffer = bytearray(self.rx_buf_size)
        self.buflen = 0
        self.written_data = bytearray()
        self.time_func = time_func
        self.init_time = self.time_func()
        self.firstframe_time = self.init_time + init_duration
        self.mode = "active"
        self.active_interval = active_interval
        self.data_frames = 0
        self.timeout = timeout

    def _tick(self):
        if self.mode != "active":
            return
        now = self.time_func()
        frames_since_init = int((now - self.firstframe_time)
                                / self.active_interval)
        if frames_since_init <= self.data_frames:
            return
        for _ in range(frames_since_init - self.data_frames):
            self.simulate_rx(GOODFRAME1)
        self.data_frames = frames_since_init

    def simulate_rx(self, data):
        """Add data to the buffer, discarding anything which
           does not fit to simulate overruns."""
        buffer_add_size = min(len(data), self.rx_buf_size - self.buflen)
        if buffer_add_size > 0:
            self.buffer[self.buflen:self.buflen + buffer_add_size] = data[0:buffer_add_size]
            self.buflen += buffer_add_size
        return buffer_add_size

    def read(self, length):
        start_time = self.time_func()
        while True:
            self._tick()
            read_size = min(length, self.rx_buf_size, self.buflen)
            if self.timeout and read_size == 0:
                if self.time_func() - start_time > self.timeout:
                    break
                else:
                    continue
            result = bytes(self.buffer[0:read_size])
            self.buflen -= read_size
            if self.buflen > 0:
                self.buffer[0:self.buflen] = self.buffer[read_size:read_size+self.buflen]
            return result
        return b''

    def write(self, data):
        self.written_data.extend(data)
        resp = self.RESPONSES.get(bytes(data))
        #print(bytes(data), "vs", self.RESPONSES, "resp=", resp)
        if resp is not None:
            self.simulate_rx(resp)
        self._tick()

    def reset_input_buffer(self):
        self.buflen = 0
        self._tick()

    def deinit(self):
        self.buflen = 0

    @property
    def in_waiting(self):
        self._tick()
        return self.buflen


def _mock():
    sys.modules['digitalio'] = mock.Mock()
    sys.modules['digitalio.DigitalInOut'] = mock.Mock()
    sys.modules['digitalio.Direction'] = mock.Mock()
    sys.modules['busio'] = mock.Mock()
    sys.modules['board'] = mock.Mock()
    sys.modules['pimoroni_physical_feather_pins'] = mock.Mock()


def test_setup():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003(serial=MockSerial())
    del sensor


def test_double_setup():
    _mock()
    import pms5003
    serial = MockSerial()
    sensor = pms5003.PMS5003(serial=serial)
    sensor.setup(serial)


def test_read():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003(serial=MockSerial())
    data = sensor.read()
    data.pm_ug_per_m3(2.5)


def test_read_fail():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003(serial=MockSerialFail())
    with pytest.raises(pms5003.ReadTimeoutError):
        data = sensor.read()
        del data


def test_checksum_pass():
    _mock()
    import pms5003
    serial = MockSerialArbitrary()
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4


def test_checksum_fail():
    _mock()
    import pms5003
    serial = MockSerialArbitrary()
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial, retries=0)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4
    serial.simulate_rx(BADFRAME1)

    with pytest.raises(pms5003.ChecksumMismatchError):
        data = sensor.read()


def test_checksum_fail_withretries():
    """This simulates a good data frame, a bad data frame, then silence."""
    _mock()
    import pms5003
    serial = MockSerialArbitrary()
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial, retries=5)
    data1 = sensor.read()
    assert data1.pm_ug_per_m3(2.5) == 4
    serial.simulate_rx(BADFRAME1)

    with pytest.raises(pms5003.ChecksumMismatchError):
        data2 = sensor.read()


def test_checksum_retries_ok():
    """This simulates a good data frame, a bad data frame, then a good data frame."""
    _mock()
    import pms5003
    serial = MockSerialArbitrary()
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial, retries=5)
    data1 = sensor.read()
    assert data1.pm_ug_per_m3(2.5) == 4
    serial.simulate_rx(BADFRAME1)
    serial.simulate_rx(GOODFRAME2)

    # This should read the bad frame, then retry and get the the good one
    data2 = sensor.read()
    assert data2.pm_ug_per_m3(2.5) == 9
    assert sensor.data_available() is False


def test_data_checksum_pass():
    """Testing the checksum verification in PMS5003Data constructor."""
    _mock()
    import pms5003
    data = pms5003.PMS5003Data(GOODFRAME1[4:],
                               frame_length_bytes=GOODFRAME1[2:4])
    assert data.pm_ug_per_m3(2.5) == 4


def test_data_checksum_pass_alt():
    """Testing the checksum verification in PMS5003Data constructor
       without passing the frame_length_bytes."""
    _mock()
    import pms5003
    data = pms5003.PMS5003Data(GOODFRAME1[4:])
    assert data.pm_ug_per_m3(2.5) == 4


def test_data_checksum_fail():
    """Testing the checksum verification in PMS5003Data constructor."""
    _mock()
    import pms5003
    with pytest.raises(pms5003.ChecksumMismatchError):
        data = pms5003.PMS5003Data(BADFRAME1[4:],
                                   frame_length_bytes=BADFRAME1[2:4])


def test_data_checksum_fail_alt():
    """Testing the checksum verification in PMS5003Data constructor
       without passing the frame_length_bytes."""
    _mock()
    import pms5003
    with pytest.raises(pms5003.ChecksumMismatchError):
        data = pms5003.PMS5003Data(BADFRAME1[4:])


def test_buffer_full_truncation():
    """Simulates the serial object's buffer being full causing
       the truncation of the third data frame."""
    _mock()
    import pms5003
    serial = MockSerialArbitrary(rx_buf_size=80)
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial)
    serial.simulate_rx(GOODFRAME2)
    serial.simulate_rx(GOODFRAME1)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 9
    with pytest.raises(pms5003.SerialTimeoutError):
        data = sensor.read()


def test_buffer_full_lucky():
    """Simulates the serial object's buffer being exactly full which
       by good fortunate prevents truncation of subsequent data frame."""
    _mock()
    import pms5003
    serial = MockSerialArbitrary(rx_buf_size=64)
    serial.simulate_rx(GOODFRAME1) # 32 bytes, fits
    sensor = pms5003.PMS5003(serial=serial)
    serial.simulate_rx(GOODFRAME2) # 32 bytes, fits
    serial.simulate_rx(GOODFRAME1) # 32 bytes, discarded completely
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 9
    with pytest.raises(pms5003.SerialTimeoutError):
        data = sensor.read()


def test_buffer_full_badframelen_long1():
    """Simulates the serial object's buffer being full,
       truncating a frame and then a good frame being
       appended to that stub to make a whole bad frame."""
    _mock()
    import pms5003
    serial = MockSerialArbitrary(rx_buf_size=34)
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial, retries=0)
    serial.simulate_rx(GOODFRAME1)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4

    # Now add a real frame to the truncated leftovers in
    # the buffer to cause a bogus frame length field with
    # value 16973
    serial.simulate_rx(GOODFRAME1)
    with pytest.raises(pms5003.FrameLengthError):
        data = sensor.read()


def test_buffer_badframelen_long2():
    """Simulates the serial object's buffer being full,
       truncating a frame and then a good frame being appended to that stub
       resulting in a long frame length field."""
    _mock()
    import pms5003
    serial = MockSerialArbitrary(rx_buf_size=34)
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial, retries=0)
    serial.simulate_rx(GOODFRAME1)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4

    # Now add part of a real frame to truncated leftovers in the buffer
    # this will be rare but something similar to this
    # could happen if library is reading from a full
    # buffer in the middle of the PMS5003 sending data
    # this has a very high probability of the checksum failing
    serial.simulate_rx(GOODFRAME1[11:])
    serial.simulate_rx(GOODFRAME1)
    with pytest.raises(pms5003.FrameLengthError):
        data = sensor.read()


def test_buffer_full_badframelen_short():
    """Simulates the serial object's buffer being full,
       truncating a frame and then a good frame being
       appended to the stub resulting in a short frame
       length field."""
    _mock()
    import pms5003
    serial = MockSerialArbitrary(rx_buf_size=34)
    serial.simulate_rx(GOODFRAME1)
    sensor = pms5003.PMS5003(serial=serial, retries=0)
    serial.simulate_rx(GOODFRAME1)
    data = sensor.read()
    data.pm_ug_per_m3(2.5)

    # Now add part of a real frame to truncated leftovers in the buffer
    # this will be rare but could happen if library is reading from full
    # buffer in the middle of PMS5003 sending data
    # this has a very high probability of the checksum failing
    serial.simulate_rx(GOODFRAME1[10:])
    serial.simulate_rx(GOODFRAME1)
    with pytest.raises(pms5003.FrameLengthError):
        data = sensor.read()


def test_active_mode_read():
    """Test active mode using new simulator object.
    """
    _mock()
    import pms5003
    serial = PMS5003Simulator()
    sensor = pms5003.PMS5003(serial=serial)

    # The constructor waits for data but does not read it therefore this
    # will always be True after the object is created successfully
    assert sensor.data_available() is True
    data1 = sensor.read()
    data1.pm_ug_per_m3(2.5)

    # This should block until new data is generated by simulator
    data2 = sensor.read()
    data2.pm_ug_per_m3(2.5)


def test_passive_mode_read():
    """Test the new passive mode using new simulator object
       where responses are requested by polling.
    """
    _mock()
    import pms5003
    serial = PMS5003Simulator()
    sensor = pms5003.PMS5003(serial=serial, mode='passive')
    assert serial.written_data == PASSIVE_REQ
    data1 = sensor.read()
    data1.pm_ug_per_m3(2.5)
    time.sleep(0.5)
    data2 = sensor.read()
    data2.pm_ug_per_m3(2.5)


def test_active_mode_to_passive():
    """Test new simulator object with instantiation in default active mode
       and then a switch to passive mode.
    """
    _mock()
    import pms5003
    serial = PMS5003Simulator()
    sensor = pms5003.PMS5003(serial=serial)
    data1 = sensor.read()
    data1.pm_ug_per_m3(2.5)

    # This should block until new data is generated by simulator
    data2 = sensor.read()
    data2.pm_ug_per_m3(2.5)

    sensor.cmd_mode_passive()

    data3 = sensor.read()
    data3.pm_ug_per_m3(2.5)


def test_active_mode_to_passive_to_active():
    """Test new simulator object with instantiation in default active mode
       and then a switch to passive mode and then back to active.
    """
    _mock()
    import pms5003
    serial = PMS5003Simulator()
    sensor = pms5003.PMS5003(serial=serial)
    data1 = sensor.read()
    data1.pm_ug_per_m3(2.5)

    # This should block until new data is generated by simulator
    data2 = sensor.read()
    data2.pm_ug_per_m3(2.5)

    sensor.cmd_mode_passive()
    assert serial.written_data == PASSIVE_REQ
    data3 = sensor.read()
    data3.pm_ug_per_m3(2.5)
    time.sleep(0.5)
    data4 = sensor.read()
    data4.pm_ug_per_m3(2.5)

    sensor.cmd_mode_active()
    assert serial.written_data == PASSIVE_REQ + READ_REQ + READ_REQ + ACTIVE_REQ
    data5 = sensor.read()
    data5.pm_ug_per_m3(2.5)


def test_active_mode_to_passive_unlucky():
    """Test new simulator object with instantiation in default active mode
       and then a switch to passive mode but with unfortunate timing where
       a data frame sneaks in before the response to passive mode command.
    """
    _mock()
    import pms5003
    serial = PMS5003Simulator()
    sensor = pms5003.PMS5003(serial=serial)
    data1 = sensor.read()
    data1.pm_ug_per_m3(2.5)

    # This should block until new data is generated by simulator
    data2 = sensor.read()
    data2.pm_ug_per_m3(2.5)

    serial.data_frames -= 1  # hacky way to sneak an inopportune data frame in
    sensor.cmd_mode_passive()
    assert serial.written_data == PASSIVE_REQ

    data3 = sensor.read()
    data3.pm_ug_per_m3(2.5)


def test_odd_zero_burst():
    """Test an odd length burst of NUL characters appearing between
       data frames. This tests the correctness of the code which
       parses the first two bytes of frame header.
    """
    _mock()
    import pms5003
    serial = PMS5003Simulator()
    sensor = pms5003.PMS5003(serial=serial)
    data1 = sensor.read()
    data1.pm_ug_per_m3(2.5)

    # Odd length (five) is important here
    serial.simulate_rx(b"\x00\x00\x00\x00\x00")
    # This should block until new data is generated by simulator
    data2 = sensor.read()
    data2.pm_ug_per_m3(2.5)
