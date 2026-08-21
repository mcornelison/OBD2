################################################################################
# File Name: ak09916_bypass.py
# Purpose/Description: US-565 direct AK09916 magnetometer acquisition (F-135).
#   Makes the magnetometer channel actually VARY by taking it off the ICM-20948's
#   auxiliary-I2C shadow path and reading it as its own I2C device at 0x0C.
#
#   WHAT WAS MEASURED, 2026-08-21 on chi-eclipse-01, and it refutes the assumed
#   cause. The story arrived believing the lever was the AK09916's CNTL2 data
#   rate. It is not:
#     - CNTL2 read back 0x08 (continuous 100 Hz) BEFORE any change: the chip was
#       already in the right mode.
#     - A VERIFIED write of 10 Hz (readback 0x02) changed nothing.
#     - Polled directly over slave4 with the shadow quiesced, the chip was
#       CONVERTING AND DITHERING -- raw X took 6 distinct values across 11 passes
#       with ST1.DRDY set -- while `dev.magnetic` was frozen.
#   So the chip was healthy the whole time and the ICM-20948's cyclic slave0
#   readout was performing ONE transfer and then stopping. Measured over a 12 s
#   window: mag changed exactly once, at sample index 1, then held for 270 more
#   samples while accel changed 265 times on the same die.
#
#   THE FIX, AND ITS EVIDENCE. Disable the aux master, set INT_PIN_CFG.BYPASS_EN,
#   and read the magnetometer on the primary bus. 90 s stationary on the bench:
#   mag_x 27 distinct / 2108 samples with 1942 changes and DRDY set on 2108 of
#   2108 reads, against 1 distinct / 20,000 on the shadow path the same day.
#   Accel and gyro are untouched -- they are read from the ICM at 0x69 exactly as
#   before, and bypass does not affect them.
#
#   THE READ MUST REACH ST2. The AK09916 loads a new measurement only once the
#   previous one has been released by a read extending through ST2, so the burst
#   runs ST1..ST2 inclusive. A "tidier" 6-byte data-only read silently re-creates
#   the original latch, which is why that extent is pinned structurally by test.
#
#   Calibration (hard/soft iron) is explicitly OUT OF SCOPE -- you cannot
#   calibrate a sensor that is not reading. The measured field magnitude here is
#   ~90 uT against Earth's ~52 uT at this latitude, i.e. a real hard-iron offset
#   is present and still owed.
# Author: Rex (US-565)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-565) | Initial -- bypass enable, verified CNTL2 config,
#               |              | ST1..ST2 burst, overflow refusal, ICM wrapper.
# ================================================================================
################################################################################

"""Direct AK09916 magnetometer acquisition over I2C bypass (US-565)."""

from __future__ import annotations

import logging
from typing import Any

__all__ = [
    "AK09916_I2C_ADDRESS",
    "FRAME_LENGTH",
    "FRAME_START_REGISTER",
    "MODE_CONTINUOUS_100HZ",
    "MODE_POWER_DOWN",
    "REG_CNTL2",
    "REG_ST1",
    "REG_ST2",
    "REG_WIA2",
    "UT_PER_LSB",
    "WHO_AM_I_VALUE",
    "Ak09916Direct",
    "Icm20948DirectMagnetometer",
    "MagnetometerConfigError",
    "MagnetometerOverflowError",
    "enableI2cBypass",
    "makeBypassMagnetometer",
]

logger = logging.getLogger(__name__)

# The AK09916's OWN address on the primary bus once the ICM-20948 stops shadowing
# it. MEASURED 2026-08-21: WIA2 read 0x09 here with bypass enabled.
AK09916_I2C_ADDRESS = 0x0C
WHO_AM_I_VALUE = 0x09

# Register map (AKM AK09916C datasheet).
REG_WIA2 = 0x01
REG_ST1 = 0x10  # bit 0 DRDY, bit 1 DOR
REG_HXL = 0x11
REG_ST2 = 0x18  # bit 3 HOFL; reading this register RELEASES the data latch
REG_CNTL2 = 0x31
REG_CNTL3 = 0x32

# CNTL2 operating modes.
MODE_POWER_DOWN = 0x00
MODE_SINGLE = 0x01
MODE_CONTINUOUS_100HZ = 0x08

# The burst extent, and it is load-bearing rather than an efficiency choice: the
# chip will not load its next measurement until a read reaches ST2, so the frame
# spans ST1..ST2 INCLUSIVE. Shortening it to the six data bytes re-creates the
# exact latch this module exists to remove, and it would do so silently -- the
# values stay plausible, they simply stop changing.
FRAME_START_REGISTER = REG_ST1
FRAME_LENGTH = REG_ST2 - REG_ST1 + 1  # 9 bytes: ST1, HXL..HZH, TMPS, ST2

