################################################################################
# File Name: test_ahrs_gyro_bias_zaru.py
# Purpose/Description: ARCH-066 (US-819) -- the AHRS gyro offset is learned from
#   the vehicle's OWN stationary truth (fresh OBD SPEED == 0) as the MEAN raw rate
#   of the stop (a zero-angular-rate update, ZARU), and can be SEEDED from the
#   last drive, instead of starting from zero at every boot and relying on
#   imufusion.Bias's per-sample 3 dps gate, which idle-engine vibration starves.
#   RCA: offices/architect/findings/2026-10-04-RESULTS-US-818-819-820-imu-rca-round-2.md
# Author: Atlas (architect)
# Creation Date: 2026-10-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-04    | Atlas        | Initial (ARCH-066, CIO-directed build).
# ================================================================================
################################################################################

"""ARCH-066: ZARU gyro-offset learning on fresh OBD speed 0, plus the boot seed."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pi.sensors.ahrs_fusion import (
    GYRO_FAULT_MIN_RAD_S,
    GYRO_FAULT_WINDOW_S,
    AhrsFusion,
)

HZ = 50.0
G = 9.80665
LEVEL = (0.0, 0.0, G)
FIELD = (0.0, 26.0, -45.0)  # level, facing east: body +y is north
# MEASURED, drives 96-100: the mean resting rate at stops (deg/s, body x/y/z).
BIAS_DPS = np.array([-0.2, 0.7, 0.15])
# MEASURED: idle-engine vibration at stops reaches sd 1.3 dps on the pitch axis.
IDLE_SD_DPS = np.array([0.4, 1.3, 0.4])


def _drive(f: AhrsFusion, rng, t0: float, seconds: float, *, speedKmh: float,
           biasDps=BIAS_DPS, sdDps=IDLE_SD_DPS, speedEveryS: float | None = 1.0) -> float:
    """Feed ``seconds`` of level, straight samples; OBD speed every ``speedEveryS``."""
    n = int(seconds * HZ)
    nextSpeed = t0
    t = t0
    for i in range(n):
        t = t0 + i / HZ
        if speedEveryS is not None and t >= nextSpeed:
            f.observeSpeed(speedKmh, t)
            nextSpeed = t + speedEveryS
        g = np.radians(np.asarray(biasDps) + rng.normal(0.0, sdDps))
        f.update(LEVEL, tuple(g), t, FIELD)
    return t + 1.0 / HZ


def test_idlingStop_learnsTheBias_whereImufusionBiasAloneCannot() -> None:
    """The RCA case. imufusion.Bias alone reached 2 % of the bias after 90 s on
    this noise (sim, 2026-10-04); a 10 s stop must now land within 0.15 dps."""
    f = AhrsFusion(sampleHz=HZ)
    _drive(f, np.random.default_rng(7), 0.0, 10.0, speedKmh=0.0)
    off = np.asarray(f.gyroOffsetDps)
    assert np.all(np.abs(off - BIAS_DPS) < 0.15), off
    assert f.zaruUpdateCount >= 1


def test_learnedBias_removesThePhantomPitchAfterPullingAway() -> None:
    """Cost the RCA measured: unlearned, this bias read pitch -1.6 deg (~2.8 %
    phantom grade) at speed. After an idling stop it must be under 0.3 deg."""
    f = AhrsFusion(sampleHz=HZ)
    rng = np.random.default_rng(11)
    t = _drive(f, rng, 0.0, 20.0, speedKmh=0.0)
    _drive(f, rng, t, 60.0, speedKmh=60.0, sdDps=np.array([0.05, 0.05, 0.05]))
    assert f.pitchRad is not None
    assert abs(math.degrees(f.pitchRad)) < 0.3


def test_movingCar_neverAdoptsAnOffset() -> None:
    f = AhrsFusion(sampleHz=HZ)
    _drive(f, np.random.default_rng(3), 0.0, 20.0, speedKmh=50.0)
    assert f.zaruUpdateCount == 0


def test_staleSpeed_isNotAStop() -> None:
    """A speed of 0 heard once and then silence is not evidence of a stop (OBD
    dropped): only FRESH speed opens the window, the same rule as the latch."""
    f = AhrsFusion(sampleHz=HZ)
    f.observeSpeed(0.0, 0.0)
    _drive(f, np.random.default_rng(5), 0.1, 20.0, speedKmh=0.0, speedEveryS=None)
    assert f.zaruUpdateCount == 0


def test_faultedWindow_isNeverAdoptedAsTheOffset() -> None:
    """A-34: a latched gyro (~29 dps on y) must latch the verdict, NOT become
    the offset that would then hide it."""
    f = AhrsFusion(sampleHz=HZ)
    latched = np.array([0.0, math.degrees(0.5), 0.0])
    _drive(f, np.random.default_rng(9), 0.0, GYRO_FAULT_WINDOW_S * 3, speedKmh=0.0,
           biasDps=latched, sdDps=np.array([0.1, 0.1, 0.1]))
    assert f.gyroImplausible is True
    assert f.zaruUpdateCount == 0
    assert max(abs(c) for c in f.gyroOffsetDps) < math.degrees(GYRO_FAULT_MIN_RAD_S)


def test_eachStop_isAveragedOnItsOwn_samples() -> None:
    """The bias drifts with temperature between stops; a new stop's mean must not
    be diluted by the previous stop's samples."""
    f = AhrsFusion(sampleHz=HZ)
    rng = np.random.default_rng(13)
    t = _drive(f, rng, 0.0, 10.0, speedKmh=0.0, biasDps=np.array([0.0, 0.5, 0.0]))
    t = _drive(f, rng, t, 10.0, speedKmh=40.0, sdDps=np.array([0.05, 0.05, 0.05]),
               biasDps=np.array([0.0, 0.5, 0.0]))
    _drive(f, rng, t, 10.0, speedKmh=0.0, biasDps=np.array([0.0, 0.9, 0.0]))
    assert abs(f.gyroOffsetDps[1] - 0.9) < 0.15


