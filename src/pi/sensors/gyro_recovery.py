"""A-34: detect the ICM-20948's latched gyro fault and clear it at startup.

THE DEFECT (measured 2026-09-14, reproduced live 2026-09-15). The gyro channel
can enter a latched analog state in which a motionless car reports a constant
14-30 deg/s. In that state:

* every register reads nominal and the user offsets are zero -- there is no
  configuration anywhere that says anything is wrong;
* ``DEVICE_RESET`` does NOT clear it (0 of 16 collector inits cleared it);
* the factory self-test FAILS (0.062 / 0.087 / 0.126 against a 0.5 floor) while
  the accelerometer passes, and the same silicon self-tests at 1.007-1.016 once
  recovered -- so the part is healthy and the state is recoverable;
* disabling and re-enabling the gyro block via ``PWR_MGMT_2`` cleared it 3 of 3.

WHY IT MATTERS. ``pitch_fusion`` integrates the gyro, so a latched rate becomes
a growing pitch error: 0.2457 rad/s x tau 5 s = 70.4 deg, against a published
70.08. US-749's plausibility guard withholds pitch and grade when that happens,
which is correct and is NOT a fix -- the guard reports the absence, it does not
restore the reading. Since 2026-09-08 the fault has been the dominant state at
IMU start, so most starts publish no grade at all.

WHY IT LIVES HERE AND NOT IN THE DRIVER. ``adafruit_icm20x`` defines no symbol
for ``PWR_MGMT_2`` -- there is no attribute to set. It also has no step that
could recover the gyro: ``reset()`` polls the reset bit and ``initialize()``
clears sleep, and neither touches the gyro power bits. So the register is
written directly through the driver's own ``i2c_device``, following the
precedent set by ``ak09916_bypass.enableI2cBypass``: reach past the driver only
where it exposes no control, and say why.

TRIGGER. Unproven, and deliberately not encoded here: onset clusters at
power-on, and ``POWER_OFF_ON_HALT=1`` means every key-on is a real power-on.
This module treats the fault as a STATE to detect, never as a condition to
predict.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ICM-20948 bank-0 register 0x07. Bits [5:3] disable accel axes, [2:0] gyro axes.
REG_PWR_MGMT_2 = 0x07
PWR_MGMT_2_GYRO_OFF = 0x07  # all three gyro axes off, accel untouched
PWR_MGMT_2_ALL_ON = 0x00

# The measured bimodal cut. Quiet minutes sit at 0.013-0.015 rad/s and faulted
# starts at 0.487-0.553, with NOTHING observed in between across 10,313
# classified minutes. 0.10 is in that empty gap: high enough that real sensor
# noise can never reach it, low enough that the 14-30 deg/s fault always does.
GYRO_FAULT_MIN_RAD_S = 0.10

DEFAULT_SAMPLE_COUNT = 20
DEFAULT_SETTLE_S = 1.0

GyroState = Literal["healthy", "faulted", "unknown"]


@dataclass(frozen=True)
class GyroRecoveryOutcome:
    """What the startup check found and what it did about it."""

    attempted: bool
    before: GyroState
    after: GyroState
    recovered: bool
    error: str | None

    def describe(self) -> str:
        """One line for the log -- the state before, after, and what was done."""
        if not self.attempted:
            return f"gyro {self.before}; no recovery attempted"
        if self.error:
            return (
                f"gyro {self.before}; recovery FAILED with {self.error}; "
                f"pitch and grade stay withheld"
            )
        return (
            f"gyro {self.before} -> {self.after}; "
            f"power cycle {'cleared it' if self.recovered else 'did NOT clear it'}"
        )


def gyroLooksFaulted(readings: list[tuple[float, float, float]]) -> bool:
    """True when a set of at-rest readings shows the latched offset.

    ⚠️ PRECONDITION, owned by the caller: the vehicle must be STATIONARY. A car
    turning at 30 deg/s produces exactly this signature, because the fault IS
    "a motionless sensor reporting rotation". At startup that precondition holds
    for the reason the fault is caught there at all -- the engine has just been
    keyed on and the car has not moved yet.

    Uses the MEAN, so a single spike cannot trigger a power cycle; the fault is
    a sustained offset with low variance, not an occasional outlier.
    """
    if not readings:
        # No samples is not evidence of a fault. Acting here would power-cycle
        # the gyro on the strength of having failed to read it.
        return False
    axisMeans = [sum(r[axis] for r in readings) / len(readings) for axis in range(3)]
    return max(abs(mean) for mean in axisMeans) >= GYRO_FAULT_MIN_RAD_S


def _sampleGyro(icm: Any, count: int) -> list[tuple[float, float, float]]:
    readings: list[tuple[float, float, float]] = []
    for _ in range(count):
        readings.append(tuple(icm.gyro))  # type: ignore[arg-type]
    return readings


def _writePwrMgmt2(icm: Any, value: int) -> None:
    """Write bank-0 PWR_MGMT_2 through the driver's own I2C device.

    The driver owns the bus handle, so the write goes through it rather than
    opening a second master on the same address.
    """
    icm._bank = 0  # noqa: SLF001 -- the driver exposes no PWR_MGMT_2 control at all
    with icm.i2c_device as device:
        device.write(bytes([REG_PWR_MGMT_2, value]))


def recoverGyroIfFaulted(
    icm: Any,
    sampleCount: int = DEFAULT_SAMPLE_COUNT,
    settleS: float = DEFAULT_SETTLE_S,
) -> GyroRecoveryOutcome:
    """Check the gyro at startup and power-cycle the block if it is latched.

    Returns an outcome rather than raising: a failed recovery must not cost the
    accelerometer and magnetometer too. The same principle as
    ``_attachDirectMagnetometer`` -- losing the whole IMU to fix one channel
    throws away valid data to punish a broken one.

    🔴 The post-check is not optional. Writing the register is not evidence the
    gyro recovered; the sequence cleared the fault 3 of 3 times in testing,
    which is not "always". When the post-check still reads faulted, this reports
    ``recovered=False`` so US-749's guard keeps withholding pitch and grade
    instead of publishing a confident wrong angle.
    """
    try:
        before = _sampleGyro(icm, sampleCount)
    except OSError as exc:
        logger.warning("IMU gyro unreadable at startup (%s); no recovery attempted", exc)
        return GyroRecoveryOutcome(
            attempted=False, before="unknown", after="unknown", recovered=False, error=str(exc)
        )

    if not gyroLooksFaulted(before):
        return GyroRecoveryOutcome(
            attempted=False, before="healthy", after="healthy", recovered=False, error=None
        )

    logger.warning(
        "IMU gyro latched fault detected at startup (mean rate above %.2f rad/s on a "
        "stationary vehicle); attempting PWR_MGMT_2 power cycle (A-34)",
        GYRO_FAULT_MIN_RAD_S,
    )

    try:
        _writePwrMgmt2(icm, PWR_MGMT_2_GYRO_OFF)
        time.sleep(settleS)
        _writePwrMgmt2(icm, PWR_MGMT_2_ALL_ON)
        time.sleep(settleS)
    except OSError as exc:
        logger.error("IMU gyro recovery failed on the bus (%s); pitch/grade stay withheld", exc)
        return GyroRecoveryOutcome(
            attempted=True, before="faulted", after="unknown", recovered=False, error=str(exc)
        )

    try:
        after = _sampleGyro(icm, sampleCount)
    except OSError as exc:
        return GyroRecoveryOutcome(
            attempted=True, before="faulted", after="unknown", recovered=False, error=str(exc)
        )

    stillFaulted = gyroLooksFaulted(after)
    outcome = GyroRecoveryOutcome(
        attempted=True,
        before="faulted",
        after="faulted" if stillFaulted else "healthy",
        recovered=not stillFaulted,
        error=None,
    )
    if outcome.recovered:
        logger.warning("IMU gyro recovered by power cycle (A-34): %s", outcome.describe())
    else:
        logger.error(
            "IMU gyro STILL faulted after power cycle (A-34): %s -- pitch and grade "
            "remain withheld by the plausibility guard",
            outcome.describe(),
        )
    return outcome