# Status bits.
ST1_DRDY_MASK = 0x01
ST2_OVERFLOW_MASK = 0x08

# Datasheet sensitivity, 0.15 uT/LSB.
UT_PER_LSB = 0.15

# Datasheet Twait: at least 100 us in power-down before another mode is set. Held
# generously because this runs once, at probe time, and never in the poll loop.
_MODE_TRANSIT_SECONDS = 0.010


class MagnetometerConfigError(RuntimeError):
    """The magnetometer could not be identified or could not be configured."""


class MagnetometerOverflowError(RuntimeError):
    """The measurement overflowed; the datasheet declares that data invalid."""


class Ak09916Direct:
    """The AK09916 read as its own I2C device, with the ICM's shadow bypassed.

    Single-threaded by contract, like every other sensor device handle: only the
    owning reader's poll thread calls into it.
    """

    def __init__(self, i2cDevice: Any, *, mode: int = MODE_CONTINUOUS_100HZ) -> None:
        """Bind to an already-addressed I2C device.

        Args:
            i2cDevice: A context-managed device exposing ``write`` and
                ``write_then_readinto`` (the adafruit ``I2CDevice`` surface).
            mode: The CNTL2 operating mode to configure. Defaults to continuous
                100 Hz, which is MEASURED to work rather than assumed -- see the
                module header.
        """
        self._device = i2cDevice
        self._mode = mode
        self._frame = bytearray(FRAME_LENGTH)
        self._lastDataReady = False

    # -- configuration ---------------------------------------------------------
    def configure(self) -> int:
        """Identify the chip and set its operating mode, VERIFYING both.

        Returns:
            The operating mode as read back from CNTL2.

        Raises:
            MagnetometerConfigError: When WHO_AM_I is not the AK09916's, or when
                CNTL2 does not read back the mode that was just written.
        """
        whoAmI = self._readRegister(REG_WIA2)
        if whoAmI != WHO_AM_I_VALUE:
            raise MagnetometerConfigError(
                f"WHO_AM_I at 0x{AK09916_I2C_ADDRESS:02X} read 0x{whoAmI:02X}, "
                f"expected 0x{WHO_AM_I_VALUE:02X} -- refusing to decode an "
                "unidentified device into micro-teslas"
            )

        # Transit through power-down before changing mode (datasheet), then
        # READ THE MODE BACK. The readback is the whole point: the adafruit
        # driver writes CNTL2, discards the completion flag its own helper
        # returns, and never verifies -- so a mode change that never reached the
        # chip was indistinguishable from one that did.
        self._writeRegister(REG_CNTL2, MODE_POWER_DOWN)
        self._writeRegister(REG_CNTL2, self._mode)
        readback = self._readRegister(REG_CNTL2)
        if readback != self._mode:
            raise MagnetometerConfigError(
                f"CNTL2 wrote 0x{self._mode:02X} but read back 0x{readback:02X} "
                "-- the mode did not land; a configuration that cannot be "
                "verified must not be reported as applied"
            )
        logger.info(
            "AK09916 configured over I2C bypass: CNTL2=0x%02X (verified by readback)",
            readback,
        )
        return readback

    def readMode(self) -> int:
        """Read CNTL2 directly.

        US-565 AC-4 forbids ``adafruit_icm20x.magnetometer_data_rate`` as a
        verifier: that getter reads CNTL2 and then falls off the end of the
        function with no ``return``, so it reports None for every mode.

        Returns:
            The CNTL2 byte.
        """
        return self._readRegister(REG_CNTL2)

    # -- measurement -----------------------------------------------------------
    @property
    def lastDataReady(self) -> bool:
        """Whether the last read carried ST1.DRDY (a fresh conversion).

        Informational, NOT a verdict. Staleness belongs to the US-564 gate, which
        judges it with a dwell over consecutive samples; a second staleness
        authority here would be two acquisitions of one fact, and at 50 Hz
        polling against a 100 Hz conversion rate it would fire on jitter.
        """
        return self._lastDataReady

    @property
    def magnetic(self) -> tuple[float, float, float]:
        """Read one measurement in micro-teslas.

        Returns:
            ``(x, y, z)`` in uT.

        Raises:
            MagnetometerOverflowError: When ST2's overflow flag is set. The
                datasheet declares that data invalid, and publishing it would be
                another non-measurement wearing ``data_source='real'``. Raising
                routes the poll into the reader's existing failed-poll path
                rather than inventing a second silence mechanism.
        """
        frame = self._frame
        with self._device:
            self._device.write_then_readinto(bytes([FRAME_START_REGISTER]), frame)
        self._lastDataReady = bool(frame[0] & ST1_DRDY_MASK)
        if frame[REG_ST2 - FRAME_START_REGISTER] & ST2_OVERFLOW_MASK:
            raise MagnetometerOverflowError(
                "AK09916 reported measurement overflow (ST2.HOFL) -- the "
                "datasheet declares this data invalid"
            )
        base = REG_HXL - FRAME_START_REGISTER
        return (
            int.from_bytes(frame[base : base + 2], "little", signed=True) * UT_PER_LSB,
            int.from_bytes(frame[base + 2 : base + 4], "little", signed=True) * UT_PER_LSB,
            int.from_bytes(frame[base + 4 : base + 6], "little", signed=True) * UT_PER_LSB,
        )

    # -- internals -------------------------------------------------------------
    def _readRegister(self, register: int) -> int:
        """Read one register byte."""
        buffer = bytearray(1)
        with self._device:
            self._device.write_then_readinto(bytes([register]), buffer)
        return buffer[0]

    def _writeRegister(self, register: int, value: int) -> None:
        """Write one register byte, then honour the datasheet's mode transit."""
        import time

        with self._device:
            self._device.write(bytes([register, value]))
        time.sleep(_MODE_TRANSIT_SECONDS)


