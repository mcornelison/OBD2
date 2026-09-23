"""ARCH-027: an independent probe of the ICM-20948 / AK09916, for RCA.

Independent is the point. This module re-derives what the sensor is doing from
raw registers and raw samples, so its answers can be compared against what
`src/pi/sensors/` publishes. It deliberately shares no code with the pipeline it
is auditing: a shared helper would make both agree about a mistake.

Two halves:

* **Pure** (decode, classify, arithmetic) -- unit tested on any machine.
* **Bus-facing** (`read*`, `gyroPowerCycle`) -- needs real hardware and root of
  the I2C bus. `smbus2` is imported lazily inside those functions so importing
  this module on a dev box costs nothing and needs no dependency.

Register semantics: ICM-20948 datasheet rev 1.5. Bank-2 `ACCEL_CONFIG` (0x14)
and `GYRO_CONFIG_1` (0x01) carry DLPF config, full-scale select and FCHOICE.

SAFETY: every bus-facing function here assumes it OWNS the sensor. Stop
`eclipse-obd` first, or two masters will interleave bank switches and both will
read nonsense. See `ownsBus()`.
"""

from __future__ import annotations

import math
import statistics
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

# --------------------------------------------------------------------------
# Register map (only what this probe touches)
# --------------------------------------------------------------------------

ADDR_IMU = 0x69
REG_BANK_SEL = 0x7F

# Bank 0
REG_WHO_AM_I = 0x00
WHO_AM_I_ICM20948 = 0xEA
REG_PWR_MGMT_1 = 0x06
REG_PWR_MGMT_2 = 0x07
REG_ACCEL_XOUT_H = 0x2D  # 12 bytes: accel xyz, gyro xyz
REG_TEMP_OUT_H = 0x39

# Bank 1: factory self-test OTP codes, three consecutive registers per block.
REG_SELF_TEST_X_GYRO = 0x02
REG_SELF_TEST_X_ACCEL = 0x0E

# Bank 2
REG_GYRO_SMPLRT_DIV = 0x00
REG_GYRO_CONFIG_1 = 0x01
REG_GYRO_CONFIG_2 = 0x02
REG_ACCEL_SMPLRT_DIV_1 = 0x10
REG_ACCEL_SMPLRT_DIV_2 = 0x11
REG_ACCEL_CONFIG = 0x14
REG_ACCEL_CONFIG_2 = 0x15

# Self-test enable bits, bank 2 CONFIG_2 registers: all three axes at once.
BIT_GYRO_CTEN = 0x38
BIT_ACCEL_CTEN = 0x1C

# Vendor self-test setup: gyro +/-250 dps and accel +/-16 g, DLPF engaged.
SELF_TEST_GYRO_CONFIG = (0 << 3) | 1
SELF_TEST_ACCEL_CONFIG = (7 << 3) | 1
SELF_TEST_SAMPLES = 200
SELF_TEST_SETTLE_S = 0.02
SELF_TEST_SAMPLE_INTERVAL_S = 0.01

# AK09916 magnetometer, addressed directly at 0x0C through the ICM's I2C bypass.
MAG_ADDRESS = 0x0C
MAG_REG_ST1 = 0x10
MAG_REG_HXL = 0x11
MAG_UT_PER_LSB = 0.15
MAG_ST1_DRDY_MASK = 0x01
MAG_ST2_OVERFLOW_MASK = 0x08

# Earth's total field at this latitude, for judging whether a reading is sane.
EARTH_FIELD_REFERENCE_UT = 52.0

# PWR_MGMT_2: three bits per block. 0x07 disables all three axes of one block.
PWR_MGMT_2_GYRO_OFF = 0x07
PWR_MGMT_2_ALL_ON = 0x00

BASE_SAMPLE_RATE_HZ = 1125.0

