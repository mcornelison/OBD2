################################################################################
# File Name: test_icm20948_direct.py
# Purpose/Description: ARCH-064 acquisition C -- clean-reset bypass, I2C master
#   NEVER enabled. Covers ``makeIcm20948Direct`` (master never turned on, bypass
#   precedes the mag read, accel scaling, a mag-only fault not raising out of
#   accel/gyro) and ``GyroRecoveryHandle`` (the A-34 gyro-latch recovery adapter
#   over the SparkFun handle).
# Author: Atlas (architect)
# Creation Date: 2026-09-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-28    | Atlas        | Initial (ARCH-064 Task 2).
# ================================================================================
################################################################################

"""ARCH-064 Task 2: ``Icm20948Direct`` + ``GyroRecoveryHandle`` unit tests."""

from __future__ import annotations

from pi.sensors.icm20948_direct import (
    ACCEL_DLPF_NEAR_50HZ,
    ACCEL_FS_4G,
    ACCEL_LSB_PER_G,
    GYRO_DLPF_NEAR_50HZ,
    GYRO_FS_500DPS,
    GYRO_LSB_PER_DPS,
    SAMPLE_MODE_CONTINUOUS,
    SENSORS_ACCEL_GYRO,
    G,
    GyroRecoveryHandle,
    Icm20948Direct,
    makeIcm20948Direct,
)


