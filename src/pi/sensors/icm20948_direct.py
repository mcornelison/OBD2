################################################################################
# File Name: icm20948_direct.py
# Purpose/Description: ARCH-064 acquisition C -- the ICM-20948 configured from a
#   CLEAN SOFTWARE RESET, with the internal I2C master NEVER enabled, and the
#   AK09916 magnetometer read directly in bypass per its own datasheet.
#
#   MEASURED on the real hardware, 2026-09-28: with the ICM-20948's internal I2C
#   master enabled -- the path both the adafruit AND the SparkFun libraries use
#   by default -- the AK09916 freezes after exactly one reading, even with every
#   other project process stopped. Switching to bypass AFTER the master has
#   already run can hang the whole I2C bus (a second, worse failure mode).
#   Reading the AK09916 directly in bypass from a clean reset, and never
#   enabling the master at all, is live at 100 Hz.
#
#   This module owns ONLY the device build (configure + read). It does NOT read
#   the AK09916's raw frame off the wire -- that is ``ak09916_bypass.Ak09916Direct``
#   (US-565, datasheet-correct ST1..ST2 burst) -- and it does NOT map the AK
#   frame into the ICM frame -- ``.magnetic`` here returns the RAW AK triple, and
#   ``sensor_reader.ImuReader._readAndPublish`` applies ``toIcmFrame`` at the one
#   seam where every acquisition path converges (see ak09916_bypass.py header).
#
#   ``GyroRecoveryHandle`` is a second, small adapter: A-34's latched-gyro
#   recovery (``pi.sensors.gyro_recovery.recoverGyroIfFaulted``) was written
#   against the adafruit driver's ``.gyro`` / ``._bank`` / ``.i2c_device``
#   surface. It needs to keep running in mode "direct" too -- a faulted gyro
#   latches at a constant offset regardless of which library configured the
#   chip -- so this adapter translates that same three-property contract onto
#   the SparkFun primitives (``setBank`` + the qwiic I2C driver's ``writeByte``)
#   rather than duplicating the recovery logic.
# Author: Atlas (architect)
# Creation Date: 2026-09-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-28    | Atlas        | Initial (ARCH-064 Task 2) -- Icm20948Direct,
#               | (ARCH-064)   | makeIcm20948Direct, GyroRecoveryHandle.
# 2026-09-28    | Atlas        | Final review I5: injectable settle after
#               | (ARCH-064)   | swReset (50 ms) and before A-34 sampling.
# ================================================================================
################################################################################