def test_seed_appliesAtOnce_andSurvivesReset() -> None:
    f = AhrsFusion(sampleHz=HZ)
    assert f.seedGyroOffsetDps((-0.2, 0.7, 0.15)) is True
    assert np.allclose(f.gyroOffsetDps, (-0.2, 0.7, 0.15))
    assert f.gyroBiasRadS is not None
    f.reset()
    assert np.allclose(f.gyroOffsetDps, (-0.2, 0.7, 0.15))


@pytest.mark.parametrize(
    "bad",
    [
        (float("nan"), 0.0, 0.0),
        (0.0, float("inf"), 0.0),
        (0.0, math.degrees(GYRO_FAULT_MIN_RAD_S), 0.0),  # a latched rate is not a bias
        (0.0, 0.0),
        None,
        "abc",
    ],
)
def test_seed_rejectsAnythingThatIsNotAPlausibleBias(bad) -> None:
    f = AhrsFusion(sampleHz=HZ)
    assert f.seedGyroOffsetDps(bad) is False
    assert f.gyroOffsetDps == (0.0, 0.0, 0.0)


def test_zaruOffsetDps_isNoneUntilAStopIsLearned_thenTheAdoptedMean() -> None:
    f = AhrsFusion(sampleHz=HZ)
    assert f.zaruOffsetDps is None
    f.seedGyroOffsetDps((0.1, 0.1, 0.1))
    assert f.zaruOffsetDps is None  # a seed is not a measurement of THIS boot
    _drive(f, np.random.default_rng(17), 0.0, 10.0, speedKmh=0.0)
    assert f.zaruOffsetDps is not None
    assert np.allclose(f.zaruOffsetDps, f.gyroOffsetDps, atol=0.05)


def test_pullAwayTurn_beforeTheFirstNonZeroSpeed_isNeverAdopted() -> None:
    """Review finding (2026-10-04, reproduced): OBD SPEED arrives ~every 2.3 s, so
    up to ~2.3 s of a pull-away still reads as 'fresh speed 0'. A turn there
    (20 dps yaw) put +2.6 dps into the yaw offset on a 5.25 s stop -- worse than
    no offset. Only samples BRACKETED by two zero readings may count."""
    f = AhrsFusion(sampleHz=HZ)
    rng = np.random.default_rng(21)
    quiet = np.array([0.05, 0.05, 0.05])
    t = 0.0
    for k in range(3):  # zero readings at 0, 2.3, 4.6 s -> stationary until 5.25 s
        f.observeSpeed(0.0, k * 2.3)
    n = int(5.25 * HZ)
    for i in range(n):
        t = i / HZ
        g = np.radians(BIAS_DPS + rng.normal(0.0, quiet))
        f.update(LEVEL, tuple(g), t, FIELD)
    turning = BIAS_DPS + np.array([0.0, 2.0, 20.0])
    for i in range(int(1.6 * HZ)):  # pull away, turning, before the next SPEED sample
        t = 5.25 + i / HZ
        f.update(LEVEL, tuple(np.radians(turning + rng.normal(0.0, quiet))), t, FIELD)
    f.observeSpeed(8.0, 6.9)  # the first non-zero reading arrives
    assert abs(f.gyroOffsetDps[2] - BIAS_DPS[2]) < 0.2, f.gyroOffsetDps


def test_anOffsetAtTheFaultCut_isNeverAdopted() -> None:
    """A window is judged faulted on (raw - offset), so a large existing offset
    could let a larger raw rate through as 'healthy'. The ADOPTED value must
    itself stay under the A-34 cut, like a seed."""
    f = AhrsFusion(sampleHz=HZ)
    assert f.seedGyroOffsetDps((0.0, 5.0, 0.0))
    _drive(f, np.random.default_rng(23), 0.0, 10.0, speedKmh=0.0,
           biasDps=np.array([0.0, 10.0, 0.0]), sdDps=np.array([0.05, 0.05, 0.05]))
    assert max(abs(c) for c in f.gyroOffsetDps) < math.degrees(GYRO_FAULT_MIN_RAD_S)
    assert f.zaruUpdateCount == 0