# 3 dB bandwidths by DLPFCFG, datasheet tables 16 (accel) and 17 (gyro).
_ACCEL_DLPF_BANDWIDTH_HZ = {0: 246.0, 1: 246.0, 2: 111.4, 3: 50.4, 4: 23.9, 5: 11.5, 6: 5.7, 7: 473.0}
_GYRO_DLPF_BANDWIDTH_HZ = {0: 196.6, 1: 151.8, 2: 119.5, 3: 51.2, 4: 23.9, 5: 11.6, 6: 5.7, 7: 361.4}

_ACCEL_FULL_SCALE_G = {0: 2, 1: 4, 2: 8, 3: 16}
_ACCEL_LSB_PER_G = {2: 16384, 4: 8192, 8: 4096, 16: 2048}
_GYRO_FULL_SCALE_DPS = {0: 250, 1: 500, 2: 1000, 3: 2000}
_GYRO_LSB_PER_DPS = {250: 131.0, 500: 65.5, 1000: 32.8, 2000: 16.4}

# Gyro health cut. Measured bimodal: quiet minutes 0.013-0.015 rad/s, faulted
# 0.487-0.553, and NOTHING in between across 10,313 classified minutes. The two
# thresholds are deliberately not one threshold: a reading in the empty gap is
# unclassifiable, and saying so beats guessing "healthy".
GYRO_HEALTHY_MAX_RAD_S = 0.02
GYRO_FAULT_MIN_RAD_S = 0.10

# InvenSense self-test constants, taken from their own driver (Icm20948SelfTest.c)
# rather than recalled: ST_OTP = 2620 / 2^FS * 1.01^(code - 1), bounds 0.5x/1.5x.
# The driver also uses 200 averaged samples and a 20 ms settle after enabling the
# self-test bits; those belong to the bus-facing routine, not here.
SELF_TEST_BASE_CONSTANT = 2620.0
SELF_TEST_STEP = 1.01
SELF_TEST_LOWER_BOUND_RATIO = 0.5
SELF_TEST_UPPER_BOUND_RATIO = 1.5

GyroHealth = Literal["healthy", "faulted", "indeterminate"]


# --------------------------------------------------------------------------
# Pure: configuration decode
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AccelConfig:
    """Decoded bank-2 ACCEL_CONFIG (0x14)."""

    raw: int
    fullScaleG: int
    lsbPerG: int
    dlpfEnabled: bool
    dlpfConfig: int
    bandwidthHz: float


@dataclass(frozen=True)
class GyroConfig:
    """Decoded bank-2 GYRO_CONFIG_1 (0x01)."""

    raw: int
    fullScaleDps: int
    lsbPerDps: float
    dlpfEnabled: bool
    dlpfConfig: int
    bandwidthHz: float


def decodeAccelConfig(value: int) -> AccelConfig:
    """Decode ACCEL_CONFIG. Bits [5:3] DLPFCFG, [2:1] FS_SEL, [0] FCHOICE.

    FCHOICE == 1 means the filter is ENGAGED (not bypassed). Our live sensor
    reads 0x05: DLPF engaged, config 0, which is its WIDEST setting at 246 Hz.
    """
    dlpfConfig = (value >> 3) & 0x07
    fullScaleG = _ACCEL_FULL_SCALE_G[(value >> 1) & 0x03]
    dlpfEnabled = bool(value & 0x01)
    return AccelConfig(
        raw=value,
        fullScaleG=fullScaleG,
        lsbPerG=_ACCEL_LSB_PER_G[fullScaleG],
        dlpfEnabled=dlpfEnabled,
        dlpfConfig=dlpfConfig,
        bandwidthHz=_ACCEL_DLPF_BANDWIDTH_HZ[dlpfConfig],
    )