def enableI2cBypass(icm: Any) -> None:
    """Hand the magnetometer back to the primary bus.

    Order matters: the auxiliary master is disabled BEFORE bypass is enabled, so
    the ICM-20948 is never driving the auxiliary bus at the same moment the Pi is
    given access to it.

    Args:
        icm: A constructed ``adafruit_icm20x.ICM20948``.
    """
    icm._bank = 0  # noqa: SLF001 -- the driver exposes no public bypass control
    icm._i2c_master_enable = False  # noqa: SLF001
    icm._bypass_i2c_master = True  # noqa: SLF001


class Icm20948DirectMagnetometer:
    """An ICM-20948 whose magnetometer comes from the direct reader.

    A wrapper rather than an ImuReader change on purpose: this is a DEVICE-layer
    defect -- the chip was mis-acquired, not mis-published -- so the fix belongs
    at the device seam, and ``ImuReader._readAndPublish`` keeps reading a device
    with ``.acceleration`` / ``.gyro`` / ``.magnetic`` exactly as before.
    """

    def __init__(self, icm: Any, magnetometer: Ak09916Direct) -> None:
        """Bind an ICM handle to a direct magnetometer reader.

        Args:
            icm: The constructed ICM-20948, already in bypass mode.
            magnetometer: The configured direct AK09916 reader.
        """
        self._icm = icm
        self._magnetometer = magnetometer

    @property
    def acceleration(self) -> Any:
        """The ICM's own acceleration -- untouched by bypass."""
        return self._icm.acceleration

    @property
    def gyro(self) -> Any:
        """The ICM's own gyro -- untouched by bypass."""
        return self._icm.gyro

    @property
    def temperature(self) -> Any:
        """The ICM's temperature, propagating AttributeError when absent.

        A genuine ICM20948 has no ``.temperature`` (US-500) and ImuReader catches
        that to degrade temp to an honest null. Swallowing it into a default here
        would fabricate a temperature.
        """
        return self._icm.temperature

    @property
    def magnetic(self) -> tuple[float, float, float]:
        """The magnetometer, read directly rather than from the ICM's shadow."""
        return self._magnetometer.magnetic

    @property
    def magnetometer(self) -> Ak09916Direct:
        """The underlying direct reader (for mode verification)."""
        return self._magnetometer


def makeBypassMagnetometer(
    icm: Any, i2cBus: Any
) -> Icm20948DirectMagnetometer:  # pragma: no cover -- real-hardware glue (Pi only)
    """Put an ICM-20948 into bypass and wrap it with a direct magnetometer reader.

    Args:
        icm: A constructed ``adafruit_icm20x.ICM20948``.
        i2cBus: The primary I2C bus the ICM was constructed on.

    Returns:
        A device handle with the ICM's accel/gyro and a live magnetometer.

    Raises:
        MagnetometerConfigError: When the magnetometer cannot be identified or
            verified after bypass.
    """
    from adafruit_bus_device import i2c_device  # local import: optional off-Pi

    enableI2cBypass(icm)
    reader = Ak09916Direct(i2c_device.I2CDevice(i2cBus, AK09916_I2C_ADDRESS))
    reader.configure()
    return Icm20948DirectMagnetometer(icm, reader)
