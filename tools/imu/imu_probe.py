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

# Bank 2
REG_GYRO_SMPLRT_DIV = 0x00
REG_GYRO_CONFIG_1 = 0x01
REG_ACCEL_SMPLRT_DIV_1 = 0x10
REG_ACCEL_SMPLRT_DIV_2 = 0x11
REG_ACCEL_CONFIG = 0x14

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

# InvenSense self-test pass floor: response must be at least half the factory trim.
SELF_TEST_PASS_RATIO = 0.5

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


def selfTestPasses(ratio: float | None) -> bool | None:
    """None in, None out: no trim means no verdict, not a failure."""
    if ratio is None:
        return None
    return ratio >= SELF_TEST_PASS_RATIO


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