"""ARCH-064 acquisition C: ICM-20948 configured from a clean reset, I2C master
NEVER enabled, AK09916 read directly in bypass per its datasheet. MEASURED
2026-09-28: master mode freezes the AK09916 on this board under adafruit AND
SparkFun with all other project software stopped."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

__all__ = [
    "ACCEL_DLPF_NEAR_50HZ",
    "ACCEL_FS_4G",
    "ACCEL_LSB_PER_G",
    "G",
    "GYRO_DLPF_NEAR_50HZ",
    "GYRO_FS_500DPS",
    "GYRO_LSB_PER_DPS",
    "GYRO_SETTLE_S",
    "RESET_SETTLE_S",
    "MAG_SOURCE_DIRECT",
    "SAMPLE_MODE_CONTINUOUS",
    "SENSORS_ACCEL_GYRO",
    "GyroRecoveryHandle",
    "Icm20948Direct",
    "makeIcm20948Direct",
]

G = 9.80665
# DS-000189 (TDK ICM-20948 datasheet) sensitivity tables for the ranges this
# module configures (+-4 g / +-500 dps -- see makeIcm20948Direct). Kept as
# constants here, alongside the range selection, so the two can never drift
# apart independently.
ACCEL_LSB_PER_G = 8192.0  # +-4 g (DS-000189 SS3.2)
GYRO_LSB_PER_DPS = 65.5  # +-500 dps (DS-000189 SS3.1)
MAG_SOURCE_DIRECT = "direct"

# ---------------------------------------------------------------------------
# SparkFun ``qwiic_icm20948`` 2.0.1's OWN named constants, MIRRORED here by
# value rather than imported. MEASURED 2026-09-28 by reading the installed
# module (``sparkfun-qwiic-icm20948==2.0.1``, ``qwiic_icm20948.py``):
#
#     ICM_20948_Internal_Acc         = 1 << 0 = 0x01
#     ICM_20948_Internal_Gyr         = 1 << 1 = 0x02
#     ICM_20948_Sample_Mode_Continuous               = 0x00
#     gpm4    (accel full-scale, +-4 g)              = 0x01
#     dps500  (gyro full-scale, +-500 dps)            = 0x01
#     acc_d50bw4_n68bw8  (accel DLPF, 50.4 Hz 3 dB BW) = 0x03
#     gyr_d51bw2_n73bw3  (gyro DLPF, 51.2 Hz 3 dB BW)  = 0x03
#
# Mirrored rather than ``import qwiic_icm20948`` so this module -- and its
# unit tests, which drive it entirely with fakes -- never require the
# SparkFun package to be importable. Only the Pi-only factory
# (``sensor_reader._makeIcm20948Direct``) imports ``qwiic_icm20948`` itself,
# lazily, to construct the real device.
SENSORS_ACCEL_GYRO = 0x01 | 0x02  # ICM_20948_Internal_Acc | ICM_20948_Internal_Gyr
SAMPLE_MODE_CONTINUOUS = 0x00  # ICM_20948_Sample_Mode_Continuous
ACCEL_FS_4G = 0x01  # gpm4
GYRO_FS_500DPS = 0x01  # dps500
ACCEL_DLPF_NEAR_50HZ = 0x03  # acc_d50bw4_n68bw8 -- 50.4 Hz 3 dB BW
GYRO_DLPF_NEAR_50HZ = 0x03  # gyr_d51bw2_n73bw3 -- 51.2 Hz 3 dB BW

# ARCH-064 Ruling 35 (I5). DOCUMENTED: SparkFun's own ICM_20948::startupDefault()
# waits ``delay(50)`` between swReset() and sleep(false), and the reference
# reader that proved direct mode live on this board slept 0.05 s there too. A
# write issued while the chip is still resetting can be dropped silently, and
# nothing downstream would notice -- the registers would simply hold defaults.
RESET_SETTLE_S = 0.05
# Settle between the end of configuration and the caller's first gyro read --
# the A-34 recovery samples the gyro the instant the build returns, and a
# just-woken gyro behind a freshly-enabled DLPF is not yet a measurement.
# 0.1 s is well past the DLPF's time constant at ~51 Hz; the datasheet's gyro
# start-up time row is not legible in our text extraction (RECALLED ~35 ms).
GYRO_SETTLE_S = 0.1


class Icm20948Direct:
    """ICM-20948 accel/gyro + directly-read AK09916, built from a clean reset
    with the I2C master never enabled (ARCH-064 acquisition C).

    Single-threaded by contract, like every other device handle in this
    package: only the owning reader's poll thread calls into it.
    """

    magSource = MAG_SOURCE_DIRECT

    def __init__(self, icm: Any, ak: Any) -> None:
        """Bind to an already-configured pair.

        Args:
            icm: A SparkFun ``QwiicIcm20948``-shaped handle, already reset and
                configured by :func:`makeIcm20948Direct`.
            ak: An ``ak09916_bypass.Ak09916Direct``-shaped handle, already
                configured (WIA2 verified, CNTL2 verified by readback).
        """
        self._icm, self._ak = icm, ak

    def _read(self) -> None:
        """Refresh the ICM's accel/gyro/temp burst (one I2C block read)."""
        self._icm.getAgmt()

    @property
    def acceleration(self) -> tuple[float, float, float]:
        """(x, y, z) m/s^2. Reads a fresh burst; ``.gyro`` reuses it (below).

        ``getAgmt()`` (qwiic_icm20948.py) already runs its own
        ``ToSignedInt`` on axRaw/ayRaw/azRaw before returning -- MEASURED by
        reading the installed module (~L679-683) -- so these are trusted as
        already-signed and only SCALED here. Re-sign-extending an
        already-signed value is not idempotent (it corrupts every negative
        axis); see test_accelNegativeAxis_isNotDoubleSignExtended.
        """
        self._read()
        i = self._icm
        return tuple(r / ACCEL_LSB_PER_G * G for r in (i.axRaw, i.ayRaw, i.azRaw))

    @property
    def gyro(self) -> tuple[float, float, float]:
        """(x, y, z) rad/s, from the SAME getAgmt burst as ``.acceleration``.

        Relies on the reader calling accel before gyro each poll (as
        ``sensor_reader.ImuReader._readAndPublish`` does) -- issuing a second
        I2C burst here would cost a transaction for no benefit. gxRaw/gyRaw/
        gzRaw are already signed by ``getAgmt()`` itself -- see
        ``.acceleration``'s docstring above -- and only scaled here.
        """
        i = self._icm
        return tuple(math.radians(r / GYRO_LSB_PER_DPS) for r in (i.gxRaw, i.gyRaw, i.gzRaw))

    @property
    def magnetic(self) -> tuple[float, float, float]:
        """(x, y, z) uT, in the RAW AK09916 frame.

        Deliberately NOT re-expressed into the ICM frame here -- that
        conversion (``ak09916_bypass.toIcmFrame``) is applied ONCE, at the
        seam in ``sensor_reader`` where every acquisition path converges, so
        this path and the master/bypass paths cannot disagree about which way
        the field points. See ``ak09916_bypass.toIcmFrame``'s docstring.

        Raises:
            Whatever ``ak.magnetic`` raises (OSError on the real bus,
            ``MagnetometerOverflowError`` on ST2.HOFL) -- propagated, never
            swallowed, so the caller (the reader) decides how a mag-only
            fault degrades. See Review Focus 1 in the task brief.
        """
        return self._ak.magnetic


