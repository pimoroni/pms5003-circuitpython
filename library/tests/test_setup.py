import sys
from unittest import mock
import pytest
import struct


# PMS5003 as seen from logic analayser
goodframe1 = (b'\x42\x4d'
              b'\x00\x1c'
              b'\x00\x02\x00\x04\x00\x04\x00\x02\x00\x04\x00\x04\x02\xe8\x00\xd4\x00\x20\x00\x00\x00\x00\x00\x00\x97\x00'
              b'\x03\x34')

corrupt_pos = len(goodframe1) // 2
badframe1 = (goodframe1[0:corrupt_pos]
             + bytes([~goodframe1[corrupt_pos] & 0xff])
             + goodframe1[corrupt_pos+1:])

# PMS5003 from REPL on Feather nRF52840 Express
goodframe2 = b'BM\x00\x1c\x00\x07\x00\t\x00\t\x00\x07\x00\t\x00\t\x05.\x01\x8a\x004\x00\x00\x00\x00\x00\x00\x97\x00\x02f'


class MockSerialFail():
    def __init__(self):
        pass

    def read(self, length):
        return b'\x00' * length


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


class MockSerialArbitrary():
    """A simulator for serial with the ability to feed the internal,
       fixed-size receieve buffer with data."""
    def __init__(self, rx_buf_size=64):
        self.rx_buf_size = rx_buf_size
        self.buffer = bytearray(self.rx_buf_size)
        self.buflen = 0


    def simulateRx(self, data):
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
    sensor = pms5003.PMS5003()
    del sensor


def test_double_setup():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor.setup()


def test_read():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerial()
    data = sensor.read()
    data.pm_ug_per_m3(2.5)


def test_read_fail():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialFail()
    with pytest.raises(pms5003.ReadTimeoutError):
        data = sensor.read()
        del data


def test_checksum_pass():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialArbitrary()
    sensor._serial.simulateRx(goodframe1)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4


def test_checksum_fail():
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialArbitrary()
    sensor._serial.simulateRx(badframe1)

    with pytest.raises(pms5003.ChecksumMismatchError):
        data = sensor.read()


def test_data_checksum_pass():
    """Testing the checksum verification in PMS5003Data constructor."""
    _mock()
    import pms5003
    data = pms5003.PMS5003Data(goodframe1[4:],
                               frame_length_bytes=goodframe1[2:4])
    assert data.pm_ug_per_m3(2.5) == 4


def test_data_checksum_pass_alt():
    """Testing the checksum verification in PMS5003Data constructor
       without passing the frame_length_bytes."""
    _mock()
    import pms5003
    data = pms5003.PMS5003Data(goodframe1[4:])
    assert data.pm_ug_per_m3(2.5) == 4


def test_data_checksum_fail():
    """Testing the checksum verification in PMS5003Data constructor."""
    _mock()
    import pms5003
    with pytest.raises(pms5003.ChecksumMismatchError):
        data = pms5003.PMS5003Data(badframe1[4:],
                                   frame_length_bytes=badframe1[2:4])


def test_data_checksum_fail_alt():
    """Testing the checksum verification in PMS5003Data constructor
       without passing the frame_length_bytes."""
    _mock()
    import pms5003
    with pytest.raises(pms5003.ChecksumMismatchError):
        data = pms5003.PMS5003Data(badframe1[4:])


def test_buffer_full_truncation():
    """Simulates the serial object's buffer being full and truncating a frame."""
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialArbitrary(rx_buf_size=80)
    sensor._serial.simulateRx(goodframe1)
    sensor._serial.simulateRx(goodframe2)
    sensor._serial.simulateRx(goodframe1)
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
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialArbitrary(rx_buf_size=64)
    sensor._serial.simulateRx(goodframe1) # 32 bytes, fits
    sensor._serial.simulateRx(goodframe2) # 32 bytes, fits
    sensor._serial.simulateRx(goodframe1) # 32 bytes, discarded completely
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 9
    with pytest.raises(pms5003.SerialTimeoutError):
        data = sensor.read()


def test_buffer_full_badframelen_long1():
    """Simulates the serial object's buffer being full,
      truncating a frame and then a good frame being appended to that stub."""
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialArbitrary(rx_buf_size=34)
    sensor._serial.simulateRx(goodframe1)
    sensor._serial.simulateRx(goodframe1)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4

    # Now add a real frame to truncated leftovers in the buffer
    # to cause a bogus frame length of 16973 bytes
    sensor._serial.simulateRx(goodframe1)
    with pytest.raises(pms5003.FrameLengthError):
        data = sensor.read()


def test_buffer_badframelen_long2():
    """Simulates the serial object's buffer being full,
      truncating a frame and then a good frame being appended to that stub
      resulting in a long frame length field."""
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialArbitrary(rx_buf_size=34)
    sensor._serial.simulateRx(goodframe1)
    sensor._serial.simulateRx(goodframe1)
    data = sensor.read()
    assert data.pm_ug_per_m3(2.5) == 4

    # Now add part of a real frame to truncated leftovers in the buffer
    # this will be rare but something similar to this
    # could happen if library is reading from a full
    # buffer in the middle of the PMS5003 sending data
    # this has a very high probability of the checksum failing
    sensor._serial.simulateRx(goodframe1[11:])
    sensor._serial.simulateRx(goodframe1)
    with pytest.raises(pms5003.FrameLengthError):
        data = sensor.read()


def test_buffer_full_badframelen_short():
    """Simulates the serial object's buffer being full,
      truncating a frame and then a good frame being appended to the stub
      resulting in a short frame length field."""
    _mock()
    import pms5003
    sensor = pms5003.PMS5003()
    sensor._serial = MockSerialArbitrary(rx_buf_size=34)
    sensor._serial.simulateRx(goodframe1)
    sensor._serial.simulateRx(goodframe1)
    data = sensor.read()
    data.pm_ug_per_m3(2.5)

    # Now add part of a real frame to truncated leftovers in the buffer
    # this will be rare but could happen if library is reading from full
    # buffer in the middle of PMS5003 sending data
    # this has a very high probability of the checksum failing
    sensor._serial.simulateRx(goodframe1[10:])
    sensor._serial.simulateRx(goodframe1)
    with pytest.raises(pms5003.FrameLengthError):
        data = sensor.read()