# --- Fakes (record every call; no real I2C anywhere in this file) -----------
class FakeIcm:
    """Mimics qwiic_icm20948.QwiicIcm20948 closely enough to drive the build
    sequence: every method call is recorded, and ``getAgmt`` sets the raw
    fields the SparkFun driver itself sets on the instance.

    axRaw/ayRaw/azRaw/gxRaw/gyRaw/gzRaw are set here as ALREADY-SIGNED Python
    ints -- the real driver's ``getAgmt()`` runs its own ``ToSignedInt`` on
    each of them before returning (qwiic_icm20948.py ~L679-687), so a fake
    that stored an unsigned 16-bit pattern instead would not match production
    and could hide a double sign-extension bug (see
    test_accelNegativeAxis_isNotDoubleSignExtended)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.address = 0x69
        self.axRaw = 0
        self.ayRaw = 0
        self.azRaw = 8192  # +1 g at +-4 g FS (ACCEL_LSB_PER_G)
        self.gxRaw = 0
        self.gyRaw = 0
        self.gzRaw = 0

    def __getattr__(self, name):
        def rec(*a):
            self.calls.append((name, a))
            return True

        return rec

    def getAgmt(self):
        self.calls.append(("getAgmt", ()))
        return True


class FakeAk:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.configureCalls = 0

    def configure(self):
        self.configureCalls += 1
        return 0x08

    @property
    def magnetic(self):
        if self.fail:
            raise OSError("121")
        return (1.0, 2.0, 3.0)


# --- Step 1 tests (from the task brief, verbatim in spirit) -----------------
def test_masterIsNeverEnabled_andPassthroughPrecedesTheMag() -> None:
    icm = FakeIcm()
    makeIcm20948Direct(lambda: icm, lambda: FakeAk())
    names = list(icm.calls)
    assert ("i2cMasterEnable", (True,)) not in names
    assert names.index(("swReset", ())) < names.index(("i2cMasterPassthrough", (True,)))


def test_accelIsScaledToMs2() -> None:
    dev = makeIcm20948Direct(lambda: FakeIcm(), lambda: FakeAk())
    assert abs(dev.acceleration[2] - G) < 1e-6


def test_magErrorDoesNotRaiseOutOfAccelOrGyro() -> None:  # Review Focus 1
    dev = makeIcm20948Direct(lambda: FakeIcm(), lambda: FakeAk(fail=True))
    assert dev.acceleration is not None and dev.gyro is not None


# --- Device identity + scaling ------------------------------------------------
def test_magSource_isDirect() -> None:
    dev = makeIcm20948Direct(lambda: FakeIcm(), lambda: FakeAk())
    assert dev.magSource == "direct"
    assert isinstance(dev, Icm20948Direct)


def test_gyroIsScaledToRadPerSec() -> None:
    icm = FakeIcm()
    icm.gxRaw = 655  # 10 dps at 65.5 LSB/dps -> ~0.1745 rad/s
    dev = makeIcm20948Direct(lambda: icm, lambda: FakeAk())
    import math

    assert dev.gyro[0] == math.radians(655 / GYRO_LSB_PER_DPS)


def test_accelNegativeAxis_isNotDoubleSignExtended() -> None:
    """The real ``getAgmt()`` already sign-extends axRaw/ayRaw/azRaw
    (qwiic_icm20948.py's own ``ToSignedInt``, run inside ``getAgmt`` itself --
    MEASURED by reading the installed module, ~L679-683). A CONSUMER that
    re-applies a 16-bit sign-extension to an already-signed negative value is
    not idempotent and corrupts it (e.g. treating -8192 as an unsigned 16-bit
    pattern would read it back as -73828). -8192 raw at +-4 g FS is exactly
    -1 g.
    """
    icm = FakeIcm()
    icm.azRaw = -8192
    dev = makeIcm20948Direct(lambda: icm, lambda: FakeAk())
    assert abs(dev.acceleration[2] - (-G)) < 1e-6


def test_gyroNegativeAxis_isNotDoubleSignExtended() -> None:
    """Same defect class as the accel case, on the gyro channel. -655 raw at
    65.5 LSB/dps is exactly -10.0 dps."""
    import math

    icm = FakeIcm()
    icm.gxRaw = -655
    dev = makeIcm20948Direct(lambda: icm, lambda: FakeAk())
    assert dev.gyro[0] == math.radians(-10.0)


def test_magneticReturnsTheRawAkFrame_readerAppliesToIcmFrame() -> None:
    """``.magnetic`` returns the RAW AK triple -- the reader (not this device)
    applies ``toIcmFrame`` (see sensor_reader.ImuReader._readAndPublish)."""
    dev = makeIcm20948Direct(lambda: FakeIcm(), lambda: FakeAk())
    assert dev.magnetic == (1.0, 2.0, 3.0)


def test_scalingConstants_matchDS_000189_forTheChosenRanges() -> None:
    """+-4 g / +-500 dps -- pinned so a range change is a visible test failure,
    not a silent scale drift (DS-000189)."""
    assert ACCEL_LSB_PER_G == 8192.0
    assert GYRO_LSB_PER_DPS == 65.5


# --- The build sequence uses the SparkFun module's NAMED constants ----------
def test_buildUsesNamedSparkFunConstants_notMagicNumbers() -> None:
    """The exported constants are MIRRORED from the installed
    ``qwiic_icm20948.py`` 2.0.1 (``sparkfun-qwiic-icm20948==2.0.1``), read
    2026-09-28: ``gpm4`` == 0x01, ``dps500`` == 0x01,
    ``ICM_20948_Sample_Mode_Continuous`` == 0x00, the accel+gyro sensor mask
    (``ICM_20948_Internal_Acc | ICM_20948_Internal_Gyr``) == 0x03, accel DLPF
    ``acc_d50bw4_n68bw8`` == 0x03 (50.4 Hz BW) and gyro DLPF
    ``gyr_d51bw2_n73bw3`` == 0x03 (51.2 Hz BW) -- the nearest-to-50-Hz option
    each table offers. This pins ``makeIcm20948Direct`` to the module's named
    constants (re-exported here, not retyped literals) rather than letting the
    call sites drift back to unexplained ints.
    """
    icm = FakeIcm()
    makeIcm20948Direct(lambda: icm, lambda: FakeAk())
    byName = dict(icm.calls)

    assert SENSORS_ACCEL_GYRO == 0x03
    assert SAMPLE_MODE_CONTINUOUS == 0x00
    assert ACCEL_FS_4G == 0x01
    assert GYRO_FS_500DPS == 0x01
    assert ACCEL_DLPF_NEAR_50HZ == 0x03
    assert GYRO_DLPF_NEAR_50HZ == 0x03

    assert byName["setSampleMode"] == (SENSORS_ACCEL_GYRO, SAMPLE_MODE_CONTINUOUS)
    assert byName["setFullScaleRangeAccel"] == (ACCEL_FS_4G,)
    assert byName["setFullScaleRangeGyro"] == (GYRO_FS_500DPS,)
    assert byName["setDLPFcfgAccel"] == (ACCEL_DLPF_NEAR_50HZ,)
    assert byName["setDLPFcfgGyro"] == (GYRO_DLPF_NEAR_50HZ,)
    assert byName["enableDlpfAccel"] == (True,)
    assert byName["enableDlpfGyro"] == (True,)


def test_akConfiguredAfterBypassEnabled() -> None:
    """``ak.configure()`` (WIA2 check + CNTL2 verify) must run only once the
    primary bus can actually reach 0x0C -- i.e. after i2cMasterPassthrough(True)."""
    icm = FakeIcm()
    ak = FakeAk()
    makeIcm20948Direct(lambda: icm, lambda: ak)
    names = [c[0] for c in icm.calls]
    assert names.index("i2cMasterPassthrough") < len(names)
    assert ak.configureCalls == 1


# --- GyroRecoveryHandle (decision 3): adapts the SparkFun handle to ----------
# --- gyro_recovery.recoverGyroIfFaulted's minimal interface. ----------------
class _FakeI2cDriver:
    def __init__(self) -> None:
        self.writeByteCalls: list[tuple[int, int, int]] = []

    def writeByte(self, address, register, value):
        self.writeByteCalls.append((address, register, value))
        return True


class _FakeSparkFunIcm:
    """A SparkFun-shaped fake: setBank + getAgmt + the underlying _i2c driver
    the real writes go through (see qwiic_icm20948.QwiicIcm20948.setBank /
    i2cMasterEnable, which call ``self._i2c.writeByte(self.address, reg, val)``).

    ``getAgmt`` hands back gxRaw/gyRaw/gzRaw as ALREADY-SIGNED Python ints,
    same real-driver contract as ``FakeIcm`` above -- ``_dpsToRaw`` below
    produces a signed value directly (``round(-20.0 * 65.5) == -1310``), never
    an unsigned 16-bit pattern."""

    def __init__(self, gyroTriples: list[tuple[float, float, float]]) -> None:
        self.address = 0x69
        self._i2c = _FakeI2cDriver()
        self.bankCalls: list[int] = []
        self._gyroTriples = iter(gyroTriples)
        self.gxRaw = self.gyRaw = self.gzRaw = 0

    def setBank(self, bank):
        self.bankCalls.append(bank)
        return True

    def getAgmt(self):
        self.gxRaw, self.gyRaw, self.gzRaw = next(self._gyroTriples)
        return True


def _dpsToRaw(dps: float) -> int:
    return round(dps * GYRO_LSB_PER_DPS)


def test_gyroRecoveryHandle_exposesGyroInRadPerSecond() -> None:
    import math

    icm = _FakeSparkFunIcm([( _dpsToRaw(20.0), 0, 0)])
    handle = GyroRecoveryHandle(icm)
    assert handle.gyro[0] == math.radians(20.0)


def test_gyroRecoveryHandle_negativeAxis_isNotDoubleSignExtended() -> None:
    """Same real-driver contract as Icm20948Direct.gyro: getAgmt() already
    hands back a signed int, so GyroRecoveryHandle must not re-sign-extend
    it either."""
    import math

    icm = _FakeSparkFunIcm([(_dpsToRaw(-20.0), 0, 0)])
    handle = GyroRecoveryHandle(icm)
    assert handle.gyro[0] == math.radians(-20.0)


def test_gyroRecoveryHandle_bankSetterCallsSetBank() -> None:
    icm = _FakeSparkFunIcm([(0, 0, 0)])
    handle = GyroRecoveryHandle(icm)
    handle._bank = 0
    assert icm.bankCalls == [0]


def test_gyroRecoveryHandle_i2cDeviceWritesThroughTheSparkFunDriver() -> None:
    """``.i2c_device`` must be usable as a context manager whose ``.write``
    lands a two-byte register write through the SparkFun handle's own I2C
    driver (gyro_recovery.py:114-122)."""
    icm = _FakeSparkFunIcm([(0, 0, 0)])
    handle = GyroRecoveryHandle(icm)
    with handle.i2c_device as device:
        device.write(bytes([0x07, 0x07]))
    assert icm._i2c.writeByteCalls == [(0x69, 0x07, 0x07)]


def test_gyroRecoveryHandle_recoverGyroIfFaulted_writesPwrMgmt2() -> None:
    """Decision 3's required test: a faulted-looking gyro drives
    ``recoverGyroIfFaulted`` to power-cycle PWR_MGMT_2 (0x07) THROUGH THE
    SPARKFUN HANDLE, via the adapter -- off (0x07) then back on (0x00)."""
    from pi.sensors.gyro_recovery import (
        PWR_MGMT_2_ALL_ON,
        PWR_MGMT_2_GYRO_OFF,
        REG_PWR_MGMT_2,
        recoverGyroIfFaulted,
    )

    faulted = (_dpsToRaw(20.0), 0, 0)  # >> GYRO_FAULT_MIN_RAD_S
    healthy = (0, 0, 0)
    # 2 startup samples, 2 post-recovery samples -- keep the test fast.
    icm = _FakeSparkFunIcm([faulted, faulted, healthy, healthy])
    handle = GyroRecoveryHandle(icm)

    outcome = recoverGyroIfFaulted(handle, sampleCount=2, settleS=0.0)

    assert outcome.recovered is True
    assert icm._i2c.writeByteCalls == [
        (0x69, REG_PWR_MGMT_2, PWR_MGMT_2_GYRO_OFF),
        (0x69, REG_PWR_MGMT_2, PWR_MGMT_2_ALL_ON),
    ]


# --- Ruling 35 / I5: settle after swReset, and before the A-34 sampling ------
#
# SparkFun's own startupDefault() waits 50 ms between swReset() and
# sleep(false) (ICM_20948.cpp, DOCUMENTED), and the reference reader that
# proved direct mode live did the same. Writing to a chip mid-reset can be
# lost. The sleeps are injected, so the ORDER is asserted, not just the delay.


class _Clock:
    """Records sleeps into the SAME call log as the fake ICM."""

    def __init__(self, icm: FakeIcm) -> None:
        self.icm = icm

    def sleep(self, seconds: float) -> None:
        self.icm.calls.append(("<sleep>", (seconds,)))


def test_i5_resetIsFollowedBySettle_beforeAnyOtherWrite() -> None:
    from pi.sensors.icm20948_direct import RESET_SETTLE_S

    icm = FakeIcm()
    makeIcm20948Direct(lambda: icm, lambda: FakeAk(), sleepFn=_Clock(icm).sleep)
    names = [c[0] for c in icm.calls]
    reset = names.index("swReset")
    assert icm.calls[reset + 1] == ("<sleep>", (RESET_SETTLE_S,))
    assert names.index("sleep") == reset + 2  # the chip's sleep(False), AFTER the wait
    assert RESET_SETTLE_S >= 0.05


def test_i5_defaultResetSettle_isFiftyMilliseconds() -> None:
    from pi.sensors.icm20948_direct import RESET_SETTLE_S

    assert RESET_SETTLE_S == 0.05


def test_i5_settleBeforeRecoverySampling_isTheLastThingTheBuildDoes() -> None:
    """The A-34 recovery samples the gyro the moment the build returns; the
    gyro must have started up and the DLPF filled first."""
    from pi.sensors.icm20948_direct import GYRO_SETTLE_S

    icm = FakeIcm()
    log = icm.calls

    class _RecordingAk(FakeAk):
        def configure(self):
            log.append(("akConfigure", ()))
            return 0x08

    makeIcm20948Direct(lambda: icm, lambda: _RecordingAk(), sleepFn=_Clock(icm).sleep)
    assert log[-1] == ("<sleep>", (GYRO_SETTLE_S,))
    assert log[-2] == ("akConfigure", ())
    assert GYRO_SETTLE_S > 0.0


def test_i5_defaultSleep_isRealTimeSleep(monkeypatch) -> None:
    """Without an injected sleep the build really waits (production path)."""
    import pi.sensors.icm20948_direct as direct

    slept: list[float] = []
    monkeypatch.setattr(direct.time, "sleep", slept.append)
    makeIcm20948Direct(lambda: FakeIcm(), lambda: FakeAk())
    assert slept == [direct.RESET_SETTLE_S, direct.GYRO_SETTLE_S]


# --- ARCH-066: chip temperature (temp_c was NULL in every row) -----------------
# DOCUMENTED, DS-000189 v1.3: TEMP_OUT_H/L at bank 0 0x39/0x3A (p.32), and
# TEMP_degC = ((TEMP_OUT - RoomTemp_Offset) / Temp_Sensitivity) + 21 (p.45), with
# RoomTemp_Offset 0 LSB and Temp_Sensitivity 333.87 LSB/degC (p.14).
# MEASURED on the car 2026-10-04: raw 1264..1424 -> 24.8..25.3 degC.
# 🔴 SparkFun's getAgmt() sign-converts accel and gyro but NOT tmpRaw
# (qwiic_icm20948.py L671 vs L681-687), so the fake stores tmpRaw UNSIGNED.
def test_temperature_convertsTempOutPerDS000189() -> None:
    icm = FakeIcm()
    icm.tmpRaw = 1408  # MEASURED on the car: 25.22 degC
    dev = makeIcm20948Direct(lambda: icm, lambda: FakeAk())
    assert abs(dev.temperature - (1408 / 333.87 + 21.0)) < 1e-9
    assert abs(dev.temperature - 25.217) < 0.01


def test_temperature_belowRoomTemp_isSignedNotWrapped() -> None:
    """A cold cabin gives a NEGATIVE TEMP_OUT. Unsigned, -3339 (about 11 degC)
    would read 0xF2F5 = 62197 -> 207 degC: a plausible-looking wrong number."""
    icm = FakeIcm()
    icm.tmpRaw = (-3339) & 0xFFFF
    dev = makeIcm20948Direct(lambda: icm, lambda: FakeAk())
    assert abs(dev.temperature - (-3339 / 333.87 + 21.0)) < 1e-9
    assert dev.temperature < 12.0


def test_temperature_constantsMatchDS000189() -> None:
    from pi.sensors.icm20948_direct import TEMP_ROOM_OFFSET_LSB, TEMP_SENSITIVITY_LSB_PER_C

    assert TEMP_SENSITIVITY_LSB_PER_C == 333.87
    assert TEMP_ROOM_OFFSET_LSB == 0.0