def makeIcm20948Direct(
    icmFactory: Callable[[], Any],
    akFactory: Callable[[], Any],
    *,
    sleepFn: Callable[[float], None] | None = None,
) -> Icm20948Direct:
    """Configure the ICM-20948 from a clean software reset and hand back a
    device that never once enables the internal I2C master.

    Ordering is the whole point (MEASURED 2026-09-28): ``swReset`` first, then
    the accel/gyro configuration while the auxiliary bus is still quiescent,
    then ``i2cMasterEnable(False)`` (belt-and-braces -- a fresh reset already
    has the master off) followed immediately by ``i2cMasterPassthrough(True)``.
    ``i2cMasterEnable`` -- on the installed SparkFun driver -- clears
    BYPASS_EN as a side effect of the master-mode setup it performs even when
    disabling, so it MUST run before, not after, passthrough is enabled; the
    reverse order would silently re-close bypass.

    Args:
        icmFactory: Returns the SparkFun ``QwiicIcm20948`` handle (injectable
            for tests -- production passes a lambda that constructs the real
            one at 0x69).
        akFactory: Returns the ``ak09916_bypass.Ak09916Direct`` handle bound to
            0x0C on the primary bus (injectable for tests).
        sleepFn: Injection seam for the two settles (RESET_SETTLE_S after
            ``swReset``; GYRO_SETTLE_S before returning, so the A-34 recovery
            never samples a gyro that has not started). Defaults to
            ``time.sleep``, looked up at call time.

    Returns:
        The configured :class:`Icm20948Direct`.
    """
    pause = sleepFn if sleepFn is not None else time.sleep
    icm = icmFactory()
    icm.swReset()
    pause(RESET_SETTLE_S)  # I5: SparkFun startupDefault's delay(50)
    icm.sleep(False)
    icm.lowPower(False)

    # +-4 g / +-500 dps, DLPF enabled at the nearest-to-50-Hz bandwidth each
    # table offers -- qwiic's own named values, mirrored above (see
    # test_buildUsesNamedSparkFunConstants_notMagicNumbers, which pins these
    # against the values read from the installed library rather than
    # allowing them to drift back into unexplained literals).
    icm.setSampleMode(SENSORS_ACCEL_GYRO, SAMPLE_MODE_CONTINUOUS)
    icm.setFullScaleRangeAccel(ACCEL_FS_4G)
    icm.setFullScaleRangeGyro(GYRO_FS_500DPS)
    icm.setDLPFcfgAccel(ACCEL_DLPF_NEAR_50HZ)
    icm.setDLPFcfgGyro(GYRO_DLPF_NEAR_50HZ)
    icm.enableDlpfAccel(True)
    icm.enableDlpfGyro(True)

    # NEVER True in mode "direct" -- see module header. Master first (also
    # clears any stale BYPASS_EN from a prior run), bypass second.
    icm.i2cMasterEnable(False)
    icm.i2cMasterPassthrough(True)

    ak = akFactory()
    ak.configure()  # WIA2 identity check, CNTL2 0x00 -> 0x08, verified by readback
    pause(GYRO_SETTLE_S)  # I5: before the caller's A-34 gyro sampling
    return Icm20948Direct(icm, ak)


