import struct
import time

import board
import busio
from digitalio import DigitalInOut, Direction

import pimoroni_physical_feather_pins

__version__ = '0.0.6'


PMS5003_SOF = bytearray(b'\x42\x4d')


class ChecksumMismatchError(RuntimeError):
    pass


class FrameLengthError(RuntimeError):
    pass


class ReadTimeoutError(RuntimeError):
    pass


class SerialTimeoutError(RuntimeError):
    pass


class PMS5003Data():
    FRAME_LEN = 32
    DATA_LEN = FRAME_LEN - 4  # includes checksum

    @classmethod
    def check_data_len(cls, raw_data_len, desc="Data"):
        if raw_data_len != cls.DATA_LEN:
            raise FrameLengthError(desc + " too "
                                   + ("short" if raw_data_len < cls.DATA_LEN else "long")
                                   + " {:d} bytes".format(raw_data_len))


    def __init__(self, raw_data, *, frame_length_bytes=None):
        raw_data_len = len(raw_data)
        self.check_data_len(raw_data_len)
        self.raw_data = raw_data
        self.data = struct.unpack(">HHHHHHHHHHHHHH", raw_data)
        self.checksum = self.data[13]

        # Don't include the checksum bytes in the checksum calculation
        checksum = sum(PMS5003_SOF) + sum(raw_data[:-2])
        if frame_length_bytes is None:
            checksum += (raw_data_len >> 256) + (raw_data_len & 0xff)
        else:
            checksum += sum(frame_length_bytes)
        if checksum != self.checksum:
            raise ChecksumMismatchError("PMS5003 Checksum Mismatch {} != {}".format(checksum,
                                                                                    self.checksum))


    def pm_ug_per_m3(self, size, atmospheric_environment=False):
        if atmospheric_environment:
            if size == 1.0:
                return self.data[3]
            if size == 2.5:
                return self.data[4]
            if size is None:
                return self.data[5]

        else:
            if size == 1.0:
                return self.data[0]
            if size == 2.5:
                return self.data[1]
            if size == 10:
                return self.data[2]

        raise ValueError("Particle size {} measurement not available.".format(size))

    def pm_per_1l_air(self, size):
        if size == 0.3:
            return self.data[6]
        if size == 0.5:
            return self.data[7]
        if size == 1.0:
            return self.data[8]
        if size == 2.5:
            return self.data[9]
        if size == 5:
            return self.data[10]
        if size == 10:
            return self.data[11]

        raise ValueError("Particle size {} measurement not available.".format(size))

    def __repr__(self):
        return """
PM1.0 ug/m3 (ultrafine particles):                             {}
PM2.5 ug/m3 (combustion particles, organic compounds, metals): {}
PM10 ug/m3  (dust, pollen, mould spores):                      {}
PM1.0 ug/m3 (atmos env):                                       {}
PM2.5 ug/m3 (atmos env):                                       {}
PM10 ug/m3 (atmos env):                                        {}
>0.3um in 0.1L air:                                            {}
>0.5um in 0.1L air:                                            {}
>1.0um in 0.1L air:                                            {}
>2.5um in 0.1L air:                                            {}
>5.0um in 0.1L air:                                            {}
>10um in 0.1L air:                                             {}
""".format(*self.data[:-2], checksum=self.checksum)

    def __str__(self):
        return self.__repr__()


class PMS5003():
    #def __init__(self, baudrate=9600, pin_enable=board.D10, pin_reset=board.D11):
    def __init__(self, baudrate=9600, pin_enable=pimoroni_physical_feather_pins.pin22(), pin_reset=pimoroni_physical_feather_pins.pin23()):
        self._serial = None
        self._baudrate = baudrate
        self._pin_enable = pin_enable
        self._enable = None
        self._pin_reset = pin_reset
        self._reset = None
        self.setup()

    def setup(self):
        self._enable = DigitalInOut(self._pin_enable)
        self._enable.direction = Direction.OUTPUT
        self._enable.value = True

        self._reset = DigitalInOut(self._pin_reset)
        self._reset.direction = Direction.OUTPUT
        self._reset.value = True


        if self._serial is not None:
            self._serial.deinit()

        self._serial = busio.UART(board.TX, board.RX, baudrate=self._baudrate, timeout=4)

        self.reset()

    def reset(self):
        time.sleep(0.1)
        self._reset.value = False
        self._serial.reset_input_buffer()
        time.sleep(0.1)
        self._reset.value = True

    def read(self):
        start = time.monotonic()

        sof_index = 0

        while True:
            elapsed = time.monotonic() - start
            if elapsed > 5:
                raise ReadTimeoutError("PMS5003 Read Timeout: Could not find start of frame")

            sof = self._serial.read(1)
            if len(sof) == 0:
                raise SerialTimeoutError("PMS5003 Read Timeout: Failed to read start of frame byte")
            sof = ord(sof) if type(sof) is bytes else sof

            if sof == PMS5003_SOF[sof_index]:
                if sof_index == 0:
                    sof_index = 1
                elif sof_index == 1:
                    break
            else:
                sof_index = 0

        len_data = bytearray(self._serial.read(2))  # Get frame length packet
        if len(len_data) != 2:
            raise SerialTimeoutError("PMS5003 Read Timeout: Could not find length packet")
        frame_length = struct.unpack(">H", len_data)[0]
        PMS5003Data.check_data_len(frame_length, desc="Length field")

        raw_data = bytearray(self._serial.read(frame_length))
        if len(raw_data) != frame_length:
            raise SerialTimeoutError("PMS5003 Read Timeout: Invalid frame length. Got {} bytes, expected {}.".format(len(raw_data), frame_length))

        return PMS5003Data(raw_data, frame_length_bytes=len_data)