def decodeGyroConfig(value: int) -> GyroConfig:
    """Decode GYRO_CONFIG_1. Bits [5:3] DLPFCFG, [2:1] FS_SEL, [0] FCHOICE."""
    dlpfConfig = (value >> 3) & 0x07
    fullScaleDps = _GYRO_FULL_SCALE_DPS[(value >> 1) & 0x03]
    return GyroConfig(
        raw=value,
        fullScaleDps=fullScaleDps,
        lsbPerDps=_GYRO_LSB_PER_DPS[fullScaleDps],
        dlpfEnabled=bool(value & 0x01),
        dlpfConfig=dlpfConfig,
        bandwidthHz=_GYRO_DLPF_BANDWIDTH_HZ[dlpfConfig],
    )


def odrHzFromDivider(divider: int) -> float:
    """Output data rate = 1125 / (1 + divider)."""
    return BASE_SAMPLE_RATE_HZ / (1 + divider)


def aliasingRisk(bandwidthHz: float, sampleHz: float) -> bool:
    """True when signal bandwidth exceeds Nyquist for the rate we actually keep.

    Content above sampleHz/2 does not vanish; it folds down and is
    indistinguishable from real low-frequency motion once recorded.
    """
    return bandwidthHz > (sampleHz / 2.0)


# --------------------------------------------------------------------------
# Pure: classification
# --------------------------------------------------------------------------


def classifyGyroHealth(meanRatesRadS: Sequence[float]) -> GyroHealth:
    """Classify a gyro mean-rate vector taken over a CONFIRMED-STATIONARY window.

    The caller owns the stillness precondition. A car turning at 30 deg/s is
    indistinguishable from the fault to this function, by construction, because
    the fault is exactly "a stationary sensor reporting rotation".
    """
    peak = max(abs(rate) for rate in meanRatesRadS)
    if peak >= GYRO_FAULT_MIN_RAD_S:
        return "faulted"
    if peak <= GYRO_HEALTHY_MAX_RAD_S:
        return "healthy"
    return "indeterminate"


def selfTestRatio(response: float, factoryTrim: float) -> float | None:
    """Self-test response as a fraction of the factory OTP value.

    Returns None when the trim is zero -- an unprogrammed or unread OTP is an
    ABSENCE, and returning a number there would fabricate a verdict.
    """
    if factoryTrim == 0:
        return None
    return abs(response) / abs(factoryTrim)


def stOtpFromCode(code: int, fullScaleSelect: int = 0) -> float:
    """Factory self-test trim from the OTP code: 2620 / 2^FS * 1.01^(code - 1).

    Verified against InvenSense's own driver (`Icm20948SelfTest.c`), which ships
    this as a 256-entry precomputed table. Code 0 means the OTP was never
    programmed, which is zero -- not 2620/1.01.
    """
    if code <= 0:
        return 0.0
    return (SELF_TEST_BASE_CONSTANT / (2**fullScaleSelect)) * (SELF_TEST_STEP ** (code - 1))


def selfTestVerdict(
    response: float, factoryTrim: float, channel: Literal["gyro", "accel"] = "gyro"
) -> Literal["pass", "fail"]:
    """Vendor pass/fail for one axis, against the factory trim.

    Bounds are InvenSense's: 0.5x lower, 1.5x upper. The driver source quotes the
    LOWER check for gyro and the UPPER check for accel explicitly; applying both
    bounds to both channels is the conservative reading, since a response at 0.1x
    is not a healthy accelerometer by any account.

    🔴 A ZERO factory trim is a FAIL, not an absence. This overrides my first
    implementation, which returned "no verdict". Honest absence is right for a
    measurement; for a safety check, a part whose trim cannot be read has not
    been validated, and unvalidated is not fine.
    """
    if factoryTrim == 0:
        return "fail"
    ratio = selfTestRatio(response, factoryTrim)
    if ratio is None:
        return "fail"
    if ratio < SELF_TEST_LOWER_BOUND_RATIO or ratio > SELF_TEST_UPPER_BOUND_RATIO:
        return "fail"
    return "pass"


# --------------------------------------------------------------------------
# Bus-facing
# --------------------------------------------------------------------------