class GyroRecoveryHandle:
    """Adapts a SparkFun ``QwiicIcm20948`` handle to the minimal interface
    ``gyro_recovery.recoverGyroIfFaulted`` needs (A-34): a ``.gyro`` triple in
    rad/s, a settable ``._bank``, and an ``.i2c_device`` usable as a context
    manager whose ``.write(bytes([reg, value]))`` lands a bank-0 register
    write (gyro_recovery.py:107-122 owns the write sequence and the
    verify-by-resampling contract; this class only translates it onto SparkFun
    primitives -- there is no ``i2c_device`` abstraction on that driver, so the
    write goes through its own I2C driver's ``writeByte`` directly, the same
    way ``makeIcm20948Direct`` reaches every other register).

    A-34 must keep running in mode "direct": a faulted gyro latches at a
    constant offset regardless of which library configured the chip, and
    nothing downstream (pitch_fusion, US-749's plausibility guard) can learn
    the fault away on its own. Called AFTER ``makeIcm20948Direct`` has
    finished (bypass enabled, AK configured) -- ARCH-032's ordering finding
    applies here too: see ``sensor_reader._buildImuDeviceDirect``.
    """

    def __init__(self, icm: Any) -> None:
        self._icm = icm

    @property
    def gyro(self) -> tuple[float, float, float]:
        """A fresh gyro triple in rad/s (triggers its own getAgmt burst).

        gxRaw/gyRaw/gzRaw are already signed by ``getAgmt()`` itself -- see
        ``Icm20948Direct.acceleration``'s docstring -- and only scaled here.
        """
        icm = self._icm
        icm.getAgmt()
        return tuple(
            math.radians(r / GYRO_LSB_PER_DPS) for r in (icm.gxRaw, icm.gyRaw, icm.gzRaw)
        )

    @property
    def _bank(self) -> None:  # pragma: no cover -- write-only, never read back
        """Write-only by contract (gyro_recovery only ever assigns ``icm._bank
        = 0``); a getter is provided so the attribute exists as a property."""
        return None

    @_bank.setter
    def _bank(self, bank: int) -> None:
        self._icm.setBank(bank)

    @property
    def i2c_device(self) -> GyroRecoveryHandle:
        """Self-as-context-manager: no separate device object exists on the
        SparkFun driver, so this adapter plays both roles."""
        return self

    def __enter__(self) -> GyroRecoveryHandle:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def write(self, data: bytes) -> None:
        """Write ``[register, value]`` through the SparkFun handle's own I2C
        driver -- the same primitive ``QwiicIcm20948.setBank``/
        ``i2cMasterEnable``/etc use internally (``self._i2c.writeByte``)."""
        register, value = data[0], data[1]
        self._icm._i2c.writeByte(self._icm.address, register, value)  # noqa: SLF001
