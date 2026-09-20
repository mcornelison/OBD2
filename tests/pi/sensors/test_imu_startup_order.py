################################################################################
# File Name: test_imu_startup_order.py
# Purpose/Description: ARCH-032 -- pin the ORDER of the IMU startup sequence.
#
#   The magnetometer bypass MUST be established BEFORE the A-34 gyro recovery
#   check runs. Measured on the Pi, 2026-09-20, n=20 per arm, interleaved, both
#   I2C contenders stopped:
#
#       A  control -- no gyro read                      14/20 = 70%
#       B  DEFECT  -- 20x icm.gyro, THEN bypass          2/20 = 10%
#       J  FIX     -- bypass FIRST, then 20x icm.gyro   16/20 = 80%
#
#       Fisher exact, two-sided:  J vs B  p = 0.000017   (decisive)
#                                 J vs A  p = 0.7164     (parity with control)
#
#   Merely READING the gyro through the driver before the hand-over drops the
#   bypass probe from ~70-85% to ~10%. Evidence:
#   offices/architect/evidence/2026-09-16-arch027a-mag-regression/REORDER-RESULT.md
#
# 🔴 WHY THIS TEST EXISTS AT ALL, AND WHY IT ASSERTS ORDER RATHER THAN CALLS
#
#   The defect shipped in V0.29.55 with a GREEN unit suite. Both functions were
#   called, both were correct in isolation, and `_makeIcm20948` -- the only place
#   their order was expressed -- is `pragma: no cover` real-hardware glue. A test
#   asserting that both ran would have passed throughout the outage. **The
#   membership of the set was right and its SEQUENCE was wrong**, so the sequence
#   is what gets pinned here.
#
# ⚠️ THE PRIOR ORDER WAS DELIBERATE AND DOCUMENTED. `_recoverGyro`'s docstring
#   argued it must run first, "while the chip is in its freshly-initialised state
#   rather than after the magnetometer bypass has reconfigured the auxiliary
#   bus." That reasoning is plausible and it is WRONG -- measured, not argued.
#   This test exists so the next reader who finds that argument persuasive
#   cannot quietly restore it.
#
# ⚠️ WHAT THIS TEST CANNOT SHOW: it pins ordering only. It does NOT prove the
#   gyro recovery still CLEARS A REAL LATCH from behind the bypass -- that needs
#   a faulted gyro on real hardware and is a separate item in ARCH-032's DoD.
#
# Author: Atlas (Architect) -- ARCH-032, CIO-directed build (override on the card)
# Creation Date: 2026-09-20
################################################################################

"""ARCH-032: the magnetometer bypass must be established before the gyro check."""

from __future__ import annotations

from typing import Any

from pi.sensors import sensor_reader


class _Recorder:
    """Records the order in which the two startup steps run."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def attach(self, icm: Any, i2cBus: Any) -> Any:  # noqa: ARG002
        self.calls.append("bypass")
        return ("wrapped", icm)

    def recover(self, icm: Any) -> Any:  # noqa: ARG002
        self.calls.append("gyro")
        return None


def test_bypass_is_established_before_the_gyro_check() -> None:
    """🔴 The ordering invariant. Reversing these two lines is the V0.29.55 defect."""
    rec = _Recorder()

    sensor_reader._buildImuDevice(
        icm="icm", i2cBus="bus", attachFn=rec.attach, recoverFn=rec.recover
    )

    assert rec.calls == ["bypass", "gyro"], (
        f"IMU startup ran {rec.calls}; the magnetometer bypass MUST come first. "
        "Running the gyro check first drops the 0x0C probe from ~70% to ~10% "
        "(ARCH-032, n=20/arm, Fisher p=0.000017)."
    )


def test_the_wrapped_device_is_returned_not_the_bare_icm() -> None:
    """The bypass wrapper is the return value; the gyro check must not displace it."""
    rec = _Recorder()

    device = sensor_reader._buildImuDevice(
        icm="icm", i2cBus="bus", attachFn=rec.attach, recoverFn=rec.recover
    )

    assert device == ("wrapped", "icm")


def test_gyro_recovery_receives_the_raw_icm_not_the_wrapper() -> None:
    """Recovery writes ICM power-management registers, so it needs the real chip.

    Handing it the bypass wrapper would work only by attribute delegation, which
    is an accident rather than a contract.
    """
    seen: dict[str, Any] = {}

    def attach(icm: Any, i2cBus: Any) -> Any:  # noqa: ARG001
        return ("wrapped", icm)

    def recover(icm: Any) -> Any:
        seen["icm"] = icm
        return None

    sensor_reader._buildImuDevice(
        icm="raw-icm", i2cBus="bus", attachFn=attach, recoverFn=recover
    )

    assert seen["icm"] == "raw-icm"


def test_a_failing_gyro_check_does_not_cost_the_magnetometer() -> None:
    """Degrade principle, now in the other direction.

    The bypass already succeeded by the time recovery runs, so a recovery that
    raises must not discard a working magnetometer. `_recoverGyro` swallows its
    own exceptions, but this pins the behaviour at the seam that owns the order.
    """

    def attach(icm: Any, i2cBus: Any) -> Any:  # noqa: ARG001
        return ("wrapped", icm)

    def recover(icm: Any) -> Any:  # noqa: ARG001
        raise OSError("gyro recovery exploded")

    device = sensor_reader._buildImuDevice(
        icm="icm", i2cBus="bus", attachFn=attach, recoverFn=recover
    )

    assert device == ("wrapped", "icm")