def ownsBus(serviceName: str = "eclipse-obd") -> bool:
    """True when the collector is stopped, so this probe is the only I2C master.

    Two masters interleaving bank switches produce readings that look plausible
    and are not. Call this before any measurement and refuse to proceed if False.
    """
    result = subprocess.run(
        ["systemctl", "is-active", serviceName],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result.stdout.strip() != "active"


def _selectBank(bus, address: int, bank: int) -> None:
    bus.write_byte_data(address, REG_BANK_SEL, (bank & 0x03) << 4)


def openBus(busNumber: int = 1):
    """Lazy import so this module loads on a machine with no I2C."""
    import smbus2  # noqa: PLC0415 -- deliberate: hardware-only dependency

    return smbus2.SMBus(busNumber)


def readConfiguration(bus, address: int = ADDR_IMU) -> dict[str, object]:
    """Read and decode what the sensor is ACTUALLY configured to do.

    This is the answer to "what full-scale range and filter are we running?",
    which no line of our source code sets -- the Adafruit driver's constructor
    leaves it wherever it leaves it, and only the registers know.
    """
    _selectBank(bus, address, 0)
    whoAmI = bus.read_byte_data(address, REG_WHO_AM_I)
    pwrMgmt1 = bus.read_byte_data(address, REG_PWR_MGMT_1)
    pwrMgmt2 = bus.read_byte_data(address, REG_PWR_MGMT_2)

    _selectBank(bus, address, 2)
    accel = decodeAccelConfig(bus.read_byte_data(address, REG_ACCEL_CONFIG))
    gyro = decodeGyroConfig(bus.read_byte_data(address, REG_GYRO_CONFIG_1))
    gyroDivider = bus.read_byte_data(address, REG_GYRO_SMPLRT_DIV)
    accelDivider = (
        bus.read_byte_data(address, REG_ACCEL_SMPLRT_DIV_1) << 8
    ) | bus.read_byte_data(address, REG_ACCEL_SMPLRT_DIV_2)
    _selectBank(bus, address, 0)

    return {
        "whoAmI": whoAmI,
        "whoAmIExpected": WHO_AM_I_ICM20948,
        "pwrMgmt1": pwrMgmt1,
        "pwrMgmt2": pwrMgmt2,
        "accel": accel,
        "gyro": gyro,
        "gyroOdrHz": odrHzFromDivider(gyroDivider),
        "accelOdrHz": odrHzFromDivider(accelDivider),
        "gyroDivider": gyroDivider,
        "accelDivider": accelDivider,
    }


def _readSigned16(data: Iterable[int]) -> list[int]:
    values = list(data)
    out: list[int] = []
    for high, low in zip(values[0::2], values[1::2], strict=True):
        raw = (high << 8) | low
        out.append(raw - 65536 if raw > 32767 else raw)
    return out


def readRawSample(bus, address: int = ADDR_IMU) -> tuple[list[int], list[int]]:
    """One burst: (accel_xyz, gyro_xyz) as signed LSB counts, unscaled.

    Returned unscaled on purpose. Scaling needs the full-scale range, and this
    probe exists partly to establish what that range really is.
    """
    _selectBank(bus, address, 0)
    block = bus.read_i2c_block_data(address, REG_ACCEL_XOUT_H, 12)
    values = _readSigned16(block)
    return values[0:3], values[3:6]


def readSelfTest(
    bus, address: int = ADDR_IMU, samples: int = SELF_TEST_SAMPLES
) -> dict[str, object]:
    """Run the vendor self-test on both blocks and report per-axis verdicts.

    Procedure follows InvenSense's own driver: gyro +/-250 dps and accel +/-16 g
    with DLPF engaged, average `samples` readings with the self-test bits OFF,
    enable CTEN, settle, average again, and compare the difference against the
    factory trim decoded from the bank-1 OTP registers.

    This is the measurement that separates "the gyro reads a constant rate"
    (which a real rotation also does) from "the gyro's sense/drive chain is not
    working" (which nothing else explains). On 2026-09-14 it read 0.06-0.13 in
    the faulted state and 1.00 once recovered, on the same silicon.
    """
    _selectBank(bus, address, 2)
    savedGyroConfig = bus.read_byte_data(address, REG_GYRO_CONFIG_1)
    savedAccelConfig = bus.read_byte_data(address, REG_ACCEL_CONFIG)
    bus.write_byte_data(address, REG_GYRO_CONFIG_1, SELF_TEST_GYRO_CONFIG)
    bus.write_byte_data(address, REG_ACCEL_CONFIG, SELF_TEST_ACCEL_CONFIG)
    _selectBank(bus, address, 0)
    time.sleep(SELF_TEST_SETTLE_S)

    normalAccel, normalGyro = _averageSamples(bus, address, samples)

    _selectBank(bus, address, 2)
    bus.write_byte_data(address, REG_GYRO_CONFIG_2, BIT_GYRO_CTEN)
    bus.write_byte_data(address, REG_ACCEL_CONFIG_2, BIT_ACCEL_CTEN)
    _selectBank(bus, address, 0)
    time.sleep(SELF_TEST_SETTLE_S)

    testAccel, testGyro = _averageSamples(bus, address, samples)

    _selectBank(bus, address, 2)
    bus.write_byte_data(address, REG_GYRO_CONFIG_2, 0x00)
    bus.write_byte_data(address, REG_ACCEL_CONFIG_2, 0x00)
    bus.write_byte_data(address, REG_GYRO_CONFIG_1, savedGyroConfig)
    bus.write_byte_data(address, REG_ACCEL_CONFIG, savedAccelConfig)

    _selectBank(bus, address, 1)
    gyroCodes = [bus.read_byte_data(address, REG_SELF_TEST_X_GYRO + i) for i in range(3)]
    accelCodes = [bus.read_byte_data(address, REG_SELF_TEST_X_ACCEL + i) for i in range(3)]
    _selectBank(bus, address, 0)

    result: dict[str, object] = {"restoredConfig": True}
    for label, codes, normal, test in (
        ("gyro", gyroCodes, normalGyro, testGyro),
        ("accel", accelCodes, normalAccel, testAccel),
    ):
        axes = {}
        for index, axisName in enumerate("xyz"):
            trim = stOtpFromCode(codes[index])
            response = test[index] - normal[index]
            axes[axisName] = {
                "otpCode": codes[index],
                "factoryTrim": round(trim, 1),
                "response": round(response, 1),
                "ratio": (
                    None
                    if selfTestRatio(response, trim) is None
                    else round(selfTestRatio(response, trim), 4)
                ),
                "verdict": selfTestVerdict(response, trim, channel=label),  # type: ignore[arg-type]
            }
        result[label] = axes
    return result


def _averageSamples(bus, address: int, samples: int) -> tuple[list[float], list[float]]:
    accelSum = [0.0, 0.0, 0.0]
    gyroSum = [0.0, 0.0, 0.0]
    for _ in range(samples):
        accel, gyro = readRawSample(bus, address)
        for axis in range(3):
            accelSum[axis] += accel[axis]
            gyroSum[axis] += gyro[axis]
        time.sleep(SELF_TEST_SAMPLE_INTERVAL_S)
    return (
        [total / samples for total in accelSum],
        [total / samples for total in gyroSum],
    )


# --------------------------------------------------------------------------
# Magnetometer: read the AK09916 directly, NOT through our own bypass module
# --------------------------------------------------------------------------


def decodeMagTriple(data: Sequence[int]) -> tuple[float, float, float]:
    """Six bytes HXL..HZH -> (x, y, z) in uT. Little-endian signed, 0.15 uT/LSB."""
    values = list(data)
    if len(values) != 6:
        raise ValueError(f"expected 6 bytes HXL..HZH, got {len(values)}")
    out: list[float] = []
    for low, high in zip(values[0::2], values[1::2], strict=True):
        raw = (high << 8) | low
        signed = raw - 65536 if raw > 32767 else raw
        out.append(signed * MAG_UT_PER_LSB)
    return (out[0], out[1], out[2])


def magDataReady(st1: int) -> bool:
    """ST1 bit 0 (DRDY)."""
    return bool(st1 & MAG_ST1_DRDY_MASK)


def magOverflowed(st2: int) -> bool:
    """ST2 bit 3 (HOFL): the reading saturated and is not a measurement."""
    return bool(st2 & MAG_ST2_OVERFLOW_MASK)


def alignMagToImuFrame(
    mag: Sequence[float],
) -> tuple[float, float, float]:
    """Rotate AK09916 axes into the ICM-20948 accel/gyro frame: negate Y and Z.

    ⚠️ The primary source for this is NOT in hand. See the test docstring: the
    datasheet figure could not be retrieved, and what supports the transform is
    two independent implementations plus our own out-of-sample GPS score
    (4.1 / 6.8 deg with it, 62.7 / 101.8 deg without). Treat it as measured on
    our car, not as quoted from TDK.
    """
    return (mag[0], -mag[1], -mag[2])


def fieldMagnitudeUt(mag: Sequence[float]) -> float:
    """Total field strength. Earth's is ~52 uT at this latitude."""
    return math.sqrt(sum(component**2 for component in mag))


def readMagnetometerDirect(bus, samples: int = 100, intervalS: float = 0.02) -> dict[str, object]:
    """Read the AK09916 at 0x0C ourselves, to compare against what our code says.

    Deliberately re-implemented rather than imported from `ak09916_bypass.py`:
    if the probe used that module, a fault in it would be invisible to the probe.
    Assumes I2C bypass is already enabled (the collector leaves it on).
    """
    accepted: list[tuple[float, float, float]] = []
    overflows = 0
    notReady = 0
    for _ in range(samples):
        st1 = bus.read_byte_data(MAG_ADDRESS, MAG_REG_ST1)
        if not magDataReady(st1):
            notReady += 1
            time.sleep(intervalS)
            continue
        frame = bus.read_i2c_block_data(MAG_ADDRESS, MAG_REG_HXL, 8)
        if magOverflowed(frame[7]):
            overflows += 1
            time.sleep(intervalS)
            continue
        accepted.append(decodeMagTriple(frame[0:6]))
        time.sleep(intervalS)

    if not accepted:
        return {"samples": 0, "overflows": overflows, "notReady": notReady, "error": "no readings"}

    meanRaw = tuple(
        statistics.fmean([sample[axis] for sample in accepted]) for axis in range(3)
    )
    return {
        "samples": len(accepted),
        "overflows": overflows,
        "notReady": notReady,
        "meanRawUt": [round(value, 2) for value in meanRaw],
        "meanAlignedUt": [round(value, 2) for value in alignMagToImuFrame(meanRaw)],
        "fieldMagnitudeUt": round(fieldMagnitudeUt(meanRaw), 2),
        "earthReferenceUt": EARTH_FIELD_REFERENCE_UT,
    }


def gyroPowerCycle(bus, address: int = ADDR_IMU, settleS: float = 1.0) -> None:
    """Power the gyro block down and back up: the measured A-34 recovery.

    Cleared the latched fault 3 of 3 times on 2026-09-14. A DEVICE_RESET does
    NOT clear it (0 of 16), so this is not interchangeable with a chip reset.
    """
    _selectBank(bus, address, 0)
    bus.write_byte_data(address, REG_PWR_MGMT_2, PWR_MGMT_2_GYRO_OFF)
    time.sleep(settleS)
    bus.write_byte_data(address, REG_PWR_MGMT_2, PWR_MGMT_2_ALL_ON)
    time.sleep(settleS)
